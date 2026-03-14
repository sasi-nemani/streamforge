"""
StreamConnector — the contract every event source must satisfy.

Design principles:
  - read_batch is the only method that touches the source. Everything else is
    coordination (ack, close). This makes connectors easy to test and mock.
  - At-least-once delivery semantics: ack() is called after successful processing.
    If the process dies before ack(), the batch is re-delivered on reconnect.
    Callers must be idempotent.
  - read_batch must honour timeout_ms. It must never block indefinitely.
    A well-behaved connector returns [] if no messages arrive within the timeout.
  - Connectors are async context managers. Use `async with connector:` —
    this guarantees close() is called even on exceptions.
  - Thread safety is NOT guaranteed. Each connector instance is owned by one
    asyncio task. Do not share instances across tasks.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a connector encounters an unrecoverable error."""


class StreamConnector(ABC):
    """
    Abstract base class for all stream source adapters.

    Implementations must satisfy this contract:
      1. read_batch returns within timeout_ms milliseconds.
      2. read_batch returns [] when no messages are available (never blocks).
      3. ack() commits the offset / deletes the message / advances the cursor
         for the most recently returned batch.
      4. Calling ack() before read_batch() is a no-op.
      5. close() releases all resources. Safe to call multiple times.
      6. The connector is usable as an async context manager.
    """

    @abstractmethod
    async def read_batch(
        self,
        max_messages: int = 200,
        timeout_ms: int = 1_000,
    ) -> list[dict[str, Any]]:
        """
        Pull up to max_messages events from the source.

        Args:
            max_messages: Upper bound on events returned. May return fewer.
            timeout_ms:   Maximum time to wait for messages before returning [].

        Returns:
            List of parsed event dicts. Empty list if none available.

        Raises:
            ConnectorError: On unrecoverable source errors (auth failure,
                            network partition that exceeded retry budget, etc.)
        """

    @abstractmethod
    async def ack(self) -> None:
        """
        Acknowledge successful processing of the last batch.

        Must be called after every successful read_batch() + processing cycle.
        Skipping ack() means the batch will be re-delivered (at-least-once).
        """

    @abstractmethod
    async def close(self) -> None:
        """Release all resources. Idempotent — safe to call multiple times."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """
        Human-readable identifier for this source.
        Used in logs and metrics. Example: "file:events/payments/stream_v1"
        """

    # -------------------------------------------------------------------------
    # Default async context manager implementation.
    # Subclasses should not need to override these.
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "StreamConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
        return None  # do not suppress exceptions
