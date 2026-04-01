"""Watch loops — file-based and Kafka-backed continuous drift detection."""

import atexit
import logging
import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import (
    DriftClass,
    DriftReport,
    DriftTier,
    FieldDrift,
)
from ..sampler import streaming_reservoir_sample_from_folder
from .classify import _handle_evolution
from .core import detect_drift
from .routing import _sub_schema_to_inferred_schema, detect_drift_multi_schema
from .webhook import _print_drift_report
from .window import (
    EventWindow,
    _load_checkpoint,
    _load_new_events,
    _save_checkpoint,
    _write_poll_state,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown infrastructure
# ---------------------------------------------------------------------------

_shutdown = threading.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    """Signal handler for SIGTERM and SIGINT."""
    logger.info("Received signal %s, initiating graceful shutdown...", signal.Signals(signum).name)
    _shutdown.set()


def watch_stream(
    stream_path: str,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    window_capacity: int = 2000,
    webhook_url: str | None = None,
) -> None:
    """
    Main watch loop. Runs until Ctrl+C.

    P1-B fix: accumulates events in a rolling EventWindow (default 2000 events)
    and samples drift candidates from the full window rather than only the
    latest batch.  This makes slow drift (field presence fading over hours)
    detectable and ensures each drift check has a statistically stable sample.

    P1-A fix: if a profile.yaml exists alongside schema.yaml, routes events to
    their sub-schema clusters and runs per-cluster drift detection.
    """
    from ..schema_writer import load_profile, load_schema

    schema_dir = Path(schema_path).parent
    profile = load_profile(schema_dir)
    multi_schema = profile is not None and len(profile.get("sub_schemas", [])) > 1

    # Fix 4 — canonical contract: when profile.yaml exists, the primary sub-schema
    # is the authoritative baseline.  Rebuilding it from profile avoids silent
    # divergence when schema.yaml has been manually edited since the last init.
    if multi_schema:
        baseline = _sub_schema_to_inferred_schema(profile["sub_schemas"][0], "")
        # Use the stream name from schema.yaml for consistent naming
        baseline.stream_name = load_schema(schema_path).stream_name
    else:
        baseline = load_schema(schema_path)

    stream_name = baseline.stream_name
    drift_output_dir = Path("drift_reports")

    mode_note = (
        f"multi-schema ({len(profile['sub_schemas'])} clusters, "
        f"routing_field={profile.get('routing_field') or 'structural'})"
        if multi_schema else "single-schema"
    )

    # Checkpoint path — persists the rolling window across restarts
    checkpoint_path = schema_dir / ".watch_state" / "window.ndjson"

    logger.info(
        "Watching %s every %ds (schema: %s, mode: %s, window: %d, checkpoint: %s)",
        stream_path, poll_interval_seconds, schema_path, mode_note, window_capacity, checkpoint_path,
    )
    logger.info(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Watching {stream_name} — {mode_note} — "
        f"window={window_capacity} events"
    )

    from ..models import DriftIncident, DriftIncidentStatus
    from ..schema_writer import load_drift_state, save_drift_state
    from ..watch_state import WatchState as _WatchState

    # Load (or create) persistent watch state — survives restarts
    _wstate = _WatchState.load(stream_name)
    if _wstate.phase == "STABLE":
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABLE phase (stable since {_wstate.stable_since or 'unknown'})"
        )
    elif _wstate.phase == "STABILIZING":
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABILIZING phase "
            f"({_wstate.stability_clean_count}/3 clean cycles)"
        )
    else:
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Phase: LEARNING — {_wstate.warmup_remaining} observation cycle(s) before stabilization check"
        )

    window = EventWindow(capacity=window_capacity)
    file_line_counts: dict[str, int] = {}
    # Tracks drift fingerprints already reported this session.
    # A fingerprint is (cluster_id_or_none, field_path, drift_type).
    # We only write a new report when a fingerprint is *newly* detected;
    # re-detecting the same drift in the next poll is silently suppressed.
    # Fingerprints are cleared when the drift stops being detected.
    # On startup we seed from any open incidents in drift_state.yaml so
    # restarting watch doesn't re-fire incidents that were already reported.
    state = load_drift_state(schema_dir)
    active_drift_sigs: set[tuple[str | None, str, str]] = {
        (inc.cluster_id, inc.field_path, inc.drift_type)
        for inc in state.incidents
        if inc.status == DriftIncidentStatus.OPEN
    }

    # Fix 2 — restore window from checkpoint if available (restart recovery)
    checkpoint_events = _load_checkpoint(checkpoint_path)
    if checkpoint_events:
        window.add(checkpoint_events)
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Restored {len(checkpoint_events)} events from checkpoint"
        )

    # Seed the window with a reservoir sample of existing events — O(window_capacity)
    # memory instead of loading all events. The deque would evict oldest anyway;
    # streaming sampling gives a representative initial window without OOM risk.
    initial, _init_total = streaming_reservoir_sample_from_folder(stream_path, window_capacity)
    if initial:
        window.add(initial)
        # Populate line counts so subsequent polls only read new lines
        for f in sorted(
            p for p in Path(stream_path).rglob("*")
            if p.suffix in (".ndjson", ".json") and p.is_file()
        ):
            try:
                with open(f, encoding="utf-8") as fh:
                    file_line_counts[str(f)] = sum(1 for _ in fh)
            except OSError:
                pass

    # Register signal handlers for graceful shutdown
    _shutdown.clear()
    prev_sigterm = signal.signal(signal.SIGTERM, _handle_signal)
    prev_sigint = signal.signal(signal.SIGINT, _handle_signal)

    def _emergency_save() -> None:
        """atexit fallback — save checkpoint if loop didn't exit cleanly."""
        if len(window) > 0:
            try:
                _save_checkpoint(window, checkpoint_path)
                logger.info("Emergency checkpoint saved via atexit")
            except Exception:
                pass

    atexit.register(_emergency_save)

    try:
        while not _shutdown.is_set():
            # Load only newly appended lines (P1-B: track by line count, not mtime)
            new_events = _load_new_events(stream_path, file_line_counts)
            if new_events:
                window.add(new_events)

            now_str = datetime.now().strftime("%H:%M:%S")

            if len(window) < 10:
                logger.info(f"[{now_str}] o {stream_name} - warming up ({len(window)} events in window)")
                if _shutdown.wait(poll_interval_seconds):
                    break
                continue

            # Advance warmup counter (file-based loop uses simple cycle count)
            _wstate.tick_warmup()

            sample = window.sample(sample_size)

            all_detected: list[FieldDrift] = []
            if multi_schema:
                reports = detect_drift_multi_schema(profile, sample, stream_name)
                for report in reports:
                    all_detected.extend(report.drifts)
            else:
                single_report = detect_drift(baseline, sample, stream_name)
                if single_report:
                    all_detected = single_report.drifts

            # During LEARNING phase: suppress non-critical drift alerts
            if _wstate.is_learning and all_detected:
                _critical_in_learning = [d for d in all_detected if d.tier == DriftTier.TIER_3]
                if not _critical_in_learning:
                    _sig_count = len(all_detected)
                    logger.info(
                        f"[{now_str}] o {stream_name} - LEARNING "
                        f"({_wstate.warmup_remaining} cycle(s) remaining, "
                        f"{_sig_count} signal(s) observed - suppressed)"
                    )
                    _wstate.save()
                    if _shutdown.wait(poll_interval_seconds):
                        break
                    continue
                # Critical drifts are never suppressed even during LEARNING

            current_sigs: set[tuple[str | None, str, str]] = {
                (d.cluster_id, d.field_path, d.drift_type) for d in all_detected
            }

            # Reload drift state — may have been updated by 'streamforge accept' externally
            state = load_drift_state(schema_dir)
            now_iso = datetime.now(UTC).isoformat()

            # Determine which signatures are actively suppressed or already accepted
            non_actionable: set[tuple[str | None, str, str]] = {
                (inc.cluster_id, inc.field_path, inc.drift_type)
                for inc in state.incidents
                if inc.status in (DriftIncidentStatus.ACCEPTED, DriftIncidentStatus.SUPPRESSED)
            }

            new_sigs = current_sigs - active_drift_sigs - non_actionable
            cleared_sigs = active_drift_sigs - current_sigs

            # Create incidents for newly detected drifts
            from ..models import DriftIncident
            new_incidents: list[DriftIncident] = []
            new_drifts_to_report: list[FieldDrift] = []
            for d in all_detected:
                sig = (d.cluster_id, d.field_path, d.drift_type)
                if sig not in new_sigs:
                    continue
                inc_id = (
                    f"drift-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
                    f"-{d.field_path.replace('.', '_')}"
                    f"{('-' + d.cluster_id) if d.cluster_id else ''}"
                )
                new_incidents.append(DriftIncident(
                    id=inc_id,
                    field_path=d.field_path,
                    cluster_id=d.cluster_id,
                    drift_type=d.drift_type,
                    tier=d.tier.value,
                    first_detected=now_iso,
                    last_seen=now_iso,
                    occurrences=1,
                    status=DriftIncidentStatus.OPEN,
                ))
                new_drifts_to_report.append(d)

            # Determine which incident IDs need occurrence bumps vs resolution.
            # We store only IDs (not full objects) so that the merge uses the
            # freshly-loaded incident as base — avoiding stale field overwrites
            # if an external process modified the incident between our two loads.
            bump_ids: set[str] = set()
            resolve_ids: set[str] = set()
            for inc in state.incidents:
                sig = (inc.cluster_id, inc.field_path, inc.drift_type)
                if inc.status == DriftIncidentStatus.OPEN and sig in current_sigs:
                    bump_ids.add(inc.id)
                elif inc.status == DriftIncidentStatus.OPEN and sig in cleared_sigs:
                    resolve_ids.add(inc.id)

            # Reload drift state to pick up any concurrent accept/suppress
            fresh_state = load_drift_state(schema_dir)
            merged_incidents = []
            for inc in fresh_state.incidents:
                if inc.id in resolve_ids and inc.status == DriftIncidentStatus.OPEN:
                    # Only resolve if still OPEN — don't overwrite accept/suppress
                    inc = inc.model_copy(update={
                        "status": DriftIncidentStatus.RESOLVED,
                        "resolved_at": now_iso,
                        "resolution_note": "Drift cleared \u2014 no longer detected in sample",
                    })
                elif inc.id in bump_ids and inc.status == DriftIncidentStatus.OPEN:
                    # Bump occurrence on the FRESH incident (not stale copy)
                    inc = inc.model_copy(
                        update={"last_seen": now_iso, "occurrences": inc.occurrences + 1}
                    )
                # If status changed externally (ACCEPTED/SUPPRESSED), keep as-is
                merged_incidents.append(inc)
            merged_incidents.extend(new_incidents)

            # Prune old resolved/accepted incidents to prevent unbounded growth.
            # Keep OPEN and SUPPRESSED (still actionable), prune RESOLVED/ACCEPTED
            # older than 7 days, and cap at 1000 total entries.
            _PRUNE_DAYS = 7
            _MAX_INCIDENTS = 1000
            from datetime import timedelta
            cutoff = (datetime.now(UTC) - timedelta(days=_PRUNE_DAYS)).isoformat()
            pruned = [
                inc for inc in merged_incidents
                if inc.status in (DriftIncidentStatus.OPEN, DriftIncidentStatus.SUPPRESSED)
                or (inc.resolved_at or inc.last_seen or "") > cutoff
            ]
            if len(pruned) > _MAX_INCIDENTS:
                # Keep most recent by last_seen
                pruned.sort(key=lambda i: i.last_seen or "", reverse=True)
                pruned = pruned[:_MAX_INCIDENTS]
            if len(pruned) < len(merged_incidents):
                logger.info(
                    "Pruned %d old resolved incidents (kept %d)",
                    len(merged_incidents) - len(pruned), len(pruned),
                )
            save_drift_state(schema_dir, fresh_state.model_copy(update={"incidents": pruned}))

            # Print to console and write report file for new drifts only
            if new_drifts_to_report:
                if multi_schema:
                    # Re-group new drifts by their original report
                    for report in reports:  # type: ignore[possibly-undefined]
                        relevant = [d for d in new_drifts_to_report if d in report.drifts]
                        if relevant:
                            filtered = report.model_copy(update={
                                "drifts": relevant,
                                "highest_tier": max(d.tier for d in relevant),
                            })
                            _print_drift_report(filtered, drift_output_dir, webhook_url)
                else:
                    assert single_report is not None  # type: ignore[possibly-undefined]
                    filtered = single_report.model_copy(update={
                        "drifts": new_drifts_to_report,
                        "highest_tier": max(d.tier for d in new_drifts_to_report),
                    })
                    _print_drift_report(filtered, drift_output_dir, webhook_url)
            elif current_sigs and not new_sigs:
                ongoing_count = len([
                    inc for inc in pruned
                    if inc.status == DriftIncidentStatus.OPEN
                ])
                logger.info(
                    f"[{now_str}] ~ {stream_name} - "
                    f"{len(sample)} sampled / {len(window)} in window - "
                    f"{ongoing_count} open incident(s) - run `streamforge status` or `streamforge accept`"
                )
            else:
                label = "all clusters clean" if multi_schema else "schema clean"
                logger.info(
                    f"[{now_str}] \u2713 {stream_name} - "
                    f"{len(sample)} sampled / {len(window)} in window - {label}"
                )

            active_drift_sigs = current_sigs - non_actionable

            # Update WatchState phase machine
            if new_drifts_to_report:
                _wstate.mark_drift()
            else:
                _wstate.mark_clean()
            _wstate.save()

            # Fix 2 — save window checkpoint after each successful poll
            _save_checkpoint(window, checkpoint_path)

            # Write last-polled state for the UI (last event timestamp + sample counts)
            _write_poll_state(schema_dir, len(sample), len(window), len(new_events))

            _shutdown.wait(poll_interval_seconds)

    except KeyboardInterrupt:
        pass
    finally:
        # Save checkpoint on any exit path (signal, KeyboardInterrupt, or loop end)
        _save_checkpoint(window, checkpoint_path)
        _wstate.save()
        atexit.unregister(_emergency_save)
        signal.signal(signal.SIGTERM, prev_sigterm)
        signal.signal(signal.SIGINT, prev_sigint)
        logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Watch stopped — checkpoint saved.")


# ---------------------------------------------------------------------------
# Kafka-backed watch loop
# ---------------------------------------------------------------------------

async def _watch_kafka_async(
    topic: str,
    kafka_cfg: Any,
    schema_path: str,
    poll_interval_seconds: int,
    sample_size: int,
    window_capacity: int,
    webhook_url: str | None,
) -> None:
    """
    Async Kafka watch loop — runs inside asyncio.run() from watch_stream_kafka().

    Uses KafkaConnector.read_batch() + ack() instead of file polling.
    The read_batch timeout IS the poll interval — no extra sleep needed.
    Committed Kafka offsets are the primary recovery mechanism; the NDJSON
    checkpoint pre-seeds the EventWindow on restart (warm-start optimisation).
    """
    from ..connectors.kafka import KafkaConnector
    from ..schema_writer import load_profile, load_schema

    schema_dir = Path(schema_path).parent
    profile = load_profile(schema_dir)
    multi_schema = profile is not None and len(profile.get("sub_schemas", [])) > 1

    if multi_schema:
        baseline = _sub_schema_to_inferred_schema(profile["sub_schemas"][0], "")
        baseline.stream_name = load_schema(schema_path).stream_name
    else:
        baseline = load_schema(schema_path)

    stream_name = baseline.stream_name
    drift_output_dir = Path("drift_reports")
    checkpoint_path = schema_dir / ".watch_state" / "window.ndjson"

    mode_note = (
        f"multi-schema ({len(profile['sub_schemas'])} clusters, "
        f"routing_field={profile.get('routing_field') or 'structural'})"
        if multi_schema else "single-schema"
    )

    logger.info(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Watching kafka://{topic} - {mode_note} - "
        f"window={window_capacity} events"
    )

    window = EventWindow(capacity=window_capacity)

    # ── Stability state machine ────────────────────────────────────────────────
    # NOTE: The canonical phase logic is in detector/phase.py (WatchPhase class).
    # This inline implementation is legacy — it will be replaced by WatchPhase
    # delegation once the persistence layer (WatchState) is migrated.
    # See: detector/phase.py for the single-source-of-truth state machine.
    #
    # Phase 1 LEARNING:     observe N cycles, no alerts (even Tier-1/2).
    #                       Tier-3 always alerts immediately (data integrity risk).
    # Phase 2 STABILIZING:  require M consecutive clean cycles before declaring stable.
    #                       Resets if Tier-2+ drift appears during this phase.
    # Phase 3 STABLE:       full alerting on. Tier-1/2 requires K consecutive drift
    #                       cycles before alerting (suppresses flapping / rollout noise).
    #                       Tier-3 always alerts immediately.
    #
    # Configurable via env:
    #   STREAMFORGE_WARMUP_CYCLES            default 10  (Phase 1 length)
    #   STREAMFORGE_STABILITY_CYCLES         default 3   (Phase 2 consecutive-clean needed)
    #   STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD default 2 (Phase 3 flap suppression)
    #
    # State is persisted in schemas/<stream>/.watch_state.json so restarts
    # resume from the correct phase rather than resetting to LEARNING.

    # Stability parameters: prefer TopicConfig.stability, fall back to env vars
    # (env var fallback keeps backward-compat for GCP deployments without config/).
    _tc = None
    try:
        from ..topic_config import load_topic_config as _load_tc
        _tc = _load_tc(topic)
        _stab = getattr(_tc, "stability", None)
    except Exception:
        _stab = None

    _warmup_total = (
        _stab.warmup_cycles if _stab else
        int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
    )
    _stability_needed = (
        _stab.stability_cycles if _stab else
        int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
    )
    _consec_threshold = (
        _stab.consecutive_drift_threshold if _stab else
        int(os.environ.get("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "2"))
    )

    # Load persistent watch state via WatchState (migrating legacy .watch_state.json if present)
    from ..watch_state import WatchState as _WatchState
    _legacy_state_file = schema_dir / ".watch_state.json"
    _kws = (
        _WatchState.migrate_legacy(topic, _legacy_state_file)
        or _WatchState.load(topic)
    )
    # Sync warmup_remaining with configured warmup total on first load
    if not _kws.warmup_done and _kws.cycle_count == 0:
        _kws.warmup_remaining = _warmup_total

    _phase                 = _kws.phase
    _warmup_remaining      = _kws.warmup_remaining
    _stability_clean_count = _kws.stability_clean_count
    _consec_drift_count    = _kws.consecutive_drifts

    def _save_watch_state_kws() -> None:
        _kws.phase = _phase
        _kws.warmup_remaining = _warmup_remaining
        _kws.stability_clean_count = _stability_clean_count
        _kws.consecutive_drifts = _consec_drift_count
        _kws.save()

    def _mark_stable(state: dict) -> None:
        nonlocal _phase
        _phase = "STABLE"
        _kws.phase = "STABLE"
        _kws.stable_since = datetime.now().isoformat()
        _kws.save()
        stable_file = schema_dir / ".stable"
        stable_file.write_text(
            f"stable_since: {_kws.stable_since}\n"
            f"warmup_cycles: {_warmup_total}\n"
            f"stability_cycles: {_stability_needed}\n"
        )
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"\u2705 {stream_name} - SYSTEM STABLE - full drift alerting now active"
        )

    if _phase == "STABLE":
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABLE phase (stable since {_kws.stable_since or 'unknown'})"
        )
    elif _phase == "STABILIZING":
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABILIZING phase ({_stability_clean_count}/{_stability_needed} clean cycles)"
        )
    else:
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Phase: LEARNING - {_warmup_remaining} observation cycle(s) before stabilization check"
        )

    # Warm-start: restore rolling window from previous checkpoint
    checkpoint_events = _load_checkpoint(checkpoint_path)
    if checkpoint_events:
        window.add(checkpoint_events)
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Restored {len(checkpoint_events)} events from checkpoint"
        )

    # Use "latest" offset reset for watch — only care about new events.
    # The checkpoint pre-seeds the window so drift detection starts immediately.
    kafka_cfg.auto_offset_reset = "latest"
    kafka_cfg.consumer_group = "streamforge-watcher"

    _shutdown.clear()

    try:
        async with KafkaConnector(topic, kafka_cfg) as conn:
            logger.info(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Connected: {conn.source_id}"
            )
            while not _shutdown.is_set():
                # Poll for up to poll_interval_seconds — the timeout IS the interval
                batch = await conn.read_batch(
                    max_messages=kafka_cfg.max_poll_records,
                    timeout_ms=poll_interval_seconds * 1_000,
                )

                if batch:
                    window.add(batch)
                    await conn.ack()  # commit offsets after adding to window

                now_str = datetime.now().strftime("%H:%M:%S")

                if len(window) < 10:
                    logger.info(f"[{now_str}] o {stream_name} - warming up ({len(window)} events in window)")
                    continue

                sample = window.sample(sample_size)

                # ── Phase 1: LEARNING ──────────────────────────────────────────
                if _phase == "LEARNING":
                    _warmup_remaining -= 1
                    # Run detection only to catch Tier-3 (critical) even in learning
                    _learning_reports = (
                        detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                        if multi_schema
                        else ([r] if (r := detect_drift(baseline, sample, stream_name)) else [])
                    )
                    _critical = [r for r in _learning_reports if r.highest_tier == DriftTier.TIER_3]
                    if _critical:
                        for report in _critical:
                            logger.info(
                                f"[{now_str}] \U0001f534 {stream_name} - TIER-3 CRITICAL during LEARNING "
                                f"- alerting immediately (data integrity risk)"
                            )
                            _print_drift_report(report, drift_output_dir, webhook_url)
                    else:
                        _non_critical_count = sum(len(r.drifts) for r in _learning_reports)
                        _observed_note = (
                            f", {_non_critical_count} signal(s) observed (suppressed)"
                            if _non_critical_count else ""
                        )
                        logger.info(
                            f"[{now_str}] o {stream_name} - LEARNING "
                            f"({_warmup_remaining} cycle(s) remaining, "
                            f"{len(window)} in window{_observed_note})"
                        )

                    if _warmup_remaining <= 0:
                        _phase = "STABILIZING"
                        _stability_clean_count = 0
                        logger.info(
                            f"[{now_str}] {stream_name} - LEARNING complete \u2192 entering STABILIZING phase "
                            f"(need {_stability_needed} consecutive clean cycles)"
                        )

                    _save_watch_state_kws()
                    _save_checkpoint(window, checkpoint_path)
                    _write_poll_state(schema_dir, len(sample), len(window), len(batch))
                    continue

                # ── Phase 2: STABILIZING ───────────────────────────────────────
                if _phase == "STABILIZING":
                    _stab_reports = (
                        detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                        if multi_schema
                        else ([r] if (r := detect_drift(baseline, sample, stream_name)) else [])
                    )
                    _critical = [r for r in _stab_reports if r.highest_tier == DriftTier.TIER_3]
                    _significant = [r for r in _stab_reports if r.highest_tier >= DriftTier.TIER_2]

                    if _critical:
                        for report in _critical:
                            logger.info(
                                f"[{now_str}] \U0001f534 {stream_name} - TIER-3 CRITICAL during STABILIZING "
                                f"- alerting immediately"
                            )
                            _print_drift_report(report, drift_output_dir, webhook_url)
                        # Reset stability clock on critical drift
                        _stability_clean_count = 0
                    elif _significant:
                        logger.info(
                            f"[{now_str}] \u26a1 {stream_name} - STABILIZING - Tier-2 drift observed, "
                            f"resetting clean-cycle counter (was {_stability_clean_count}/{_stability_needed})"
                        )
                        _stability_clean_count = 0
                    else:
                        _stability_clean_count += 1
                        logger.info(
                            f"[{now_str}] o {stream_name} - STABILIZING "
                            f"({_stability_clean_count}/{_stability_needed} clean cycles, "
                            f"{len(window)} in window)"
                        )
                        if _stability_clean_count >= _stability_needed:
                            _mark_stable({})
                            _phase = "STABLE"
                            _consec_drift_count = 0

                    _save_watch_state_kws()
                    _save_checkpoint(window, checkpoint_path)
                    _write_poll_state(schema_dir, len(sample), len(window), len(batch))
                    continue

                # ── Phase 3: STABLE ────────────────────────────────────────────
                if multi_schema:
                    reports = detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                else:
                    _r = detect_drift(baseline, sample, stream_name)
                    reports = [_r] if _r else []

                if not reports:
                    _consec_drift_count = 0
                    logger.info(
                        f"[{now_str}] \u2713 {stream_name} - "
                        f"{len(sample)} sampled / {len(window)} in window - all clusters clean"
                    )
                else:
                    # Split each report's drifts by drift_class before routing.
                    # Build a DRIFT-only view for the alert path and collect
                    # evolution / noise signals for their respective handlers.
                    _drift_reports: list[DriftReport] = []
                    _evolution_drifts: list[FieldDrift] = []
                    _noise_count = 0

                    for report in reports:
                        _rd = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
                        _re = [d for d in report.drifts if d.drift_class == DriftClass.EVOLUTION]
                        _rn = [d for d in report.drifts if d.drift_class == DriftClass.NOISE]

                        _evolution_drifts.extend(_re)
                        _noise_count += len(_rn)

                        if _rd:
                            _drift_reports.append(
                                report.model_copy(update={
                                    "drifts": _rd,
                                    "highest_tier": max(d.tier for d in _rd),
                                    "evolution_count": 0,
                                    "noise_count": len(_rn),
                                })
                            )

                    # EVOLUTION → evolution handler (no alert)
                    if _evolution_drifts:
                        _handle_evolution(_evolution_drifts, stream_name, schema_dir, _tc)

                    # NOISE → suppress (debug log only)
                    if _noise_count:
                        logger.debug(
                            "[%s] %s \u2014 %d noise signal(s) suppressed",
                            now_str, stream_name, _noise_count,
                        )

                    # DRIFT → existing alert path (tier-based flap suppression)
                    _critical = [r for r in _drift_reports if r.highest_tier == DriftTier.TIER_3]
                    _non_critical = [r for r in _drift_reports if r.highest_tier < DriftTier.TIER_3]

                    # Tier-3: always alert immediately
                    for report in _critical:
                        _consec_drift_count = 0  # critical resets flap counter
                        _print_drift_report(report, drift_output_dir, webhook_url)

                    # Tier-1/2: only alert after K consecutive drift cycles
                    if _non_critical:
                        _consec_drift_count += 1
                        if _consec_drift_count >= _consec_threshold:
                            for report in _non_critical:
                                _print_drift_report(report, drift_output_dir, webhook_url)
                        else:
                            _total_drifts = sum(len(r.drifts) for r in _non_critical)
                            logger.info(
                                f"[{now_str}] o {stream_name} - {_total_drifts} signal(s) observed "
                                f"(cycle {_consec_drift_count}/{_consec_threshold} - suppressing until sustained)"
                            )

                    # If all signals were evolution/noise (nothing left for DRIFT alert),
                    # and no critical drift fired, treat as clean for the flap counter.
                    if not _critical and not _non_critical:
                        _consec_drift_count = 0

                _save_watch_state_kws()
                _save_checkpoint(window, checkpoint_path)
                _write_poll_state(schema_dir, len(sample), len(window), len(batch))

    except KeyboardInterrupt:
        pass
    finally:
        _save_checkpoint(window, checkpoint_path)
        logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Watch stopped — checkpoint saved.")


def watch_stream_kafka(
    topic: str,
    kafka_cfg: Any,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    window_capacity: int = 2000,
    webhook_url: str | None = None,
) -> None:
    """
    Kafka-backed watch loop. Identical logic to watch_stream() but reads
    from a Kafka topic via KafkaConnector instead of polling NDJSON files.

    This is a thin synchronous wrapper — the real loop runs in asyncio.run()
    so it can use the async KafkaConnector interface cleanly.

    Recovery model:
      Primary:   Kafka committed offsets (via ack() after each batch).
                 On restart the broker serves events from the last committed
                 offset — nothing is missed as long as the topic's retention
                 window covers the outage.
      Secondary: NDJSON window checkpoint at schema_dir/.watch_state/window.ndjson.
                 Pre-seeds the EventWindow so drift detection is immediately
                 statistically meaningful without waiting for 2000+ new events.

    Args:
        topic:                 Kafka topic name (without kafka:// prefix).
        kafka_cfg:             KafkaConfig with broker/auth settings.
        schema_path:           Path to schema.yaml (or profile.yaml directory).
        poll_interval_seconds: How long read_batch() waits for each batch.
        sample_size:           Events to reservoir-sample from the window per tick.
        window_capacity:       Rolling window size (older events evicted first).
        webhook_url:           Optional webhook for drift notifications.
    """
    import asyncio
    import sys

    # Ensure logger output appears immediately even when stdout is redirected
    # to a file (e.g. in demo.sh). Python uses block buffering for non-ttys;
    # reconfigure() switches to line-buffered mode for the duration of watch.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass  # not available in all environments

    asyncio.run(_watch_kafka_async(
        topic, kafka_cfg, schema_path,
        poll_interval_seconds, sample_size, window_capacity, webhook_url,
    ))
