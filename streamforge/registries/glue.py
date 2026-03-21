"""
streamforge/registries/glue.py — AWS Glue Schema Registry Backend
===================================================================

Implements RegistryBackend against AWS Glue Schema Registry.

Auth: Standard boto3 credential chain (env vars, ~/.aws/credentials, IAM role).
Config:
  GLUE_REGISTRY_NAME — Glue registry name (default: "StreamForge")
  GLUE_REGISTRY_ARN  — Glue registry ARN (alternative to name)
  AWS_REGION         — AWS region (or boto3 default)

Optional dependency: boto3. Import-guarded — ImportError is raised at
construction time with a helpful install message if boto3 is absent.

Format: Avro (AWS Glue supports AVRO and JSON natively).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from .base import RegistryResult, _validate_format

_GLUE_SUPPORTED_FORMATS: frozenset[str] = frozenset({"avro"})

if TYPE_CHECKING:
    from ..models import InferredSchema

logger = logging.getLogger(__name__)


class GlueRegistryBackend:
    """
    AWS Glue Schema Registry backend.

    Requires boto3: pip install streamforge-cli[aws]
    """

    def __init__(
        self,
        registry_name: str = "StreamForge",
        region_name: str | None = None,
    ) -> None:
        try:
            import boto3
            self._glue = boto3.client(
                "glue",
                region_name=region_name or os.environ.get("AWS_REGION", "us-east-1"),
            )
        except ImportError as e:
            raise ImportError(
                "boto3 is required for AWS Glue Schema Registry. "
                "Install it: pip install streamforge-cli[aws]"
            ) from e

        self._registry_name = registry_name
        self._ensure_registry_exists()

    # ── RegistryBackend protocol ───────────────────────────────────────────────

    def push_schema(
        self,
        subject: str,
        schema: InferredSchema,
        fmt: str = "avro",
    ) -> RegistryResult:
        if (err := _validate_format(fmt, _GLUE_SUPPORTED_FORMATS)) is not None:
            return err

        try:
            avro_str = self._to_avro_str(schema)
            # Create schema definition if it doesn't exist
            schema_arn = self._ensure_schema_exists(subject, avro_str)

            # Register new version
            resp = self._glue.register_schema_version(
                SchemaId={"SchemaArn": schema_arn} if schema_arn else {"SchemaName": subject, "RegistryName": self._registry_name},
                SchemaDefinition=avro_str,
            )

            version_number = resp.get("VersionNumber")
            logger.info("Pushed schema to Glue: %s v%s", subject, version_number)
            return RegistryResult(
                success=True,
                version=version_number,
                subject=subject,
                message=f"Glue schema {subject} v{version_number}",
                url=f"https://console.aws.amazon.com/glue/home#/schema/{self._registry_name}/{subject}",
            )
        except Exception as e:
            logger.error("Glue registry push failed: %s", e)
            return RegistryResult(success=False, error=str(e), subject=subject)

    def get_schema(self, subject: str, version: str = "latest") -> dict | None:
        try:
            if version == "latest":
                resp = self._glue.get_schema_version(
                    SchemaId={"SchemaName": subject, "RegistryName": self._registry_name},
                    SchemaVersionNumber={"LatestVersion": True},
                )
            else:
                resp = self._glue.get_schema_version(
                    SchemaId={"SchemaName": subject, "RegistryName": self._registry_name},
                    SchemaVersionNumber={"VersionNumber": int(version)},
                )
            schema_str = resp.get("SchemaDefinition", "{}")
            return json.loads(schema_str)
        except Exception:
            return None

    def list_subjects(self, filter: str | None = None) -> list[str]:
        try:
            paginator = self._glue.get_paginator("list_schemas")
            subjects: list[str] = []
            for page in paginator.paginate(RegistryId={"RegistryName": self._registry_name}):
                for s in page.get("Schemas", []):
                    subjects.append(s["SchemaName"])

            if filter:
                import fnmatch
                subjects = [s for s in subjects if fnmatch.fnmatch(s, filter)]
            return subjects
        except Exception:
            return []

    def is_compatible(self, subject: str, schema: InferredSchema) -> bool:
        try:
            avro_str = self._to_avro_str(schema)
            resp = self._glue.query_schema_version_validity(
                SchemaDefinition=avro_str,
                DataFormat="AVRO",
                SchemaId={"SchemaName": subject, "RegistryName": self._registry_name},
            )
            return resp.get("Valid", False)
        except self._glue.exceptions.EntityNotFoundException:
            # No existing versions — by protocol definition, any schema is compatible
            return True
        except Exception:
            return False

    def ping(self) -> RegistryResult:
        """Check connectivity by reading the registry metadata."""
        try:
            self._glue.get_registry(RegistryId={"RegistryName": self._registry_name})
            return RegistryResult(success=True, message=f"Glue registry '{self._registry_name}' reachable")
        except Exception as e:
            return RegistryResult(success=False, error=str(e))

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _to_avro_str(self, schema: InferredSchema) -> str:
        from ..exporters.avro import schema_to_avro
        return json.dumps(schema_to_avro(schema))

    def _ensure_registry_exists(self) -> None:
        try:
            self._glue.get_registry(RegistryId={"RegistryName": self._registry_name})
        except self._glue.exceptions.EntityNotFoundException:
            self._glue.create_registry(
                RegistryName=self._registry_name,
                Description="StreamForge schema registry",
            )
        except Exception:
            pass  # Not fatal — push will fail with a clearer error if registry is missing

    def _ensure_schema_exists(self, subject: str, avro_str: str) -> str | None:
        """Create schema if it doesn't exist. Returns schema ARN."""
        try:
            resp = self._glue.get_schema(
                SchemaId={"SchemaName": subject, "RegistryName": self._registry_name}
            )
            return resp.get("SchemaArn")
        except Exception:
            pass
        try:
            resp = self._glue.create_schema(
                RegistryId={"RegistryName": self._registry_name},
                SchemaName=subject,
                DataFormat="AVRO",
                Compatibility="BACKWARD",
                SchemaDefinition=avro_str,
            )
            return resp.get("SchemaArn")
        except Exception:
            return None


def from_env() -> GlueRegistryBackend:
    """Construct backend from environment variables."""
    registry_name = os.environ.get("GLUE_REGISTRY_NAME", "StreamForge")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return GlueRegistryBackend(registry_name=registry_name, region_name=region)
