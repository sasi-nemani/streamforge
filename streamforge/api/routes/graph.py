"""Cross-topic dependency graph — the blast-radius view.

Powers the cockpit homepage: which fields are shared across topics, which are
defined INCONSISTENTLY (the cross-topic bugs no schema registry surfaces), and
the blast radius of changing a field (other topics + downstream consumers).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Query

from ...dependency_graph import SchemaGraph

router = APIRouter()

_CACHE: dict[str, dict] = {}


def _schemas_dir() -> str:
    return os.environ.get("STREAMFORGE_SCHEMA_DIR", "schemas")


def _types(node) -> list[dict]:
    by_type: dict[str, list[str]] = {}
    for u in node.usages:
        by_type.setdefault(u.field_type, []).append(u.stream_name)
    # Most-used type first so the UI can show the "majority" vs the outliers.
    return [
        {"type": t, "streams": sorted(s)}
        for t, s in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]


def _build_overview() -> dict:
    g = SchemaGraph.from_schemas(_schemas_dir())
    nodes = g._nodes  # noqa: SLF001 — internal map; read-only access here
    shared = [n for n in nodes.values() if len(n.usages) > 1]
    inconsistent = [n for n in shared if n.is_inconsistent]

    return {
        "overview": {
            "fields": len(nodes),
            "streams": g.meta.stream_count,
            "shared_fields": len(shared),
            "inconsistencies": len(inconsistent),
        },
        "inconsistencies": [
            {"field_path": n.field_path, "types": _types(n)}
            for n in sorted(inconsistent, key=lambda n: -len(n.usages))
        ],
        "shared_fields": [
            {
                "field_path": n.field_path,
                "streams": sorted(u.stream_name for u in n.usages),
                "count": len(n.usages),
                "inconsistent": n.is_inconsistent,
                "pii": sorted({p for u in n.usages for p in u.pii_categories}),
            }
            for n in sorted(shared, key=lambda n: -len(n.usages))
        ],
    }


@router.get("/graph")
async def graph_overview():
    key = _schemas_dir()
    if key not in _CACHE:
        _CACHE[key] = _build_overview()
    return _CACHE[key]


@router.get("/graph/field")
async def field_detail(path: str = Query(..., description="Field path, e.g. 'timestamp'")):
    """Blast radius for one field: every topic it appears in (with type + PII) and
    the downstream consumers that would be affected by a change."""
    schemas_dir = _schemas_dir()
    g = SchemaGraph.from_schemas(schemas_dir)
    node = g.field_usage(path)
    if node is None:
        return {"field_path": path, "found": False, "usages": [], "consumers": []}

    consumers: list[str] = []
    try:
        from ...consumer_registry import load_consumers

        for u in node.usages:
            for c in load_consumers(schemas_dir, u.stream_name):
                name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
                if name and name not in consumers:
                    consumers.append(name)
    except Exception:  # noqa: BLE001 — consumer registry is optional/best-effort
        pass

    return {
        "field_path": path,
        "found": True,
        "is_inconsistent": node.is_inconsistent,
        "usages": [
            {
                "stream": u.stream_name,
                "type": u.field_type,
                "presence_rate": u.presence_rate,
                "required": u.required,
                "pii": u.pii_categories,
            }
            for u in node.usages
        ],
        "consumers": consumers,
    }
