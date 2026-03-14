"""
MockConnector — deterministic in-process event stream for demos and tests.

Design goals:
  1. Zero external dependencies. Runs on any machine, no Docker, no broker.
  2. Deterministic with a seed — identical output given identical config.
     Essential for reproducible tests and benchmarks.
  3. Configurable drift injection — phases switch on event count, not wall
     clock time. This makes demos predictable regardless of machine speed.
  4. Realistic variance — events within a phase are not identical copies.
     Values are drawn from configurable distributions so the profiler sees
     realistic statistics (presence rates, type distributions, cardinality).
  5. Rate control — events_per_second limits consumption speed for live demos.

Usage — demo scenario:

    from streamforge.connectors.mock import MockConnector, DriftPhase
    from streamforge.connectors.generators import payment_events, drifted_payment_events

    connector = MockConnector(
        phases=[
            DriftPhase(events=payment_events(n=300), label="baseline"),
            DriftPhase(events=drifted_payment_events(n=200), label="drift: amount renamed + timestamp format changed"),
        ],
        events_per_second=20.0,
    )

    async with connector:
        while True:
            batch = await connector.read_batch(max_messages=50)
            if not batch:
                break
            process(batch)
            await connector.ack()

Usage — test scenario (deterministic, no rate limiting):

    connector = MockConnector(
        phases=[DriftPhase(events=FIXTURE_EVENTS)],
        events_per_second=0,  # 0 = no rate limiting, return immediately
    )
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .base import ConnectorError, StreamConnector

logger = logging.getLogger(__name__)

# Sentinel: no rate limiting (return batches as fast as requested)
_NO_RATE_LIMIT = 0.0


@dataclass(frozen=True)
class DriftPhase:
    """
    A sequence of events that will be fed to consumers in order.

    Args:
        events:  The events for this phase. Consumed in order.
        label:   Human-readable description logged when this phase starts.
                 Useful for correlating demo output with expected behaviour.
    """
    events: list[dict[str, Any]]
    label: str = ""

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("DriftPhase must contain at least one event")


class MockConnector(StreamConnector):
    """
    In-process event stream with configurable phases and drift injection.

    Args:
        phases:            Ordered list of DriftPhase. Phases are consumed
                           sequentially. When all phases are exhausted,
                           read_batch returns [].
        events_per_second: Simulated ingestion rate. Set to 0 for no rate
                           limiting (useful in tests). Default: 10.0.
        loop_last_phase:   If True, the last phase repeats indefinitely.
                           Useful for long-running watch demos.
    """

    def __init__(
        self,
        phases: list[DriftPhase],
        events_per_second: float = 10.0,
        loop_last_phase: bool = False,
    ) -> None:
        if not phases:
            raise ValueError("MockConnector requires at least one DriftPhase")

        self._phases = phases
        self._rate = events_per_second
        self._loop_last = loop_last_phase

        # Mutable state — advanced as events are consumed
        self._phase_idx = 0
        self._event_idx = 0
        self._total_emitted = 0
        self._closed = False
        self._last_batch_size = 0

        self._log_phase_start(0)

    @property
    def source_id(self) -> str:
        return "mock:in-process"

    @property
    def total_emitted(self) -> int:
        """Total events emitted across all phases. Useful for assertions."""
        return self._total_emitted

    @property
    def current_phase_label(self) -> str:
        if self._phase_idx < len(self._phases):
            return self._phases[self._phase_idx].label
        return "exhausted"

    async def read_batch(
        self,
        max_messages: int = 200,
        timeout_ms: int = 1_000,
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise ConnectorError("read_batch called on closed MockConnector")

        batch: list[dict[str, Any]] = []

        while len(batch) < max_messages:
            event = self._next_event()
            if event is None:
                break
            batch.append(event)

        if not batch:
            # No events left — honour timeout so callers don't busy-loop
            if timeout_ms > 0:
                await asyncio.sleep(timeout_ms / 1000)
            self._last_batch_size = 0
            return []

        # Rate limiting: sleep for the time it would take to receive this batch
        if self._rate > _NO_RATE_LIMIT:
            sleep_s = len(batch) / self._rate
            await asyncio.sleep(sleep_s)

        self._total_emitted += len(batch)
        self._last_batch_size = len(batch)
        return batch

    async def ack(self) -> None:
        # MockConnector does not re-deliver events. ack() is a no-op.
        # This mirrors at-least-once semantics without needing persistent state.
        pass

    async def close(self) -> None:
        self._closed = True
        logger.debug(
            "MockConnector closed after %d events across %d phase(s)",
            self._total_emitted,
            len(self._phases),
        )

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _next_event(self) -> dict[str, Any] | None:
        """Return the next event, advancing phase state. None when exhausted."""
        while self._phase_idx < len(self._phases):
            phase = self._phases[self._phase_idx]

            if self._event_idx < len(phase.events):
                event = phase.events[self._event_idx]
                self._event_idx += 1
                return event

            # Current phase exhausted — advance
            next_phase_idx = self._phase_idx + 1

            if next_phase_idx >= len(self._phases):
                if self._loop_last:
                    # Restart current (last) phase
                    self._event_idx = 0
                    return self._next_event()
                return None  # all phases done

            self._phase_idx = next_phase_idx
            self._event_idx = 0
            self._log_phase_start(self._phase_idx)

        return None

    def _log_phase_start(self, idx: int) -> None:
        phase = self._phases[idx]
        label = f" ({phase.label})" if phase.label else ""
        logger.info(
            "MockConnector: phase %d/%d starting%s — %d events queued",
            idx + 1,
            len(self._phases),
            label,
            len(phase.events),
        )
