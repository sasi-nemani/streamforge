"""
Unit tests for GlueRegistryBackend.

All tests are offline — boto3 is not installed in the test environment and
is fully mocked via sys.modules injection. Tests verify the correct Glue API
calls are made and that results/errors are handled gracefully.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from streamforge.models import FieldSchema, FieldType, InferredSchema

# ── shared fixtures ───────────────────────────────────────────────────────────

_AVRO_DOC = {"type": "record", "name": "TestStream", "fields": [{"name": "id", "type": "string"}]}
_SCHEMA_ARN = "arn:aws:glue:us-east-1:123456789:schema/StreamForge/test_stream"


def make_schema(stream_name: str = "test_stream") -> InferredSchema:
    return InferredSchema(
        stream_name=stream_name,
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=100,
        fields=[
            FieldSchema(name="id", path="id", field_type=FieldType.UUID),
            FieldSchema(name="sensor_id", path="sensor_id", field_type=FieldType.STRING),
        ],
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.92,
    )


@pytest.fixture()
def mock_boto3():
    """Inject a mock boto3 module into sys.modules for the duration of each test."""
    mock_b3 = MagicMock()
    with patch.dict(sys.modules, {"boto3": mock_b3}):
        yield mock_b3


@pytest.fixture()
def mock_glue_client(mock_boto3) -> MagicMock:
    """A pre-configured mock Glue client wired into the mock boto3 module."""
    client = MagicMock()
    # Provide a real exception class so `except self._glue.exceptions.EntityNotFoundException`
    # can actually catch it.
    client.exceptions.EntityNotFoundException = type(
        "EntityNotFoundException", (Exception,), {}
    )
    # Default: registry already exists — get_registry succeeds
    client.get_registry.return_value = {"RegistryName": "StreamForge", "Status": "AVAILABLE"}
    mock_boto3.client.return_value = client
    return client


@pytest.fixture()
def backend(mock_glue_client) -> GlueRegistryBackend:  # noqa: F821
    """GlueRegistryBackend with fully mocked boto3."""
    from streamforge.registries.glue import GlueRegistryBackend
    return GlueRegistryBackend(registry_name="StreamForge")


# ── push_schema ───────────────────────────────────────────────────────────────

class TestGluePushSchema:
    def test_success_with_existing_schema(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.get_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.return_value = {
            "VersionNumber": 2,
            "Status": "AVAILABLE",
        }

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is True
        assert result.version == 2
        assert result.subject == "test_stream"
        assert "test_stream" in (result.url or "")

    def test_success_creating_new_schema_on_first_push(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.get_schema.side_effect = Exception("EntityNotFoundException")
        mock_glue_client.create_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is True
        assert result.version == 1
        mock_glue_client.create_schema.assert_called_once()

    def test_create_schema_called_with_avro_format_and_backward_compat(
        self, backend, mock_glue_client
    ):
        schema = make_schema()
        mock_glue_client.get_schema.side_effect = Exception("not found")
        mock_glue_client.create_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("new_schema", schema)

        create_kwargs = mock_glue_client.create_schema.call_args[1]
        assert create_kwargs["DataFormat"] == "AVRO"
        assert create_kwargs["Compatibility"] == "BACKWARD"
        assert create_kwargs["SchemaName"] == "new_schema"

    def test_register_version_called_with_schema_arn(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.get_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 3}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("test_stream", schema)

        call_kwargs = mock_glue_client.register_schema_version.call_args[1]
        assert call_kwargs["SchemaId"] == {"SchemaArn": _SCHEMA_ARN}

    def test_register_version_uses_schema_name_when_no_arn(self, backend, mock_glue_client):
        """_ensure_schema_exists can return None — falls back to name+registry."""
        schema = make_schema()
        mock_glue_client.get_schema.side_effect = Exception("not found")
        mock_glue_client.create_schema.side_effect = Exception("create also failed")
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is True
        call_kwargs = mock_glue_client.register_schema_version.call_args[1]
        assert call_kwargs["SchemaId"] == {
            "SchemaName": "test_stream",
            "RegistryName": "StreamForge",
        }

    def test_register_version_failure_returns_failure_result(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.get_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.side_effect = Exception("invalid Avro schema")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is False
        assert "invalid Avro schema" in result.error

    def test_push_includes_registry_console_url(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.get_schema.return_value = {"SchemaArn": _SCHEMA_ARN}
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.url is not None
        assert "glue" in result.url


# ── get_schema ────────────────────────────────────────────────────────────────

class TestGlueGetSchema:
    def test_get_latest_returns_parsed_dict(self, backend, mock_glue_client):
        schema_content = {"type": "record", "name": "Test", "fields": []}
        mock_glue_client.get_schema_version.return_value = {
            "SchemaDefinition": json.dumps(schema_content),
            "Status": "AVAILABLE",
        }

        result = backend.get_schema("test_stream", version="latest")

        assert result == schema_content

    def test_get_latest_uses_latest_version_flag(self, backend, mock_glue_client):
        mock_glue_client.get_schema_version.return_value = {
            "SchemaDefinition": '{"type": "record"}',
        }

        backend.get_schema("test_stream", version="latest")

        call_kwargs = mock_glue_client.get_schema_version.call_args[1]
        assert call_kwargs["SchemaVersionNumber"] == {"LatestVersion": True}

    def test_get_specific_version_uses_integer(self, backend, mock_glue_client):
        mock_glue_client.get_schema_version.return_value = {
            "SchemaDefinition": '{"type": "record"}',
        }

        backend.get_schema("test_stream", version="5")

        call_kwargs = mock_glue_client.get_schema_version.call_args[1]
        assert call_kwargs["SchemaVersionNumber"] == {"VersionNumber": 5}

    def test_uses_registry_name_in_schema_id(self, backend, mock_glue_client):
        mock_glue_client.get_schema_version.return_value = {
            "SchemaDefinition": '{"type": "record"}',
        }

        backend.get_schema("test_stream")

        call_kwargs = mock_glue_client.get_schema_version.call_args[1]
        assert call_kwargs["SchemaId"] == {
            "SchemaName": "test_stream",
            "RegistryName": "StreamForge",
        }

    def test_not_found_returns_none(self, backend, mock_glue_client):
        mock_glue_client.get_schema_version.side_effect = Exception("EntityNotFoundException")

        result = backend.get_schema("nonexistent_stream")

        assert result is None

    def test_malformed_schema_definition_returns_none(self, backend, mock_glue_client):
        mock_glue_client.get_schema_version.return_value = {
            "SchemaDefinition": "this is not JSON!!!",
        }

        result = backend.get_schema("test_stream")

        assert result is None


# ── list_subjects ─────────────────────────────────────────────────────────────

class TestGlueListSubjects:
    def _setup_paginator(self, mock_glue_client, pages: list[list[dict]]) -> MagicMock:
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Schemas": page} for page in pages]
        mock_glue_client.get_paginator.return_value = paginator
        return paginator

    def test_success_returns_all_schema_names(self, backend, mock_glue_client):
        self._setup_paginator(mock_glue_client, [
            [{"SchemaName": "payments_stream"}, {"SchemaName": "flights_stream"}],
            [{"SchemaName": "iot_stream"}],
        ])

        result = backend.list_subjects()

        assert result == ["payments_stream", "flights_stream", "iot_stream"]

    def test_paginates_across_multiple_pages(self, backend, mock_glue_client):
        schemas_page1 = [{"SchemaName": f"schema_{i}"} for i in range(5)]
        schemas_page2 = [{"SchemaName": f"schema_{i}"} for i in range(5, 8)]
        self._setup_paginator(mock_glue_client, [schemas_page1, schemas_page2])

        result = backend.list_subjects()

        assert len(result) == 8

    def test_filter_applied(self, backend, mock_glue_client):
        self._setup_paginator(mock_glue_client, [[
            {"SchemaName": "payments_stream"},
            {"SchemaName": "payments_v2"},
            {"SchemaName": "flights_stream"},
        ]])

        result = backend.list_subjects(filter="payments*")

        assert sorted(result) == ["payments_stream", "payments_v2"]

    def test_filter_with_no_matches_returns_empty(self, backend, mock_glue_client):
        self._setup_paginator(mock_glue_client, [[{"SchemaName": "flights_stream"}]])

        result = backend.list_subjects(filter="payments*")

        assert result == []

    def test_empty_registry_returns_empty_list(self, backend, mock_glue_client):
        self._setup_paginator(mock_glue_client, [[]])

        result = backend.list_subjects()

        assert result == []

    def test_paginator_called_with_registry_name(self, backend, mock_glue_client):
        self._setup_paginator(mock_glue_client, [[]])

        backend.list_subjects()

        paginator = mock_glue_client.get_paginator.return_value
        paginator.paginate.assert_called_once_with(RegistryId={"RegistryName": "StreamForge"})

    def test_exception_returns_empty_list(self, backend, mock_glue_client):
        mock_glue_client.get_paginator.side_effect = Exception("access denied")

        result = backend.list_subjects()

        assert result == []


# ── is_compatible ─────────────────────────────────────────────────────────────

class TestGlueIsCompatible:
    def test_valid_schema_returns_true(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.return_value = {"Valid": True}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("test_stream", schema)

        assert result is True

    def test_invalid_schema_returns_false(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.return_value = {"Valid": False}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("test_stream", schema)

        assert result is False

    def test_called_with_avro_data_format(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.return_value = {"Valid": True}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("test_stream", schema)

        call_kwargs = mock_glue_client.query_schema_version_validity.call_args[1]
        assert call_kwargs["DataFormat"] == "AVRO"

    def test_called_with_correct_schema_id(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.return_value = {"Valid": True}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("test_stream", schema)

        call_kwargs = mock_glue_client.query_schema_version_validity.call_args[1]
        assert call_kwargs["SchemaId"] == {
            "SchemaName": "test_stream",
            "RegistryName": "StreamForge",
        }

    def test_exception_returns_false(self, backend, mock_glue_client):
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.side_effect = Exception("access denied")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("test_stream", schema)

        assert result is False

    def test_entity_not_found_means_compatible(self, backend, mock_glue_client):
        """No existing versions = any schema is compatible (protocol contract)."""
        schema = make_schema()
        mock_glue_client.query_schema_version_validity.side_effect = (
            mock_glue_client.exceptions.EntityNotFoundException("Schema not found")
        )

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("brand_new_stream", schema)

        assert result is True, (
            "is_compatible must return True when schema doesn't exist yet (no prior version)"
        )

    def test_resource_not_found_means_compatible(self, backend, mock_glue_client):
        """Glue also raises EntityNotFoundException for missing schemas — must return True."""
        schema = make_schema()
        # Simulate the same exception type since Glue uses EntityNotFoundException
        mock_glue_client.query_schema_version_validity.side_effect = (
            mock_glue_client.exceptions.EntityNotFoundException("ResourceNotFoundException")
        )

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("nonexistent", schema)

        assert result is True


# ── registry initialisation ───────────────────────────────────────────────────

class TestGlueRegistryInit:
    def test_creates_registry_when_not_found(self, mock_boto3):
        from streamforge.registries.glue import GlueRegistryBackend

        client = MagicMock()
        client.exceptions.EntityNotFoundException = type(
            "EntityNotFoundException", (Exception,), {}
        )
        client.get_registry.side_effect = client.exceptions.EntityNotFoundException("not found")
        client.create_registry.return_value = {"RegistryName": "NewRegistry"}
        mock_boto3.client.return_value = client

        GlueRegistryBackend(registry_name="NewRegistry")

        client.create_registry.assert_called_once_with(
            RegistryName="NewRegistry",
            Description="StreamForge schema registry",
        )

    def test_does_not_create_registry_when_it_exists(self, mock_boto3):
        from streamforge.registries.glue import GlueRegistryBackend

        client = MagicMock()
        client.exceptions.EntityNotFoundException = type(
            "EntityNotFoundException", (Exception,), {}
        )
        client.get_registry.return_value = {"RegistryName": "StreamForge"}
        mock_boto3.client.return_value = client

        GlueRegistryBackend(registry_name="StreamForge")

        client.create_registry.assert_not_called()

    def test_other_exception_in_ensure_registry_is_suppressed(self, mock_boto3):
        """Non-EntityNotFoundException errors are silently suppressed at init."""
        from streamforge.registries.glue import GlueRegistryBackend

        client = MagicMock()
        client.exceptions.EntityNotFoundException = type(
            "EntityNotFoundException", (Exception,), {}
        )
        client.get_registry.side_effect = PermissionError("access denied")
        mock_boto3.client.return_value = client

        backend = GlueRegistryBackend(registry_name="StreamForge")

        # Backend still constructed — push will fail later with clearer error
        assert backend._registry_name == "StreamForge"


# ── missing boto3 ─────────────────────────────────────────────────────────────

class TestGlueMissingBoto3:
    def test_import_error_raised_with_helpful_message(self):
        import builtins

        from streamforge.registries.glue import GlueRegistryBackend
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        # Remove boto3 from sys.modules to ensure the import runs
        with patch.dict(sys.modules, {"boto3": None}), \
             patch("builtins.__import__", side_effect=mock_import), \
             pytest.raises(ImportError, match="boto3 is required"):
            GlueRegistryBackend()

    def test_error_message_includes_install_hint(self):
        import builtins

        from streamforge.registries.glue import GlueRegistryBackend
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"boto3": None}), \
             patch("builtins.__import__", side_effect=mock_import), \
             pytest.raises(ImportError, match="pip install"):
            GlueRegistryBackend()


# ── from_env ──────────────────────────────────────────────────────────────────

class TestGlueFromEnv:
    def _make_client(self, mock_boto3) -> MagicMock:
        client = MagicMock()
        client.exceptions.EntityNotFoundException = type(
            "EntityNotFoundException", (Exception,), {}
        )
        client.get_registry.return_value = {}
        mock_boto3.client.return_value = client
        return client

    def test_default_registry_name(self, monkeypatch, mock_boto3):
        monkeypatch.delenv("GLUE_REGISTRY_NAME", raising=False)
        self._make_client(mock_boto3)

        from streamforge.registries.glue import from_env
        backend = from_env()

        assert backend._registry_name == "StreamForge"

    def test_env_registry_name_applied(self, monkeypatch, mock_boto3):
        monkeypatch.setenv("GLUE_REGISTRY_NAME", "MyRegistry")
        self._make_client(mock_boto3)

        from streamforge.registries.glue import from_env
        backend = from_env()

        assert backend._registry_name == "MyRegistry"

    def test_aws_region_env_var_passed_to_constructor(self, monkeypatch, mock_boto3):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        self._make_client(mock_boto3)

        from streamforge.registries.glue import from_env
        from_env()

        # The boto3 mock was called — region resolved without error
        mock_boto3.client.assert_called_once()
        assert mock_boto3.client.call_args[0][0] == "glue"

    def test_aws_default_region_fallback(self, monkeypatch, mock_boto3):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
        self._make_client(mock_boto3)

        from streamforge.registries.glue import from_env
        backend = from_env()

        assert backend._registry_name == "StreamForge"
