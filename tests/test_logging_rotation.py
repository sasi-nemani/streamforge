"""Tests for log rotation configuration (production bug fix)."""
import logging
import os

import pytest


def test_log_file_uses_rotating_handler(tmp_path, monkeypatch):
    """Log file handler should use RotatingFileHandler, not plain FileHandler."""
    # Clear any existing handlers first
    root = logging.getLogger("streamforge")
    root.handlers.clear()

    # Import and configure
    from streamforge.logging_config import configure

    log_file = tmp_path / "test.log"
    configure(log_file=str(log_file))

    # Verify handler type
    from logging.handlers import RotatingFileHandler

    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 100_000_000  # 100MB default
    assert file_handlers[0].backupCount == 10  # 10 backups default


def test_log_rotation_respects_env_vars(tmp_path, monkeypatch):
    """Log rotation should respect STREAMFORGE_LOG_MAX_BYTES and STREAMFORGE_LOG_BACKUP_COUNT."""
    # Clear any existing handlers first
    root = logging.getLogger("streamforge")
    root.handlers.clear()

    # Set custom env vars
    monkeypatch.setenv("STREAMFORGE_LOG_MAX_BYTES", "50000000")  # 50MB
    monkeypatch.setenv("STREAMFORGE_LOG_BACKUP_COUNT", "5")

    from streamforge.logging_config import configure

    log_file = tmp_path / "test.log"
    configure(log_file=str(log_file))

    from logging.handlers import RotatingFileHandler

    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 50_000_000
    assert file_handlers[0].backupCount == 5
