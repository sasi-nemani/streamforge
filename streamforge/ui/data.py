"""
StreamForge Dashboard — Data Loading Functions (cached)
"""

from __future__ import annotations

from datetime import datetime as _dt

import streamlit as st
import yaml

from .styling import CONSUMERS_SUBDIR, DRIFT_DIR, SCHEMAS_DIR


@st.cache_data(ttl=30)
def load_all_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    if not SCHEMAS_DIR.exists():
        return schemas
    for schema_file in sorted(SCHEMAS_DIR.glob("*/schema.yaml")):
        try:
            data = yaml.safe_load(schema_file.read_text()) or {}
            schemas[schema_file.parent.name] = data
        except Exception:
            pass
    return schemas


@st.cache_data(ttl=30)
def load_profile(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_consumers(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / CONSUMERS_SUBDIR
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_drift_reports(stream_name: str) -> list[tuple[str, str]]:
    d = DRIFT_DIR / stream_name
    if not d.exists():
        return []
    return [(f.name, f.read_text()) for f in sorted(d.glob("*.md"), reverse=True)]


@st.cache_data(ttl=15)
def load_open_incidents(stream_name: str) -> list[dict]:
    """Return open drift incidents from drift_state.yaml (cached 15 s)."""
    import yaml as _yaml
    p = SCHEMAS_DIR / stream_name / "drift_state.yaml"
    if not p.exists():
        return []
    try:
        doc = _yaml.safe_load(p.read_text())
        return [
            inc for inc in (doc.get("incidents") or [])
            if inc.get("status") == "open"
        ]
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_policy(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=15)
def load_poll_state(stream_name: str) -> dict | None:
    """
    Load the last-polled state written by watch_stream after every poll cycle.
    Returns dict with keys: ts, sampled, window_size, new_events — or None if
    watch has never run for this stream.
    """
    import json as _json
    p = SCHEMAS_DIR / stream_name / ".watch_state" / "last_polled.json"
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text())
    except Exception:
        return None


def _is_live(stream_name: str, stale_minutes: int = 15) -> bool:
    """
    Return True if watch_stream polled this stream within the last stale_minutes.
    Uses last_polled.json written after every watch cycle.
    """
    ps = load_poll_state(stream_name)
    if not ps or not ps.get("ts"):
        return False
    try:
        polled_at = _dt.fromisoformat(ps["ts"]).replace(tzinfo=None)
        age = (_dt.utcnow() - polled_at).total_seconds()
        return age < stale_minutes * 60
    except Exception:
        return False
