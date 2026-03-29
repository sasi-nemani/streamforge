"""
streamforge.history.snapshot — Snapshot I/O
============================================

Archive and retrieve dated profile snapshots.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..models import SnapshotMeta

logger = logging.getLogger(__name__)


def snapshot_dir(output_dir: str, stream_name: str, date: str) -> Path:
    """Return path to a specific snapshot directory (does not create it)."""
    return Path(output_dir) / stream_name / "history" / date


def write_snapshot(
    profile_raw: dict,
    stream_name: str,
    output_dir: str,
    triggered_by: str = "manual",
    date: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """
    Archive profile_raw (as loaded by schema_writer.load_profile) into
    schemas/<stream>/history/<YYYY-MM-DD>/profile.yaml + meta.yaml.

    If a snapshot for today already exists and force=False, logs a warning and
    overwrites it (idempotent re-runs are fine — same-day snapshots are rare
    and should not crash the caller).

    Returns (profile_path, meta_path) as strings.
    """
    today = date or datetime.now(UTC).strftime("%Y-%m-%d")
    snap_dir = snapshot_dir(output_dir, stream_name, today)

    if snap_dir.exists() and not force:
        logger.warning(
            "Snapshot for %s/%s already exists — overwriting", stream_name, today
        )

    snap_dir.mkdir(parents=True, exist_ok=True)

    # Write profile.yaml verbatim
    profile_path = snap_dir / "profile.yaml"
    with open(profile_path, "w", encoding="utf-8") as fh:
        yaml.dump(profile_raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Build and write meta.yaml
    sub_schemas = profile_raw.get("sub_schemas", [])
    field_count = sum(len(s.get("fields", [])) for s in sub_schemas)
    meta = SnapshotMeta(
        stream_name=stream_name,
        snapshot_date=today,
        profiled_at=profile_raw.get("profiled_at", today),
        total_events_sampled=profile_raw.get("total_events_sampled", 0),
        cluster_ids=[s["cluster_id"] for s in sub_schemas],
        field_count=field_count,
        triggered_by=triggered_by,
    )
    meta_path = snap_dir / "meta.yaml"
    with open(meta_path, "w", encoding="utf-8") as fh:
        yaml.dump(meta.model_dump(), fh, default_flow_style=False, sort_keys=False)

    logger.info("Snapshot written: %s", snap_dir)
    return str(profile_path), str(meta_path)


def list_snapshots(output_dir: str, stream_name: str) -> list[Path]:
    """
    Return all valid snapshot directories sorted chronologically (oldest first).

    A valid snapshot has both profile.yaml and meta.yaml. YYYY-MM-DD directory
    names sort lexicographically = chronologically, so no date parsing needed.
    """
    history_root = Path(output_dir) / stream_name / "history"
    if not history_root.exists():
        return []
    dirs = sorted(
        d for d in history_root.iterdir()
        if d.is_dir()
        and (d / "profile.yaml").exists()
        and (d / "meta.yaml").exists()
    )
    return dirs


def load_snapshot_profile(snapshot_path: Path) -> dict:
    """Load profile.yaml from a snapshot directory. Raises FileNotFoundError if missing."""
    p = snapshot_path / "profile.yaml"
    if not p.exists():
        raise FileNotFoundError(f"No profile.yaml in snapshot: {snapshot_path}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_snapshot_meta(snapshot_path: Path) -> SnapshotMeta:
    """Load meta.yaml from a snapshot directory. Returns SnapshotMeta model."""
    p = snapshot_path / "meta.yaml"
    if not p.exists():
        raise FileNotFoundError(f"No meta.yaml in snapshot: {snapshot_path}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return SnapshotMeta(**raw)
