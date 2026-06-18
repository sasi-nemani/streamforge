"""
streamforge/sidecar/manager.py — Sidecar Lifecycle Manager
===========================================================

Manages sidecar lifecycle: start, stop, observe, status.

Core principle: NEVER touch or modify messages. NEVER alter queue state.

The manager orchestrates sidecars but provides NO destructive operations.
"""

from __future__ import annotations

from typing import Any, TextIO

from .factory import SidecarConfig, create_sidecar
from .ibmmq import IBMMQSidecar
from .models import ObservationBatch, TelemetryEvent
from .sqs import SQSSidecar


class SidecarManager:
    """
    Lifecycle manager for queue sidecars.

    Manages:
    - Starting and stopping sidecars
    - Health checks
    - Collecting observations
    - Status reporting

    SAFETY: No destructive operations (delete, consume, ack, send)
    are exposed through this manager.
    """

    def __init__(self, telemetry_stream: TextIO | None = None) -> None:
        self._sidecar: SQSSidecar | IBMMQSidecar | None = None
        self._telemetry_stream = telemetry_stream
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Whether a sidecar is currently running."""
        return self._is_running

    async def start(self, config: SidecarConfig) -> TelemetryEvent:
        """
        Start sidecar and run initial health check.

        Args:
            config: Queue configuration

        Returns:
            TelemetryEvent from health check

        Raises:
            SidecarError: If health check fails
        """
        self._sidecar = create_sidecar(
            config,
            telemetry_stream=self._telemetry_stream,
        )

        health = await self._sidecar.health_check()
        self._is_running = True
        return health

    async def stop(self) -> None:
        """Stop the sidecar and release resources."""
        if self._sidecar is not None:
            await self._sidecar.close()
            self._sidecar = None
        self._is_running = False

    async def observe(
        self,
        max_messages: int = 10,
        timeout_ms: int = 5000,
    ) -> ObservationBatch:
        """
        Collect observations from the queue.

        Uses peek (not consume) to observe messages.

        Args:
            max_messages: Maximum messages to observe
            timeout_ms: Timeout for observation

        Returns:
            ObservationBatch with observed messages
        """
        if self._sidecar is None:
            raise RuntimeError("Sidecar not started. Call start() first.")

        return await self._sidecar.peek(
            max_messages=max_messages,
            timeout_ms=timeout_ms,
        )

    async def browse(
        self,
        cursor: str | None = None,
        max_messages: int = 100,
    ) -> tuple[ObservationBatch, str | None]:
        """
        Browse queue from cursor position.

        Args:
            cursor: Position to start browsing
            max_messages: Maximum messages to observe

        Returns:
            Tuple of (ObservationBatch, next_cursor)
        """
        if self._sidecar is None:
            raise RuntimeError("Sidecar not started. Call start() first.")

        return await self._sidecar.browse(
            cursor=cursor,
            max_messages=max_messages,
        )

    async def get_queue_depth(self) -> int:
        """Get approximate number of messages in queue."""
        if self._sidecar is None:
            raise RuntimeError("Sidecar not started. Call start() first.")

        return await self._sidecar.get_queue_depth()

    async def health_check(self) -> TelemetryEvent:
        """Run health check on the sidecar."""
        if self._sidecar is None:
            raise RuntimeError("Sidecar not started. Call start() first.")

        return await self._sidecar.health_check()

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of the sidecar.

        Returns:
            Status dictionary with queue info
        """
        if self._sidecar is None:
            return {
                "is_running": False,
                "queue_name": None,
                "queue_type": None,
            }

        return {
            "is_running": self._is_running,
            "queue_name": self._sidecar.queue_name,
            "queue_type": self._sidecar.queue_type,
        }

    # =========================================================================
    # SAFETY: NO DESTRUCTIVE METHODS EXIST
    # These methods are intentionally NOT implemented:
    # - delete
    # - consume
    # - ack
    # - send
    # =========================================================================
