"""
streamforge/registries/apicurio.py — Apicurio Registry v2 Backend
===================================================================

Implements RegistryBackend against Apicurio Registry v2 REST API.

Auth: APICURIO_TOKEN env var (Bearer token) or no auth for open instances.
Config:
  APICURIO_URL   — Base URL (e.g. http://localhost:8080, default)
  APICURIO_GROUP — Artifact group (default: "default")

Apicurio supports Avro, JSON Schema, Protobuf. We default to Avro.

API reference: https://www.apicur.io/registry/docs/apicurio-registry/latest/assets-attachments/registry-rest-api.htm
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

_APICURIO_SUPPORTED_FORMATS: frozenset[str] = frozenset({"avro", "json-schema"})


class ApicurioRegistryBackend:
    """
    Apicurio Registry v2 backend.

    Uses the /apis/registry/v2 REST API.
    """

    def __init__(
        self,
        url: str = "http://localhost:8080",
        group: str = "default",
        token: str = "",
    ) -> None:
        self._base = url.rstrip("/") + "/apis/registry/v2"
        self._group = group
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(headers=headers, timeout=15)

    # ── RegistryBackend protocol ───────────────────────────────────────────────

    def push_schema(
        self,
        subject: str,
        schema: InferredSchema,
        fmt: str = "avro",
    ) -> RegistryResult:
        if (err := _validate_format(fmt, _APICURIO_SUPPORTED_FORMATS)) is not None:
            return err

        try:
            schema_str, artifact_type, content_type = self._serialise(schema, fmt)
        except Exception as e:
            return RegistryResult(success=False, error=f"Schema serialisation failed: {e}")

        enc = _quote(subject, safe="")
        url = f"{self._base}/groups/{self._group}/artifacts"
        headers = {
            "Content-Type": content_type,
            "X-Registry-ArtifactId": subject,          # header value — raw, not encoded
            "X-Registry-ArtifactType": artifact_type,
            "X-Registry-IfExists": "UPDATE",
        }

        try:
            resp = self._client.post(url, content=schema_str.encode(), headers=headers)
            if resp.status_code in (200, 201):
                data = resp.json()
                version = data.get("version")
                global_id = data.get("globalId")
                art_url = f"{self._base}/groups/{self._group}/artifacts/{enc}"
                logger.info("Pushed to Apicurio: %s version=%s", subject, version)
                return RegistryResult(
                    success=True,
                    schema_id=global_id,
                    version=version,
                    subject=subject,
                    url=art_url,
                    message=f"Apicurio artifact {subject} v{version}",
                )
            error = _http_error(resp)
            logger.error("Apicurio push failed: %s", error)
            return RegistryResult(success=False, error=error, subject=subject)
        except httpx.TimeoutException:
            return RegistryResult(success=False, error="Apicurio request timed out", subject=subject)
        except Exception as e:
            logger.exception("Unexpected error pushing to Apicurio")
            return RegistryResult(success=False, error=str(e), subject=subject)

    def get_schema(self, subject: str, version: str = "latest") -> dict | None:
        try:
            enc = _quote(subject, safe="")
            url = f"{self._base}/groups/{self._group}/artifacts/{enc}/versions/{version}/meta"
            resp = self._client.get(url)
            if resp.status_code == 200:
                # Fetch the actual content
                content_url = f"{self._base}/groups/{self._group}/artifacts/{enc}"
                c = self._client.get(content_url)
                if c.status_code == 200:
                    return json.loads(c.text)
            return None
        except Exception:
            return None

    def list_subjects(self, filter: str | None = None) -> list[str]:
        try:
            resp = self._client.get(
                f"{self._base}/groups/{self._group}/artifacts",
                params={"limit": 500},
            )
            if resp.status_code == 200:
                items = resp.json().get("artifacts", [])
                subjects = [a["id"] for a in items]
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
            schema_str, artifact_type, content_type = self._serialise(schema, "avro")
            url = f"{self._base}/groups/{self._group}/artifacts/{enc}/test"
            resp = self._client.post(url, content=schema_str.encode(), headers={"Content-Type": content_type})
            # 204 No Content = compatible
            return resp.status_code == 204
        except Exception:
            return False

    def ping(self) -> RegistryResult:
        """Check connectivity via GET /groups — returns without modifying any state."""
        try:
            resp = self._client.get(f"{self._base}/groups", params={"limit": 0})
            if resp.status_code == 200:
                return RegistryResult(success=True, message="Apicurio Registry reachable")
            return RegistryResult(success=False, error=_http_error(resp))
        except httpx.TimeoutException:
            return RegistryResult(success=False, error="Apicurio request timed out")
        except Exception as e:
            return RegistryResult(success=False, error=str(e))

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _serialise(self, schema: InferredSchema, fmt: str) -> tuple[str, str, str]:
        """Returns (schema_string, artifact_type, content_type)."""
        if fmt == "avro":
            from ..exporters.avro import schema_to_avro
            schema_str = json.dumps(schema_to_avro(schema))
            return schema_str, "AVRO", "application/json"
        if fmt == "json-schema":
            from ..exporters.json_schema import schema_to_json_schema
            schema_str = json.dumps(schema_to_json_schema(schema))
            return schema_str, "JSON", "application/json"
        raise ValueError(f"Unsupported format: {fmt!r}. Use 'avro' or 'json-schema'.")


def from_env(url: str | None = None) -> ApicurioRegistryBackend:
    """Construct backend from environment variables."""
    registry_url = url or os.environ.get("APICURIO_URL", "http://localhost:8080")
    group = os.environ.get("APICURIO_GROUP", "default")
    token = os.environ.get("APICURIO_TOKEN", "")
    return ApicurioRegistryBackend(url=registry_url, group=group, token=token)
