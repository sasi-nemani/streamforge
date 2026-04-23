"""Stream detail endpoints."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from ..store import get_store

router = APIRouter(prefix="/api/streams", tags=["streams"])


def _extract_field_stats(samples: list[dict], field_path: str) -> dict:
    """Extract statistics for a field from sample data."""
    values: list[Any] = []

    for event in samples:
        val = event
        for key in field_path.split("."):
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val is not None:
            values.append(val)

    if not values:
        return {"sample_values": [], "enum_values": None, "range": None}

    sample_values = values[:5]

    # Detect enums (if <= 20 unique values and all strings)
    enum_values = None
    if all(isinstance(v, str) for v in values):
        unique = set(values)
        if len(unique) <= 20:
            counts = Counter(values)
            enum_values = [{"value": k, "count": v} for k, v in counts.most_common()]

    # Detect ranges for numeric/timestamp
    data_range = None
    numeric = [v for v in values if isinstance(v, (int, float))]
    if numeric:
        data_range = {"min": min(numeric), "max": max(numeric)}

    return {
        "sample_values": sample_values,
        "enum_values": enum_values,
        "range": data_range,
    }


@router.get("/{stream_name}")
def get_stream_detail(stream_name: str) -> dict:
    """Get full stream detail with field stats."""
    store = get_store()
    schema_path = store._schema_dir / stream_name / "schema.yaml"

    if not schema_path.exists():
        raise HTTPException(status_code=404, detail=f"Stream not found: {stream_name}")

    schema = yaml.safe_load(schema_path.read_text())

    # Load samples for statistics
    samples_path = store._schema_dir / stream_name / ".samples" / "latest.json"
    samples: list[dict] = []
    if samples_path.exists():
        try:
            samples = json.loads(samples_path.read_text())
        except Exception:
            pass

    # Enrich fields with stats
    fields = []
    for field in schema.get("fields", []):
        stats = _extract_field_stats(samples, field["path"])
        fields.append({
            "path": field["path"],
            "type": field.get("type", "unknown"),
            "required": field.get("required", False),
            "nullable": field.get("nullable", True),
            "presence_rate": field.get("presence_rate", 0),
            "confidence": field.get("confidence", 0),
            "pii": field.get("pii", []),
            "notes": field.get("notes", ""),
            "sample_values": stats["sample_values"],
            "enum_values": stats["enum_values"],
            "range": stats["range"],
        })

    # Load profile for sub-schema info
    profile_path = store._schema_dir / stream_name / "profile.yaml"
    sub_schemas = []
    if profile_path.exists():
        try:
            profile = yaml.safe_load(profile_path.read_text())
            for ss in profile.get("sub_schemas", []):
                sub_schemas.append({
                    "cluster_id": ss.get("cluster_id"),
                    "event_count": ss.get("event_count", 0),
                    "detection_method": ss.get("detection_method"),
                })
        except Exception:
            pass

    return {
        "stream": stream_name,
        "version": schema.get("version", "1.0.0"),
        "inferred_at": schema.get("inferred_at"),
        "inference_model": schema.get("inference_model"),
        "event_count_sampled": schema.get("event_count_sampled", 0),
        "fields": fields,
        "sub_schemas": sub_schemas,
        "sample_count": len(samples),
    }


@router.get("/{stream_name}/samples")
def get_stream_samples(stream_name: str, limit: int = 10) -> dict:
    """Get sample events from a stream."""
    store = get_store()
    samples_path = store._schema_dir / stream_name / ".samples" / "latest.json"

    if not samples_path.exists():
        raise HTTPException(status_code=404, detail=f"No samples for: {stream_name}")

    samples = json.loads(samples_path.read_text())
    return {"stream": stream_name, "samples": samples[:limit], "total": len(samples)}
