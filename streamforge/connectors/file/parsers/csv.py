"""CSV parser — handles comma/tab/semicolon separated files."""
from __future__ import annotations

import csv
import io
from typing import Any

from .base import FormatParser, ParseResult


class CsvParser(FormatParser):
    """Parses CSV files with automatic delimiter detection."""

    @property
    def name(self) -> str:
        return "csv"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".csv", ".tsv", ".txt")

    def can_parse(self, content: bytes, filename: str) -> bool:
        if not content:
            return False
        # Check extension first (CSV is ambiguous from content alone)
        if any(filename.lower().endswith(ext) for ext in (".csv", ".tsv")):
            return True
        # Heuristic: multiple lines with consistent delimiter count
        try:
            text = content[:2000].decode("utf-8", errors="ignore")
            lines = [l for l in text.splitlines() if l.strip()][:5]
            if len(lines) < 2:
                return False
            # Check for consistent comma/tab/semicolon counts
            for delim in (",", "\t", ";"):
                counts = [line.count(delim) for line in lines]
                if counts[0] > 0 and len(set(counts)) == 1:
                    return True
            return False
        except Exception:
            return False

    def parse(self, content: bytes, filename: str) -> ParseResult:
        records: list[dict[str, Any]] = []
        errors = 0

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except UnicodeDecodeError:
                return ParseResult(records=[], errors=1, format_detected="csv")

        if not text.strip():
            return ParseResult(records=[], errors=0, format_detected="csv")

        # Detect delimiter
        delimiter = self._detect_delimiter(text)
        format_name = "tsv" if delimiter == "\t" else "csv"

        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            for row in reader:
                # Convert empty strings to None, try numeric conversion
                clean_row: dict[str, Any] = {}
                for key, value in row.items():
                    if key is None:
                        continue
                    clean_key = key.strip()
                    if value is None or value.strip() == "":
                        clean_row[clean_key] = None
                    else:
                        clean_row[clean_key] = self._convert_value(value.strip())
                if clean_row:
                    records.append(clean_row)
        except csv.Error:
            errors += 1

        return ParseResult(records=records, errors=errors, format_detected=format_name)

    def _detect_delimiter(self, text: str) -> str:
        """Detect the most likely delimiter."""
        first_lines = text.splitlines()[:10]
        if not first_lines:
            return ","

        best_delim = ","
        best_score = 0

        for delim in (",", "\t", ";", "|"):
            counts = [line.count(delim) for line in first_lines if line.strip()]
            if not counts:
                continue
            # Score: consistency (all same count) + count > 0
            if counts[0] > 0 and len(set(counts)) == 1:
                score = counts[0]
                if score > best_score:
                    best_score = score
                    best_delim = delim

        return best_delim

    def _convert_value(self, value: str) -> Any:
        """Convert string to appropriate type."""
        # Boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # Integer
        try:
            if "." not in value and "e" not in value.lower():
                return int(value)
        except ValueError:
            pass
        # Float
        try:
            return float(value)
        except ValueError:
            pass
        # String
        return value
