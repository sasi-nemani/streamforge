"""Tests for multi-tenant namespace isolation."""
import pytest
from streamforge.config import Config


class TestNamespaceConfig:
    def test_default_namespace(self):
        cfg = Config()
        assert cfg.namespace == "default"

    def test_custom_namespace(self):
        cfg = Config(namespace="payments-team")
        assert cfg.namespace == "payments-team"

    def test_namespace_slug_sanitization(self):
        cfg = Config(namespace="Acme Corp! #123")
        assert cfg.namespace_slug == "acme_corp___123"

    def test_namespace_slug_lowercase(self):
        cfg = Config(namespace="PaymentsTeam")
        assert cfg.namespace_slug == "paymentsteam"

    def test_default_namespace_slug(self):
        cfg = Config()
        assert cfg.namespace_slug == "default"

    def test_namespace_from_env(self, monkeypatch):
        monkeypatch.setenv("STREAMFORGE_NAMESPACE", "my-team")
        from streamforge.config import load
        cfg = load()
        assert cfg.namespace == "my-team"
