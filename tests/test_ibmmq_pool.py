"""
IBM MQ Connection Pool Tests.

Tests verify:
1. Pool reuses connections
2. Pool limits max connections
3. Pool handles stale connections
4. Pool provides stats for monitoring
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from streamforge.sidecar.models import IBMMQConfig


@pytest.fixture
def mock_pymqi():
    """Mock pymqi module."""
    with patch("streamforge.sidecar.ibmmq._pymqi") as mock:
        mock.connect.return_value = MagicMock()
        mock.Queue.return_value = MagicMock()
        yield mock


@pytest.fixture
def mq_config():
    """Create test MQ config."""
    return IBMMQConfig(
        host="localhost",
        port=1414,
        queue_manager="QM1",
        queue_name="TEST.QUEUE",
        channel="DEV.APP.SVRCONN",
        browse_mode=True,
    )


class TestIBMMQConnectionPool:
    """Connection pool behavior tests."""

    def test_pool_creates_connection_on_first_acquire(self, mock_pymqi, mq_config):
        """First acquire creates a new connection."""
        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=2)

        with pool.acquire() as (conn, queue):
            assert conn is not None
            assert queue is not None

        assert pool.stats["total_created"] == 1

    def test_pool_reuses_connections(self, mock_pymqi, mq_config):
        """Pool reuses released connections."""
        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=2)

        # First acquire
        with pool.acquire() as (conn1, _):
            first_conn = conn1

        # Second acquire should reuse
        with pool.acquire() as (conn2, _):
            second_conn = conn2

        # Should only create one connection
        assert pool.stats["total_created"] == 1
        assert pool.stats["pool_size"] == 1  # Connection returned to pool

    def test_pool_limits_size(self, mock_pymqi, mq_config):
        """Pool doesn't grow beyond max_size when connections are released."""
        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=2)

        # Acquire and release 5 times sequentially
        for _ in range(5):
            with pool.acquire():
                pass

        # Pool should have max 2 connections, only 1 created (reused)
        assert pool.stats["pool_size"] <= pool.max_size
        # All operations reused the same connection
        assert pool.stats["total_created"] == 1

    def test_pool_closes_stale_connections(self, mock_pymqi, mq_config):
        """Pool closes connections older than max_idle_seconds."""
        import time

        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=2, max_idle_seconds=0.1)

        # First acquire
        with pool.acquire():
            pass

        # Wait for connection to become stale
        time.sleep(0.15)

        # Second acquire should create new (stale one discarded)
        with pool.acquire():
            pass

        assert pool.stats["total_created"] == 2

    def test_pool_provides_stats(self, mock_pymqi, mq_config):
        """Pool exposes statistics for monitoring."""
        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=3)

        stats = pool.stats
        assert "pool_size" in stats
        assert "max_size" in stats
        assert "total_created" in stats
        assert stats["max_size"] == 3

    def test_pool_close_all(self, mock_pymqi, mq_config):
        """close_all releases all pooled connections."""
        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=2)

        # Create and release connection
        with pool.acquire():
            pass

        assert pool.stats["pool_size"] == 1

        # Close all
        pool.close_all()

        assert pool.stats["pool_size"] == 0


class TestIBMMQConnectionPoolConcurrency:
    """Concurrency tests for connection pool."""

    def test_pool_thread_safe(self, mock_pymqi, mq_config):
        """Pool handles concurrent access safely."""
        import threading

        from streamforge.sidecar.ibmmq import IBMMQConnectionPool

        pool = IBMMQConnectionPool(config=mq_config, max_size=5)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    with pool.acquire() as (conn, queue):
                        pass  # Simulate work
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
