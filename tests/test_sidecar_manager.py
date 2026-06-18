"""
tests/test_sidecar_manager.py — TDD Tests for Sidecar Manager
==============================================================

Tests for sidecar orchestration and lifecycle management.

Phase 5: Integration & Orchestration
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest


class TestSidecarFactory:
    """Tests for sidecar factory."""

    def test_factory_creates_sqs_sidecar(self):
        """Factory must create SQS sidecar from config."""
        from streamforge.sidecar.factory import create_sidecar
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        sidecar = create_sidecar(config)
        assert isinstance(sidecar, SQSSidecar)

    def test_factory_creates_ibmmq_sidecar(self):
        """Factory must create IBM MQ sidecar from config."""
        from streamforge.sidecar.factory import create_sidecar
        from streamforge.sidecar.ibmmq import IBMMQSidecar
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        sidecar = create_sidecar(config)
        assert isinstance(sidecar, IBMMQSidecar)

    def test_factory_rejects_unknown_config(self):
        """Factory must reject unknown config types."""
        from streamforge.sidecar.factory import create_sidecar

        with pytest.raises(ValueError, match="Unsupported"):
            create_sidecar({"unknown": "config"})


class TestSidecarManager:
    """Tests for sidecar lifecycle manager."""

    @pytest.mark.asyncio
    async def test_manager_starts_sidecar(self):
        """Manager must start sidecar and run health check."""
        from streamforge.sidecar.manager import SidecarManager
        from streamforge.sidecar.models import SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar.health_check") as mock_health:
            from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation
            mock_health.return_value = TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name="orders",
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=10.0,
            )

            manager = SidecarManager()
            await manager.start(config)

            assert manager.is_running
            mock_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_manager_stops_sidecar(self):
        """Manager must properly stop sidecar."""
        from streamforge.sidecar.manager import SidecarManager
        from streamforge.sidecar.models import SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar.health_check") as mock_health:
            from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation
            mock_health.return_value = TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name="orders",
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=10.0,
            )

            manager = SidecarManager()
            await manager.start(config)
            await manager.stop()

            assert not manager.is_running

    @pytest.mark.asyncio
    async def test_manager_collects_observations(self):
        """Manager must collect observations from sidecar."""
        from streamforge.sidecar.manager import SidecarManager
        from streamforge.sidecar.models import ObservationBatch, SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar.health_check") as mock_health, \
             patch("streamforge.sidecar.sqs.SQSSidecar.peek") as mock_peek:

            from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation
            mock_health.return_value = TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name="orders",
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=10.0,
            )

            mock_peek.return_value = ObservationBatch(
                queue_name="orders",
                observations=(),
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

            manager = SidecarManager()
            await manager.start(config)
            batch = await manager.observe()

            assert isinstance(batch, ObservationBatch)


class TestSidecarStatus:
    """Tests for sidecar status and metrics."""

    @pytest.mark.asyncio
    async def test_status_reports_queue_info(self):
        """Status must report queue name and type."""
        from streamforge.sidecar.manager import SidecarManager
        from streamforge.sidecar.models import SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar.health_check") as mock_health:
            from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation
            mock_health.return_value = TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name="orders",
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=10.0,
            )

            manager = SidecarManager()
            await manager.start(config)
            status = manager.get_status()

            assert status["queue_name"] == "orders"
            assert status["queue_type"] == "sqs"
            assert status["is_running"] is True


class TestSidecarSafety:
    """Integration tests for safety guarantees."""

    def test_manager_has_no_destructive_operations(self):
        """Manager must NOT expose any destructive operations."""
        from streamforge.sidecar.manager import SidecarManager

        assert not hasattr(SidecarManager, "delete")
        assert not hasattr(SidecarManager, "consume")
        assert not hasattr(SidecarManager, "ack")
        assert not hasattr(SidecarManager, "send")

    @pytest.mark.asyncio
    async def test_observations_are_immutable(self):
        """Observations from manager must be immutable."""
        from streamforge.sidecar.manager import SidecarManager
        from streamforge.sidecar.models import ObservationBatch, SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar.health_check") as mock_health, \
             patch("streamforge.sidecar.sqs.SQSSidecar.peek") as mock_peek:

            from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation
            mock_health.return_value = TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name="orders",
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=10.0,
            )

            mock_peek.return_value = ObservationBatch(
                queue_name="orders",
                observations=(),
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

            manager = SidecarManager()
            await manager.start(config)
            batch = await manager.observe()

            # Batch should be immutable (frozen Pydantic model)
            from pydantic import ValidationError
            with pytest.raises((TypeError, AttributeError, ValidationError)):
                batch.queue_name = "tampered"
