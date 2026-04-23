"""NDJSON/JSON parser — handles newline-delimited JSON and JSON arrays."""
from __future__ import annotations

import json
from typing import Any

from .base import FormatParser, ParseResult


class NdjsonParser(FormatParser):
    """Parses NDJSON (one JSON object per line) and JSON array files."""

    @property
    def name(self) -> str:
        return "ndjson"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".json", ".ndjson", ".jsonl")

    def can_parse(self, content: bytes, filename: str) -> bool:
        if not content:
            return False
        try:
            text = content[:1000].decode("utf-8", errors="ignore").strip()
            if not text:
                return False
            first_char = text[0]
            return first_char in ("{", "[")
        except Exception:
            return False

    def parse(self, content: bytes, filename: str) -> ParseResult:
        records: list[dict[str, Any]] = []
        errors = 0

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return ParseResult(records=[], errors=1, format_detected="ndjson")

        text = text.strip()
        if not text:
            return ParseResult(records=[], errors=0, format_detected="ndjson")

        # Try JSON array first
        if text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            records.append(item)
                        else:
                            errors += 1
                    return ParseResult(records=records, errors=errors, format_detected="json_array")
            except json.JSONDecodeError:
                pass  # Fall through to NDJSON

        # NDJSON: one object per line
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    errors += 1
            except json.JSONDecodeError:
                errors += 1

        return ParseResult(records=records, errors=errors, format_detected="ndjson")
