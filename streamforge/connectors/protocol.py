"""Source-agnostic stream protocol.

Any connector (Kafka, Pub/Sub, Kinesis, NDJSON files, webhooks) can be
plugged into StreamForge by implementing the StreamSource protocol.

The watcher, profiler, and inference engine all consume list[dict] —
they don't know or care where the events came from.

Usage:
    source = NdjsonSource("events/payments/stream")
    events = source.read_batch(max_messages=500)
    # → list[dict], same as KafkaConnector.read_batch()
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class StreamSource(Protocol):
    """Protocol for all event stream connectors.

    Implementations must provide:
      read_batch() — read up to N events, return list[dict]
      ack()        — confirm processing (commit offsets, etc.)
    """

    def read_batch(self, max_messages: int = 500, timeout_ms: int = 5000) -> list[dict]:
        """Read up to max_messages events. Returns list of parsed dicts."""
        ...

    def ack(self) -> None:
        """Acknowledge/commit the last batch (at-least-once semantics)."""
        ...


class NdjsonSource:
    """File-based StreamSource — reads from NDJSON files in a directory.

    Stateless: reads from the beginning each time (suitable for init/profile,
    not for continuous watch). For watch mode, use KafkaConnector.
    """

    def __init__(self, folder_path: str) -> None:
        self._folder = Path(folder_path)
        self._events: list[dict] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        files = sorted(
            f for f in self._folder.rglob("*")
            if f.suffix in (".ndjson", ".json") and f.is_file()
            and not f.name.startswith("._")
        )
        for fp in files:
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if not stripped or len(stripped) > 65_536:
                            continue
                        try:
                            obj = json.loads(stripped)
                            if isinstance(obj, dict):
                                self._events.append(obj)
                        except json.JSONDecodeError:
                            pass
            except OSError:
                continue
        self._loaded = True
        logger.info("NdjsonSource loaded %d events from %s", len(self._events), self._folder)

    def read_batch(self, max_messages: int = 500, timeout_ms: int = 5000) -> list[dict]:
        """Read up to max_messages events from NDJSON files."""
        self._load()
        return self._events[:max_messages]

    def ack(self) -> None:
        """No-op for file-based sources."""
        pass
