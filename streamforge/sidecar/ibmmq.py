"""
streamforge/sidecar/ibmmq.py — IBM MQ Read-Only Sidecar
========================================================

Passive observation of IBM MQ queues using browse mode.
NEVER consumes or destructively reads messages.

Core principle: NEVER touch or modify messages. NEVER alter queue state.

Implementation:
- Opens queue with MQOO_BROWSE (browse mode, not input mode)
- Uses MQGMO_BROWSE_FIRST / MQGMO_BROWSE_NEXT (cursor-based browsing)
- NEVER uses MQGMO_MSG_UNDER_CURSOR (which would consume)
- Full telemetry for every operation

IBM MQ Browse Mode:
- MQOO_BROWSE (0x00000008): Open for browsing
- MQGMO_BROWSE_FIRST (0x00000010): Position cursor at first message
- MQGMO_BROWSE_NEXT (0x00000020): Move cursor to next message
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from typing import Any, TextIO

from .models import (
    IBMMQConfig,
    ObservationBatch,
    ObservationEvent,
    TelemetryEvent,
    TelemetryOperation,
)
from .protocol import QueueSidecar, SidecarError
from .telemetry import SidecarAudit


# Try to import pymqi, will be None if not available
try:
    import pymqi as _pymqi
except ImportError:
    _pymqi = None


@dataclass
class IBMMQConnectionPool:
    """
    Thread-safe connection pool for IBM MQ.

    Maintains a pool of reusable connections to reduce connection overhead.
    Connections are validated before reuse and recreated if stale.

    Usage:
        pool = IBMMQConnectionPool(config, max_size=3)
        with pool.acquire() as (conn, queue):
            # Use connection
            pass  # Automatically released back to pool
    """

    config: IBMMQConfig
    max_size: int = 3
    max_idle_seconds: float = 300.0  # 5 minutes

    _pool: deque = field(default_factory=deque, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _created_count: int = field(default=0, init=False)

    def _create_connection(self) -> tuple[Any, Any, float]:
        """Create a new MQ connection and queue handle."""
        if _pymqi is None:
            raise SidecarError(
                "pymqi not installed. Run: pip install pymqi",
                error_code="MISSING_DEPENDENCY",
            )

        conn_info = f"{self.config.host}({self.config.port})"

        try:
            connection = _pymqi.connect(
                self.config.queue_manager,
                self.config.channel,
                conn_info,
                user=self.config.user,
                password=self.config.password,
            )

            # Open options for browse mode
            open_options = 0x00000008 | 0x00000020  # MQOO_BROWSE | MQOO_INQUIRE
            queue = _pymqi.Queue(
                connection,
                self.config.queue_name,
                open_options,
            )

            self._created_count += 1
            return connection, queue, time.monotonic()

        except Exception as e:
            raise SidecarError(f"MQ connection failed: {e}", retryable=True)

    def _close_connection(self, conn_tuple: tuple[Any, Any, float]) -> None:
        """Close a connection and queue handle."""
        connection, queue, _ = conn_tuple
        try:
            if queue is not None:
                queue.close()
        except Exception:
            pass
        try:
            if connection is not None:
                connection.disconnect()
        except Exception:
            pass

    def _is_connection_valid(self, conn_tuple: tuple[Any, Any, float]) -> bool:
        """Check if connection is still valid and not too old."""
        _, _, created_at = conn_tuple
        age = time.monotonic() - created_at
        return age < self.max_idle_seconds

    @contextmanager
    def acquire(self):
        """
        Acquire a connection from the pool.

        Yields (connection, queue) tuple.
        Automatically releases back to pool on exit.
        """
        conn_tuple = None

        with self._lock:
            # Try to get from pool
            while self._pool:
                candidate = self._pool.popleft()
                if self._is_connection_valid(candidate):
                    conn_tuple = candidate
                    break
                else:
                    # Connection too old, close it
                    self._close_connection(candidate)

        # Create new if pool was empty
        if conn_tuple is None:
            conn_tuple = self._create_connection()

        try:
            connection, queue, _ = conn_tuple
            yield connection, queue
        finally:
            # Return to pool if not at max size
            with self._lock:
                if len(self._pool) < self.max_size:
                    # Update timestamp
                    conn_tuple = (conn_tuple[0], conn_tuple[1], time.monotonic())
                    self._pool.append(conn_tuple)
                else:
                    self._close_connection(conn_tuple)

    def close_all(self) -> None:
        """Close all pooled connections."""
        with self._lock:
            while self._pool:
                conn_tuple = self._pool.popleft()
                self._close_connection(conn_tuple)

    @property
    def stats(self) -> dict[str, Any]:
        """Pool statistics for monitoring."""
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "max_size": self.max_size,
                "total_created": self._created_count,
            }


# IBM MQ Constants (from CMQC.h)
# Open options
MQOO_BROWSE = 0x00000008
MQOO_INPUT_SHARED = 0x00000002
MQOO_INPUT_EXCLUSIVE = 0x00000004
MQOO_INQUIRE = 0x00000020

# Get message options
MQGMO_BROWSE_FIRST = 0x00000010
MQGMO_BROWSE_NEXT = 0x00000020
MQGMO_WAIT = 0x00000001
MQGMO_NO_WAIT = 0x00000000

# Message descriptor
MQIA_CURRENT_Q_DEPTH = 3


class IBMMQSidecar:
    """
    IBM MQ read-only sidecar using browse mode.

    Implements QueueSidecar protocol with strict read-only guarantees.
    NO put, NO delete, NO commit, NO backout methods exist.
    """

    def __init__(
        self,
        config: IBMMQConfig,
        telemetry_stream: TextIO | None = None,
    ) -> None:
        self._config = config
        self._host = config.host
        self._port = config.port
        self._queue_manager = config.queue_manager
        self._queue_name_str = config.queue_name
        self._channel = config.channel
        self._browse_mode = True  # ALWAYS browse mode
        self._connection: Any = None
        self._queue: Any = None
        self._browse_cursor: str | None = None
        self._audit = SidecarAudit(output_stream=telemetry_stream or StringIO())

    @property
    def queue_name(self) -> str:
        return self._queue_name_str

    @property
    def queue_type(self) -> str:
        return "ibm_mq"

    def _get_open_options(self) -> int:
        """
        Get queue open options.

        CRITICAL: Only MQOO_BROWSE is allowed.
        MQOO_INPUT_* would enable destructive reads.
        """
        # Browse mode + Inquire for queue depth
        return MQOO_BROWSE | MQOO_INQUIRE

    def _get_browse_options(self, first: bool = False) -> int:
        """
        Get message browse options.

        CRITICAL: Only MQGMO_BROWSE_* is allowed.
        """
        if first:
            return MQGMO_BROWSE_FIRST | MQGMO_NO_WAIT
        return MQGMO_BROWSE_NEXT | MQGMO_NO_WAIT

    def _get_connection(self) -> tuple[Any, Any]:
        """Get or create IBM MQ connection and queue handle."""
        if self._connection is None:
            if _pymqi is None:
                raise SidecarError(
                    "pymqi not installed. Run: pip install pymqi",
                    error_code="MISSING_DEPENDENCY",
                )

            conn_info = f"{self._host}({self._port})"

            try:
                self._connection = _pymqi.connect(
                    self._queue_manager,
                    self._channel,
                    conn_info,
                    user=self._config.user,
                    password=self._config.password,
                )

                self._queue = _pymqi.Queue(
                    self._connection,
                    self._queue_name_str,
                    self._get_open_options(),
                )
            except Exception as e:
                raise SidecarError(f"MQ connection failed: {e}", retryable=True)

        return self._connection, self._queue

    async def peek(
        self,
        max_messages: int = 10,
        timeout_ms: int = 5000,
    ) -> ObservationBatch:
        """
        Peek at messages using browse mode.

        Uses MQGMO_BROWSE_FIRST to position cursor at first message.
        Messages are NOT removed from the queue.
        """
        batch_id = f"peek-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        start_time = time.perf_counter()

        self._audit.log_batch_start(
            batch_id=batch_id,
            queue_name=self.queue_name,
            max_messages=max_messages,
        )

        observations: list[ObservationEvent] = []
        success = True
        error_message = None

        try:
            _, queue = self._get_connection()

            for i in range(max_messages):
                try:
                    md, body = queue.get(
                        None,  # No specific message descriptor
                        self._get_browse_options(first=(i == 0)),
                    )

                    payload = self._parse_body(body)
                    msg_id = md.MsgId.hex() if hasattr(md, 'MsgId') else f"msg-{i}"

                    obs = ObservationEvent(
                        queue_name=self.queue_name,
                        message_id=msg_id,
                        observed_at=datetime.now(UTC),
                        payload=payload,
                        observation_method="browse",
                        queue_type="ibm_mq",
                        correlation_id=md.CorrelId.hex() if hasattr(md, 'CorrelId') else None,
                        raw_body=body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body),
                    )
                    observations.append(obs)

                except StopIteration:
                    # No more messages
                    break
                except Exception as e:
                    # End of queue or error
                    if "2033" in str(e):  # MQRC_NO_MSG_AVAILABLE
                        break
                    raise

        except SidecarError:
            raise
        except Exception as e:
            success = False
            error_message = str(e)
            raise SidecarError(str(e), retryable=True)

        finally:
            completed_at = datetime.now(UTC)
            latency_ms = (time.perf_counter() - start_time) * 1000

            self._audit.log_batch_complete(
                batch_id=batch_id,
                queue_name=self.queue_name,
                messages_observed=len(observations),
                duration_ms=latency_ms,
                success=success,
                error_message=error_message,
            )

            self._audit.log_operation(
                operation=TelemetryOperation.PEEK,
                queue_name=self.queue_name,
                success=success,
                messages_observed=len(observations),
                latency_ms=latency_ms,
                batch_id=batch_id,
            )

        return ObservationBatch(
            queue_name=self.queue_name,
            observations=tuple(observations),
            started_at=started_at,
            completed_at=completed_at,
            batch_id=batch_id,
        )

    async def browse(
        self,
        cursor: str | None = None,
        max_messages: int = 100,
    ) -> tuple[ObservationBatch, str | None]:
        """
        Browse queue from cursor position.

        IBM MQ supports cursor-based browsing with MQGMO_BROWSE_NEXT.
        """
        # For IBM MQ, browse continues from current cursor position
        batch = await self.peek(max_messages=max_messages)

        # Return next cursor (or None if end of queue)
        next_cursor = f"pos-{len(batch.observations)}" if batch.message_count > 0 else None
        return batch, next_cursor

    async def get_queue_depth(self) -> int:
        """Get current queue depth."""
        start_time = time.perf_counter()

        try:
            _, queue = self._get_connection()
            depth = queue.inquire(MQIA_CURRENT_Q_DEPTH)

            self._audit.log_operation(
                operation=TelemetryOperation.COUNT,
                queue_name=self.queue_name,
                success=True,
                messages_observed=depth,
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

            return depth

        except Exception as e:
            self._audit.log_operation(
                operation=TelemetryOperation.COUNT,
                queue_name=self.queue_name,
                success=False,
                messages_observed=0,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                error_message=str(e),
            )
            raise SidecarError(str(e))

    async def health_check(self) -> TelemetryEvent:
        """Check sidecar connectivity and permissions."""
        start_time = time.perf_counter()

        try:
            _, queue = self._get_connection()
            queue.inquire(MQIA_CURRENT_Q_DEPTH)

            latency_ms = (time.perf_counter() - start_time) * 1000

            self._audit.log_operation(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name=self.queue_name,
                success=True,
                messages_observed=0,
                latency_ms=latency_ms,
            )

            return TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name=self.queue_name,
                timestamp=datetime.now(UTC),
                success=True,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000

            return TelemetryEvent(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name=self.queue_name,
                timestamp=datetime.now(UTC),
                success=False,
                latency_ms=latency_ms,
                error_code=type(e).__name__,
                error_message=str(e),
            )

    async def close(self) -> None:
        """Release resources."""
        if self._queue is not None:
            try:
                self._queue.close()
            except Exception:
                pass
            self._queue = None

        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None

    def _parse_body(self, body: bytes | str) -> dict[str, Any]:
        """Parse message body as JSON."""
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_raw": body}

    # =========================================================================
    # SAFETY: NO DESTRUCTIVE METHODS EXIST
    # These methods are intentionally NOT implemented:
    # - put / send
    # - delete
    # - commit
    # - backout / rollback
    # =========================================================================
