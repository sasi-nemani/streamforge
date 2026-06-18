"""
Unit tests for ConfluentRegistryBackend.

All tests are offline — no real HTTP calls. The httpx client is replaced with
a MagicMock so every test controls exactly what the server returns.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.registries.confluent import ConfluentRegistryBackend, from_env

# ── shared fixtures ───────────────────────────────────────────────────────────

_AVRO_DOC = {"type": "record", "name": "TestStream", "fields": [{"name": "id", "type": "string"}]}


def make_schema(stream_name: str = "test_stream") -> InferredSchema:
    return InferredSchema(
        stream_name=stream_name,
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=100,
        fields=[
            FieldSchema(name="id", path="id", field_type=FieldType.UUID),
            FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT),
        ],
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.95,
    )


def make_backend(url: str = "http://localhost:8081") -> ConfluentRegistryBackend:
    """Return a backend whose HTTP client is fully mocked."""
    backend = ConfluentRegistryBackend(url=url)
    backend._client = MagicMock()
    return backend


def _mock_response(status: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


# ── push_schema ───────────────────────────────────────────────────────────────

class TestPushSchema:
    def test_success_returns_schema_id_and_version(self):
        backend = make_backend()
        schema = make_schema()

        # POST → 201, id=42
        backend._client.post.return_value = _mock_response(201, {"id": 42})
        # GET versions list → [1, 2]
        versions_resp = _mock_response(200, [1, 2])
        # GET version detail → matches id 42
        ver2_resp = _mock_response(200, {"id": 42, "version": 2})
        backend._client.get.side_effect = [versions_resp, ver2_resp]

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream-value", schema, fmt="avro")

        assert result.success is True
        assert result.schema_id == 42
        assert result.version == 2
        assert result.subject == "test_stream-value"
        assert "test_stream-value" in (result.url or "")

    def test_http_201_and_200_both_accepted(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.return_value = _mock_response(200, {"id": 7})
        backend._client.get.side_effect = [
            _mock_response(200, [1]),
            _mock_response(200, {"id": 7, "version": 1}),
        ]

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert result.success is True
        assert result.schema_id == 7

    def test_http_error_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.return_value = _mock_response(422, {"error_code": 42201})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream-value", schema)

        assert result.success is False
        assert "422" in result.error
        assert result.subject == "test_stream-value"

    def test_timeout_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.side_effect = httpx.TimeoutException("timed out")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream-value", schema)

        assert result.success is False
        assert "timed out" in result.error.lower()
        assert result.subject == "test_stream-value"

    def test_network_exception_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.side_effect = ConnectionError("connection refused")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert result.success is False
        assert result.error  # non-empty error message

    def test_serialisation_error_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        with patch("streamforge.exporters.avro.schema_to_avro", side_effect=ValueError("bad schema")):
            result = backend.push_schema("s", schema, fmt="avro")

        assert result.success is False
        assert "serialisation" in result.error.lower()

    def test_unsupported_format_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        result = backend.push_schema("s", schema, fmt="protobuf")

        assert result.success is False
        assert "Unsupported format" in result.error

    def test_json_schema_format_success(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.return_value = _mock_response(201, {"id": 10})
        backend._client.get.side_effect = [
            _mock_response(200, [1]),
            _mock_response(200, {"id": 10, "version": 1}),
        ]

        js_doc = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}
        with patch("streamforge.exporters.json_schema.schema_to_json_schema", return_value=js_doc):
            result = backend.push_schema("s", schema, fmt="json-schema")

        assert result.success is True
        assert result.schema_id == 10

    def test_version_lookup_fails_gracefully(self):
        """If the version lookup returns no match, version is None but push still succeeds."""
        backend = make_backend()
        schema = make_schema()

        backend._client.post.return_value = _mock_response(201, {"id": 99})
        # Versions list call fails
        backend._client.get.return_value = _mock_response(500, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert result.success is True
        assert result.schema_id == 99
        assert result.version is None  # lookup failed, version unknown


# ── get_schema ────────────────────────────────────────────────────────────────

class TestGetSchema:
    def test_success_returns_parsed_dict(self):
        backend = make_backend()
        schema_content = {"type": "record", "name": "Payment", "fields": []}
        backend._client.get.return_value = _mock_response(
            200, {"schema": json.dumps(schema_content)}
        )

        result = backend.get_schema("test_stream-value")

        assert result == schema_content

    def test_not_found_returns_none(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {"error_code": 40401})

        result = backend.get_schema("nonexistent-subject")

        assert result is None

    def test_exception_returns_none(self):
        backend = make_backend()
        backend._client.get.side_effect = Exception("network failure")

        result = backend.get_schema("test_stream-value")

        assert result is None

    def test_uses_latest_version_by_default(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("s")

        called_url = backend._client.get.call_args[0][0]
        assert "/versions/latest" in called_url

    def test_specific_version_in_url(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("s", version="3")

        called_url = backend._client.get.call_args[0][0]
        assert "/versions/3" in called_url


# ── list_subjects ─────────────────────────────────────────────────────────────

class TestListSubjects:
    def test_success_returns_all_subjects(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(
            200, ["payments-value", "flights-value", "bookings-value"]
        )

        result = backend.list_subjects()

        assert result == ["payments-value", "flights-value", "bookings-value"]

    def test_filter_applied(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(
            200, ["payments-value", "flights-value", "payments-key"]
        )

        result = backend.list_subjects(filter="payments*")

        assert sorted(result) == ["payments-key", "payments-value"]

    def test_filter_with_no_matches_returns_empty(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(
            200, ["flights-value", "bookings-value"]
        )

        result = backend.list_subjects(filter="payments*")

        assert result == []

    def test_http_error_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(500, {})

        result = backend.list_subjects()

        assert result == []

    def test_exception_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.side_effect = Exception("connection refused")

        result = backend.list_subjects()

        assert result == []

    def test_empty_registry_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, [])

        result = backend.list_subjects()

        assert result == []


# ── is_compatible ─────────────────────────────────────────────────────────────

class TestIsCompatible:
    def test_compatible_returns_true(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(200, {"is_compatible": True})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("test_stream-value", schema)

        assert result is True

    def test_incompatible_returns_false(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(200, {"is_compatible": False})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("test_stream-value", schema)

        assert result is False

    def test_404_means_no_prior_version_thus_compatible(self):
        """Subject does not exist yet → compatible by definition."""
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("brand-new-subject", schema)

        assert result is True

    def test_other_http_error_returns_false(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(500, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is False

    def test_exception_returns_false(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.side_effect = Exception("network error")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is False


# ── result truthiness ─────────────────────────────────────────────────────────

class TestRegistryResult:
    def test_success_result_is_truthy(self):
        backend = make_backend()
        schema = make_schema()

        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.side_effect = [
            _mock_response(200, [1]),
            _mock_response(200, {"id": 1, "version": 1}),
        ]

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert bool(result) is True

    def test_failure_result_is_falsy(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(500, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert bool(result) is False


# ── from_env ──────────────────────────────────────────────────────────────────

class TestFromEnv:
    def test_default_url_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SCHEMA_REGISTRY_URL", raising=False)

        backend = from_env()

        assert "localhost:8081" in backend._base

    def test_uses_env_url(self, monkeypatch):
        monkeypatch.setenv("SCHEMA_REGISTRY_URL", "http://myregistry:8081")

        backend = from_env()

        assert backend._base == "http://myregistry:8081"

    def test_explicit_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SCHEMA_REGISTRY_URL", "http://env-registry:8081")

        backend = from_env(url="http://explicit:8081")

        assert backend._base == "http://explicit:8081"

    def test_trailing_slash_stripped(self):
        backend = ConfluentRegistryBackend(url="http://localhost:8081/")

        assert not backend._base.endswith("/")
