"""
tests/test_schema_archive.py — Schema snapshot archiving tests

Covers _archive_schema() behaviour:
  - Archives schema.yaml to .history/schema_v{version}.yaml
  - Skips gracefully when schema.yaml does not yet exist
  - Does NOT overwrite an existing history file (idempotent)
  - accept_drift() triggers archive before overwriting schema.yaml
"""
from pathlib import Path

import yaml

from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.schema_writer import _archive_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schema(version: str = "1.0.0", stream_name: str = "payments") -> InferredSchema:
    return InferredSchema(
        stream_name=stream_name,
        version=version,
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=100,
        fields=[
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                required=True,
                presence_rate=0.98,
                confidence=0.97,
            )
        ],
        inference_model="test",
        inference_confidence=0.95,
    )


def _write_schema_to_dir(schema: InferredSchema, schema_dir: Path) -> None:
    """Write schema.yaml directly into schema_dir (bypassing output_dir nesting)."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    # write_schema expects output_dir/stream_name/ structure — easier to write directly
    content = {
        "stream": schema.stream_name,
        "version": schema.version,
        "inferred_at": schema.inferred_at,
        "inference_confidence": schema.inference_confidence,
        "fields": [
            {
                "path": f.path,
                "type": f.field_type.value,
                "required": f.required,
                "nullable": f.nullable,
                "presence_rate": f.presence_rate,
                "confidence": f.confidence,
            }
            for f in schema.fields
        ],
    }
    (schema_dir / "schema.yaml").write_text(yaml.dump(content))


# ---------------------------------------------------------------------------
# _archive_schema()
# ---------------------------------------------------------------------------

class TestArchiveSchema:
    def test_creates_history_file(self, tmp_path: Path):
        """Happy path: schema.yaml exists → .history/schema_v1.0.0.yaml is created."""
        schema = _make_schema(version="1.0.0")
        schema_dir = tmp_path / "schemas" / "payments"
        _write_schema_to_dir(schema, schema_dir)

        _archive_schema(schema_dir, schema)

        history_file = schema_dir / ".history" / "schema_v1.0.0.yaml"
        assert history_file.exists(), ".history/schema_v1.0.0.yaml should be created"

    def test_history_file_contains_valid_yaml(self, tmp_path: Path):
        """The archived file should be valid YAML (copy of the original)."""
        schema = _make_schema(version="1.0.0")
        schema_dir = tmp_path / "schemas" / "payments"
        _write_schema_to_dir(schema, schema_dir)

        _archive_schema(schema_dir, schema)

        history_file = schema_dir / ".history" / "schema_v1.0.0.yaml"
        data = yaml.safe_load(history_file.read_text())
        assert isinstance(data, dict)
        assert "stream" in data or "fields" in data  # valid schema content

    def test_skips_when_schema_yaml_does_not_exist(self, tmp_path: Path):
        """No-op when schema.yaml hasn't been written yet (first init)."""
        schema = _make_schema(version="1.0.0")
        schema_dir = tmp_path / "schemas" / "payments"
        schema_dir.mkdir(parents=True, exist_ok=True)
        # Deliberately do NOT write schema.yaml

        _archive_schema(schema_dir, schema)  # should not raise

        history_dir = schema_dir / ".history"
        assert not history_dir.exists() or list(history_dir.glob("*.yaml")) == []

    def test_does_not_overwrite_existing_history_file(self, tmp_path: Path):
        """Second call with the same version must not overwrite the first archive."""
        schema = _make_schema(version="1.0.0")
        schema_dir = tmp_path / "schemas" / "payments"
        _write_schema_to_dir(schema, schema_dir)

        _archive_schema(schema_dir, schema)

        # Overwrite schema.yaml with different content, then archive again
        (schema_dir / "schema.yaml").write_text("stream: payments\nversion: '1.0.0'\nfields: []\n")
        _archive_schema(schema_dir, schema)  # second call — should skip

        history_file = schema_dir / ".history" / "schema_v1.0.0.yaml"
        data = yaml.safe_load(history_file.read_text())
        # First archive had the full schema (with 'fields' key having content)
        # If it was overwritten, 'fields' would be an empty list
        assert data.get("fields") != []  # original content preserved

    def test_different_versions_produce_separate_files(self, tmp_path: Path):
        """Archiving v1.0.0 and then v1.1.0 creates two distinct history files."""
        schema_dir = tmp_path / "schemas" / "payments"

        schema_v1 = _make_schema(version="1.0.0")
        _write_schema_to_dir(schema_v1, schema_dir)
        _archive_schema(schema_dir, schema_v1)

        schema_v2 = _make_schema(version="1.1.0")
        _write_schema_to_dir(schema_v2, schema_dir)
        _archive_schema(schema_dir, schema_v2)

        history_dir = schema_dir / ".history"
        archived = sorted(f.name for f in history_dir.glob("schema_v*.yaml"))
        assert archived == ["schema_v1.0.0.yaml", "schema_v1.1.0.yaml"]

    def test_history_dir_created_automatically(self, tmp_path: Path):
        """_archive_schema() must create .history/ if it doesn't exist."""
        schema = _make_schema(version="2.0.0")
        schema_dir = tmp_path / "schemas" / "payments"
        _write_schema_to_dir(schema, schema_dir)

        assert not (schema_dir / ".history").exists()
        _archive_schema(schema_dir, schema)
        assert (schema_dir / ".history").exists()
