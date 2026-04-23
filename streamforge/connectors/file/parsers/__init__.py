"""Parser registry — pluggable format detection and parsing.

To add a new format:
  1. Create a new parser in this package (e.g., xml.py)
  2. Implement FormatParser protocol
  3. Register in PARSER_REGISTRY below

Parsers are tried in order. First parser where can_parse() returns True wins.
Order matters: more specific formats (NDJSON) before generic (CSV).
"""
from __future__ import annotations

from .base import FormatParser, ParseResult
from .ndjson import NdjsonParser
from .csv import CsvParser

# Registry: ordered list of parsers to try
PARSER_REGISTRY: list[FormatParser] = [
    NdjsonParser(),
    CsvParser(),
]


def get_parser_for_file(content: bytes, filename: str) -> FormatParser | None:
    """Find the appropriate parser for a file."""
    for parser in PARSER_REGISTRY:
        if parser.can_parse(content, filename):
            return parser
    return None


def parse_file(content: bytes, filename: str) -> ParseResult | None:
    """Parse a file using the appropriate parser."""
    parser = get_parser_for_file(content, filename)
    if parser is None:
        return None
    return parser.parse(content, filename)


def supported_extensions() -> tuple[str, ...]:
    """Get all supported file extensions."""
    extensions: set[str] = set()
    for parser in PARSER_REGISTRY:
        extensions.update(parser.extensions)
    return tuple(sorted(extensions))


__all__ = [
    "FormatParser",
    "ParseResult",
    "PARSER_REGISTRY",
    "get_parser_for_file",
    "parse_file",
    "supported_extensions",
]
