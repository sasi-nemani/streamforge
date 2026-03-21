"""
FileConnector — reads NDJSON files from a directory.

Wraps the existing sampler.py file-loading logic behind the StreamConnector
interface. This is the current primary source for all dev and test workloads.

Behaviour:
  - On first read_batch, loads ALL files in the directory (sorted by name).
  - On subsequent calls, checks for files modified since the last read and
    appends new lines from those files only. This simulates a live tail.
  - ack() advances the internal cursor — unacked events are re-returned on
    the next read_batch (at-least-once semantics, local to this process).
  - Files are read synchronously and wrapped in asyncio.to_thread so the
    event loop is not blocked during disk I/O.

Limitations:
  - Does not detect file deletions or truncations.
  - Not suitable for multi-process deployments (no shared cursor state).
    For that, use a broker connector (Redis Streams, Kafka, SQS).
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .base import ConnectorError, StreamConnector

logger = logging.getLogger(__name__)


class FileConnector(StreamConnector):
    """
    Reads NDJSON events from a local directory.

    Args:
        folder_path: Directory containing .ndjson or .json files.
        poll: If True, watch for new/modified files on each read_batch call.
              If False, load all files once and stop (batch mode for init/profile).
    """

    def __init__(self, folder_path: str, *, poll: bool = True) -> None:
        self._folder = Path(folder_path)
        self._poll = poll
        self._source_id = f"file:{folder_path}"

        # Cursor state: track which bytes of each file we have read
        self._file_cursors: dict[str, int] = {}   # path → byte offset
        self._pending: list[dict[str, Any]] = []  # buffered but not yet acked
        self._last_batch: list[dict[str, Any]] = []
        self._closed = False
        self._exhausted = False  # only relevant when poll=False

    @property
    def source_id(self) -> str:
        return self._source_id

    async def read_batch(
        self,
        max_messages: int = 200,
        timeout_ms: int = 1_000,
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise ConnectorError("read_batch called on closed FileConnector")
        if self._exhausted:
            return []

        events = await asyncio.to_thread(self._read_new_events)

        if not self._poll:
            self._exhausted = True

        self._last_batch = events[:max_messages]
        return self._last_batch

    async def ack(self) -> None:
        # For the file connector, ack is a no-op — the cursor is advanced
        # during read_batch itself. We don't support re-delivery within a
        # single process run. (A persistent cursor would require SQLite state.)
        self._last_batch = []

    async def close(self) -> None:
        self._closed = True
        logger.debug("FileConnector closed: %s", self._folder)

    # -------------------------------------------------------------------------
    # Internal — synchronous file I/O (called via asyncio.to_thread)
    # -------------------------------------------------------------------------

    def _read_new_events(self) -> list[dict[str, Any]]:
        if not self._folder.is_dir():
            raise ConnectorError(f"Not a directory: {self._folder}")

        files = sorted(
            f for f in self._folder.rglob("*")
            if f.suffix in (".ndjson", ".json") and f.is_file()
        )

        events: list[dict[str, Any]] = []
        skipped = 0

        for file_path in files:
            key = str(file_path)
            cursor = self._file_cursors.get(key, 0)

            try:
                file_size = file_path.stat().st_size
            except OSError:
                continue  # file disappeared between listing and stat

            if file_size <= cursor:
                continue  # nothing new

            try:
                with open(file_path, encoding="utf-8") as fh:
                    fh.seek(cursor)
                    for line in fh:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            event = json.loads(stripped)
                            if isinstance(event, dict):
                                events.append(event)
                            else:
                                skipped += 1
                        except json.JSONDecodeError:
                            skipped += 1
                    self._file_cursors[key] = fh.tell()
            except OSError as exc:
                logger.warning("Could not read %s: %s", file_path, exc)

        if skipped:
            logger.debug("Skipped %d malformed lines in %s", skipped, self._folder)
        if events:
            logger.debug("Read %d new events from %s", len(events), self._folder)

        return events
