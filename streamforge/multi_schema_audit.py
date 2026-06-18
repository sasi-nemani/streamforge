"""
Audit Event Emission Utility.

Provides safe, centralized audit event emission for multi-schema modules.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any, TextIO

from .models import MultiSchemaAuditEvent

logger = logging.getLogger(__name__)


def emit_audit(
    stream: TextIO | None,
    stream_name: str,
    operation: str,
    start_time: float,
    input_count: int,
    output_count: int | None = None,
    success: bool = True,
    error_message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Emit an audit event to the stream.

    Safe: catches and logs any write failures instead of propagating.
    """
    if stream is None:
        return

    duration_ms = (time.perf_counter() - start_time) * 1000

    event = MultiSchemaAuditEvent(
        timestamp=datetime.now(UTC).isoformat(),
        operation=operation,
        stream_name=stream_name,
        duration_ms=duration_ms,
        input_count=input_count,
        output_count=output_count,
        success=success,
        error_message=error_message,
        details=details or {},
    )

    try:
        stream.write(event.model_dump_json() + "\n")
    except Exception:
        logger.warning("Failed to write audit event for %s", operation, exc_info=True)
        from .metrics import AUDIT_FAILURES
        AUDIT_FAILURES.inc()
