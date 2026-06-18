"""Structural-fingerprint cache for schema inference.

The idea: a stream's *structure* — the set of (field path, type, required) — is a
stable fingerprint. If we've already inferred a schema for an identical shape, we
can return it WITHOUT calling the LLM again. This makes steady-state inference
deterministic and (near) free: the model is consulted only the first time a novel
shape appears.

The fingerprint is computed from the deterministic statistical pass (quorum /
statistical_inference), so it never depends on LLM output. The cached payload is
the *enriched* schema (LLM names/notes/enums included) from the first time the
shape was seen — identical shape ⇒ identical schema.

This module is pure data + JSON persistence; it has no LLM or network deps and is
designed to fail safe: any I/O error degrades to a cache miss, never an exception
that could break inference.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .models import FieldSchema

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path(".streamforge") / "schema_cache.json"


def structural_fingerprint(fields: list[FieldSchema]) -> str:
    """Stable, order-independent hash of a schema's structure.

    Two field lists with the same set of (path, type, required) produce the same
    fingerprint regardless of ordering. Values, confidence, notes and PII are
    intentionally excluded — they are not part of the *shape*.
    """
    triples = sorted(
        (f.path, f.field_type.value, bool(f.required)) for f in fields
    )
    canonical = ";".join(f"{p}|{t}|{int(r)}" for p, t, r in triples)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class SchemaFingerprintCache:
    """Maps a structural fingerprint to a previously-inferred field list."""

    def __init__(self, entries: dict[str, list[dict]] | None = None) -> None:
        self._entries: dict[str, list[dict]] = entries or {}

    def get(self, fingerprint: str) -> list[FieldSchema] | None:
        raw = self._entries.get(fingerprint)
        if raw is None:
            return None
        try:
            return [FieldSchema(**d) for d in raw]
        except Exception:  # noqa: BLE001 — corrupt entry ⇒ treat as a miss
            logger.warning("Corrupt schema-cache entry for %s; ignoring", fingerprint)
            return None

    def put(self, fingerprint: str, fields: list[FieldSchema]) -> None:
        self._entries[fingerprint] = [f.model_dump(mode="json") for f in fields]

    def __contains__(self, fingerprint: str) -> bool:
        return fingerprint in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    # ── persistence (fail-safe) ───────────────────────────────────────────────
    @staticmethod
    def load(path: Path | None = None) -> SchemaFingerprintCache:
        path = path or DEFAULT_CACHE_PATH
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return SchemaFingerprintCache(data)
        except Exception as exc:  # noqa: BLE001 — never let cache I/O break inference
            logger.warning("Could not load schema cache %s: %s", path, exc)
        return SchemaFingerprintCache()

    def save(self, path: Path | None = None) -> None:
        path = path or DEFAULT_CACHE_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
            tmp.replace(path)  # atomic
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not save schema cache %s: %s", path, exc)


def cache_enabled() -> bool:
    """Schema fingerprint cache is on by default; disable with
    STREAMFORGE_SCHEMA_CACHE=0 (e.g. to force fresh inference in a demo)."""
    return os.environ.get("STREAMFORGE_SCHEMA_CACHE", "1") != "0"
