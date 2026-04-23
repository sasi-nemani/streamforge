"""Source-agnostic URI resolution and connector factory.

Replaces hardcoded string matching (is_kafka = uri.startswith("kafka://"))
with a registry-based dispatch pattern. Adding a new source type (kinesis://,
pubsub://) requires only registering a new scheme handler here — no changes
to supervisor, CLI, or watch loops.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Registry of URI scheme -> (source_type, parser)
# parser takes the full URI and returns the source-specific identifier
_SCHEME_REGISTRY: dict[str, tuple[str, callable]] = {
    "kafka://": ("kafka", lambda uri: uri[len("kafka://"):]),
    "kinesis://": ("kinesis", lambda uri: uri[len("kinesis://"):]),
    "pubsub://": ("pubsub", lambda uri: uri[len("pubsub://"):]),
}


def resolve_stream_source(uri: str) -> tuple[str, str]:
    """Resolve a stream URI to (source_type, parsed_identifier).

    Examples:
        "kafka://events.payments" -> ("kafka", "events.payments")
        "kinesis://my-stream"     -> ("kinesis", "my-stream")
        "events/payments"         -> ("file", "events/payments")

    Raises ValueError for unsupported URI schemes.
    """
    for scheme, (source_type, parser) in _SCHEME_REGISTRY.items():
        if uri.startswith(scheme):
            return source_type, parser(uri)

    # Check for unsupported schemes (has :// but not registered)
    if "://" in uri:
        scheme = uri.split("://")[0]
        raise ValueError(
            f"Unsupported stream source scheme: '{scheme}://'. "
            f"Supported: {', '.join(_SCHEME_REGISTRY.keys())} or file paths."
        )

    # No scheme = file path
    return "file", uri


def register_scheme(scheme: str, source_type: str, parser: callable) -> None:
    """Register a new URI scheme for source resolution.

    This is the extension point for adding new source types without
    modifying existing code.
    """
    if not scheme.endswith("://"):
        scheme = f"{scheme}://"
    _SCHEME_REGISTRY[scheme] = (source_type, parser)
    logger.info("Registered stream source scheme: %s -> %s", scheme, source_type)
