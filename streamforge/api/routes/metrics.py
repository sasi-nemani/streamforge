"""Metrics endpoint — aggregated statistics."""
from __future__ import annotations

from fastapi import APIRouter

from ..store import get_store

router = APIRouter()


@router.get("/metrics/summary")
async def metrics_summary():
    """Get aggregated metrics across all sources."""
    store = get_store()
    return store.get_metrics_summary()
