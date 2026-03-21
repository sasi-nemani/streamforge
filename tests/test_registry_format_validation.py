"""
Tests that push_schema validates the fmt argument early and returns a clean error.

RED phase — these tests fail until format validation is moved to the start of
push_schema in each backend:

  BEFORE fix: error = "Schema serialisation failed: Unsupported format: 'xml'..."
  AFTER  fix: error = "Unsupported format 'xml'. Supported: avro, json-schema"

Also tests that Glue (Avro-only) rejects non-avro formats instead of silently
producing Avro output.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from streamforge.models import FieldSchema, FieldType, InferredSchema

_AVRO_DOC = {"type": "record", "name": "Test", "fields": []}


def make_schema() -> InferredSchema:
    return InferredSchema(
        stream_name="test",
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=10,
        fields=[FieldSchema(name="id", path="id", field_type=FieldType.UUID)],
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.9,
    )


def _mock_response(status: int, body=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


# ── Confluent format validation ────────────────────────────────────────────────


class TestConfluentFormatValidation:
    def _make(self):
        from streamforge.registries.confluent import ConfluentRegistryBackend
        b = ConfluentRegistryBackend(url="http://localhost:8081")
        b._client = MagicMock()
        return b

    def test_unsupported_format_error_does_not_mention_serialisation(self):
        """Error message must not blame serialisation when the format itself is wrong."""
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="xml")

        assert result.success is False
        assert "serialisation" not in (result.error or "").lower(), (
            f"Error mentions 'serialisation' when it should say 'Unsupported format': {result.error}"
        )

    def test_unsupported_format_error_names_the_format(self):
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="xml")

        assert "xml" in (result.error or "").lower()

    def test_unsupported_format_error_lists_supported_formats(self):
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="protobuf")

        error = result.error or ""
        assert "avro" in error.lower()

    def test_unsupported_format_does_not_call_http(self):
        """Validation failure must short-circuit before any network call."""
        backend = self._make()

        backend.push_schema("s", make_schema(), fmt="toml")

        backend._client.post.assert_not_called()

    def test_valid_avro_format_is_not_rejected(self):
        backend = self._make()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", make_schema(), fmt="avro")

        assert result.success is True

    def test_valid_json_schema_format_is_not_rejected(self):
        backend = self._make()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})
        js_doc = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}

        with patch("streamforge.exporters.json_schema.schema_to_json_schema", return_value=js_doc):
            result = backend.push_schema("s", make_schema(), fmt="json-schema")

        assert result.success is True

    def test_empty_string_format_returns_failure(self):
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="")

        assert result.success is False
        backend._client.post.assert_not_called()


# ── Apicurio format validation ─────────────────────────────────────────────────


class TestApicurioFormatValidation:
    def _make(self):
        from streamforge.registries.apicurio import ApicurioRegistryBackend
        b = ApicurioRegistryBackend(url="http://localhost:8080")
        b._client = MagicMock()
        return b

    def test_unsupported_format_error_does_not_mention_serialisation(self):
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="xml")

        assert result.success is False
        assert "serialisation" not in (result.error or "").lower(), (
            f"Error mentions 'serialisation': {result.error}"
        )

    def test_unsupported_format_names_the_format(self):
        backend = self._make()

        result = backend.push_schema("s", make_schema(), fmt="thrift")

        assert "thrift" in (result.error or "").lower()

    def test_unsupported_format_does_not_call_http(self):
        backend = self._make()

        backend.push_schema("s", make_schema(), fmt="csv")

        backend._client.post.assert_not_called()

    def test_valid_avro_format_is_not_rejected(self):
        backend = self._make()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", make_schema(), fmt="avro")

        assert result.success is True

    def test_valid_json_schema_format_is_not_rejected(self):
        backend = self._make()
        backend._client.post.return_value = _mock_response(201, {"globalId": 2, "version": "1"})
        js_doc = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}

        with patch("streamforge.exporters.json_schema.schema_to_json_schema", return_value=js_doc):
            result = backend.push_schema("s", make_schema(), fmt="json-schema")

        assert result.success is True


# ── Glue format validation ─────────────────────────────────────────────────────


@pytest.fixture()
def mock_boto3():
    mock_b3 = MagicMock()
    with patch.dict(sys.modules, {"boto3": mock_b3}):
        yield mock_b3


@pytest.fixture()
def mock_glue_client(mock_boto3) -> MagicMock:
    client = MagicMock()
    client.exceptions.EntityNotFoundException = type(
        "EntityNotFoundException", (Exception,), {}
    )
    client.get_registry.return_value = {"RegistryName": "StreamForge", "Status": "AVAILABLE"}
    mock_boto3.client.return_value = client
    return client


@pytest.fixture()
def glue_backend(mock_glue_client):
    from streamforge.registries.glue import GlueRegistryBackend
    return GlueRegistryBackend(registry_name="StreamForge")


class TestGlueFormatValidation:
    def test_json_schema_format_returns_failure(self, glue_backend, mock_glue_client):
        """Glue only supports Avro — json-schema must be rejected cleanly."""
        result = glue_backend.push_schema("s", make_schema(), fmt="json-schema")

        assert result.success is False

    def test_json_schema_format_error_is_descriptive(self, glue_backend, mock_glue_client):
        result = glue_backend.push_schema("s", make_schema(), fmt="json-schema")

        error = result.error or ""
        assert "json-schema" in error.lower() or "avro" in error.lower()

    def test_unsupported_format_does_not_call_register_schema_version(
        self, glue_backend, mock_glue_client
    ):
        """Validation must short-circuit before any Glue API call."""
        glue_backend.push_schema("s", make_schema(), fmt="protobuf")

        mock_glue_client.register_schema_version.assert_not_called()

    def test_avro_format_is_accepted(self, glue_backend, mock_glue_client):
        mock_glue_client.get_schema.return_value = {
            "SchemaArn": "arn:aws:glue:us-east-1:123:schema/StreamForge/s"
        }
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = glue_backend.push_schema("s", make_schema(), fmt="avro")

        assert result.success is True

    def test_default_format_avro_is_accepted(self, glue_backend, mock_glue_client):
        """Default fmt='avro' must work without explicit argument."""
        mock_glue_client.get_schema.return_value = {
            "SchemaArn": "arn:aws:glue:us-east-1:123:schema/StreamForge/s"
        }
        mock_glue_client.register_schema_version.return_value = {"VersionNumber": 1}

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = glue_backend.push_schema("s", make_schema())

        assert result.success is True
