"""
Health Endpoint Tests for K8s Probes.

Tests verify:
1. /health returns liveness status
2. /ready returns readiness with checks
3. /startup tracks initialization
4. /health/sidecar returns circuit breaker status
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestHealthEndpoint:
    """Tests for /health (liveness probe)."""

    @pytest.mark.asyncio
    async def test_health_returns_status(self):
        """Health endpoint returns status and components."""
        from streamforge.api.routes.health import health_check

        with patch("streamforge.api.routes.health.get_store") as mock_store:
            mock_store.return_value.check_health.return_value = {"status": "ok"}

            result = await health_check()

            assert "status" in result
            assert "components" in result
            assert result["status"] in ("ok", "degraded")

    @pytest.mark.asyncio
    async def test_health_degraded_when_component_fails(self):
        """Health returns degraded when any component fails."""
        from streamforge.api.routes.health import health_check

        with patch("streamforge.api.routes.health.get_store") as mock_store:
            mock_store.return_value.check_health.side_effect = [
                {"status": "ok"},
                {"status": "error"},
            ]

            result = await health_check()

            assert result["status"] == "degraded"


class TestReadinessEndpoint:
    """Tests for /ready (readiness probe)."""

    @pytest.mark.asyncio
    async def test_ready_returns_checks(self):
        """Readiness endpoint returns check details."""
        from streamforge.api.routes.health import readiness_check

        mock_response = MagicMock()

        with patch("streamforge.api.routes.health.get_store") as mock_store:
            mock_store.return_value.check_health.return_value = {"status": "ok"}

            with patch("streamforge.api.routes.health.Path") as mock_path:
                mock_path.return_value.exists.return_value = True
                mock_path.return_value.glob.return_value = []

                result = await readiness_check(mock_response)

                assert "ready" in result
                assert "checks" in result

    @pytest.mark.asyncio
    async def test_ready_503_when_not_ready(self):
        """Readiness returns 503 when checks fail."""
        from streamforge.api.routes.health import readiness_check

        mock_response = MagicMock()

        with patch("streamforge.api.routes.health.get_store") as mock_store:
            mock_store.return_value.check_health.return_value = {"status": "error"}

            with patch("streamforge.api.routes.health.Path") as mock_path:
                mock_path.return_value.exists.return_value = False

                result = await readiness_check(mock_response)

                assert result["ready"] is False
                assert mock_response.status_code == 503


class TestStartupEndpoint:
    """Tests for /startup (startup probe)."""

    @pytest.mark.asyncio
    async def test_startup_returns_phase(self):
        """Startup endpoint returns phase info."""
        from streamforge.api.routes.health import startup_check

        mock_response = MagicMock()

        result = await startup_check(mock_response)

        assert "started" in result
        assert "phase" in result

    @pytest.mark.asyncio
    async def test_startup_complete_after_mark(self):
        """Startup returns started=True after mark_startup_complete()."""
        from streamforge.api.routes import health
        from streamforge.api.routes.health import mark_startup_complete, startup_check

        # Reset state
        health._startup_complete = False

        mock_response = MagicMock()

        # Before marking complete
        result1 = await startup_check(mock_response)
        assert result1["started"] is False

        # Mark complete
        mark_startup_complete()

        # After marking complete
        result2 = await startup_check(mock_response)
        assert result2["started"] is True
        assert result2["phase"] == "ready"


class TestSidecarHealthEndpoint:
    """Tests for /health/sidecar (circuit breaker status)."""

    @pytest.mark.asyncio
    async def test_sidecar_health_returns_breakers(self):
        """Sidecar health returns circuit breaker status."""
        from streamforge.api.routes.health import sidecar_health

        # First, create some circuit breakers
        from streamforge.resilience import get_or_create_breaker

        breaker = get_or_create_breaker("test-queue", fail_max=3)

        result = await sidecar_health()

        assert "status" in result
        assert "circuit_breakers" in result
        assert "test-queue" in result["circuit_breakers"]

    @pytest.mark.asyncio
    async def test_sidecar_health_degraded_when_open(self):
        """Sidecar health returns degraded when circuit is open."""
        from streamforge.api.routes.health import sidecar_health
        from streamforge.resilience import get_or_create_breaker

        breaker = get_or_create_breaker("failing-queue", fail_max=1)

        # Open the circuit
        def failing():
            raise Exception("fail")

        try:
            breaker.call(failing)
        except Exception:
            pass

        result = await sidecar_health()

        assert result["status"] == "degraded"
        assert result["circuit_breakers"]["failing-queue"]["state"] == "open"

    @pytest.mark.asyncio
    async def test_sidecar_health_healthy_when_closed(self):
        """Sidecar health returns healthy when all circuits closed."""
        from streamforge.api.routes.health import sidecar_health
        from streamforge.resilience import get_or_create_breaker

        # Reset breaker
        breaker = get_or_create_breaker("healthy-queue", fail_max=5)
        breaker.reset()

        result = await sidecar_health()

        assert result["circuit_breakers"]["healthy-queue"]["state"] == "closed"
