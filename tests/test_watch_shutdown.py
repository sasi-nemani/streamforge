"""Tests for graceful shutdown in watch loops."""

import signal

from streamforge.detector.watch import _handle_signal, _shutdown


class TestSignalHandler:
    def setup_method(self):
        _shutdown.clear()

    def teardown_method(self):
        _shutdown.clear()

    def test_signal_handler_sets_shutdown(self):
        """Calling _handle_signal sets the _shutdown event."""
        assert not _shutdown.is_set()
        _handle_signal(signal.SIGTERM, None)
        assert _shutdown.is_set()

    def test_signal_handler_works_with_sigint(self):
        """SIGINT also triggers shutdown."""
        _handle_signal(signal.SIGINT, None)
        assert _shutdown.is_set()

    def test_shutdown_event_is_waitable(self):
        """_shutdown.wait() returns immediately when set."""
        _shutdown.set()
        # Should return True immediately (not block)
        result = _shutdown.wait(timeout=0.01)
        assert result is True

    def test_shutdown_wait_returns_false_on_timeout(self):
        """_shutdown.wait() returns False on timeout when not set."""
        result = _shutdown.wait(timeout=0.01)
        assert result is False

    def test_shutdown_clear_resets(self):
        """clear() resets so loops can be restarted."""
        _shutdown.set()
        _shutdown.clear()
        assert not _shutdown.is_set()
