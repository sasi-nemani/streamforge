"""Modular file connector with pluggable format parsing.

Usage:
    from streamforge.connectors.file import FileConnector

    connector = FileConnector("/path/to/data")
    async with connector:
        events = await connector.read_batch()

Supported formats:
    - JSON / NDJSON / JSONL
    - CSV / TSV

To add a new format, create a parser in connectors/file/parsers/
and register it in parsers/__init__.py.
"""
from .connector import FileConnector, ModularFileConnector
from .parsers import (
    PARSER_REGISTRY,
    FormatParser,
    ParseResult,
    parse_file,
    supported_extensions,
)
from .scanner import FileScanner, ScannedFile, ScanState

__all__ = [
    "FileConnector",
    "ModularFileConnector",
    "FileScanner",
    "ScannedFile",
    "ScanState",
    "FormatParser",
    "ParseResult",
    "PARSER_REGISTRY",
    "parse_file",
    "supported_extensions",
]
