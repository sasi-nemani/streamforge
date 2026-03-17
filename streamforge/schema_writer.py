import json
import logging
from pathlib import Path

import yaml

from .models import FieldSchema, FieldType, InferredSchema, StreamProfile

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


def _inject_parent_objects(fields: list[FieldSchema]) -> list[FieldSchema]:
    """
    Ensure nested JSON structure is self-documenting in schema.yaml.

    For any dot-notation path whose parent object is not already an explicit
    field, injects a synthetic FieldSchema(type=object) entry immediately
    before the first child.  This makes the nesting visible in the schema and
    gives the generator enough information to reconstruct nested JSON.

    Examples:
        "user.email", "user.name"  →  inserts "user" (object) before them
        "items[].id"               →  inserts "items" (array)  before it
        "amount"                   →  no parent, left alone

    Fields that are already present at a path (either inferred by the LLM or
    previously injected) are never duplicated.
    """
    existing_paths = {f.path for f in fields}
    # Map parent_path → first index where a child appears (insertion point)
    parent_first_child: dict[str, int] = {}

    for idx, field in enumerate(fields):
        parts = field.path.split(".")
        for depth in range(1, len(parts)):
            # Strip [] suffix from array-child segments to get the container path
            parent = ".".join(
                p[:-2] if p.endswith("[]") else p
                for p in parts[:depth]
            )
            if parent and parent not in existing_paths and parent not in parent_first_child:
                parent_first_child[parent] = idx

    if not parent_first_child:
        return fields

    # Build insertion list — only inject each parent once
    injected: dict[str, FieldSchema] = {}
    for parent_path, _insert_at in parent_first_child.items():
        # Determine representative type: array if the parent is referenced as "parent[].*"
        is_array = any(
            f.path.startswith(f"{parent_path}[].") or f.path.startswith(f"{parent_path}[]")
            for f in fields
        )
        parent_type = FieldType.ARRAY if is_array else FieldType.OBJECT

        # Derive presence/required from direct children for accuracy
        children = [
            f for f in fields
            if f.path.startswith(f"{parent_path}.") or f.path.startswith(f"{parent_path}[]")
        ]
        child_presence = min((c.presence_rate for c in children), default=1.0)
        child_required = all(c.required for c in children)
        child_confidence = min((c.confidence for c in children), default=1.0)

        # Short list of direct child leaf names for the notes field
        direct_children = sorted({
            c.path[len(parent_path):].lstrip(".").lstrip("[").lstrip("].").split(".")[0]
            for c in children
        })[:6]
        notes = f"Nested {parent_type.value} — contains: {', '.join(direct_children)}"

        injected[parent_path] = FieldSchema(
            name=parent_path.split(".")[-1],
            path=parent_path,
            field_type=parent_type,
            required=child_required,
            nullable=False,
            presence_rate=round(child_presence, 4),
            confidence=round(child_confidence, 4),
            notes=notes,
        )

    # Rebuild field list, inserting parent stubs just before their first child
    result: list[FieldSchema] = []
    inserted: set[str] = set()
    for idx, field in enumerate(fields):
        # Insert any parents whose first-child index is this field
        for parent_path, insert_at in parent_first_child.items():
            if insert_at == idx and parent_path not in inserted:
                result.append(injected[parent_path])
                inserted.add(parent_path)
        result.append(field)

    return result


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

    # Inject explicit object/array entries for nested paths so the schema is
    # self-documenting and the generate command can reconstruct nested JSON.
    tagged_fields = _inject_parent_objects(schema.fields)
    doc["fields"] = [_field_to_yaml_dict(f) for f in tagged_fields]

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


def load_profile(schema_dir: Path) -> "dict | None":
    """
    Load profile.yaml from the given schema directory if it exists.
    Returns the raw parsed dict or None when the file is absent.
    Callers use this to decide whether multi-schema drift detection is available.
    """
    p = schema_dir / "profile.yaml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def write_inference_report(
    schema: InferredSchema,
    output_dir: str,
    ingest_stats: "dict | None" = None,
) -> str:
    """
    Write inference_report.md. Returns path written.

    ingest_stats (optional): dict with keys total, clean, partial.
    When provided, an Ingest Quality section is prepended showing how many
    events were used vs excluded from inference.
    """
    out = Path(output_dir) / schema.stream_name
    out.mkdir(parents=True, exist_ok=True)

    pii_fields = [f for f in schema.fields if f.pii_categories]
    low_confidence = [f for f in schema.fields if f.confidence < 0.8]
    mixed_fields = [f for f in schema.fields if f.field_type == FieldType.MIXED]
    rare_fields = [f for f in schema.fields if f.presence_rate < 0.1]

    lines = [
        f"# Inference Report — {schema.stream_name}",
        "",
        f"**Inferred:** {schema.inferred_at}  ",
        f"**Model:** {schema.inference_model}  ",
        f"**Events sampled:** {schema.event_count_sampled}  ",
        f"**Overall confidence:** {schema.inference_confidence:.0%}",
        "",
        "---",
        "",
    ]

    if ingest_stats:
        total = ingest_stats.get("total", 0) or 1
        clean = ingest_stats.get("clean", 0)
        partial = ingest_stats.get("partial", 0)
        parse_rate = clean / total
        lines += [
            "## Ingest Quality",
            "",
            "| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |",
            "|---|---|---|---|",
            f"| {total} | {clean} | {partial} | {parse_rate:.1%} |",
            "",
            "---",
            "",
        ]

    lines += [
        "## Field Summary",
        "",
        "| Field | Type | Required | Confidence | PII |",
        "|-------|------|----------|------------|-----|",
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


def write_profile(profile: StreamProfile, output_dir: str) -> str:
    """Write profile.yaml containing all discovered sub-schemas. Returns path written."""
    out = Path(output_dir) / profile.stream_name
    out.mkdir(parents=True, exist_ok=True)

    n_sub = len(profile.sub_schemas)
    header = (
        f"# StreamForge Stream Profile — {profile.stream_name}\n"
        f"# Profiled: {profile.profiled_at}\n"
        f"# Events sampled: {profile.total_events_sampled}\n"
        f"# Parse success rate: {profile.parse_success_rate:.1%}\n"
        f"# Sub-schemas discovered: {n_sub}\n"
        f"# Discovery method: {profile.discovery_method}\n"
        f"#\n"
        f"# Each sub-schema is a distinct event shape found in the stream.\n"
        f"# Edit fields to declare corrections. Run 'streamforge watch' to detect drift.\n\n"
    )

    sub_docs = []
    for sub in profile.sub_schemas:
        sub_docs.append({
            "cluster_id": sub.cluster_id,
            "detection_method": sub.detection_method,
            "event_count": sub.event_count,
            "sample_rate": sub.sample_rate,
            "inference_confidence": round(sub.inference_confidence, 4),
            "top_keys": sub.top_keys,
            "fields": [_field_to_yaml_dict(f) for f in _inject_parent_objects(sub.fields)],
        })

    doc = {
        "stream": profile.stream_name,
        "profiled_at": profile.profiled_at,
        "total_events_sampled": profile.total_events_sampled,
        "parse_success_rate": round(profile.parse_success_rate, 4),
        "discovery_method": profile.discovery_method,
        # routing_field is the explicit field name used to distinguish clusters at
        # runtime (e.g. "event_type").  None means structural fingerprint routing.
        # Storing it here avoids re-deriving from hash logic during watch/plan.
        "routing_field": profile.routing_field,
        "profile_model": profile.profile_model,
        "sub_schemas": sub_docs,
    }

    profile_path = out / "profile.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(doc, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("Written profile: %s", profile_path)
    return str(profile_path)


def write_profile_report(profile: StreamProfile, output_dir: str) -> str:
    """Write profile_report.md with per-cluster field breakdowns. Returns path written."""
    out = Path(output_dir) / profile.stream_name
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Stream Profile Report — {profile.stream_name}",
        "",
        f"**Profiled:** {profile.profiled_at}  ",
        f"**Model:** {profile.profile_model}  ",
        f"**Events sampled:** {profile.total_events_sampled}  ",
        f"**Parse success rate:** {profile.parse_success_rate:.1%}  ",
        f"**Discovery method:** {profile.discovery_method}  ",
        f"**Sub-schemas:** {len(profile.sub_schemas)}",
        "",
        "---",
        "",
        "## Sub-Schema Summary",
        "",
        "| Cluster | Events | % Stream | Fields | Confidence | PII |",
        "|---------|--------|----------|--------|------------|-----|",
    ]

    for sub in profile.sub_schemas:
        pii_fields = [f for f in sub.fields if f.pii_categories]
        pii_str = ", ".join(f"`{f.path}`" for f in pii_fields[:3]) if pii_fields else "—"
        lines.append(
            f"| `{sub.cluster_id}` | {sub.event_count} | {sub.sample_rate:.0%} | "
            f"{len(sub.fields)} | {sub.inference_confidence:.0%} | {pii_str} |"
        )

    for sub in profile.sub_schemas:
        pii_fields = [f for f in sub.fields if f.pii_categories]
        lines += [
            "",
            "---",
            "",
            f"## `{sub.cluster_id}`",
            "",
            f"- **Events:** {sub.event_count} ({sub.sample_rate:.0%} of stream)",
            f"- **Top-level keys:** {', '.join(sub.top_keys[:10])}",
            f"- **Confidence:** {sub.inference_confidence:.0%}",
            "",
            "| Field | Type | Required | Confidence | PII |",
            "|-------|------|----------|------------|-----|",
        ]
        for f in sub.fields:
            pii_str = ", ".join(p.value for p in f.pii_categories) if f.pii_categories else "—"
            req = "✓" if f.required else "○"
            lines.append(
                f"| `{f.path}` | {f.field_type.value} | {req} | {f.confidence:.0%} | {pii_str} |"
            )
        if pii_fields:
            lines += ["", "**PII in this cluster:** " + ", ".join(
                f"`{f.path}` ({', '.join(p.value for p in f.pii_categories)})" for f in pii_fields
            )]

    report_path = out / "profile_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info("Written profile report: %s", report_path)
    return str(report_path)


def load_schema(schema_path: str) -> InferredSchema:
    """Load a schema.yaml back into InferredSchema model."""
    with open(schema_path, encoding="utf-8") as f:
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
