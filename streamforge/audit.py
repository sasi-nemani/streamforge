"""
streamforge/audit.py — Production Audit Logger
================================================

Dedicated audit trail for type decisions, drift detection, and registry
operations. Separate from the main application logger so it can be toggled
independently at the finest granularity.

Usage:
    STREAMFORGE_AUDIT=1                  # enable audit logging (default: off)
    STREAMFORGE_AUDIT_LEVEL=DEBUG        # set audit log level
    STREAMFORGE_AUDIT_FILE=audit.jsonl   # write to file (structured JSON)

Audit events are structured JSON with a consistent schema:

    {"ts": "...", "audit": "type_decision", "field": "timestamp",
     "source": "registry", "type": "timestamp_epoch_ms", "confidence": 0.90,
     "corrected_from": "timestamp_iso8601", "sample_values": [1775062354503, ...],
     "evidence": "13-digit integer matches epoch_ms range", "stream": "events.payments"}

Categories:
    type_decision      — how a field's type was determined
    type_correction    — when post-processing overrode a type
    registry_hit       — field resolved from cache
    registry_miss      — field not in cache, sent to LLM
    registry_update    — field recorded back to registry
    drift_check        — per-field drift detection verdict
    drift_alert        — drift event raised
    validation_pass    — field values match expected type
    validation_fail    — field values don't match expected type
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import threading
from datetime import UTC, datetime
from typing import Any

# ── Audit logger — separate from main app logger ────────────────────────────
_audit_logger = logging.getLogger("streamforge.audit")
_configured = False
_configure_lock = threading.Lock()


def _ensure_configured() -> None:
    """Configure audit logger on first use. Thread-safe and idempotent."""
    global _configured
    if _configured:
        return
    with _configure_lock:
        if _configured:  # double-checked locking
            return
        _configured = True

    enabled = os.environ.get("STREAMFORGE_AUDIT", "1") != "0"
    if not enabled:
        _audit_logger.setLevel(logging.CRITICAL + 1)  # effectively disabled
        return

    level = os.environ.get("STREAMFORGE_AUDIT_LEVEL", "DEBUG")
    _audit_logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    _audit_logger.propagate = False  # don't bubble to root logger

    # Structured JSON formatter for audit events
    class _AuditFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            ts = datetime.fromtimestamp(record.created, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z"
            obj = {"ts": ts, "level": record.levelname}
            # Merge in all extra fields (the audit payload)
            for k, v in record.__dict__.items():
                if k.startswith("_") or k in (
                    "args", "created", "exc_info", "exc_text", "filename",
                    "funcName", "levelno", "lineno", "module", "msecs",
                    "message", "msg", "name", "pathname", "process",
                    "processName", "relativeCreated", "stack_info",
                    "thread", "threadName",
                ):
                    continue
                obj[k] = v
            obj["msg"] = record.getMessage()
            return json.dumps(obj, default=str)

    # stderr handler
    stderr_h = logging.StreamHandler()
    stderr_h.setFormatter(_AuditFormatter())
    _audit_logger.addHandler(stderr_h)

    # File handler (if configured)
    audit_file = os.environ.get("STREAMFORGE_AUDIT_FILE")
    if not audit_file:
        log_dir = os.environ.get("STREAMFORGE_LOG_DIR")
        if log_dir:
            audit_file = os.path.join(log_dir, "audit.jsonl")

    if audit_file:
        os.makedirs(os.path.dirname(audit_file) or ".", exist_ok=True)
        max_bytes = int(os.environ.get("STREAMFORGE_AUDIT_MAX_BYTES", "100000000"))  # 100MB
        backup_count = int(os.environ.get("STREAMFORGE_AUDIT_BACKUP_COUNT", "10"))
        file_h = logging.handlers.RotatingFileHandler(
            audit_file, mode="a", encoding="utf-8",
            maxBytes=max_bytes, backupCount=backup_count,
        )
        file_h.setFormatter(_AuditFormatter())
        _audit_logger.addHandler(file_h)

    # Optional syslog forwarding
    syslog_addr = os.environ.get("STREAMFORGE_AUDIT_SYSLOG")
    if syslog_addr:
        parts = syslog_addr.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 514
        syslog_h = logging.handlers.SysLogHandler(address=(host, port))
        syslog_h.setFormatter(_AuditFormatter())
        _audit_logger.addHandler(syslog_h)


def _enabled() -> bool:
    """Check if audit logging is active (not disabled via STREAMFORGE_AUDIT=0).

    Individual functions check their own log level — this only gates
    whether the audit system is enabled at all.
    """
    _ensure_configured()
    # Level is set to CRITICAL+1 when disabled, any normal level means enabled
    return _audit_logger.level <= logging.CRITICAL


# ── Public API — audit event emitters ────────────────────────────────────────

def log_type_decision(
    field_path: str,
    inferred_type: str,
    source: str,  # "registry" | "llm" | "statistical" | "schema_hints"
    confidence: float,
    sample_values: list[Any] | None = None,
    stream: str = "",
    notes: str = "",
) -> None:
    """Log a type inference decision with evidence."""
    if not _enabled():
        return
    _audit_logger.info(
        "type_decision: %s -> %s (source=%s, confidence=%.2f)",
        field_path, inferred_type, source, confidence,
        extra={
            "audit": "type_decision",
            "field": field_path,
            "type": inferred_type,
            "source": source,
            "confidence": confidence,
            "sample_values": _safe_samples(sample_values),
            "stream": stream,
            "notes": notes,
        },
    )


def log_type_correction(
    field_path: str,
    original_type: str,
    corrected_type: str,
    reason: str,
    sample_values: list[Any] | None = None,
    stream: str = "",
) -> None:
    """Log when post-processing overrides a type."""
    if not _enabled():
        return
    _audit_logger.warning(
        "type_correction: %s %s -> %s (%s)",
        field_path, original_type, corrected_type, reason,
        extra={
            "audit": "type_correction",
            "field": field_path,
            "original_type": original_type,
            "corrected_type": corrected_type,
            "reason": reason,
            "sample_values": _safe_samples(sample_values),
            "stream": stream,
        },
    )


def log_registry_event(
    event_type: str,  # "hit" | "miss" | "update"
    field_path: str,
    cached_type: str | None = None,
    observation_count: int = 0,
    stream: str = "",
) -> None:
    """Log registry lookup/update operations."""
    if not _enabled():
        return
    _audit_logger.debug(
        "registry_%s: %s (type=%s, obs=%d)",
        event_type, field_path, cached_type or "N/A", observation_count,
        extra={
            "audit": f"registry_{event_type}",
            "field": field_path,
            "cached_type": cached_type,
            "observation_count": observation_count,
            "stream": stream,
        },
    )


def log_drift_check(
    field_path: str,
    check_type: str,  # "presence" | "type" | "enum" | "pii"
    verdict: str,  # "clean" | "drift"
    details: dict[str, Any] | None = None,
    stream: str = "",
) -> None:
    """Log per-field drift detection verdict with evidence.

    Clean verdicts log at DEBUG (reduces noise by ~90%).
    Drift verdicts log at INFO (always visible when audit is on).
    """
    if not _enabled():
        return
    level = logging.DEBUG if verdict == "clean" else logging.INFO
    _audit_logger.log(
        level,
        "drift_check: %s %s=%s",
        field_path, check_type, verdict,
        extra={
            "audit": "drift_check",
            "field": field_path,
            "check": check_type,
            "verdict": verdict,
            "stream": stream,
            **(details or {}),
        },
    )


def log_drift_detected(
    stream: str,
    drift_count: int,
    highest_tier: int,
    evolution_count: int = 0,
    noise_count: int = 0,
    events_sampled: int = 0,
) -> None:
    """Log aggregate drift detection event for alerting/monitoring.

    Emitted once per poll cycle when drift is detected, summarizing
    all drift across all fields. This is the event to alert on.
    """
    if not _enabled():
        return
    _audit_logger.warning(
        "drift_detected: %s — %d drift(s), tier %d (%d sampled)",
        stream, drift_count, highest_tier, events_sampled,
        extra={
            "audit": "drift_detected",
            "stream": stream,
            "drift_count": drift_count,
            "highest_tier": highest_tier,
            "evolution_count": evolution_count,
            "noise_count": noise_count,
            "events_sampled": events_sampled,
        },
    )


# Heartbeat sampling — reduces audit log volume at scale.
# STREAMFORGE_AUDIT_HEARTBEAT_EVERY=N logs every Nth heartbeat (default=1 = every cycle).
# Drift events are NEVER sampled — always logged.
_heartbeat_counter: int = 0
_heartbeat_lock = threading.Lock()


def log_poll_heartbeat(
    stream: str,
    events_sampled: int,
    window_size: int,
    drift_count: int,
    highest_tier: int = 0,
) -> None:
    """Log a per-poll-cycle heartbeat for a stream.

    Heartbeats are sampled via STREAMFORGE_AUDIT_HEARTBEAT_EVERY env var
    to reduce log volume at scale (default=1, meaning every cycle).
    At 1000 streams x 30s intervals, HEARTBEAT_EVERY=10 reduces from
    2.88M to 288K heartbeat lines/day.
    """
    if not _enabled():
        return
    global _heartbeat_counter
    every_n = int(os.environ.get("STREAMFORGE_AUDIT_HEARTBEAT_EVERY", "1"))
    with _heartbeat_lock:
        _heartbeat_counter += 1
        current = _heartbeat_counter
    if every_n > 1 and (current % every_n) != 0:
        return
    verdict = "clean" if drift_count == 0 else f"{drift_count} drift(s), tier {highest_tier}"
    _audit_logger.info(
        "poll_heartbeat: %s — %s (%d sampled, %d in window)",
        stream, verdict, events_sampled, window_size,
        extra={
            "audit": "poll_heartbeat",
            "stream": stream,
            "events_sampled": events_sampled,
            "window_size": window_size,
            "drift_count": drift_count,
            "highest_tier": highest_tier,
        },
    )


def log_validation(
    field_path: str,
    expected_type: str,
    values_checked: int,
    values_matching: int,
    mismatches: list[Any] | None = None,
    stream: str = "",
) -> None:
    """Log multi-value type validation results."""
    if not _enabled():
        return
    match_rate = values_matching / max(values_checked, 1)
    passed = match_rate >= 0.95
    _audit_logger.log(
        logging.INFO if passed else logging.WARNING,
        "validation_%s: %s expected=%s checked=%d matching=%d (%.0f%%)",
        "pass" if passed else "fail",
        field_path, expected_type, values_checked, values_matching, match_rate * 100,
        extra={
            "audit": "validation_pass" if passed else "validation_fail",
            "field": field_path,
            "expected_type": expected_type,
            "values_checked": values_checked,
            "values_matching": values_matching,
            "match_rate": round(match_rate, 4),
            "mismatches": _safe_samples(mismatches) if mismatches else [],
            "stream": stream,
        },
    )


_PREVIEW_MAX = 2000


def log_llm_request(
    provider: str,
    model: str,
    stream: str = "",
    fields_sent: int = 0,
    fields_returned: int = 0,
    confidence: float = 0.0,
    latency_ms: float = 0.0,
    success: bool = True,
    prompt_chars: int = 0,
    response_chars: int = 0,
    error: str = "",
    prompt_preview: str = "",
    response_preview: str = "",
) -> None:
    """Log an LLM API call with request/response details.

    Every LLM call — successful or failed — must be logged for:
    - Cost tracking (prompt_chars → token estimation)
    - Latency monitoring (latency_ms)
    - Data flow audit (which stream's data went to which provider)
    - Failure analysis (error messages, retry patterns)

    Success logs at INFO. Failures log at WARNING.
    """
    if not _enabled():
        return
    level = logging.INFO if success else logging.WARNING
    _audit_logger.log(
        level,
        "llm_request: provider=%s model=%s stream=%s fields=%d->%d confidence=%.2f %sms%s",
        provider, model, stream, fields_sent, fields_returned,
        confidence, f"{latency_ms:.0f}",
        "" if success else f" ERROR: {error}",
        extra={
            "audit": "llm_request",
            "provider": provider,
            "model": model,
            "stream": stream,
            "fields_sent": fields_sent,
            "fields_returned": fields_returned,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "success": success,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "error": error,
            "prompt_preview": _scrub_preview(prompt_preview[:_PREVIEW_MAX]) if prompt_preview else "",
            "response_preview": _scrub_preview(response_preview[:_PREVIEW_MAX]) if response_preview else "",
        },
    )


_PII_REDACT_PATTERNS = [
    re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),  # email
    re.compile(r'\d{3}-\d{2}-\d{4}'),                                  # SSN
    re.compile(r'\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}'),            # card number
    re.compile(r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b'),    # IP address
    re.compile(r'\+\d{1,3}[\s-]?\d{3,14}'),                            # phone intl
    re.compile(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?\b'),   # name (John Smith)
    re.compile(r'\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b'),  # DOB (1990-05-15)
    re.compile(r'\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Ct|Way|Pl)\b'),  # address
]


def _scrub_preview(text: str) -> str:
    """Scrub PII from preview strings using the module-level redaction patterns."""
    if not text:
        return text
    for pattern in _PII_REDACT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _safe_samples(values: list[Any] | None, max_items: int = 5) -> list:
    """Sanitize sample values for logging — truncate, stringify, redact PII.

    PII patterns (email, SSN, card number, IP, phone) are replaced with
    [REDACTED:<category>] before the value reaches the audit log.
    """
    if not values:
        return []
    result = []
    for v in values[:max_items]:
        s = repr(v)
        # Redact PII patterns in the stringified value
        for pattern in _PII_REDACT_PATTERNS:
            s = pattern.sub("[REDACTED]", s)
        result.append(s[:100] if len(s) > 100 else s)
    return result
