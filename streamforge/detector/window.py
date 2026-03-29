"""Rolling event window and checkpoint persistence."""

import json as _json
import logging
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from ..sampler import reservoir_sample

logger = logging.getLogger(__name__)


class EventWindow:
    """
    Bounded rolling buffer of recent stream events used as the drift comparison
    population.  Each watch poll adds newly-seen events; the oldest fall off
    when capacity is reached (collections.deque maxlen behaviour).

    Sampling from the full window — rather than from only the latest batch —
    gives statistically stable signals and makes slow drift (e.g. a field
    presence rate falling from 80% to 60% over hours) detectable.
    """

    def __init__(self, capacity: int = 2000) -> None:
        self._buf: deque[dict] = deque(maxlen=capacity)

    def add(self, events: list[dict]) -> None:
        """Append new events; oldest are evicted automatically when at capacity."""
        self._buf.extend(events)

    def sample(self, n: int) -> list[dict]:
        """Reservoir-sample n events from the current window contents."""
        return reservoir_sample(list(self._buf), n)

    def __len__(self) -> int:
        return len(self._buf)


def _load_new_events(
    stream_path: str,
    file_line_counts: dict[str, int],
) -> list[dict]:
    """
    Load only lines that have been appended to files since the last call.

    Tracks the number of lines already read per file (not mtime), so:
    - Files that have grown get their new lines read.
    - Files that haven't changed are skipped cheaply.
    - Rotated / replaced files (line count drops) are re-read in full.

    Returns a flat list of successfully parsed event dicts.
    """
    folder = Path(stream_path)
    files = sorted(
        f for f in folder.rglob("*")
        if f.suffix in (".ndjson", ".json") and f.is_file()
        and not f.name.startswith("._")
    )
    new_events: list[dict] = []

    for file_path in files:
        key = str(file_path)
        prev_count = file_line_counts.get(key, 0)
        try:
            # Quick line count to detect rotation — iterates without buffering
            with open(file_path, encoding="utf-8") as fh:
                current_count = sum(1 for _ in fh)
        except OSError:
            continue

        if current_count < prev_count:
            # File was truncated / rotated — read from the top
            prev_count = 0

        if current_count <= prev_count:
            continue  # nothing new

        try:
            # Stream only new lines — O(new_lines) memory, not O(total_lines)
            with open(file_path, encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, 1):
                    if line_num <= prev_count:
                        continue
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        ev = _json.loads(stripped)
                        if isinstance(ev, dict):
                            new_events.append(ev)
                    except _json.JSONDecodeError:
                        pass
        except OSError:
            continue

        file_line_counts[key] = current_count

    return new_events


def _write_poll_state(schema_dir: Path, sampled: int, window_size: int, new_events: int) -> None:
    """
    Write a small JSON file after every watch poll so the UI can show
    accurate last-polled time and sample counts.

    File: <schema_dir>/.watch_state/last_polled.json
    Contents: {ts, sampled, window_size, new_events}
    """
    try:
        state_dir = schema_dir / ".watch_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "ts": datetime.now(UTC).isoformat(),
            "sampled": sampled,
            "window_size": window_size,
            "new_events": new_events,
        }
        (state_dir / "last_polled.json").write_text(_json.dumps(state))
    except OSError as e:
        logger.warning("Could not write poll state: %s", e)


def _save_checkpoint(window: EventWindow, checkpoint_path: Path) -> None:
    """
    Persist the rolling window contents to disk as NDJSON.

    Called after every successful poll cycle.  The file is overwritten in full
    (not appended) so it always reflects the current window state.  If writing
    fails (permissions, disk full) it logs a warning and continues — a stale or
    missing checkpoint is safe; the watcher will simply reseed from stream files.
    """
    tmp = checkpoint_path.with_suffix(".tmp")
    try:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            for event in window._buf:
                fh.write(_json.dumps(event) + "\n")
            fh.flush()
        tmp.replace(checkpoint_path)  # atomic on POSIX
        logger.debug("Checkpoint saved: %d events → %s", len(window), checkpoint_path)
    except OSError as e:
        logger.warning("Could not save window checkpoint (%s): %s", checkpoint_path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _load_checkpoint(checkpoint_path: Path) -> list[dict]:
    """
    Load window events from a checkpoint file written by _save_checkpoint.

    Returns an empty list when the file doesn't exist or can't be read.
    Malformed lines are silently skipped — a partially-corrupt checkpoint is
    better than crashing: the watcher will fill in missing events on the next
    poll from the live stream files.
    """
    if not checkpoint_path.exists():
        return []
    events: list[dict] = []
    try:
        with open(checkpoint_path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    ev = _json.loads(stripped)
                    if isinstance(ev, dict):
                        events.append(ev)
                except _json.JSONDecodeError:
                    pass
        logger.info("Loaded %d events from checkpoint: %s", len(events), checkpoint_path)
    except OSError as e:
        logger.warning("Could not read window checkpoint (%s): %s", checkpoint_path, e)
    return events
