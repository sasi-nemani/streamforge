"""
streamforge/registries/confluent.py — Confluent Schema Registry Backend
=========================================================================

Implements RegistryBackend against the Confluent Schema Registry REST API v1.

Auth:
  SCHEMA_REGISTRY_URL        — required (e.g. http://localhost:8081)
  SCHEMA_REGISTRY_API_KEY    — Confluent Cloud API key (optional for local SR)
  SCHEMA_REGISTRY_API_SECRET — Confluent Cloud API secret

Subject naming: ``<topic>-value`` (Confluent convention).
Format support: Avro (default) and JSON Schema.

API reference: https://docs.confluent.io/platform/current/schema-registry/develop/api.html
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING
from urllib.parse import quote as _quote

import httpx

from .base import RegistryResult, _http_error, _validate_format

if TYPE_CHECKING:
    from ..models import InferredSchema

logger = logging.getLogger(__name__)

_CONTENT_TYPE = "application/vnd.schemaregistry.v1+json"


class ConfluentRegistryBackend:
    """
    Confluent Schema Registry backend.

    Converts InferredSchema to Avro or JSON Schema, then registers it.
    Falls back gracefully on API errors — all methods return RegistryResult.
    """

    def __init__(
        self,
        url: str,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self._base = url.rstrip("/")
        auth = (api_key, api_secret) if api_key and api_secret else None
        self._client = httpx.Client(
            auth=auth,
            headers={"Content-Type": _CONTENT_TYPE, "Accept": _CONTENT_TYPE},
            timeout=15,
        )

    # ── RegistryBackend protocol ───────────────────────────────────────────────

    def push_schema(
        self,
        subject: str,
        schema: InferredSchema,
        fmt: str = "avro",
    ) -> RegistryResult:
        """Register schema under ``subject``. Returns schema_id and version."""
        if (err := _validate_format(fmt)) is not None:
            return err

        try:
            payload = self._build_payload(schema, fmt)
        except Exception as e:
            return RegistryResult(success=False, error=f"Schema serialisation failed: {e}")

        try:
            enc = _quote(subject, safe="")
            resp = self._client.post(
                f"{self._base}/subjects/{enc}/versions",
                content=payload,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                schema_id = data.get("id")
                # Fetch the version number separately
                version = self._get_version_for_id(subject, schema_id)
                logger.info("Pushed schema %s → id=%s version=%s", subject, schema_id, version)
                return RegistryResult(
                    success=True,
                    schema_id=schema_id,
                    version=version,
                    subject=subject,
                    url=f"{self._base}/subjects/{enc}/versions/{version or 'latest'}",
                    message=f"Registered {subject} id={schema_id}",
                )
            error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("Registry push failed: %s", error)
            return RegistryResult(success=False, error=error, subject=subject)
        except httpx.TimeoutException:
            return RegistryResult(success=False, error="Schema Registry request timed out", subject=subject)
        except Exception as e:
            logger.exception("Unexpected error pushing to Confluent SR")
            return RegistryResult(success=False, error=str(e), subject=subject)

    def get_schema(self, subject: str, version: str = "latest") -> dict | None:
        try:
            enc = _quote(subject, safe="")
            resp = self._client.get(f"{self._base}/subjects/{enc}/versions/{version}")
            if resp.status_code == 200:
                data = resp.json()
                schema_str = data.get("schema", "{}")
                return json.loads(schema_str)
            return None
        except Exception:
            return None

    def list_subjects(self, filter: str | None = None) -> list[str]:
        try:
            resp = self._client.get(f"{self._base}/subjects")
            if resp.status_code == 200:
                subjects = resp.json()
                if filter:
                    import fnmatch
                    subjects = [s for s in subjects if fnmatch.fnmatch(s, filter)]
                return subjects
            return []
        except Exception:
            return []

    def is_compatible(self, subject: str, schema: InferredSchema) -> bool:
        try:
            enc = _quote(subject, safe="")
            payload = self._build_payload(schema, "avro")
            resp = self._client.post(
                f"{self._base}/compatibility/subjects/{enc}/versions/latest",
                content=payload,
            )
            if resp.status_code == 200:
                return resp.json().get("is_compatible", False)
            # 404 = subject doesn't exist yet → compatible by definition
            return resp.status_code == 404
        except Exception:
            return False

    def ping(self) -> RegistryResult:
        """Check connectivity via GET /config — returns without modifying any state."""
        try:
            resp = self._client.get(f"{self._base}/config")
            if resp.status_code == 200:
                return RegistryResult(success=True, message="Confluent SR reachable")
            return RegistryResult(success=False, error=_http_error(resp))
        except httpx.TimeoutException:
            return RegistryResult(success=False, error="Confluent SR request timed out")
        except Exception as e:
            return RegistryResult(success=False, error=str(e))

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_payload(self, schema: InferredSchema, fmt: str) -> bytes:
        if fmt == "avro":
            from ..exporters.avro import schema_to_avro
            avro_doc = schema_to_avro(schema)
            schema_str = json.dumps(avro_doc)
            body = {"schema": schema_str, "schemaType": "AVRO"}
        elif fmt == "json-schema":
            from ..exporters.json_schema import schema_to_json_schema
            js_doc = schema_to_json_schema(schema)
            schema_str = json.dumps(js_doc)
            body = {"schema": schema_str, "schemaType": "JSON"}
        else:
            raise ValueError(f"Unsupported format: {fmt!r}. Use 'avro' or 'json-schema'.")
        return json.dumps(body).encode()

    def _get_version_for_id(self, subject: str, schema_id: int | None) -> int | None:
        if schema_id is None:
            return None
        try:
            enc = _quote(subject, safe="")
            resp = self._client.get(f"{self._base}/subjects/{enc}/versions")
            if resp.status_code != 200:
                return None
            versions = resp.json()
            # Check latest version first (most common case)
            for v in reversed(versions):
                r = self._client.get(f"{self._base}/subjects/{enc}/versions/{v}")
                if r.status_code == 200 and r.json().get("id") == schema_id:
                    return v
        except Exception:
            pass
        return None


def from_env(url: str | None = None) -> ConfluentRegistryBackend:
    """Construct backend from environment variables."""
    registry_url = url or os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8081")
    api_key = os.environ.get("SCHEMA_REGISTRY_API_KEY", "")
    api_secret = os.environ.get("SCHEMA_REGISTRY_API_SECRET", "")
    return ConfluentRegistryBackend(url=registry_url, api_key=api_key, api_secret=api_secret)
