"""
Tests that subject names with special characters are percent-encoded in URLs.

These tests are in the RED phase — they will FAIL until confluent.py and
apicurio.py apply urllib.parse.quote(subject, safe="") before interpolation.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.registries.confluent import ConfluentRegistryBackend
from streamforge.registries.apicurio import ApicurioRegistryBackend

# ── shared fixtures ────────────────────────────────────────────────────────────

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


def make_confluent(url: str = "http://localhost:8081") -> ConfluentRegistryBackend:
    b = ConfluentRegistryBackend(url=url)
    b._client = MagicMock()
    return b


def make_apicurio(
    url: str = "http://localhost:8080",
    group: str = "default",
) -> ApicurioRegistryBackend:
    b = ApicurioRegistryBackend(url=url, group=group)
    b._client = MagicMock()
    return b


# ── Confluent — push_schema ────────────────────────────────────────────────────


class TestConfluentPushSchemaUrlEncoding:
    def test_slash_in_subject_is_encoded(self):
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("org/events", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%2F" in url, f"Expected %2F in URL, got: {url}"
        # Raw slash must not appear in the path component
        path = url.split("localhost:8081", 1)[1]
        assert "/org/events/" not in path, f"Unencoded slash in path: {path}"

    def test_space_in_subject_is_encoded(self):
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("my topic", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%20" in url, f"Expected %20 in URL, got: {url}"
        assert " " not in url, f"Unencoded space in URL: {url}"

    def test_plus_in_subject_is_encoded(self):
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("events+stream", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%2B" in url, f"Expected %2B in URL, got: {url}"

    def test_dots_and_dashes_preserved(self):
        """Dots and dashes are safe in URL path segments and must NOT be encoded."""
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(201, {"id": 1})
        backend._client.get.return_value = _mock_response(404, {})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("events.payments-value", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "events.payments-value" in url, f"Dots/dashes should be preserved: {url}"


# ── Confluent — get_schema ─────────────────────────────────────────────────────


class TestConfluentGetSchemaUrlEncoding:
    def test_slash_in_subject_encoded_in_get(self):
        backend = make_confluent()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("org/events")

        url = backend._client.get.call_args[0][0]
        assert "%2F" in url, f"Expected %2F in URL, got: {url}"

    def test_space_in_subject_encoded_in_get(self):
        backend = make_confluent()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("my topic")

        url = backend._client.get.call_args[0][0]
        assert "%20" in url
        assert " " not in url


# ── Confluent — is_compatible ──────────────────────────────────────────────────


class TestConfluentIsCompatibleUrlEncoding:
    def test_slash_in_subject_encoded_in_compatibility_check(self):
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(200, {"is_compatible": True})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("org/events", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%2F" in url, f"Expected %2F in compatibility URL, got: {url}"

    def test_space_in_subject_encoded_in_compatibility_check(self):
        backend = make_confluent()
        backend._client.post.return_value = _mock_response(200, {"is_compatible": True})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("my topic", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%20" in url
        assert " " not in url


# ── Apicurio — push_schema ─────────────────────────────────────────────────────
#
# Apicurio posts to {base}/groups/{group}/artifacts — the subject is NOT in the
# request URL (it goes in the X-Registry-ArtifactId header). However, the returned
# RegistryResult.url must be percent-encoded so consumers can use it as a URL.


class TestApicurioPushSchemaUrlEncoding:
    def test_slash_in_subject_encoded_in_result_url(self):
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("org/events", make_schema())

        assert result.success is True
        assert result.url is not None
        assert "%2F" in result.url, f"Expected %2F in result.url, got: {result.url}"
        path = result.url.split("localhost:8080", 1)[1]
        assert "/org/events" not in path, f"Unencoded slash in result URL path: {path}"

    def test_space_in_subject_encoded_in_result_url(self):
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("my topic", make_schema())

        assert "%20" in (result.url or "")
        assert " " not in (result.url or "")

    def test_plus_in_subject_encoded_in_result_url(self):
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            result = backend.push_schema("events+stream", make_schema())

        assert "%2B" in (result.url or "")

    def test_artifact_id_header_is_raw_not_encoded(self):
        """X-Registry-ArtifactId header must use the raw subject (Apicurio reads it as-is)."""
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(201, {"globalId": 1, "version": "1"})

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.push_schema("org/events", make_schema())

        headers = backend._client.post.call_args[1]["headers"]
        assert headers["X-Registry-ArtifactId"] == "org/events"


# ── Apicurio — get_schema ──────────────────────────────────────────────────────


class TestApicurioGetSchemaUrlEncoding:
    def test_slash_in_subject_encoded_in_meta_url(self):
        backend = make_apicurio()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("org/events")

        url = backend._client.get.call_args_list[0][0][0]
        assert "%2F" in url, f"Expected %2F in meta URL, got: {url}"

    def test_space_in_subject_encoded_in_meta_url(self):
        backend = make_apicurio()
        backend._client.get.return_value = _mock_response(404, {})

        backend.get_schema("my topic")

        url = backend._client.get.call_args_list[0][0][0]
        assert "%20" in url
        assert " " not in url


# ── Apicurio — is_compatible ───────────────────────────────────────────────────


class TestApicurioIsCompatibleUrlEncoding:
    def test_slash_in_subject_encoded_in_test_url(self):
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(204)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("org/events", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%2F" in url, f"Expected %2F in test URL, got: {url}"
        assert url.endswith("/test"), f"URL should end with /test, got: {url}"

    def test_space_in_subject_encoded_in_test_url(self):
        backend = make_apicurio()
        backend._client.post.return_value = _mock_response(204)

        with patch("streamforge.exporters.avro.schema_to_avro", return_value=_AVRO_DOC):
            backend.is_compatible("my topic", make_schema())

        url = backend._client.post.call_args[0][0]
        assert "%20" in url
        assert " " not in url
