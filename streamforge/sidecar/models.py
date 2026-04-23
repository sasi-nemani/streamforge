"""
streamforge/sidecar/models.py — Sidecar Data Models
=====================================================

Immutable models for queue observation. Every model captures:
- WHAT: the data observed
- WHEN: timestamp of observation
- HOW: method used (peek, browse, etc.)

Core principle: NEVER touch or modify messages. NEVER alter queue state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TelemetryOperation(StrEnum):
    """Read-only operations only. No consume, delete, ack, or purge."""

    PEEK = "peek"
    BROWSE = "browse"
    COUNT = "count"
    HEALTH_CHECK = "health_check"


class ObservationEvent(BaseModel):
    """
    A single observed message from a queue.

    Immutable record of what was seen, when, and how.
    The payload is a copy — the original message is untouched.
    """

    model_config = {"frozen": True}

    queue_name: str = Field(..., description="Name/URL of the observed queue")
    message_id: str = Field(..., description="Queue-assigned message identifier")
    observed_at: datetime = Field(..., description="When the observation occurred")
    payload: dict[str, Any] = Field(..., description="Copy of message body (parsed)")
    observation_method: str = Field(..., description="How observed: peek, browse")

    # Optional metadata
    queue_type: str | None = Field(default=None, description="sqs, ibm_mq, rabbitmq")
    approximate_receive_count: int | None = Field(
        default=None, description="How many times message has been received"
    )
    message_attributes: dict[str, Any] | None = Field(
        default=None, description="Queue-specific message attributes"
    )
    raw_body: str | None = Field(default=None, description="Original unparsed body")
    correlation_id: str | None = Field(default=None, description="Message correlation ID")


class TelemetryEvent(BaseModel):
    """
    Audit record for a sidecar operation.

    Captures what operation was performed, success/failure, timing, and errors.
    Every sidecar action emits a TelemetryEvent for full auditability.
    """

    model_config = {"frozen": True}

    operation: TelemetryOperation = Field(..., description="What operation was performed")
    queue_name: str = Field(..., description="Target queue")
    timestamp: datetime = Field(..., description="When operation occurred")
    success: bool = Field(..., description="Whether operation succeeded")
    messages_observed: int = Field(default=0, description="Number of messages observed")
    latency_ms: float = Field(default=0.0, description="Operation latency in milliseconds")

    # Error details (for failures)
    error_code: str | None = Field(default=None, description="Error code if failed")
    error_message: str | None = Field(default=None, description="Error message if failed")

    # Additional context
    batch_id: str | None = Field(default=None, description="Batch identifier for correlation")
    sidecar_instance: str | None = Field(default=None, description="Sidecar instance ID")


class SQSConfig(BaseModel):
    """
    Configuration for SQS sidecar.

    CRITICAL: visibility_timeout_seconds MUST be 0.
    Any value > 0 would hide messages from other consumers, violating
    the core principle of never altering queue state.
    """

    model_config = {"frozen": True}

    queue_url: str = Field(..., description="Full SQS queue URL")
    region: str = Field(..., description="AWS region")
    visibility_timeout_seconds: int = Field(
        default=0,
        description="Must be 0 for peek-only observation",
    )
    max_messages_per_peek: int = Field(
        default=10, ge=1, le=10, description="Max messages per ReceiveMessage call"
    )
    wait_time_seconds: int = Field(
        default=0, ge=0, le=20, description="Long polling wait time"
    )

    # Optional AWS credentials (use IAM role if not provided)
    aws_access_key_id: str | None = Field(default=None)
    aws_secret_access_key: str | None = Field(default=None)

    @field_validator("visibility_timeout_seconds")
    @classmethod
    def validate_visibility_timeout(cls, v: int) -> int:
        """Enforce read-only: visibility timeout must be 0."""
        if v != 0:
            raise ValueError(
                "visibility_timeout_seconds must be 0 for read-only observation. "
                "Any value > 0 would hide messages from other consumers."
            )
        return v


class IBMMQConfig(BaseModel):
    """
    Configuration for IBM MQ sidecar.

    CRITICAL: browse_mode MUST be True.
    Setting browse_mode=False would consume and remove messages.
    """

    model_config = {"frozen": True}

    host: str = Field(..., description="MQ server hostname")
    port: int = Field(..., ge=1, le=65535, description="MQ server port")
    queue_manager: str = Field(..., description="Queue manager name")
    queue_name: str = Field(..., description="Queue name to observe")
    channel: str = Field(..., description="Channel name")
    browse_mode: bool = Field(
        default=True, description="Must be True for read-only observation"
    )

    # Optional authentication
    user: str | None = Field(default=None)
    password: str | None = Field(default=None)
    ssl_cipher: str | None = Field(default=None)

    @field_validator("browse_mode")
    @classmethod
    def validate_browse_mode(cls, v: bool) -> bool:
        """Enforce read-only: browse mode must be enabled."""
        if not v:
            raise ValueError(
                "browse_mode must be True for read-only observation. "
                "Setting False would consume messages."
            )
        return v


class ObservationBatch(BaseModel):
    """
    A batch of observations from a single peek/browse operation.

    Immutable container for a set of observed messages with statistics.
    """

    model_config = {"frozen": True}

    queue_name: str = Field(..., description="Source queue")
    observations: tuple[ObservationEvent, ...] = Field(
        default_factory=tuple, description="Observed messages"
    )
    started_at: datetime = Field(..., description="When batch started")
    completed_at: datetime = Field(..., description="When batch completed")
    batch_id: str | None = Field(default=None, description="Unique batch identifier")

    @property
    def message_count(self) -> int:
        """Number of messages in this batch."""
        return len(self.observations)

    @property
    def duration_ms(self) -> float:
        """Batch duration in milliseconds."""
        return (self.completed_at - self.started_at).total_seconds() * 1000

    @model_validator(mode="before")
    @classmethod
    def convert_observations_to_tuple(cls, data: Any) -> Any:
        """Convert list to tuple for immutability."""
        if isinstance(data, dict) and "observations" in data:
            obs = data["observations"]
            if isinstance(obs, list):
                data["observations"] = tuple(obs)
        return data
