"""Load hand-labeled ground-truth schemas from eval/benchmarks/*.yaml.

The YAML is validated at the boundary (fail-fast on unknown field types / PII
categories) so a typo in a label can never silently corrupt a benchmark score.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from streamforge.eval.types import FieldTruth, SchemaTruth
from streamforge.models import FieldType, PIICategory

# eval/benchmarks/ lives at the repo root, two levels up from this file
# (streamforge/eval/benchmark.py -> repo_root/eval/benchmarks).
_BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "eval" / "benchmarks"


def benchmarks_dir() -> Path:
    return _BENCHMARK_DIR


def available_benchmarks() -> list[str]:
    """Names of all labeled streams (filename stems), sorted."""
    if not _BENCHMARK_DIR.is_dir():
        return []
    return sorted(p.stem for p in _BENCHMARK_DIR.glob("*.yaml"))


def _parse_field(raw: dict, stream: str) -> FieldTruth:
    if "path" not in raw or "field_type" not in raw:
        raise ValueError(f"[{stream}] field missing 'path' or 'field_type': {raw!r}")
    try:
        ftype = FieldType(raw["field_type"])
    except ValueError as exc:
        raise ValueError(
            f"[{stream}] unknown field_type {raw['field_type']!r} for path "
            f"{raw['path']!r}; valid: {[t.value for t in FieldType]}"
        ) from exc

    pii_raw = raw.get("pii", []) or []
    pii: list[PIICategory] = []
    for cat in pii_raw:
        try:
            pii.append(PIICategory(cat))
        except ValueError as exc:
            raise ValueError(
                f"[{stream}] unknown pii category {cat!r} for path {raw['path']!r}; "
                f"valid: {[c.value for c in PIICategory]}"
            ) from exc

    return FieldTruth(
        path=str(raw["path"]),
        field_type=ftype,
        required=bool(raw.get("required", True)),
        pii_categories=tuple(pii),
    )


def load_truth(stream: str) -> SchemaTruth:
    """Load ground truth for one stream by name (e.g. 'payments')."""
    path = _BENCHMARK_DIR / f"{stream}.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"No benchmark for {stream!r} at {path}. "
            f"Available: {available_benchmarks()}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "fields" not in data:
        raise ValueError(f"[{stream}] benchmark must be a mapping with a 'fields' list")

    name = data.get("stream_name", stream)
    fields = tuple(_parse_field(f, name) for f in data["fields"])
    if not fields:
        raise ValueError(f"[{stream}] benchmark has no fields")
    return SchemaTruth(stream_name=name, fields=fields)
