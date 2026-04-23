"""Drift detection endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..store import get_store

router = APIRouter()


@router.get("/drift/active")
async def active_drifts():
    """Get list of active drift alerts."""
    store = get_store()
    return store.get_active_drifts()


@router.get("/drift/history")
async def drift_history():
    """Get drift detection history (last 50 events)."""
    store = get_store()
    # For now, same as active — could add resolved drifts later
    return store.get_active_drifts()
