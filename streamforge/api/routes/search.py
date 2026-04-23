"""Search endpoints."""
from __future__ import annotations

import yaml
from fastapi import APIRouter

from ..store import get_store

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search_fields(q: str = "", type: str | None = None, pii_only: bool = False) -> dict:
    """Search fields across all streams."""
    store = get_store()
    results = []
    query = q.lower().strip()

    for schema_path in store._schema_dir.glob("*/schema.yaml"):
        stream_name = schema_path.parent.name
        try:
            schema = yaml.safe_load(schema_path.read_text())
        except Exception:
            continue

        for field in schema.get("fields", []):
            path = field.get("path", "")
            field_type = field.get("type", "")
            pii = field.get("pii", [])

            # Apply filters
            if pii_only and not pii:
                continue
            if type and field_type != type:
                continue
            if query and query not in path.lower():
                continue

            results.append({
                "stream": stream_name,
                "path": path,
                "type": field_type,
                "required": field.get("required", False),
                "nullable": field.get("nullable", True),
                "presence_rate": field.get("presence_rate", 0),
                "pii": pii,
                "notes": field.get("notes", ""),
            })

    return {
        "query": q,
        "filters": {"type": type, "pii_only": pii_only},
        "count": len(results),
        "results": results,
    }


@router.get("/types")
def get_field_types() -> dict:
    """Get all unique field types across streams."""
    store = get_store()
    types: set[str] = set()

    for schema_path in store._schema_dir.glob("*/schema.yaml"):
        try:
            schema = yaml.safe_load(schema_path.read_text())
            for field in schema.get("fields", []):
                if t := field.get("type"):
                    types.add(t)
        except Exception:
            continue

    return {"types": sorted(types)}
