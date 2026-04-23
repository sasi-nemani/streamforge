"""FileConnector — unified file ingestion with pluggable format parsing.

This is the main entry point for file-based data ingestion. It combines:
  - FileScanner: discovers and reads files
  - Parser registry: converts content to records

Supports: JSON, NDJSON, CSV, TSV (and any format with a registered parser)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..base import ConnectorError, StreamConnector
from .scanner import FileScanner
from .parsers import parse_file, supported_extensions

logger = logging.getLogger(__name__)


class FileConnector(StreamConnector):
    """Reads events from files in a directory.

    Supports multiple formats through pluggable parsers.
    Auto-detects format based on content and extension.

    Args:
        folder_path: Directory containing data files
        poll: If True, watch for new/modified files on each read_batch
        extensions: File extensions to include (default: all supported)
        recursive: Scan subdirectories (default: True)
    """

    def __init__(
        self,
        folder_path: str,
        *,
        poll: bool = True,
        extensions: tuple[str, ...] | None = None,
        recursive: bool = True,
    ) -> None:
        self._folder = Path(folder_path)
        self._poll = poll
        self._source_id = f"file:{folder_path}"

        self._scanner = FileScanner(
            self._folder,
            extensions=extensions,
            recursive=recursive,
        )

        self._last_batch: list[dict[str, Any]] = []
        self._closed = False
        self._exhausted = False
        self._stats = {"files_read": 0, "records_parsed": 0, "errors": 0}

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def stats(self) -> dict[str, int]:
        return self._stats.copy()

    @classmethod
    def supported_formats(cls) -> tuple[str, ...]:
        """List of supported file extensions."""
        return supported_extensions()

    async def read_batch(
        self,
        max_messages: int = 200,
        timeout_ms: int = 1_000,
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise ConnectorError("read_batch called on closed FileConnector")
        if self._exhausted:
            return []

        events = await asyncio.to_thread(self._read_new_events, max_messages)

        if not self._poll:
            self._exhausted = True

        self._last_batch = events
        return events

    async def ack(self) -> None:
        self._last_batch = []

    async def close(self) -> None:
        self._closed = True
        logger.debug(
            "FileConnector closed: %s (files=%d, records=%d, errors=%d)",
            self._folder,
            self._stats["files_read"],
            self._stats["records_parsed"],
            self._stats["errors"],
        )

    def _read_new_events(self, max_messages: int) -> list[dict[str, Any]]:
        """Synchronous read — called via asyncio.to_thread."""
        if not self._folder.is_dir():
            raise ConnectorError(f"Not a directory: {self._folder}")

        files = self._scanner.scan_new()
        events: list[dict[str, Any]] = []

        for file in files:
            if len(events) >= max_messages:
                break

            content = self._scanner.read_new_content(file)
            if content is None:
                continue

            result = parse_file(content, file.path.name)
            if result is None:
                logger.debug("No parser for: %s", file.path)
                continue

            self._stats["files_read"] += 1
            self._stats["records_parsed"] += len(result.records)
            self._stats["errors"] += result.errors

            if result.errors > 0:
                logger.debug(
                    "Parsed %s: %d records, %d errors (format=%s)",
                    file.path.name,
                    len(result.records),
                    result.errors,
                    result.format_detected,
                )

            events.extend(result.records)

        return events[:max_messages]


# Backwards compatibility alias
ModularFileConnector = FileConnector
