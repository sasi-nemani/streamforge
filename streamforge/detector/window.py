"""Rolling event window and checkpoint persistence."""

import json as _json
import logging
import random
import time as _time
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

    Supports both count-based AND time-based eviction:
      capacity:         max events in window (deque maxlen)
      max_age_seconds:  evict events older than this (0 = disabled)

    Time-based eviction is critical for high-throughput streams: at 1M/sec,
    a 2000-event window is 2ms of data. A 300-second window at 1M/sec is
    300M events (too many to hold), so the count cap still applies — but
    time eviction ensures stale events from quiet periods don't pollute
    the sample.

    Performance: sample() uses in-place reservoir sampling over the deque
    via indexed access — O(n) allocation where n=sample_size, NOT O(window_capacity).
    At 100K window capacity with 200 sample size, this is 200KB not 100MB.

    Configurable per topic via stream_policy.yaml:
      window_capacity: 5000
      window_max_age_seconds: 300
    """

    def __init__(self, capacity: int = 2000, max_age_seconds: int = 0) -> None:
        self._buf: deque[tuple[float, dict]] = deque(maxlen=capacity)
        self._max_age = max_age_seconds  # 0 = no time eviction

    def add(self, events: list[dict]) -> None:
        """Append new events with timestamp. Oldest evicted by deque maxlen."""
        now = _time.time()
        for e in events:
            self._buf.append((now, e))

    def evict_expired(self) -> int:
        """Remove events older than max_age_seconds. Returns count evicted."""
        if self._max_age <= 0:
            return 0
        cutoff = _time.time() - self._max_age
        evicted = 0
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()
            evicted += 1
        return evicted

    def sample(self, n: int) -> list[dict]:
        """Reservoir-sample n events directly from deque — O(n) memory, not O(len(buf)).

        Uses Algorithm R with indexed deque access. The deque supports O(1)
        __getitem__, so we never materialize the full window as a list.
        At 100K window with n=200, allocates 200 events not 100K.
        """
        self.evict_expired()
        buf_len = len(self._buf)
        if buf_len == 0:
            return []
        if buf_len <= n:
            return [self._buf[i][1] for i in range(buf_len)]

        # Algorithm R: reservoir of size n, then replace with probability n/i
        reservoir = [self._buf[i][1] for i in range(n)]
        for i in range(n, buf_len):
            j = random.randint(0, i)
            if j < n:
                reservoir[j] = self._buf[i][1]
        return reservoir

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def events(self) -> list[dict]:
        """Return all events without timestamps (for checkpoint compatibility)."""
        return [e for _, e in self._buf]


class ClusterWindowMap:
    """Per-cluster event windows — each cluster gets undiluted samples.

    Routes incoming events to the correct cluster window based on a routing
    field (e.g. event_type). Each cluster has its own EventWindow with its
    own capacity. Sampling from a cluster returns full sample_size events
    from that cluster only — no dilution across clusters.

    If an event doesn't match any known cluster, it goes to the unrouted list
    for new-cluster detection.
    """

    def __init__(
        self,
        cluster_ids: list[str],
        routing_field: str = "event_type",
        capacity: int = 2000,
        max_age_seconds: int = 0,
        max_clusters: int = 100,
    ) -> None:
        self.routing_field = routing_field
        self.windows: dict[str, EventWindow] = {
            cid: EventWindow(capacity=capacity, max_age_seconds=max_age_seconds)
            for cid in cluster_ids
        }
        self.unrouted: list[dict] = []
        self._capacity = capacity
        self._max_age = max_age_seconds
        self._max_clusters = max_clusters

    def add(self, events: list[dict]) -> None:
        """Route events to cluster windows. Unmatched go to unrouted.

        Dynamic cluster discovery: when an event's routing field value is not
        in self.windows and we haven't hit max_clusters, a new EventWindow is
        created automatically. Logs WARNING when max_clusters is exceeded.
        """
        self.unrouted.clear()
        _warned_clusters: set[str] = set()
        for event in events:
            cid = event.get(self.routing_field)
            if cid is not None and cid in self.windows:
                self.windows[cid].add([event])
            elif cid is not None and len(self.windows) < self._max_clusters:
                # Dynamic cluster discovery
                self.windows[cid] = EventWindow(capacity=self._capacity, max_age_seconds=self._max_age)
                self.windows[cid].add([event])
            else:
                self.unrouted.append(event)
                if cid is not None and cid not in _warned_clusters:
                    _warned_clusters.add(cid)
                    logger.warning(
                        "max_clusters (%d) exceeded — cluster '%s' routed to unrouted "
                        "(per-cluster drift detection disabled for this type). "
                        "Set STREAMFORGE_MAX_CLUSTERS to increase limit.",
                        self._max_clusters, cid,
                    )

    def sample_cluster(self, cluster_id: str, n: int) -> list[dict]:
        """Sample n events from a specific cluster — full sample, no dilution."""
        w = self.windows.get(cluster_id)
        if w is None:
            return []
        return w.sample(n)

    @property
    def total_count(self) -> int:
        """Total events across all cluster windows + unrouted."""
        return sum(len(w) for w in self.windows.values()) + len(self.unrouted)

    def cluster_counts(self) -> dict[str, int]:
        """Return event count per cluster."""
        return {cid: len(w) for cid, w in self.windows.items()}


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
            for item in window._buf:
                # _buf contains (timestamp, event) tuples; persist only the event
                event = item[1] if isinstance(item, tuple) else item
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
