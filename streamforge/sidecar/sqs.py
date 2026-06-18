"""
streamforge/sidecar/sqs.py — AWS SQS Read-Only Sidecar
=======================================================

Passive observation of SQS queues. NEVER consumes or deletes messages.

Core principle: NEVER touch or modify messages. NEVER alter queue state.

Implementation:
- Uses ReceiveMessage with VisibilityTimeout=0 (messages stay visible)
- NEVER calls DeleteMessage
- NEVER calls ChangeMessageVisibility
- Full telemetry for every operation

CRITICAL: VisibilityTimeout=0 ensures messages are immediately visible
to other consumers. This is a peek, not a consume.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from io import StringIO
from typing import Any, TextIO

from .models import (
    ObservationBatch,
    ObservationEvent,
    SQSConfig,
    TelemetryEvent,
    TelemetryOperation,
)
from .protocol import SidecarError
from .telemetry import SidecarAudit

# Detect async AWS SDK availability
_AIOBOTO3_AVAILABLE = False
try:
    import aioboto3  # noqa: F401 — import is an availability probe only
    _AIOBOTO3_AVAILABLE = True
except ImportError:
    pass


class SQSSidecar:
    """
    AWS SQS read-only sidecar.

    Implements QueueSidecar protocol with strict read-only guarantees.
    NO delete, NO ack, NO send, NO purge methods exist.
    """

    def __init__(
        self,
        config: SQSConfig,
        telemetry_stream: TextIO | None = None,
    ) -> None:
        self._config = config
        self._queue_url = config.queue_url
        self._region = config.region
        self._visibility_timeout = 0  # ALWAYS 0 — never hide messages
        self._client: Any = None
        self._audit = SidecarAudit(output_stream=telemetry_stream or StringIO())

    @property
    def queue_name(self) -> str:
        """Extract queue name from URL."""
        return self._queue_url.rstrip("/").split("/")[-1]

    @property
    def queue_type(self) -> str:
        return "sqs"

    def _get_client(self) -> Any:
        """Get or create boto3 SQS client."""
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise SidecarError(
                    "boto3 not installed. Run: pip install boto3",
                    error_code="MISSING_DEPENDENCY",
                )

            session_kwargs: dict[str, Any] = {"region_name": self._region}
            if self._config.aws_access_key_id:
                session_kwargs["aws_access_key_id"] = self._config.aws_access_key_id
                session_kwargs["aws_secret_access_key"] = self._config.aws_secret_access_key

            self._client = boto3.client("sqs", **session_kwargs)
        return self._client

    async def peek(
        self,
        max_messages: int = 10,
        timeout_ms: int = 5000,
    ) -> ObservationBatch:
        """
        Peek at messages without consuming them.

        Uses ReceiveMessage with VisibilityTimeout=0.
        Messages remain visible to all consumers.
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
            client = self._get_client()

            # Run blocking boto3 call in thread pool to avoid blocking event loop
            response = await asyncio.to_thread(
                self._call_receive_message,
                client,
                min(max_messages, 10),  # SQS max is 10
                min(timeout_ms // 1000, 20),  # SQS max wait is 20s
            )

            messages = response.get("Messages", [])

            for msg in messages:
                payload = self._parse_body(msg.get("Body", "{}"))
                obs = ObservationEvent(
                    queue_name=self.queue_name,
                    message_id=msg.get("MessageId", "unknown"),
                    observed_at=datetime.now(UTC),
                    payload=payload,
                    observation_method="peek",
                    queue_type="sqs",
                    approximate_receive_count=int(
                        msg.get("Attributes", {}).get("ApproximateReceiveCount", 0)
                    ),
                    message_attributes=msg.get("MessageAttributes"),
                    raw_body=msg.get("Body"),
                )
                observations.append(obs)

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

    def _call_receive_message(
        self,
        client: Any,
        max_messages: int,
        wait_time: int,
    ) -> dict[str, Any]:
        """
        Call SQS ReceiveMessage with VisibilityTimeout=0.

        CRITICAL: VisibilityTimeout=0 ensures we peek, not consume.
        """
        return client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time,
            VisibilityTimeout=0,  # CRITICAL: Always 0 for read-only
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )

    async def browse(
        self,
        cursor: str | None = None,
        max_messages: int = 100,
    ) -> tuple[ObservationBatch, str | None]:
        """
        Browse queue from cursor position.

        SQS doesn't support true browsing with cursors.
        Returns peek results with no next cursor.
        """
        batch = await self.peek(max_messages=min(max_messages, 10))
        # SQS doesn't have cursor-based browsing
        return batch, None

    async def get_queue_depth(self) -> int:
        """Get approximate number of messages in queue."""
        start_time = time.perf_counter()

        try:
            client = self._get_client()
            # Run blocking boto3 call in thread pool
            response = await asyncio.to_thread(
                client.get_queue_attributes,
                QueueUrl=self._queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            depth = int(response["Attributes"]["ApproximateNumberOfMessages"])

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
            client = self._get_client()
            # Run blocking boto3 call in thread pool
            await asyncio.to_thread(
                client.get_queue_attributes,
                QueueUrl=self._queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )

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

            self._audit.log_operation(
                operation=TelemetryOperation.HEALTH_CHECK,
                queue_name=self.queue_name,
                success=False,
                messages_observed=0,
                latency_ms=latency_ms,
                error_message=str(e),
            )

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
        self._client = None

    def _parse_body(self, body: str) -> dict[str, Any]:
        """Parse message body as JSON."""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_raw": body}

    # =========================================================================
    # SAFETY: NO DESTRUCTIVE METHODS EXIST
    # These methods are intentionally NOT implemented:
    # - delete / delete_message
    # - ack / acknowledge
    # - send / send_message
    # - purge / purge_queue
    # - change_message_visibility
    # =========================================================================
