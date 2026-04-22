"""
streamforge/resilience.py — Circuit Breaker & Resilience Patterns
==================================================================

Provides fault tolerance for queue sidecars and connectors.

Circuit Breaker Pattern:
- CLOSED: Normal operation, requests pass through
- OPEN: Failures exceeded threshold, requests rejected immediately
- HALF-OPEN: After timeout, allow one request to test recovery

This module is designed to be lightweight with no external dependencies.
For production with more features, install pybreaker and use PyBreakerCircuitBreaker.

Usage:
    from streamforge.resilience import CircuitBreaker

    breaker = CircuitBreaker(name="sqs-queue", fail_max=5, reset_timeout=30)

    # Sync call
    result = breaker.call(my_function, arg1, arg2)

    # Async call
    result = await breaker.call_async(my_async_function, arg1)
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open and rejecting calls."""

    def __init__(self, name: str, remaining_seconds: float) -> None:
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Circuit '{name}' is open. Retry in {remaining_seconds:.1f}s"
        )


@dataclass
class CircuitBreaker:
    """
    Thread-safe circuit breaker implementation.

    States:
    - closed: Normal operation
    - open: Rejecting all calls
    - half-open: Testing recovery with single call

    Attributes:
        name: Identifier for logging and health checks
        fail_max: Consecutive failures before opening circuit
        reset_timeout: Seconds before half-open attempt
    """

    name: str
    fail_max: int = 5
    reset_timeout: float = 30.0

    _failure_count: int = field(default=0, init=False, repr=False)
    _last_failure_time: float = field(default=0.0, init=False, repr=False)
    _state: str = field(default="closed", init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def state(self) -> str:
        """Current circuit state: closed, open, or half-open."""
        with self._lock:
            if self._state == "open":
                # Check if we should transition to half-open
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.reset_timeout:
                    self._state = "half-open"
            return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        with self._lock:
            return self._failure_count

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through circuit breaker.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of func(*args, **kwargs)

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: If func raises (and possibly opens circuit)
        """
        self._check_state()

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    async def call_async(
        self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        """
        Execute async function through circuit breaker.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of await func(*args, **kwargs)

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: If func raises (and possibly opens circuit)
        """
        self._check_state()

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _check_state(self) -> None:
        """Check if circuit allows the call."""
        current_state = self.state  # This handles open→half-open transition

        if current_state == "open":
            remaining = self.reset_timeout - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitBreakerOpen(self.name, max(0, remaining))

        # closed or half-open: allow the call

    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"

    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == "half-open":
                # Failure in half-open: reopen
                self._state = "open"
            elif self._failure_count >= self.fail_max:
                # Exceeded threshold: open circuit
                self._state = "open"

    def to_health_dict(self) -> dict[str, Any]:
        """
        Export circuit state for health checks.

        Returns:
            Dict with name, state, failure_count, fail_max, reset_timeout
        """
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "fail_max": self.fail_max,
            "reset_timeout": self.reset_timeout,
        }

    def reset(self) -> None:
        """Force reset the circuit to closed state."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._last_failure_time = 0.0


# Registry to track all circuit breakers for health aggregation
_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_or_create_breaker(
    name: str, fail_max: int = 5, reset_timeout: float = 30.0
) -> CircuitBreaker:
    """
    Get existing circuit breaker or create new one.

    Thread-safe singleton pattern per name.

    Args:
        name: Unique identifier for the breaker
        fail_max: Max failures before opening (only used on creation)
        reset_timeout: Seconds before half-open (only used on creation)

    Returns:
        CircuitBreaker instance
    """
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name, fail_max=fail_max, reset_timeout=reset_timeout
            )
        return _breakers[name]


def get_all_breakers() -> dict[str, CircuitBreaker]:
    """Get all registered circuit breakers."""
    with _registry_lock:
        return dict(_breakers)


def get_health_summary() -> dict[str, dict[str, Any]]:
    """
    Get health status of all circuit breakers.

    Returns:
        Dict mapping breaker name to health dict
    """
    with _registry_lock:
        return {name: breaker.to_health_dict() for name, breaker in _breakers.items()}
