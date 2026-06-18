"""File scanner — shared file discovery and reading logic.

This module handles all filesystem operations. Parsers never touch the disk.
Separation allows:
  - Easy testing of parsers with in-memory content
  - Future: swap for cloud storage scanner (S3, GCS)
  - Consistent error handling across all formats
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .parsers import supported_extensions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannedFile:
    """A file discovered by the scanner."""
    path: Path
    size: int
    mtime: float

    def read_content(self) -> bytes:
        """Read file content. Caller handles exceptions."""
        return self.path.read_bytes()


@dataclass
class ScanState:
    """Tracks which files/bytes have been processed."""
    file_cursors: dict[str, int]  # path → byte offset

    def __init__(self) -> None:
        self.file_cursors = {}

    def get_cursor(self, path: str) -> int:
        return self.file_cursors.get(path, 0)

    def set_cursor(self, path: str, offset: int) -> None:
        self.file_cursors[path] = offset

    def has_new_content(self, file: ScannedFile) -> bool:
        cursor = self.get_cursor(str(file.path))
        return file.size > cursor


class FileScanner:
    """Discovers and reads files from a directory.

    Thread-safe for reads. Not safe for concurrent state modification.
    """

    def __init__(
        self,
        folder: Path,
        *,
        extensions: tuple[str, ...] | None = None,
        recursive: bool = True,
    ) -> None:
        self._folder = folder
        self._extensions = extensions or supported_extensions()
        self._recursive = recursive
        self._state = ScanState()

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def state(self) -> ScanState:
        return self._state

    def scan(self) -> list[ScannedFile]:
        """Scan directory for matching files."""
        if not self._folder.is_dir():
            logger.warning("Not a directory: %s", self._folder)
            return []

        glob_fn = self._folder.rglob if self._recursive else self._folder.glob
        files: list[ScannedFile] = []

        for pattern in ("*",):
            for path in glob_fn(pattern):
                if not path.is_file():
                    continue
                if not any(path.suffix.lower() == ext for ext in self._extensions):
                    continue
                try:
                    stat = path.stat()
                    files.append(ScannedFile(
                        path=path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    ))
                except OSError as e:
                    logger.debug("Could not stat %s: %s", path, e)

        return sorted(files, key=lambda f: f.path)

    def scan_new(self) -> list[ScannedFile]:
        """Scan for files with new content since last read."""
        return [f for f in self.scan() if self._state.has_new_content(f)]

    def read_new_content(self, file: ScannedFile) -> bytes | None:
        """Read only new content from a file (incremental read)."""
        cursor = self._state.get_cursor(str(file.path))
        try:
            with open(file.path, "rb") as fh:
                fh.seek(cursor)
                content = fh.read()
                self._state.set_cursor(str(file.path), fh.tell())
                return content
        except OSError as e:
            logger.warning("Could not read %s: %s", file.path, e)
            return None

    def read_full(self, file: ScannedFile) -> bytes | None:
        """Read entire file content."""
        try:
            return file.path.read_bytes()
        except OSError as e:
            logger.warning("Could not read %s: %s", file.path, e)
            return None
