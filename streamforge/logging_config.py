"""
streamforge/logging_config.py — Structured Logging
====================================================

Provides two log formats:

  "human"      — Colourised, concise output for local development.
                 [14:32:01] INFO  streamforge.inference  Schema inference complete
                 Matches what Rich would render if we used it for logging.

  "structured" — JSON lines for production / CI / log aggregation (Datadog,
                 Elastic, CloudWatch, Splunk, etc.). Each log record is a
                 single JSON object on one line.
                 {"ts":"2026-03-14T14:32:01Z","level":"INFO","logger":"...",
                  "msg":"...","stream":"payments.stream_v1","dur_ms":2341}

Design decisions:
  ADR-005: Python's stdlib logging, not loguru / structlog. The stdlib is
           always available, has zero extra deps, and is understood by every
           Python developer. We layer structured formatting on top without
           forcing a third-party logging library on embedders.

  ADR-006: Contextual fields are attached via log record 'extra' dicts,
           NOT via a thread-local context manager. Explicit is better than
           implicit — callers say what they're logging about.

  ADR-007: The structured formatter drops all fields that structlog or
           datadog would consider "noise" (thread, process, filename, lineno)
           in favour of explicit business-context fields.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

# ── ANSI colour codes for human mode ──────────────────────────────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_GREY   = "\033[90m"

_LEVEL_COLOURS = {
    "DEBUG":    _GREY,
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    _RED,
    "CRITICAL": f"{_BOLD}{_RED}",
}

# Fields from LogRecord that we don't want in the JSON output because they
# either duplicate other fields or are irrelevant to distributed systems.
_SKIP_FIELDS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process",
    "processName", "relativeCreated", "stack_info",
    "thread", "threadName",
})


class HumanFormatter(logging.Formatter):
    """
    Colourised single-line log format for interactive use.

    Format:
      HH:MM:SS  LEVEL   logger.name   message   [key=val ...]
    """

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp — local time for developer readability
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        level_colour = _LEVEL_COLOURS.get(record.levelname, "")
        level_str = f"{level_colour}{record.levelname:<8}{_RESET}"

        # Logger name — trim "streamforge." prefix to reduce noise
        name = record.name.removeprefix("streamforge.")
        name_str = f"{_GREY}{name:<30}{_RESET}"

        # Main message
        msg = record.getMessage()

        # Extract extra fields the caller attached
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _SKIP_FIELDS and not k.startswith("_")
        }
        extra_str = ""
        if extras:
            parts = [f"{_DIM}{k}={_RESET}{v}" for k, v in extras.items()]
            extra_str = "  " + "  ".join(parts)

        # Exception, if any
        exc_str = ""
        if record.exc_info:
            exc_str = "\n" + self.formatException(record.exc_info)

        return f"{_DIM}{ts}{_RESET}  {level_str}  {name_str}  {msg}{extra_str}{exc_str}"


class StructuredFormatter(logging.Formatter):
    """
    JSON-lines structured log formatter.

    Each log record becomes a single JSON object. Additional fields passed
    via logger.info("msg", extra={"stream": "payments"}) are merged in.

    Output example:
      {"ts":"2026-03-14T14:32:01.234Z","level":"INFO","logger":"streamforge.inference",
       "msg":"Inference complete","stream":"payments.stream_v1","dur_ms":2341}
    """

    def format(self, record: logging.LogRecord) -> str:
        # ISO 8601 UTC timestamp with millisecond precision
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z"

        obj: dict = {
            "ts":     ts,
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }

        # Merge in any extra fields the caller provided
        for k, v in record.__dict__.items():
            if k in _SKIP_FIELDS or k.startswith("_"):
                continue
            obj[k] = v

        # Exception info
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(obj, default=str)


def configure(
    level: str = "INFO",
    fmt: str = "human",
    log_file: str | None = None,
) -> None:
    """
    Configure the root logger for StreamForge.

    Call this once at process startup (in __main__.py) before any log records
    are emitted. Subsequent calls are idempotent — they replace handlers rather
    than adding duplicates.

    Args:
        level:    Log level string: "DEBUG", "INFO", "WARNING", "ERROR".
        fmt:      "human" for development, "structured" for production/CI.
        log_file: If provided, write structured JSON logs to this file IN
                  ADDITION to stderr. File is opened in append mode.
    """
    root = logging.getLogger("streamforge")

    # Remove any existing handlers to avoid duplicates on re-configuration
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False  # Don't bubble up to the root Python logger

    # ── stderr handler ────────────────────────────────────────────────────────
    stderr_handler = logging.StreamHandler(sys.stderr)
    # Use colour/human format only when stderr is a real terminal.
    # When redirected to a file (e.g. >> watch.log 2>&1) fall back to
    # structured JSON so ANSI escape codes don't pollute the log file.
    use_human = fmt != "structured" and getattr(sys.stderr, "isatty", lambda: False)()
    stderr_handler.setFormatter(HumanFormatter() if use_human else StructuredFormatter())
    root.addHandler(stderr_handler)

    # ── file handler (always structured JSON for machine parsing) ─────────────
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setFormatter(StructuredFormatter())
        root.addHandler(file_handler)

    # Silence noisy third-party libraries
    for noisy_lib in ("openai", "httpx", "httpcore", "kafka", "urllib3"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)

    root.debug(
        "Logging configured",
        extra={"level": level, "format": fmt, "file": log_file},
    )
