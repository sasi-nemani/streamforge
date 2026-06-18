"""
tests/test_schema_as_code.py — Schema-as-code linter
=====================================================

These tests act as a CI gate: any schema.yaml that violates the declared
contract fails the build. Run in schema-guard.yml before `streamforge plan`.

Tests:
  1. schemas/ directory exists with at least 1 schema
  2. Every schema.yaml has required top-level keys
  3. Version matches semver X.Y.Z
  4. inference_confidence >= 0.60 for all schemas
  5. No schema has zero fields
  6. profile.yaml has sub_schemas key when present (multi-cluster streams)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Project root — one level above tests/
_PROJECT_ROOT = Path(__file__).parent.parent
_SCHEMAS_DIR = _PROJECT_ROOT / "schemas"

# Collect all schema.yaml paths once at import time
_ALL_SCHEMA_PATHS = sorted(_SCHEMAS_DIR.glob("*/schema.yaml"))
_ALL_SCHEMA_IDS = [p.parent.name for p in _ALL_SCHEMA_PATHS]

# ── Required top-level keys every schema.yaml MUST have ─────────────────────
_REQUIRED_SCHEMA_KEYS = {"stream", "version", "fields"}

# ── Semver pattern ────────────────────────────────────────────────────────────
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

# ── Confidence threshold ──────────────────────────────────────────────────────
_MIN_CONFIDENCE = 0.60


# ---------------------------------------------------------------------------
# 1. schemas/ directory exists with at least 1 schema
# ---------------------------------------------------------------------------

def test_schemas_directory_exists():
    """The schemas/ directory must exist in the project root."""
    assert _SCHEMAS_DIR.exists(), (
        f"schemas/ directory not found at {_SCHEMAS_DIR}. "
        "Run 'streamforge init' to create baseline schemas."
    )
    assert _SCHEMAS_DIR.is_dir(), f"{_SCHEMAS_DIR} exists but is not a directory"


def test_schemas_directory_has_at_least_one_schema():
    """There must be at least one schema.yaml in schemas/."""
    assert len(_ALL_SCHEMA_PATHS) >= 1, (
        f"No schema.yaml files found under {_SCHEMAS_DIR}. "
        "Run 'streamforge init <stream>' to create at least one schema."
    )


# ---------------------------------------------------------------------------
# 2. Every schema.yaml has required top-level keys
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_each_schema_has_required_fields(schema_path: Path):
    """
    Every schema.yaml must have: stream, version, fields.
    These are load-bearing fields used by streamforge plan and the VCS commit.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    assert isinstance(content, dict), (
        f"{schema_path}: expected YAML dict, got {type(content)}"
    )

    missing = _REQUIRED_SCHEMA_KEYS - set(content.keys())
    assert not missing, (
        f"{schema_path}: missing required keys: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 3. version matches semver X.Y.Z
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_schema_version_format(schema_path: Path):
    """
    schema.version must be a valid semver string (MAJOR.MINOR.PATCH).
    Other formats (e.g. '1.0', 'v1.0.0', '1') are rejected.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    version = str(content.get("version", ""))
    assert _SEMVER_PATTERN.match(version), (
        f"{schema_path}: version '{version}' does not match semver X.Y.Z pattern"
    )


# ---------------------------------------------------------------------------
# 4. inference_confidence >= 0.60
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_schema_inference_confidence_above_threshold(schema_path: Path):
    """
    inference_confidence (if present) must be >= 0.60.
    A schema with confidence below this threshold is unreliable and should
    be re-inferred with more events or reviewed manually.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    confidence = content.get("inference_confidence")

    if confidence is None:
        # Field may be absent for manually-authored schemas — skip
        pytest.skip(f"{schema_path.parent.name}: no inference_confidence field (manual schema)")

    assert float(confidence) >= _MIN_CONFIDENCE, (
        f"{schema_path}: inference_confidence={confidence} is below minimum {_MIN_CONFIDENCE}. "
        "Re-run 'streamforge init' with more events or review manually."
    )


# ---------------------------------------------------------------------------
# 5. No schema has zero fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_no_schema_has_empty_fields(schema_path: Path):
    """
    schema.fields must be a non-empty list.
    An empty fields list means inference produced no useful output.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    fields = content.get("fields")

    assert fields is not None, (
        f"{schema_path}: 'fields' key is missing"
    )
    assert isinstance(fields, list), (
        f"{schema_path}: 'fields' must be a list, got {type(fields)}"
    )
    assert len(fields) > 0, (
        f"{schema_path}: 'fields' list is empty — schema has no inferred fields"
    )


# ---------------------------------------------------------------------------
# 6. profile.yaml has sub_schemas if it exists (multi-cluster streams)
# ---------------------------------------------------------------------------

_ALL_PROFILE_PATHS = sorted(_SCHEMAS_DIR.glob("*/profile.yaml"))
_ALL_PROFILE_IDS = [p.parent.name for p in _ALL_PROFILE_PATHS]


@pytest.mark.skipif(len(_ALL_PROFILE_PATHS) == 0, reason="No profile.yaml files found")
@pytest.mark.parametrize("profile_path", _ALL_PROFILE_PATHS, ids=_ALL_PROFILE_IDS)
def test_profile_yaml_has_sub_schemas_if_multi_cluster(profile_path: Path):
    """
    profile.yaml (produced by multi-cluster streams) must have a 'sub_schemas' key.
    This is used by streamforge plan to compare per-cluster schemas.
    """
    content = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert isinstance(content, dict), (
        f"{profile_path}: expected YAML dict, got {type(content)}"
    )
    assert "sub_schemas" in content, (
        f"{profile_path}: missing 'sub_schemas' key. "
        "profile.yaml for multi-cluster streams must list all cluster schemas."
    )
    sub_schemas = content["sub_schemas"]
    assert isinstance(sub_schemas, list), (
        f"{profile_path}: 'sub_schemas' must be a list, got {type(sub_schemas)}"
    )
    assert len(sub_schemas) > 0, (
        f"{profile_path}: 'sub_schemas' list is empty"
    )


# ---------------------------------------------------------------------------
# 7. stream field in schema.yaml matches the directory name
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_schema_stream_field_matches_directory(schema_path: Path):
    """
    schema.stream must match the parent directory name.
    This ensures schemas are not accidentally misplaced or renamed without
    updating the stream field.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    declared_stream = content.get("stream", "")
    dir_name = schema_path.parent.name

    assert declared_stream == dir_name, (
        f"{schema_path}: stream='{declared_stream}' does not match "
        f"directory name '{dir_name}'"
    )


# ---------------------------------------------------------------------------
# 8. fields list items have required sub-keys
# ---------------------------------------------------------------------------

@pytest.mark.skipif(len(_ALL_SCHEMA_PATHS) == 0, reason="No schemas found")
@pytest.mark.parametrize("schema_path", _ALL_SCHEMA_PATHS, ids=_ALL_SCHEMA_IDS)
def test_schema_fields_have_required_sub_keys(schema_path: Path):
    """
    Each field in schema.fields must have at minimum: path and type.
    These are the keys used by streamforge plan for drift comparison.
    """
    content = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    fields = content.get("fields") or []

    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            pytest.fail(
                f"{schema_path}: fields[{i}] is not a dict: {f!r}"
            )
        missing = {"path", "type"} - set(f.keys())
        assert not missing, (
            f"{schema_path}: fields[{i}] (path='{f.get('path', '?')}') "
            f"missing required sub-keys: {sorted(missing)}"
        )
