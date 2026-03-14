import json
import logging
from pathlib import Path

import yaml

from .models import FieldSchema, FieldType, InferredSchema

logger = logging.getLogger(__name__)


def _field_to_yaml_dict(field: FieldSchema) -> dict:
    d: dict = {
        "path": field.path,
        "type": field.field_type.value,
        "required": field.required,
        "nullable": field.nullable,
        "presence_rate": round(field.presence_rate, 4),
        "confidence": round(field.confidence, 4),
    }
    if field.pii_categories:
        d["pii"] = [p.value for p in field.pii_categories]
    if field.enum_values:
        d["enum_values"] = field.enum_values
    if field.notes:
        d["notes"] = field.notes
    return d


def write_schema(schema: InferredSchema, output_dir: str) -> str:
    """Write schema.yaml. Returns path written."""
    out = Path(output_dir) / schema.stream_name
    out.mkdir(parents=True, exist_ok=True)

    # Build ordered structure manually for readability
    doc = {
        "stream": schema.stream_name,
        "version": schema.version,
        "inferred_at": schema.inferred_at,
        "inference_confidence": round(schema.inference_confidence, 4),
        "inference_model": schema.inference_model,
        "event_count_sampled": schema.event_count_sampled,
    }
    if schema.top_level_event_types:
        doc["event_types"] = schema.top_level_event_types

    doc["fields"] = [_field_to_yaml_dict(f) for f in schema.fields]

    header = (
        f"# StreamForge Schema — {schema.stream_name}\n"
        f"# Version: {schema.version}\n"
        f"# Inferred: {schema.inferred_at}\n"
        f"# Events sampled: {schema.event_count_sampled}\n"
        f"# Overall confidence: {schema.inference_confidence:.0%}\n"
        f"#\n"
        f"# This file is the source of truth for stream: {schema.stream_name}\n"
        f"# Edit this file to declare corrections. Run 'streamforge watch' to detect future drift.\n\n"
    )

    schema_path = out / "schema.yaml"
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(doc, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("Written schema: %s", schema_path)
    return str(schema_path)


def write_inference_report(schema: InferredSchema, output_dir: str) -> str:
    """Write inference_report.md. Returns path written."""
    out = Path(output_dir) / schema.stream_name
    out.mkdir(parents=True, exist_ok=True)

    pii_fields = [f for f in schema.fields if f.pii_categories]
    low_confidence = [f for f in schema.fields if f.confidence < 0.8]
    mixed_fields = [f for f in schema.fields if f.field_type == FieldType.MIXED]
    rare_fields = [f for f in schema.fields if f.presence_rate < 0.1]

    lines = [
        f"# Inference Report — {schema.stream_name}",
        f"",
        f"**Inferred:** {schema.inferred_at}  ",
        f"**Model:** {schema.inference_model}  ",
        f"**Events sampled:** {schema.event_count_sampled}  ",
        f"**Overall confidence:** {schema.inference_confidence:.0%}",
        f"",
        f"---",
        f"",
        f"## Field Summary",
        f"",
        f"| Field | Type | Required | Confidence | PII |",
        f"|-------|------|----------|------------|-----|",
    ]

    for f in schema.fields:
        pii_str = ", ".join(p.value for p in f.pii_categories) if f.pii_categories else "—"
        req_str = "✓" if f.required else "○"
        lines.append(
            f"| `{f.path}` | {f.field_type.value} | {req_str} | {f.confidence:.0%} | {pii_str} |"
        )

    if pii_fields:
        lines += ["", "---", "", "## PII Fields", ""]
        for f in pii_fields:
            cats = ", ".join(p.value for p in f.pii_categories)
            lines.append(f"- **`{f.path}`** — {cats}")

    if low_confidence:
        lines += ["", "---", "", "## Low Confidence Fields (< 80%)", ""]
        for f in low_confidence:
            lines.append(f"- **`{f.path}`** — {f.confidence:.0%} confidence — {f.notes or 'no notes'}")

    if mixed_fields:
        lines += ["", "---", "", "## Mixed Type Fields", ""]
        for f in mixed_fields:
            lines.append(f"- **`{f.path}`** — {f.notes or 'type inconsistency detected'}")

    if rare_fields:
        lines += ["", "---", "", "## Rare Fields (< 10% presence)", ""]
        for f in rare_fields:
            lines.append(f"- **`{f.path}`** — present in {f.presence_rate:.0%} of events")

    report_path = out / "inference_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info("Written report: %s", report_path)
    return str(report_path)


def write_samples(sample_events: list[dict], output_dir: str, stream_name: str) -> str:
    """Write sample events used for inference."""
    out = Path(output_dir) / stream_name / ".samples"
    out.mkdir(parents=True, exist_ok=True)
    samples_path = out / "latest.json"
    with open(samples_path, "w", encoding="utf-8") as f:
        json.dump(sample_events, f, indent=2)
    return str(samples_path)


def load_schema(schema_path: str) -> InferredSchema:
    """Load a schema.yaml back into InferredSchema model."""
    with open(schema_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    fields = []
    for fd in doc.get("fields", []):
        fields.append(FieldSchema(
            name=fd["path"].split(".")[-1],
            path=fd["path"],
            field_type=FieldType(fd["type"]),
            nullable=fd.get("nullable", False),
            required=fd.get("required", True),
            presence_rate=fd.get("presence_rate", 1.0),
            enum_values=fd.get("enum_values"),
            pii_categories=fd.get("pii", []),
            confidence=fd.get("confidence", 1.0),
            notes=fd.get("notes"),
        ))

    return InferredSchema(
        stream_name=doc["stream"],
        version=doc.get("version", "1.0.0"),
        inferred_at=doc.get("inferred_at", ""),
        event_count_sampled=doc.get("event_count_sampled", 0),
        fields=fields,
        top_level_event_types=doc.get("event_types"),
        inference_model=doc.get("inference_model", "unknown"),
        inference_confidence=doc.get("inference_confidence", 1.0),
    )
