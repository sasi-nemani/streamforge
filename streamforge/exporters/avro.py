"""
streamforge/exporters/avro.py — Apache Avro Schema Exporter
=============================================================

Converts an InferredSchema into an Apache Avro Schema (.avsc) file.
Avro is the dominant schema format in Kafka ecosystems — Confluent Schema
Registry speaks Avro natively, and most stream processing frameworks
(Flink, Spark Streaming, Kafka Streams) have first-class Avro support.

Design decisions:
  ADR-021: We produce Avro Record type (not Map or Array). Every event stream
           worth schematising is fundamentally a record of named fields.

  ADR-022: Nullable fields produce union types: ["null", "actual_type"].
           In Avro, "null" must be the FIRST type in a union if the field
           has a default of null. We always put null first — it's the
           correct Avro pattern and avoids "default does not match schema"
           errors in confluent-kafka producers.

  ADR-023: Timestamps use Avro logical types (timestamp-millis, date) rather
           than raw long/int. This is how Avro encodes temporal semantics and
           is what Kafka Connect, Flink, and BigQuery expect.

  ADR-024: Mixed types produce a union of all primitive types plus null:
           ["null", "string", "int", "long", "float", "double", "boolean"].
           This is permissive but honest — use it as a starting point and
           narrow the type once the data is better understood.

  ADR-025: Nested objects are represented as embedded Avro records.
           Arrays use {"type": "array", "items": "string"} (defaulting to
           string items since we don't infer array element types in v1).

Avro Schema Registry compatibility:
  The output is compatible with Confluent Schema Registry's REST API.
  To register a schema: POST to /subjects/<topic>-value/versions
  with Content-Type: application/vnd.schemaregistry.v1+json
  body: {"schema": "<escaped JSON string of the .avsc content>"}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import FieldSchema, FieldType, InferredSchema

logger = logging.getLogger(__name__)


# ── Type mapping ───────────────────────────────────────────────────────────────
# Maps StreamForge FieldType → Avro type definition.
# Reference: https://avro.apache.org/docs/current/spec.html

def _avro_type(field: FieldSchema) -> Any:
    """
    Produce the Avro type representation for a single field.

    Returns either a primitive string ("string", "int", ...) or a complex
    type dict ({"type": "record", ...}, logical types, etc.).
    """
    base: Any

    if field.field_type == FieldType.STRING:
        # Use native Avro enum for low-cardinality string fields with known values
        if field.enum_values and len(field.enum_values) <= 50:
            # Avro enum names must be [A-Za-z_][A-Za-z0-9_]* — sanitize
            import re
            enum_name = re.sub(r'[^A-Za-z0-9_]', '_', field.path.split(".")[-1]).title() + "Enum"
            safe_symbols = [re.sub(r'[^A-Za-z0-9_.]', '_', v) for v in field.enum_values]
            base = {"type": "enum", "name": enum_name, "symbols": safe_symbols}
        else:
            base = "string"
    elif field.field_type == FieldType.INTEGER:
        base = "long"          # Use long (64-bit) to avoid overflow on large IDs
    elif field.field_type == FieldType.FLOAT:
        base = "double"        # double is more portable than float across Avro runtimes
    elif field.field_type == FieldType.BOOLEAN:
        base = "boolean"

    elif field.field_type == FieldType.TIMESTAMP_EPOCH_MS:
        # Avro logical type: timestamp-millis encodes as a long + logical annotation
        base = {"type": "long", "logicalType": "timestamp-millis"}

    elif field.field_type == FieldType.TIMESTAMP_ISO8601:
        # ISO strings don't have a dedicated Avro logical type — use string.
        # A comment annotation documents the expected format.
        base = {"type": "string", "doc": "ISO 8601 timestamp string (e.g., 2026-03-14T14:32:01Z)"}

    elif field.field_type == FieldType.TIMESTAMP_RFC2822:
        base = {"type": "string", "doc": "RFC 2822 date-time string"}

    elif field.field_type == FieldType.DATE:
        # Avro logical type: date encodes days since epoch as int
        base = {"type": "int", "logicalType": "date"}

    elif field.field_type == FieldType.UUID:
        # Avro 1.10+ logical type: uuid (string with UUID format)
        base = {"type": "string", "logicalType": "uuid"}

    elif field.field_type == FieldType.EMAIL:
        base = {"type": "string", "doc": "Email address field (PII)"}

    elif field.field_type == FieldType.PHONE:
        base = {"type": "string", "doc": "Phone number field (PII)"}

    elif field.field_type == FieldType.ARRAY:
        # Default to array of strings — v1 limitation, see ADR-025
        base = {"type": "array", "items": "string"}

    elif field.field_type == FieldType.OBJECT:
        # Nested object — emit as a record with no fields (schema incomplete)
        # In practice, nested fields are flattened to dot-notation so this
        # case only appears when the entire field is typed as "object".
        safe_name = field.path.replace(".", "_")
        base = {
            "type": "record",
            "name": f"{safe_name}_record",
            "fields": [],
            "doc": "Nested object — field-level schema not inferred in this version",
        }

    elif field.field_type == FieldType.NULL:
        return "null"   # pure null field — rare but valid

    elif field.field_type == FieldType.MIXED:
        # See ADR-024: union of all primitives + null
        return ["null", "string", "long", "double", "boolean"]

    else:
        base = "string"   # safe fallback

    # Nullable: wrap in union with null first (Avro convention, see ADR-022)
    if field.nullable and field.field_type not in (FieldType.NULL, FieldType.MIXED):
        return ["null", base]

    return base


def field_to_avro_field(field: FieldSchema) -> dict:
    """
    Convert a FieldSchema to an Avro field definition.

    Args:
        field: FieldSchema from the inference engine.

    Returns:
        Avro field dict compatible with the Avro spec.
    """
    # Use only the last segment of dot-notation as the Avro field name.
    # Nested fields are handled by the record nesting logic in schema_to_avro().
    avro_name = field.path.split(".")[-1]

    avro_field: dict = {
        "name": avro_name,
        "type": _avro_type(field),
    }

    # Default: nullable fields default to null, non-nullable required fields
    # have no default (required in Avro sense — producers must supply them).
    if field.nullable:
        avro_field["default"] = None   # Avro: null default must match first union type

    # Documentation from LLM-generated notes
    parts = []
    if field.notes:
        parts.append(field.notes)
    if field.pii_categories:
        parts.append(f"PII: {', '.join(p.value for p in field.pii_categories)}")
    if field.enum_values:
        parts.append(f"Known values: {', '.join(field.enum_values[:10])}")
    if parts:
        avro_field["doc"] = " | ".join(parts)

    # Avro doesn't have a standard extension mechanism like JSON Schema's x-.
    # We add StreamForge metadata as a top-level property that Avro ignores
    # but tools like Kafka Connect preserve.
    avro_field["x-streamforge"] = {
        "confidence":    round(field.confidence, 4),
        "presence_rate": round(field.presence_rate, 4),
        "required":      field.required,
    }

    return avro_field


def schema_to_avro(schema: InferredSchema, namespace: str | None = None) -> dict:
    """
    Convert an InferredSchema to a complete Avro Record Schema.

    Dot-notation field paths are expanded into nested Avro records.
    For example, "user.email" and "user.name" produce a "user" record
    containing "email" and "name" fields.

    Args:
        schema:     The InferredSchema to export.
        namespace:  Avro namespace (e.g., "com.mycompany.events").
                    Defaults to "io.streamforge.{stream_name}".

    Returns:
        Avro schema dict (.avsc format, serialisable to JSON).
    """
    if namespace is None:
        # Sanitise stream name to valid Java/Avro namespace segment
        safe_name = schema.stream_name.replace("-", "_").replace(".", "_")
        namespace = f"io.streamforge.{safe_name}"

    # Group fields by top-level key to handle nesting
    top_level_fields: dict[str, list[FieldSchema]] = {}
    for f in schema.fields:
        top_key = f.path.split(".")[0]
        top_level_fields.setdefault(top_key, []).append(f)

    avro_fields = []
    for top_key, fields in top_level_fields.items():
        if len(fields) == 1 and "." not in fields[0].path:
            # Simple top-level field
            avro_fields.append(field_to_avro_field(fields[0]))
        else:
            # Nested fields — create an embedded record
            nested_record = _build_nested_record(top_key, fields, namespace)
            # The top-level field wraps the nested record
            outer_field = fields[0]  # use first for metadata
            avro_fields.append({
                "name": top_key,
                "type": nested_record if not outer_field.nullable else ["null", nested_record],
                "default": None if outer_field.nullable else None,
                "doc": f"Nested object: {top_key}",
            })

    avro_schema = {
        "type": "record",
        "name": _sanitise_name(schema.stream_name),
        "namespace": namespace,
        "doc": (
            f"Auto-inferred by StreamForge on {schema.inferred_at[:10]}. "
            f"Model: {schema.inference_model}. "
            f"Confidence: {schema.inference_confidence:.0%}. "
            f"{schema.event_count_sampled} events sampled."
        ),
        "fields": avro_fields,
        # StreamForge metadata — preserved by most Avro tooling
        "x-streamforge-version": schema.version,
        "x-streamforge-stream":  schema.stream_name,
    }

    return avro_schema


def export_to_file(
    schema: InferredSchema,
    output_path: str,
    namespace: str | None = None,
    indent: int = 2,
) -> str:
    """
    Export InferredSchema to an Avro Schema (.avsc) file.

    Args:
        schema:      The schema to export.
        output_path: File path to write (.avsc extension recommended).
        namespace:   Avro namespace. Auto-generated if None.
        indent:      JSON indentation level.

    Returns:
        Absolute path of the written file.
    """
    doc = schema_to_avro(schema, namespace)
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=indent, ensure_ascii=False), encoding="utf-8")
    logger.info("Exported Avro schema: %s", p)
    return str(p.resolve())


def to_confluent_registry_payload(schema: InferredSchema) -> str:
    """
    Produce the JSON payload for registering with Confluent Schema Registry.

    Usage:
        payload = to_confluent_registry_payload(schema)
        requests.post(
            f"{REGISTRY_URL}/subjects/{topic}-value/versions",
            headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            data=payload,
        )

    Returns:
        JSON string with {"schema": "<escaped Avro schema>"}.
    """
    avro_doc = schema_to_avro(schema)
    avro_str = json.dumps(avro_doc)
    return json.dumps({"schema": avro_str, "schemaType": "AVRO"})


# ── Internal helpers ───────────────────────────────────────────────────────────

def _sanitise_name(name: str) -> str:
    """Convert a stream name to a valid Avro record name (alphanumeric + underscores)."""
    result = ""
    for ch in name:
        result += ch if ch.isalnum() or ch == "_" else "_"
    # Avro names cannot start with a digit
    if result and result[0].isdigit():
        result = "_" + result
    return result or "UnknownRecord"


def _build_nested_record(
    top_key: str,
    fields: list[FieldSchema],
    namespace: str,
) -> dict:
    """
    Build an Avro embedded record for a group of dot-notation fields
    that share the same top-level key.

    Example: fields with paths "user.email", "user.name", "user.id"
    → Avro record named "user_record" with fields email, name, id.
    """
    # Strip the top-level key from paths to get sub-field names
    sub_fields = []
    for f in fields:
        parts = f.path.split(".")
        if len(parts) > 1:
            # Create a shallow copy with the sub-path
            sub_field = FieldSchema(
                name=parts[-1],
                path=".".join(parts[1:]),
                field_type=f.field_type,
                nullable=f.nullable,
                required=f.required,
                presence_rate=f.presence_rate,
                sample_values=f.sample_values,
                enum_values=f.enum_values,
                pii_categories=f.pii_categories,
                confidence=f.confidence,
                notes=f.notes,
            )
            sub_fields.append(field_to_avro_field(sub_field))

    return {
        "type": "record",
        "name": f"{_sanitise_name(top_key)}_record",
        "namespace": namespace,
        "fields": sub_fields,
    }
