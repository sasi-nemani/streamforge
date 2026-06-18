"""
Tests for ping() connectivity check on all three registry backends.

RED phase — all tests fail until ping() is implemented in each backend.

Confluent ping:  GET {base}/config  — 200 = reachable
Apicurio ping:   GET {base}/groups  — 200 = reachable
Glue ping:       get_registry(...)  — success = reachable
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ── helpers ────────────────────────────────────────────────────────────────────


def _mock_response(status: int, body=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


# ── Confluent ping ─────────────────────────────────────────────────────────────


class TestConfluentPing:
    def _make(self) -> ConfluentRegistryBackend:  # noqa: F821
        from streamforge.registries.confluent import ConfluentRegistryBackend
        b = ConfluentRegistryBackend(url="http://localhost:8081")
        b._client = MagicMock()
        return b

    def test_200_from_config_endpoint_returns_success(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {"defaultCompatibilityLevel": "BACKWARD"})

        result = backend.ping()

        assert result.success is True

    def test_ping_calls_config_endpoint(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {})

        backend.ping()

        url = backend._client.get.call_args[0][0]
        assert "/config" in url

    def test_non_200_returns_failure(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(503, {})

        result = backend.ping()

        assert result.success is False
        assert "503" in (result.error or "")

    def test_timeout_returns_failure(self):
        backend = self._make()
        backend._client.get.side_effect = httpx.TimeoutException("timeout")

        result = backend.ping()

        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    def test_connection_error_returns_failure(self):
        backend = self._make()
        backend._client.get.side_effect = ConnectionError("connection refused")

        result = backend.ping()

        assert result.success is False

    def test_ping_returns_registry_result(self):
        from streamforge.registries.base import RegistryResult
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {})

        result = backend.ping()

        assert isinstance(result, RegistryResult)

    def test_success_ping_is_truthy(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {})

        assert bool(backend.ping()) is True

    def test_failure_ping_is_falsy(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(503, {})

        assert bool(backend.ping()) is False


# ── Apicurio ping ──────────────────────────────────────────────────────────────


class TestApicurioPing:
    def _make(self) -> ApicurioRegistryBackend:  # noqa: F821
        from streamforge.registries.apicurio import ApicurioRegistryBackend
        b = ApicurioRegistryBackend(url="http://localhost:8080")
        b._client = MagicMock()
        return b

    def test_200_returns_success(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {"groups": []})

        result = backend.ping()

        assert result.success is True

    def test_ping_calls_groups_endpoint(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {})

        backend.ping()

        url = backend._client.get.call_args[0][0]
        assert "/groups" in url

    def test_non_200_returns_failure(self):
        backend = self._make()
        backend._client.get.return_value = _mock_response(503, {})

        result = backend.ping()

        assert result.success is False
        assert "503" in (result.error or "")

    def test_timeout_returns_failure(self):
        backend = self._make()
        backend._client.get.side_effect = httpx.TimeoutException("timeout")

        result = backend.ping()

        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    def test_connection_error_returns_failure(self):
        backend = self._make()
        backend._client.get.side_effect = ConnectionError("refused")

        result = backend.ping()

        assert result.success is False

    def test_ping_url_contains_api_version(self):
        """Ping URL must target the v2 API path, not the raw host."""
        backend = self._make()
        backend._client.get.return_value = _mock_response(200, {})

        backend.ping()

        url = backend._client.get.call_args[0][0]
        assert "registry/v2" in url


# ── Glue ping ──────────────────────────────────────────────────────────────────


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


class TestGluePing:
    def test_get_registry_success_returns_success(self, glue_backend, mock_glue_client):
        mock_glue_client.get_registry.return_value = {
            "RegistryName": "StreamForge",
            "Status": "AVAILABLE",
        }

        result = glue_backend.ping()

        assert result.success is True

    def test_ping_calls_get_registry(self, glue_backend, mock_glue_client):
        # Reset call count from __init__
        mock_glue_client.get_registry.reset_mock()
        mock_glue_client.get_registry.return_value = {"RegistryName": "StreamForge"}

        glue_backend.ping()

        mock_glue_client.get_registry.assert_called_once()

    def test_ping_uses_registry_name(self, glue_backend, mock_glue_client):
        mock_glue_client.get_registry.reset_mock()
        mock_glue_client.get_registry.return_value = {"RegistryName": "StreamForge"}

        glue_backend.ping()

        call_kwargs = mock_glue_client.get_registry.call_args[1]
        assert call_kwargs.get("RegistryId", {}).get("RegistryName") == "StreamForge"

    def test_get_registry_exception_returns_failure(self, glue_backend, mock_glue_client):
        mock_glue_client.get_registry.reset_mock()
        mock_glue_client.get_registry.side_effect = Exception("AccessDeniedException")

        result = glue_backend.ping()

        assert result.success is False
        assert result.error is not None

    def test_ping_returns_registry_result(self, glue_backend, mock_glue_client):
        from streamforge.registries.base import RegistryResult
        mock_glue_client.get_registry.return_value = {"RegistryName": "StreamForge"}

        result = glue_backend.ping()

        assert isinstance(result, RegistryResult)

    def test_ping_truthy_on_success(self, glue_backend, mock_glue_client):
        mock_glue_client.get_registry.return_value = {"RegistryName": "StreamForge"}

        assert bool(glue_backend.ping()) is True

    def test_ping_falsy_on_failure(self, glue_backend, mock_glue_client):
        mock_glue_client.get_registry.reset_mock()
        mock_glue_client.get_registry.side_effect = Exception("network error")

        assert bool(glue_backend.ping()) is False
