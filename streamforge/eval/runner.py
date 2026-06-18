"""Wire inference + drift detection + metrics into a reproducible scorecard.

Design choices that keep scores honest and reproducible:
  * Drift is measured against a baseline inferred from a CLEAN held-out half of
    the same stream (mirroring init→watch), and injected into the other half.
    The baseline is self-consistent, so clean-vs-clean detection reflects
    detector noise — not label mismatch — and FPR-under-null is meaningful.
  * Schema accuracy is scored against hand-labeled ground truth (eval/benchmarks).
  * Event loading is ordered and the injector is seeded — same seed ⇒ same score.
  * The harness runs OFFLINE: if no LLM key is present, inference uses the
    deterministic statistical path (quorum/statistical_inference). The scorecard
    records which path was used so the number is never misread.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from streamforge.eval import calibration, metrics
from streamforge.eval.benchmark import load_truth
from streamforge.eval.inject import inject
from streamforge.eval.types import (
    CalibrationResult,
    DriftEvalResult,
    DriftSpec,
    SchemaEvalResult,
    SchemaTruth,
)
from streamforge.models import FieldSchema, InferredSchema
from streamforge.sampler import get_all_field_paths, load_events_from_folder

# Repo root → events live at repo_root/events/<stream_path>
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Where each labeled stream's events live (relative to repo root).
_STREAM_EVENT_PATHS: dict[str, str] = {
    "payments": "events/payments/stream_v1",
    "bookings": "events/bookings/stream",
}


@dataclass(frozen=True)
class Scorecard:
    """Everything the demo/CI needs from one benchmark run."""

    stream: str
    inference_path: str            # "llm" | "statistical"
    schema: SchemaEvalResult
    drift: DriftEvalResult
    calibration: CalibrationResult
    scenarios: tuple[tuple[str, float], ...]  # (scenario label, drift F1)
    seed: int


# ── event loading ───────────────────────────────────────────────────────────────
def load_stream_events(stream: str) -> list[dict]:
    rel = _STREAM_EVENT_PATHS.get(stream)
    if rel is None:
        raise KeyError(f"No event path mapped for stream {stream!r}")
    folder = _REPO_ROOT / rel
    if not folder.is_dir():
        raise FileNotFoundError(f"Events not found for {stream!r} at {folder}")
    return load_events_from_folder(str(folder))


# ── inference ─────────────────────────────────────────────────────────────────────
def _api_key() -> str:
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY"):
        val = os.environ.get(var)
        if val:
            return val
    return ""


def infer_fields(stream: str, events: list[dict]) -> tuple[list[FieldSchema], str]:
    """Infer a schema for the stream. Returns (fields, path) where path is
    'llm' if a model was reachable, else 'statistical' for the deterministic
    fallback. Never raises on a missing key."""
    key = _api_key()
    if key:
        try:
            from streamforge.inference import (
                DEFAULT_BASE_URL,
                DEFAULT_MODEL,
                infer_sub_schema,
            )

            sub = infer_sub_schema(
                cluster_id=stream,
                events=events,
                detection_method="single",
                total_stream_events=len(events),
                api_key=key,
                model=DEFAULT_MODEL,
                base_url=DEFAULT_BASE_URL,
            )
            return list(sub.fields), "llm"
        except Exception:  # noqa: BLE001 — eval must degrade, never crash the scorecard
            pass
    # Deterministic statistical path
    from streamforge.inference import statistical_inference

    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    field_stats, presence_rates = get_all_field_paths(clean)
    return statistical_inference(field_stats, presence_rates), "statistical"


# ── baseline schema from ground truth (isolates drift measurement) ───────────────
def build_inferred_schema(
    stream: str, fields: list[FieldSchema], event_count: int
) -> InferredSchema:
    """Wrap inferred FieldSchemas into an InferredSchema the detector accepts."""
    return InferredSchema(
        stream_name=stream,
        version="1.0.0",
        inferred_at=datetime.now(UTC).isoformat(),
        event_count_sampled=event_count,
        fields=fields,
        inference_model="streamforge-eval",
        inference_confidence=1.0,
    )


# ── standard drift scenarios per stream ──────────────────────────────────────────
def default_scenarios(stream: str) -> dict[str, list[DriftSpec]]:
    """A fixed, labeled scenario suite. Each entry maps a human label to the
    drift(s) injected for it. Kept per-stream so paths are valid."""
    if stream == "payments":
        return {
            "type_flip:payment_method->int": [DriftSpec("type_flip", "payment_method", rate=0.4, params={"to": "int"})],
            "enum_add:status=BLOCKED": [DriftSpec("enum_add", "status", rate=0.2, params={"new_value": "BLOCKED"})],
            "presence_drop:metadata.region": [DriftSpec("presence_drop", "metadata.region", rate=0.5)],
            "field_added:risk_score": [DriftSpec("field_added", "risk_score", rate=0.6, params={"value": 0.9})],
            "field_removed:currency": [DriftSpec("field_removed", "currency")],
            "pii_add:transaction_id": [DriftSpec("pii_add", "transaction_id", rate=0.3, params={"value": "user@bank.com"})],
        }
    if stream == "bookings":
        return {
            "type_flip:booking_reference->int": [DriftSpec("type_flip", "booking_reference", rate=0.6, params={"to": "int"})],
            "enum_add:cabin_class=SUITE": [DriftSpec("enum_add", "cabin_class", rate=0.2, params={"new_value": "SUITE"})],
            "presence_drop:contact_phone": [DriftSpec("presence_drop", "contact_phone", rate=0.5)],
            "field_added:promo_code": [DriftSpec("field_added", "promo_code", rate=0.6, params={"value": "SUMMER"})],
            "field_removed:loyalty_number": [DriftSpec("field_removed", "loyalty_number")],
        }
    return {}


# ── drift evaluation ──────────────────────────────────────────────────────────────
def evaluate_drift(
    stream: str,
    clean_events: list[dict],
    *,
    seed: int = 42,
) -> tuple[DriftEvalResult, tuple[tuple[str, float], ...]]:
    from streamforge.detector.core import detect_drift

    # Baseline = a clean inference of the FIRST half; drift is injected into the
    # SECOND half. This mirrors how the tool runs (init builds the schema, watch
    # compares later events) and keeps the baseline self-consistent, so
    # clean-vs-clean detection reflects detector noise — not label mismatch.
    half = max(1, len(clean_events) // 2)
    baseline_events, test_events = clean_events[:half], clean_events[half:]
    base_fields, _ = infer_fields(stream, baseline_events)
    baseline = build_inferred_schema(stream, base_fields, len(baseline_events))
    scenarios = default_scenarios(stream)

    total_tp = total_fp = total_fn = 0
    per_scenario: list[tuple[str, float]] = []
    first_latency: int | None = None

    for label, specs in scenarios.items():
        mutated, expected = inject(test_events, specs, seed=seed)
        report = detect_drift(baseline, mutated, stream)
        prf = metrics.score_drift(report, expected)
        total_tp += prf.tp
        total_fp += prf.fp
        total_fn += prf.fn
        per_scenario.append((label, round(prf.f1, 3)))

        # Detection latency: smallest prefix of mutated events that surfaces a TP.
        if first_latency is None and expected:
            for size in (50, 100, 200, 400, len(mutated)):
                size = min(size, len(mutated))
                r = detect_drift(baseline, mutated[:size], stream)
                if metrics.score_drift(r, expected).tp > 0:
                    first_latency = size
                    break

    from streamforge.eval.types import PRF

    agg = PRF.from_counts(total_tp, total_fp, total_fn)

    # FPR under the null: detect on the CLEAN second half (no injected drift)
    # against the baseline inferred from the first half. Any drift here is a
    # genuine false positive of the detector.
    null_report = detect_drift(baseline, test_events, stream)
    fpr = metrics.fpr_null(null_report, n_fields_tested=len(base_fields))

    return (
        DriftEvalResult(prf=agg, detection_latency_events=first_latency, fpr_null=fpr),
        tuple(per_scenario),
    )


# ── calibration ───────────────────────────────────────────────────────────────────
def evaluate_calibration(
    inferred: list[FieldSchema], truth: SchemaTruth
) -> CalibrationResult:
    """Pair each matched-path field's reported confidence with whether its
    inferred type was correct, then compute ECE."""
    truth_by_path = truth.by_path()
    pairs: list[tuple[float, bool]] = []
    for f in inferred:
        t = truth_by_path.get(f.path)
        if t is None:
            continue
        pairs.append((float(f.confidence), f.field_type == t.field_type))
    return calibration.expected_calibration_error(pairs)


# ── top-level ─────────────────────────────────────────────────────────────────────
def run_benchmark(stream: str, *, seed: int = 42) -> Scorecard:
    truth = load_truth(stream)
    events = load_stream_events(stream)

    inferred, path = infer_fields(stream, events)
    schema_res = metrics.score_schema(inferred, truth)
    calib = evaluate_calibration(inferred, truth)
    drift_res, scenarios = evaluate_drift(stream, events, seed=seed)

    return Scorecard(
        stream=stream,
        inference_path=path,
        schema=schema_res,
        drift=drift_res,
        calibration=calib,
        scenarios=scenarios,
        seed=seed,
    )
