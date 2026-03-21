"""
streamforge/registries — Schema Registry Integration
=====================================================

Factory module. Usage:

    from streamforge.registries import get_registry_backend, RegistryConfig

    cfg = RegistryConfig(
        enabled=True,
        backend="confluent",
        url="http://localhost:8081",
        format="avro",
    )
    backend = get_registry_backend(cfg)
    if backend:
        result = backend.push_schema("events.payments-value", schema)
        print(result)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .base import RegistryBackend, RegistryResult

logger = logging.getLogger(__name__)


@dataclass
class RegistryConfig:
    """
    All schema registry configuration. Typically populated from config/default.yaml
    and the registry section via topic_config.py.
    """
    enabled: bool = False

    # "confluent" | "glue" | "apicurio"
    backend: str = "confluent"

    # Registry URL (Confluent SR / Apicurio)
    url: str = "http://localhost:8081"

    # "avro" | "json-schema"
    format: str = "avro"

    # Subject suffix (Confluent convention: "<topic>-value")
    subject_suffix: str = "-value"

    # AWS Glue specific
    glue_registry_name: str = "StreamForge"


def get_registry_backend(cfg: RegistryConfig) -> RegistryBackend | None:
    """
    Construct the right registry backend from config.

    Returns None if registry is disabled — callers should check
    `if backend:` before using it.
    """
    if not cfg.enabled:
        return None

    if cfg.backend == "confluent":
        from .confluent import ConfluentRegistryBackend
        api_key = os.environ.get("SCHEMA_REGISTRY_API_KEY", "")
        api_secret = os.environ.get("SCHEMA_REGISTRY_API_SECRET", "")
        url = os.environ.get("SCHEMA_REGISTRY_URL", cfg.url)
        return ConfluentRegistryBackend(url=url, api_key=api_key, api_secret=api_secret)

    if cfg.backend == "glue":
        try:
            from .glue import GlueRegistryBackend
            registry_name = os.environ.get("GLUE_REGISTRY_NAME", cfg.glue_registry_name)
            return GlueRegistryBackend(registry_name=registry_name)
        except ImportError as e:
            logger.warning("AWS Glue backend unavailable: %s", e)
            return None

    if cfg.backend == "apicurio":
        from .apicurio import ApicurioRegistryBackend
        url = os.environ.get("APICURIO_URL", cfg.url)
        group = os.environ.get("APICURIO_GROUP", "default")
        token = os.environ.get("APICURIO_TOKEN", "")
        return ApicurioRegistryBackend(url=url, group=group, token=token)

    logger.warning("Unknown registry backend: %r — registry disabled", cfg.backend)
    return None


def subject_for_topic(topic: str, suffix: str = "-value") -> str:
    """Return the registry subject name for a Kafka topic."""
    return f"{topic}{suffix}"


__all__ = [
    "RegistryConfig",
    "RegistryResult",
    "RegistryBackend",
    "get_registry_backend",
    "subject_for_topic",
]
