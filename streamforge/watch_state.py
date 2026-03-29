"""
Persistent watch loop state for StreamForge.

Persisted to .streamforge/state/{slug}.json after each cycle.
Loaded on startup to survive restarts without false drift alerts.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_DIR = Path(".streamforge") / "state"

_VALID_FIELDS = {
    "topic", "phase", "cycle_count", "warmup_remaining",
    "warmup_done", "stability_clean_count", "consecutive_drifts",
    "last_drift_at", "stable_since",
}


def _slug(topic: str) -> str:
    """Sanitize topic name for filesystem use."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", topic)


@dataclass
class WatchState:
    topic: str
    phase: str = "LEARNING"           # LEARNING | STABILIZING | STABLE
    cycle_count: int = 0
    warmup_remaining: int = 10        # decrements each cycle; 0 = done
    warmup_done: bool = False
    stability_clean_count: int = 0    # consecutive clean cycles in STABILIZING
    consecutive_drifts: int = 0       # consecutive drift cycles (flap suppression)
    last_drift_at: str | None = None   # ISO8601 timestamp of last drift
    stable_since: str | None = None   # ISO8601 timestamp when STABLE entered

    # --- persistence ---

    def save(self, state_dir: Path = _STATE_DIR) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / f"{_slug(self.topic)}.json"
        data = {
            "topic": self.topic,
            "phase": self.phase,
            "cycle_count": self.cycle_count,
            "warmup_remaining": self.warmup_remaining,
            "warmup_done": self.warmup_done,
            "stability_clean_count": self.stability_clean_count,
            "consecutive_drifts": self.consecutive_drifts,
            "last_drift_at": self.last_drift_at,
            "stable_since": self.stable_since,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)  # atomic on POSIX
        logger.debug("WatchState saved: %s", path)

    @classmethod
    def load(cls, topic: str, state_dir: Path = _STATE_DIR) -> WatchState:
        path = state_dir / f"{_slug(topic)}.json"

        if path.exists():
            try:
                data = json.loads(path.read_text())
                # Ensure topic matches (guard against slug collisions)
                data["topic"] = topic
                filtered = {k: v for k, v in data.items() if k in _VALID_FIELDS}
                return cls(**filtered)
            except Exception as exc:
                logger.warning("WatchState load failed (%s) — starting fresh: %s", path, exc)

        return cls(topic=topic)

    @classmethod
    def migrate_legacy(cls, topic: str, legacy_path: Path, state_dir: Path = _STATE_DIR) -> WatchState | None:
        """If a legacy .watch_state.json exists, migrate it to the new location."""
        if not legacy_path.exists():
            return None
        try:
            data = json.loads(legacy_path.read_text())
            non_topic_fields = _VALID_FIELDS - {"topic"}
            filtered = {k: v for k, v in data.items() if k in non_topic_fields}
            state = cls(topic=topic, **filtered)
            state.save(state_dir)
            legacy_path.unlink()
            logger.info("Migrated watch state from %s to %s", legacy_path, state_dir / f"{_slug(topic)}.json")
            return state
        except Exception as exc:
            logger.warning("Legacy WatchState migration failed: %s", exc)
            return None

    def mark_drift(self) -> None:
        self.consecutive_drifts += 1
        self.stability_clean_count = 0
        self.last_drift_at = datetime.now(UTC).isoformat()

    def mark_clean(self, stability_cycles_required: int = 3) -> bool:
        """Returns True if state just transitioned to STABLE."""
        self.consecutive_drifts = 0
        if self.phase == "STABILIZING":
            self.stability_clean_count += 1
            if self.stability_clean_count >= stability_cycles_required:
                self.phase = "STABLE"
                self.stable_since = datetime.now(UTC).isoformat()
                return True
        return False

    def tick_warmup(self, warmup_cycles: int = 10) -> None:
        """Call once per cycle during LEARNING phase."""
        self.cycle_count += 1
        if not self.warmup_done:
            self.warmup_remaining = max(0, self.warmup_remaining - 1)
            if self.warmup_remaining <= 0:
                self.warmup_done = True
                self.phase = "STABILIZING"

    @property
    def is_stable(self) -> bool:
        return self.phase == "STABLE"

    @property
    def is_learning(self) -> bool:
        return self.phase == "LEARNING"
