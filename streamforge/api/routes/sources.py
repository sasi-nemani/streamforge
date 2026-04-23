"""Sources endpoint — list connected data sources."""
from __future__ import annotations

from fastapi import APIRouter

from ..store import get_store

router = APIRouter()


@router.get("/sources")
async def list_sources():
    """List all connected data sources with status."""
    store = get_store()
    return store.get_sources()


