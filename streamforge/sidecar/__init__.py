"""
streamforge/sidecar — Read-Only Queue Observation Sidecar
==========================================================

Core principle: NEVER touch or modify messages. NEVER alter queue state.

This module provides passive observation of message queues for schema
inference and drift detection without consuming or modifying messages.

Supported queue types:
- AWS SQS (via ReceiveMessage with VisibilityTimeout=0)
- IBM MQ (via browse mode)
- RabbitMQ (via passive consume)

Design:
- Peek/browse only — no consume, no delete, no ack
- Copy-on-read to local observation buffer
- Full telemetry baked into every operation
"""

from .factory import create_sidecar
from .ibmmq import IBMMQSidecar
from .manager import SidecarManager
from .models import (
    IBMMQConfig,
    ObservationBatch,
    ObservationEvent,
    SQSConfig,
    TelemetryEvent,
    TelemetryOperation,
)
from .protocol import QueueSidecar, SidecarError
from .sqs import SQSSidecar
from .telemetry import MetricsCollector, SidecarAudit, telemetry_context

__all__ = [
    # Models
    "ObservationEvent",
    "ObservationBatch",
    "TelemetryEvent",
    "TelemetryOperation",
    "SQSConfig",
    "IBMMQConfig",
    # Protocol
    "QueueSidecar",
    "SidecarError",
    # Sidecars
    "SQSSidecar",
    "IBMMQSidecar",
    # Factory & Manager
    "create_sidecar",
    "SidecarManager",
    # Telemetry
    "SidecarAudit",
    "MetricsCollector",
    "telemetry_context",
]
