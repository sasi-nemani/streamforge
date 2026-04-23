"""Parser protocol — the contract every format parser must satisfy.

Design principles (Google-style):
  - Single responsibility: parsers only convert bytes → dicts
  - No I/O: parsers receive file content, not file handles
  - Stateless: parsers are pure functions wrapped in a class for registration
  - Fail gracefully: return partial results + error count, never raise
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParseResult:
    """Result of parsing a file's content."""
    records: list[dict[str, Any]]
    errors: int
    format_detected: str


class FormatParser(ABC):
    """Abstract base for all format parsers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this parser (e.g., 'ndjson', 'csv')."""

    @property
    @abstractmethod
    def extensions(self) -> tuple[str, ...]:
        """File extensions this parser handles (e.g., ('.json', '.ndjson'))."""

    @abstractmethod
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Quick check if this parser can handle the content.

        Should be fast — peek at first few bytes, check magic numbers.
        Called in priority order until a parser returns True.
        """

    @abstractmethod
    def parse(self, content: bytes, filename: str) -> ParseResult:
        """Parse file content into records.

        Args:
            content: Raw file bytes
            filename: Original filename (for error messages)

        Returns:
            ParseResult with records, error count, and detected format
        """
