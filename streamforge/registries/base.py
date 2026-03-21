"""
streamforge/registries/base.py — Schema Registry Protocol
==========================================================

Defines the RegistryBackend Protocol that all registry backends must implement,
plus RegistryResult — the never-raises return type (mirrors VCSResult pattern).

Backends:
  confluent.py — Confluent Schema Registry REST API (SR)
  glue.py      — AWS Glue Schema Registry
  apicurio.py  — Apicurio Registry v2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..models import InferredSchema

# ── Shared helpers ─────────────────────────────────────────────────────────────

_SUPPORTED_FORMATS: frozenset[str] = frozenset({"avro", "json-schema"})


def _http_error(resp: object, truncate: int = 200) -> str:
    """Format a registry HTTP error from an httpx Response (or any object with
    .status_code and .text attributes)."""
    status = getattr(resp, "status_code", "?")
    text = getattr(resp, "text", "")[:truncate]
    return f"HTTP {status}: {text}"


def _validate_format(fmt: str, supported: frozenset[str] = _SUPPORTED_FORMATS) -> RegistryResult | None:
    """Return a failure RegistryResult if *fmt* is not in *supported*, else None.

    Callers must use ``if (err := _validate_format(fmt)) is not None:`` — NOT
    ``if err:`` — because RegistryResult.__bool__ returns success (False for failures).
    """
    if fmt not in supported:
        supported_str = ", ".join(sorted(supported))
        return RegistryResult(
            success=False,
            error=f"Unsupported format {fmt!r}. Supported: {supported_str}",
        )
    return None


@dataclass
class RegistryResult:
    """
    Result of any registry operation.

    Never raises — callers should check ``result.success`` before using
    schema_id / version. ``__bool__`` returns ``self.success`` for convenience::

        result = backend.push_schema(subject, schema)
        if not result:
            logger.warning("Registry push failed: %s", result.error)
    """

    success: bool
    schema_id: int | None = None
    version: int | None = None
    subject: str | None = None
    url: str | None = None
    error: str | None = None
    message: str = ""

    def __bool__(self) -> bool:
        return self.success


@runtime_checkable
class RegistryBackend(Protocol):
    """
    Interface every schema registry backend must satisfy.

    All methods return RegistryResult — they never raise. Errors are surfaced
    through ``result.success = False`` and ``result.error``.
    """

    def push_schema(
        self,
        subject: str,
        schema: InferredSchema,
        fmt: str = "avro",
    ) -> RegistryResult:
        """
        Register or update a schema for the given subject.

        Args:
            subject: Registry subject name (e.g. ``events.payments-value``).
            schema:  InferredSchema to push.
            fmt:     ``"avro"`` or ``"json-schema"``.

        Returns:
            RegistryResult with schema_id and version on success.
        """
        ...

    def get_schema(
        self,
        subject: str,
        version: str = "latest",
    ) -> dict | None:
        """
        Retrieve a registered schema.

        Returns the raw schema dict from the registry, or None on failure.
        """
        ...

    def list_subjects(self, filter: str | None = None) -> list[str]:
        """
        List all subjects in the registry.

        Args:
            filter: Optional glob pattern to filter subjects (e.g. ``"events.*"``).

        Returns:
            List of matching subject names.
        """
        ...

    def is_compatible(
        self,
        subject: str,
        schema: InferredSchema,
    ) -> bool:
        """
        Check whether the schema is compatible with the latest registered version.

        Returns True if compatible or if the subject has no prior version.
        Returns False on incompatibility or API failure.
        """
        ...

    def ping(self) -> RegistryResult:
        """
        Check registry connectivity without modifying any state.

        Returns a successful RegistryResult if the registry is reachable,
        or a failure result with an error description otherwise.

        Never raises.
        """
        ...
