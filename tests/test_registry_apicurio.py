"""
Unit tests for ApicurioRegistryBackend.

All tests are offline — no real HTTP calls. The httpx client is replaced with
a MagicMock so every test controls exactly what the server returns.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.registries.apicurio import ApicurioRegistryBackend, from_env

# ── shared fixtures ───────────────────────────────────────────────────────────

_AVRO_DOC = {"type": "record", "name": "TestStream", "fields": [{"name": "id", "type": "string"}]}


def make_schema(stream_name: str = "test_stream") -> InferredSchema:
    return InferredSchema(
        stream_name=stream_name,
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=100,
        fields=[
            FieldSchema(name="id", path="id", field_type=FieldType.UUID),
            FieldSchema(name="status", path="status", field_type=FieldType.STRING),
        ],
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.93,
    )


def make_backend(
    url: str = "http://localhost:8080",
    group: str = "default",
    token: str = "",
) -> ApicurioRegistryBackend:
    """Return a backend whose HTTP client is fully mocked."""
    backend = ApicurioRegistryBackend(url=url, group=group, token=token)
    backend._client = MagicMock()
    return backend


def _mock_response(status: int, body=None, text: str | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = text if text is not None else json.dumps(body or {})
    return resp


# ── push_schema ───────────────────────────────────────────────────────────────

class TestApicurioPushSchema:
    def test_success_201_returns_version_and_global_id(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(
            201, {"globalId": 7, "version": "3", "id": "test_stream"}
        )

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema, fmt="avro")

        assert result.success is True
        assert result.schema_id == 7
        assert result.version == "3"
        assert result.subject == "test_stream"
        assert "test_stream" in (result.url or "")

    def test_success_200_also_accepted(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(
            200, {"globalId": 1, "version": "1"}
        )

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert result.success is True

    def test_push_sets_correct_artifact_headers(self):
        backend = make_backend(group="production")
        schema = make_schema()
        backend._client.post.return_value = _mock_response(200, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("my-subject", schema, fmt="avro")

        call_headers = backend._client.post.call_args[1]["headers"]
        assert call_headers["X-Registry-ArtifactId"] == "my-subject"
        assert call_headers["X-Registry-ArtifactType"] == "AVRO"
        assert call_headers["X-Registry-IfExists"] == "UPDATE"

    def test_json_schema_format_uses_json_artifact_type(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(201, {"globalId": 2, "version": "1"})

        js_doc = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}
        with patch("streamforge.exporters.json_schema.schema_to_json_schema", return_value=js_doc):
            backend.push_schema("my-subject", schema, fmt="json-schema")

        call_headers = backend._client.post.call_args[1]["headers"]
        assert call_headers["X-Registry-ArtifactType"] == "JSON"

    def test_http_error_returns_failure(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(409, {})
        backend._client.post.return_value.text = "Conflict"

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is False
        assert "409" in result.error

    def test_timeout_returns_failure(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.side_effect = httpx.TimeoutException("timeout")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("test_stream", schema)

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_network_exception_returns_failure(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.side_effect = ConnectionError("refused")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("s", schema)

        assert result.success is False

    def test_serialisation_error_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        with patch("streamforge.exporters.avro.schema_to_avro", side_effect=RuntimeError("bad avro")):
            result = backend.push_schema("s", schema, fmt="avro")

        assert result.success is False
        assert "serialisation" in result.error.lower()

    def test_unsupported_format_returns_failure(self):
        backend = make_backend()
        schema = make_schema()

        result = backend.push_schema("s", schema, fmt="protobuf")

        assert result.success is False
        assert "Unsupported format" in result.error

    def test_url_contains_group_name(self):
        backend = make_backend(group="my-group")
        schema = make_schema()
        backend._client.post.return_value = _mock_response(200, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("s", schema)

        called_url = backend._client.post.call_args[0][0]
        assert "my-group" in called_url


# ── get_schema ────────────────────────────────────────────────────────────────

class TestApicurioGetSchema:
    def test_success_returns_parsed_schema(self):
        backend = make_backend()
        schema_content = {"type": "record", "name": "Flight", "fields": []}

        meta_resp = _mock_response(200, {"version": "2"})
        content_resp = _mock_response(200, schema_content, text=json.dumps(schema_content))
        backend._client.get.side_effect = [meta_resp, content_resp]

        result = backend.get_schema("flights-stream")

        assert result == schema_content

    def test_meta_not_found_returns_none(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {})

        result = backend.get_schema("nonexistent")

        assert result is None

    def test_content_not_found_returns_none(self):
        backend = make_backend()
        meta_resp = _mock_response(200, {})
        content_resp = _mock_response(404, {})
        backend._client.get.side_effect = [meta_resp, content_resp]

        result = backend.get_schema("s")

        assert result is None

    def test_exception_returns_none(self):
        backend = make_backend()
        backend._client.get.side_effect = Exception("connection error")

        result = backend.get_schema("s")

        assert result is None

    def test_uses_latest_version_by_default(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("s")

        first_url = backend._client.get.call_args_list[0][0][0]
        assert "/versions/latest/meta" in first_url

    def test_specific_version_in_meta_url(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("s", version="5")

        first_url = backend._client.get.call_args_list[0][0][0]
        assert "/versions/5/meta" in first_url

    def test_url_contains_group_and_artifact(self):
        backend = make_backend(group="my-group")
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("my-artifact")

        first_url = backend._client.get.call_args_list[0][0][0]
        assert "my-group" in first_url
        assert "my-artifact" in first_url


# ── list_subjects ─────────────────────────────────────────────────────────────

class TestApicurioListSubjects:
    def test_success_returns_artifact_ids(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, {
            "artifacts": [
                {"id": "payments-stream", "type": "AVRO"},
                {"id": "flights-stream", "type": "AVRO"},
            ]
        })

        result = backend.list_subjects()

        assert result == ["payments-stream", "flights-stream"]

    def test_filter_applied(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, {
            "artifacts": [
                {"id": "payments-stream"},
                {"id": "payments-v2"},
                {"id": "flights-stream"},
            ]
        })

        result = backend.list_subjects(filter="payments*")

        assert sorted(result) == ["payments-stream", "payments-v2"]

    def test_filter_with_no_matches_returns_empty(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, {
            "artifacts": [{"id": "flights-stream"}]
        })

        result = backend.list_subjects(filter="payments*")

        assert result == []

    def test_empty_registry_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, {"artifacts": []})

        result = backend.list_subjects()

        assert result == []

    def test_http_error_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(500, {})

        result = backend.list_subjects()

        assert result == []

    def test_exception_returns_empty_list(self):
        backend = make_backend()
        backend._client.get.side_effect = Exception("network error")

        result = backend.list_subjects()

        assert result == []

    def test_requests_up_to_500_artifacts(self):
        backend = make_backend()
        backend._client.get.return_value = _mock_response(200, {"artifacts": []})

        backend.list_subjects()

        call_params = backend._client.get.call_args[1].get("params", {})
        assert call_params.get("limit") == 500

    def test_url_contains_group(self):
        backend = make_backend(group="staging")
        backend._client.get.return_value = _mock_response(200, {"artifacts": []})

        backend.list_subjects()

        called_url = backend._client.get.call_args[0][0]
        assert "staging" in called_url


# ── is_compatible ─────────────────────────────────────────────────────────────

class TestApicurioIsCompatible:
    def test_204_means_compatible(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(204)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is True

    def test_409_means_incompatible(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(409)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is False

    def test_200_means_incompatible(self):
        """Apicurio returns 204 for compatible — any other 2xx is not 204."""
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(200)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is False

    def test_exception_returns_false(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.side_effect = Exception("error")

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.is_compatible("s", schema)

        assert result is False

    def test_uses_test_endpoint(self):
        backend = make_backend(group="my-group")
        schema = make_schema()
        backend._client.post.return_value = _mock_response(204)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("my-artifact", schema)

        called_url = backend._client.post.call_args[0][0]
        assert "my-group" in called_url
        assert "my-artifact" in called_url
        assert called_url.endswith("/test")


# ── result truthiness ─────────────────────────────────────────────────────────

class TestRegistryResult:
    def test_success_result_is_truthy(self):
        backend = make_backend()
        schema = make_schema()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

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


# ── authentication ────────────────────────────────────────────────────────────

class TestApicurioAuth:
    def test_bearer_token_set_in_client_headers(self):
        backend = ApicurioRegistryBackend(url="http://localhost:8080", token="mytoken123")

        assert backend._client.headers.get("Authorization") == "Bearer mytoken123"

    def test_no_token_means_no_auth_header(self):
        backend = ApicurioRegistryBackend(url="http://localhost:8080", token="")

        assert "Authorization" not in backend._client.headers


# ── from_env ──────────────────────────────────────────────────────────────────

class TestApicurioFromEnv:
    def test_default_url_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("APICURIO_URL", raising=False)
        monkeypatch.delenv("APICURIO_GROUP", raising=False)
        monkeypatch.delenv("APICURIO_TOKEN", raising=False)

        backend = from_env()

        assert "localhost:8080" in backend._base
        assert backend._group == "default"

    def test_env_vars_applied(self, monkeypatch):
        monkeypatch.setenv("APICURIO_URL", "http://apicurio.prod:8080")
        monkeypatch.setenv("APICURIO_GROUP", "production")
        monkeypatch.setenv("APICURIO_TOKEN", "tok-abc")

        backend = from_env()

        assert "apicurio.prod" in backend._base
        assert backend._group == "production"

    def test_explicit_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("APICURIO_URL", "http://env-apicurio:8080")

        backend = from_env(url="http://explicit:8080")

        assert "explicit" in backend._base

    def test_trailing_slash_stripped(self):
        backend = ApicurioRegistryBackend(url="http://localhost:8080/")

        assert not backend._base.startswith("http://localhost:8080//")

    def test_base_url_includes_v2_api_path(self):
        backend = ApicurioRegistryBackend(url="http://localhost:8080")

        assert backend._base.endswith("/apis/registry/v2")
