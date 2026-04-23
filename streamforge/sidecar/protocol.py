"""
streamforge/sidecar/protocol.py — Read-Only Queue Sidecar Protocol
====================================================================

Defines the contract for queue sidecars. ALL operations are read-only.

Core principle: NEVER touch or modify messages. NEVER alter queue state.

This protocol deliberately EXCLUDES:
- consume() — would remove messages
- delete() — would remove messages
- ack() — would advance cursor / remove from DLQ
- purge() — would empty queue
- send() — would add messages
- commit() — would alter transaction state

Only passive observation methods are allowed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ObservationBatch, TelemetryEvent


@runtime_checkable
class QueueSidecar(Protocol):
    """
    Protocol for read-only queue observation sidecars.

    Implementations must:
    1. NEVER consume or delete messages
    2. NEVER alter queue state
    3. Return copies of message data, not references
    4. Emit telemetry for every operation
    5. Handle errors gracefully without side effects

    All methods are async to support non-blocking I/O.
    """

    async def peek(
        self,
        max_messages: int = 10,
        timeout_ms: int = 5000,
    ) -> ObservationBatch:
        """
        Peek at messages without consuming them.

        For SQS: Uses ReceiveMessage with VisibilityTimeout=0
        For IBM MQ: Uses browse mode
        For RabbitMQ: Uses passive consume with requeue

        Args:
            max_messages: Maximum messages to observe (queue-specific limits apply)
            timeout_ms: Maximum time to wait for messages

        Returns:
            ObservationBatch containing observed messages

        Raises:
            SidecarError: On connection or permission errors
        """
        ...

    async def browse(
        self,
        cursor: str | None = None,
        max_messages: int = 100,
    ) -> tuple[ObservationBatch, str | None]:
        """
        Browse queue from a cursor position.

        Unlike peek(), browse() can iterate through entire queue
        without re-reading the same messages.

        Args:
            cursor: Position to start browsing (None = beginning)
            max_messages: Maximum messages to observe

        Returns:
            Tuple of (ObservationBatch, next_cursor)
            next_cursor is None if end of queue reached

        Raises:
            SidecarError: On connection or permission errors
        """
        ...

    async def get_queue_depth(self) -> int:
        """
        Get approximate number of messages in queue.

        This is a metadata operation — no messages are read.

        Returns:
            Approximate message count

        Raises:
            SidecarError: On connection or permission errors
        """
        ...

    async def health_check(self) -> TelemetryEvent:
        """
        Check sidecar connectivity and permissions.

        Verifies:
        - Connection to queue service
        - Read permissions are present
        - Write permissions are ABSENT (safety check)

        Returns:
            TelemetryEvent with health status

        Raises:
            SidecarError: On critical connectivity failures
        """
        ...

    @property
    def queue_name(self) -> str:
        """Human-readable queue identifier for logs and metrics."""
        ...

    @property
    def queue_type(self) -> str:
        """Queue type: 'sqs', 'ibm_mq', 'rabbitmq', etc."""
        ...

    async def close(self) -> None:
        """Release resources. Safe to call multiple times."""
        ...


class SidecarError(Exception):
    """Base exception for sidecar errors."""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
