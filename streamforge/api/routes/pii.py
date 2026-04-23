"""PII detection endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..store import get_store

router = APIRouter()


@router.get("/pii/summary")
async def pii_summary():
    """Get PII field summary by category."""
    store = get_store()
    return store.get_pii_summary()


@router.get("/pii/fields")
async def pii_fields():
    """Get detailed PII field list."""
    store = get_store()
    summary = store.get_pii_summary()
    # Expand to field-level detail in future
    return {
        "total": summary["total"],
        "by_category": summary["by_category"],
        "fields": [],  # TODO: add field-level details
    }
