"""
streamforge/exporters/json_schema.py — JSON Schema (Draft 2020-12) Exporter
=============================================================================

Converts an InferredSchema or StreamProfile into a JSON Schema document.
JSON Schema is the universal interchange format — every major language has
a validator, and it's the basis for OpenAPI, AsyncAPI, and Avro (partially).

Design decisions:
  ADR-016: We target JSON Schema Draft 2020-12 (latest stable). It's supported
           by all modern validators (ajv, jsonschema, pydantic). We include a
           $schema header so validators auto-detect the draft.

  ADR-017: Nullable fields produce {"anyOf": [{"type": "..."}, {"type": "null"}]}
           rather than {"type": ["...", "null"]}. The anyOf form is more widely
           supported by code generators (e.g., quicktype, openapi-generator).

  ADR-018: Mixed types produce an unconstrained {} schema (no type assertion).
           This is honest — we don't know the type, so we don't constrain it.
           A comment in the output explains why.

  ADR-019: Enum values are always strings in the output (we coerce them during
           inference). JSON Schema enum allows mixed types, but string enums are
           more portable across code generators.

  ADR-020: PII fields are annotated with a custom x-pii extension property.
           This is non-standard but follows the OpenAPI extension convention
           (x- prefix). It allows downstream tools to filter PII fields.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ..models import FieldSchema, FieldType, InferredSchema, StreamProfile

logger = logging.getLogger(__name__)


# ── Type mapping ───────────────────────────────────────────────────────────────
# Maps StreamForge FieldType → JSON Schema type + format.
# Reference: https://json-schema.org/understanding-json-schema/reference/type

_TYPE_MAP: dict[FieldType, dict] = {
    FieldType.STRING:             {"type": "string"},
    FieldType.INTEGER:            {"type": "integer"},
    FieldType.FLOAT:              {"type": "number"},
    FieldType.BOOLEAN:            {"type": "boolean"},
    FieldType.TIMESTAMP_EPOCH_MS: {"type": "integer", "format": "int64",
                                   "description": "Unix epoch milliseconds"},
    FieldType.TIMESTAMP_ISO8601:  {"type": "string", "format": "date-time"},
    FieldType.TIMESTAMP_RFC2822:  {"type": "string", "format": "date-time",
                                   "description": "RFC 2822 date-time string"},
    FieldType.DATE:               {"type": "string", "format": "date"},
    FieldType.UUID:               {"type": "string", "format": "uuid",
                                   "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"},
    FieldType.EMAIL:              {"type": "string", "format": "email"},
    FieldType.PHONE:              {"type": "string", "format": "phone"},
    FieldType.ARRAY:              {"type": "array"},
    FieldType.OBJECT:             {"type": "object"},
    FieldType.NULL:               {"type": "null"},
    FieldType.MIXED:              {},          # Unconstrained — see ADR-018
}


def field_to_json_schema(field: FieldSchema) -> dict:
    """
    Convert one FieldSchema to a JSON Schema property definition.

    Args:
        field: A FieldSchema from the inference engine.

    Returns:
        JSON Schema property dict. Compatible with Draft 2020-12.
    """
    base = _TYPE_MAP.get(field.field_type, {}).copy()

    # Mixed type annotation — honest about uncertainty
    if field.field_type == FieldType.MIXED:
        base["$comment"] = "Mixed type field — StreamForge observed multiple types. Unconstrained."

    # Enum values — only set if we have them
    if field.enum_values:
        base["enum"] = field.enum_values

    # Nullable: wrap in anyOf
    if field.nullable and field.field_type != FieldType.NULL:
        base = {"anyOf": [base, {"type": "null"}]}

    # Description from LLM-generated notes
    if field.notes:
        base["description"] = field.notes

    # PII annotation (non-standard x- extension, follows OpenAPI convention)
    if field.pii_categories:
        base["x-pii"] = [cat.value for cat in field.pii_categories]

    # Confidence annotation — useful for downstream data quality tools
    base["x-streamforge-confidence"] = round(field.confidence, 4)
    base["x-streamforge-presence-rate"] = round(field.presence_rate, 4)

    return base


def schema_to_json_schema(
    schema: InferredSchema,
    include_examples: bool = True,
) -> dict:
    """
    Convert an InferredSchema to a complete JSON Schema document.

    The output is a JSON Schema "object" type where each field path becomes
    a nested property. Dot-notation paths are expanded into nested objects.

    Args:
        schema:           The InferredSchema to export.
        include_examples: Whether to include sample_values as JSON Schema examples.

    Returns:
        Complete JSON Schema document (dict, serialisable to JSON).
    """
    # Build flat property definitions first
    flat_properties: dict[str, dict] = {}
    required_fields: list[str] = []

    for f in schema.fields:
        prop = field_to_json_schema(f)
        if include_examples and f.sample_values:
            prop["examples"] = f.sample_values[:3]
        flat_properties[f.path] = prop

        # Top-level required fields
        if f.required and "." not in f.path:
            required_fields.append(f.path)

    # Expand dot-notation into nested object structure
    nested = _expand_dot_notation(flat_properties)

    doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://streamforge.io/schemas/{schema.stream_name}.json",
        "title": schema.stream_name,
        "description": (
            f"Auto-inferred schema for stream '{schema.stream_name}'. "
            f"Generated by StreamForge on {schema.inferred_at[:10]}. "
            f"Model: {schema.inference_model}. "
            f"Confidence: {schema.inference_confidence:.0%}. "
            f"Based on {schema.event_count_sampled} sampled events."
        ),
        "type": "object",
        "properties": nested,
    }

    # Top-level required array (only non-nested fields)
    top_required = [f for f in required_fields if "." not in f]
    if top_required:
        doc["required"] = top_required

    # Event types as an enum hint (informational)
    if schema.top_level_event_types:
        doc["x-streamforge-event-types"] = schema.top_level_event_types

    # Metadata as custom extension
    doc["x-streamforge-meta"] = {
        "stream_name":         schema.stream_name,
        "version":             schema.version,
        "inferred_at":         schema.inferred_at,
        "event_count_sampled": schema.event_count_sampled,
        "inference_model":     schema.inference_model,
        "inference_confidence": schema.inference_confidence,
    }

    return doc


def profile_to_json_schema(profile: StreamProfile) -> dict:
    """
    Convert a StreamProfile (multi-cluster) to a JSON Schema with oneOf variants.

    Each sub-schema becomes a variant in a oneOf array. This accurately
    represents polymorphic event streams where different event types
    have different shapes.

    Example output structure:
      {
        "oneOf": [
          { "title": "payment_initiated", "properties": {...} },
          { "title": "payment_completed", "properties": {...} }
        ]
      }
    """
    variants = []
    for sub in profile.sub_schemas:
        # Build a minimal InferredSchema-like object for the sub-schema
        from ..models import InferredSchema as IS
        sub_inferred = IS(
            stream_name=sub.cluster_id,
            version="1.0.0",
            inferred_at=profile.profiled_at,
            event_count_sampled=sub.event_count,
            fields=sub.fields,
            inference_model=profile.profile_model,
            inference_confidence=sub.inference_confidence,
        )
        variant = schema_to_json_schema(sub_inferred, include_examples=False)
        variant["title"] = sub.cluster_id
        variant["x-streamforge-sample-rate"] = sub.sample_rate
        variants.append(variant)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://streamforge.io/schemas/{profile.stream_name}-profile.json",
        "title": profile.stream_name,
        "description": (
            f"Multi-cluster schema profile for '{profile.stream_name}'. "
            f"Discovered {len(profile.sub_schemas)} sub-schema(s) via {profile.discovery_method}."
        ),
        "oneOf": variants,
        "x-streamforge-meta": {
            "stream_name":          profile.stream_name,
            "profiled_at":          profile.profiled_at,
            "total_events_sampled": profile.total_events_sampled,
            "parse_success_rate":   profile.parse_success_rate,
            "discovery_method":     profile.discovery_method,
            "sub_schema_count":     len(profile.sub_schemas),
        },
    }


def export_to_file(
    schema: InferredSchema,
    output_path: str,
    indent: int = 2,
) -> str:
    """
    Export InferredSchema to a JSON Schema file.

    Args:
        schema:      The schema to export.
        output_path: File path to write. Created if it doesn't exist.
        indent:      JSON indentation level (2 is standard).

    Returns:
        Absolute path of the written file.
    """
    doc = schema_to_json_schema(schema)
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=indent, ensure_ascii=False), encoding="utf-8")
    logger.info("Exported JSON Schema: %s", p)
    return str(p.resolve())


# ── Internal helpers ───────────────────────────────────────────────────────────

def _expand_dot_notation(flat: dict[str, dict]) -> dict:
    """
    Convert dot-notation field paths into a nested JSON Schema properties dict.

    Example:
      {"user.email": {...}, "user.name": {...}, "amount": {...}}
      →
      {
        "user": {"type": "object", "properties": {"email": {...}, "name": {...}}},
        "amount": {...}
      }
    """
    nested: dict = {}

    for path, schema_def in flat.items():
        parts = path.split(".")

        # Walk the nesting structure, creating intermediate objects as needed
        target = nested
        for part in parts[:-1]:
            if part not in target:
                target[part] = {"type": "object", "properties": {}}
            elif "properties" not in target[part]:
                target[part]["properties"] = {}
            target = target[part]["properties"]

        # Set the leaf property
        target[parts[-1]] = schema_def

    return nested
