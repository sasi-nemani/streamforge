"""
streamforge/sidecar/factory.py — Sidecar Factory
=================================================

Creates appropriate sidecar instance based on configuration type.

Core principle: NEVER touch or modify messages. NEVER alter queue state.
"""

from __future__ import annotations

from typing import Any, TextIO

from .ibmmq import IBMMQSidecar
from .models import IBMMQConfig, SQSConfig
from .sqs import SQSSidecar

SidecarConfig = SQSConfig | IBMMQConfig


def create_sidecar(
    config: SidecarConfig | dict[str, Any],
    telemetry_stream: TextIO | None = None,
) -> SQSSidecar | IBMMQSidecar:
    """
    Create a sidecar instance based on configuration type.

    Args:
        config: Queue configuration (SQSConfig, IBMMQConfig, or dict)
        telemetry_stream: Optional stream for telemetry output

    Returns:
        Appropriate sidecar instance

    Raises:
        ValueError: If config type is not supported
    """
    if isinstance(config, SQSConfig):
        return SQSSidecar(config, telemetry_stream=telemetry_stream)

    if isinstance(config, IBMMQConfig):
        return IBMMQSidecar(config, telemetry_stream=telemetry_stream)

    if isinstance(config, dict):
        raise ValueError(
            "Unsupported config type: dict. "
            "Use SQSConfig or IBMMQConfig instead."
        )

    raise ValueError(f"Unsupported config type: {type(config).__name__}")
