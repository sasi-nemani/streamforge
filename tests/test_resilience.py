"""
Circuit Breaker Tests (TDD RED phase).

Tests verify:
1. Circuit opens after N consecutive failures
2. Circuit half-opens after timeout
3. Circuit closes on success in half-open state
4. Breaker state is exposed for health checks

Run with: pytest tests/test_resilience.py -v
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCircuitBreakerBasics:
    """Basic circuit breaker behavior."""

    def test_circuit_starts_closed(self):
        """New circuit breaker starts in closed state."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=3, reset_timeout=10)
        assert breaker.state == "closed"

    def test_circuit_opens_after_fail_max(self):
        """Circuit opens after fail_max consecutive failures."""
        from streamforge.resilience import CircuitBreaker, CircuitBreakerOpen

        breaker = CircuitBreaker(name="test", fail_max=3, reset_timeout=10)

        def failing_func():
            raise Exception("simulated failure")

        # First 2 failures keep circuit closed
        for _ in range(2):
            with pytest.raises(Exception, match="simulated failure"):
                breaker.call(failing_func)
            assert breaker.state == "closed"

        # Third failure opens circuit
        with pytest.raises(Exception, match="simulated failure"):
            breaker.call(failing_func)

        assert breaker.state == "open"

    def test_open_circuit_rejects_calls(self):
        """Open circuit immediately rejects calls without executing function."""
        from streamforge.resilience import CircuitBreaker, CircuitBreakerOpen

        breaker = CircuitBreaker(name="test", fail_max=1, reset_timeout=60)

        call_count = 0

        def counting_func():
            nonlocal call_count
            call_count += 1
            raise Exception("fail")

        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(counting_func)

        assert breaker.state == "open"
        assert call_count == 1

        # Now calls should be rejected without executing
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(counting_func)

        # Function was NOT called again
        assert call_count == 1

    def test_circuit_exposes_failure_count(self):
        """Circuit exposes current failure count for monitoring."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=5, reset_timeout=10)

        def failing_func():
            raise Exception("fail")

        assert breaker.failure_count == 0

        for i in range(3):
            with pytest.raises(Exception):
                breaker.call(failing_func)
            assert breaker.failure_count == i + 1


class TestCircuitBreakerRecovery:
    """Circuit breaker recovery behavior."""

    def test_success_resets_failure_count(self):
        """Successful call resets failure count."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=5, reset_timeout=10)

        def failing_func():
            raise Exception("fail")

        def success_func():
            return "ok"

        # Accumulate failures
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.call(failing_func)

        assert breaker.failure_count == 3

        # Success resets count
        result = breaker.call(success_func)
        assert result == "ok"
        assert breaker.failure_count == 0

    def test_circuit_half_opens_after_timeout(self):
        """Circuit transitions to half-open after reset_timeout."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=1, reset_timeout=0.1)

        def failing_func():
            raise Exception("fail")

        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(failing_func)

        assert breaker.state == "open"

        # Wait for reset timeout
        time.sleep(0.15)

        # Circuit should be half-open now
        assert breaker.state == "half-open"

    def test_success_in_half_open_closes_circuit(self):
        """Successful call in half-open state closes the circuit."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=1, reset_timeout=0.1)

        fail = True

        def conditional_func():
            if fail:
                raise Exception("fail")
            return "success"

        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(conditional_func)

        assert breaker.state == "open"

        # Wait for half-open
        time.sleep(0.15)
        assert breaker.state == "half-open"

        # Now succeed
        fail = False
        result = breaker.call(conditional_func)
        assert result == "success"
        assert breaker.state == "closed"

    def test_failure_in_half_open_reopens_circuit(self):
        """Failure in half-open state reopens the circuit."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=1, reset_timeout=0.1)

        def failing_func():
            raise Exception("fail")

        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(failing_func)

        # Wait for half-open
        time.sleep(0.15)
        assert breaker.state == "half-open"

        # Fail again
        with pytest.raises(Exception):
            breaker.call(failing_func)

        # Back to open
        assert breaker.state == "open"


class TestCircuitBreakerAsync:
    """Async circuit breaker support."""

    @pytest.mark.asyncio
    async def test_async_call_support(self):
        """Circuit breaker supports async functions."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=3, reset_timeout=10)

        async def async_success():
            await asyncio.sleep(0.01)
            return "async ok"

        result = await breaker.call_async(async_success)
        assert result == "async ok"

    @pytest.mark.asyncio
    async def test_async_circuit_opens_on_failures(self):
        """Async failures also open the circuit."""
        from streamforge.resilience import CircuitBreaker, CircuitBreakerOpen

        breaker = CircuitBreaker(name="test", fail_max=2, reset_timeout=10)

        async def async_fail():
            raise Exception("async fail")

        for _ in range(2):
            with pytest.raises(Exception, match="async fail"):
                await breaker.call_async(async_fail)

        assert breaker.state == "open"

        with pytest.raises(CircuitBreakerOpen):
            await breaker.call_async(async_fail)


class TestCircuitBreakerHealthExport:
    """Health check integration."""

    def test_to_health_dict(self):
        """Circuit breaker exports health-check-friendly dict."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="sqs-queue-1", fail_max=5, reset_timeout=30)

        health = breaker.to_health_dict()

        assert health["name"] == "sqs-queue-1"
        assert health["state"] == "closed"
        assert health["failure_count"] == 0
        assert health["fail_max"] == 5
        assert health["reset_timeout"] == 30

    def test_health_dict_reflects_state_changes(self):
        """Health dict reflects current circuit state."""
        from streamforge.resilience import CircuitBreaker

        breaker = CircuitBreaker(name="test", fail_max=1, reset_timeout=10)

        def failing_func():
            raise Exception("fail")

        with pytest.raises(Exception):
            breaker.call(failing_func)

        health = breaker.to_health_dict()
        assert health["state"] == "open"
        assert health["failure_count"] == 1
