"""Evaluation scorecard endpoint — the system grades itself vs ground truth.

This powers the cockpit "Proof" panel: precision/recall/F1 for schema inference
and drift detection, plus confidence calibration. Runs offline (no LLM key) and
is memoized per stream so the dashboard loads instantly after the first hit.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...eval.benchmark import available_benchmarks
from ...eval.runner import Scorecard, run_benchmark

router = APIRouter()

_CACHE: dict[str, dict] = {}


def _payload(sc: Scorecard) -> dict:
    return {
        "stream": sc.stream,
        "inference_path": sc.inference_path,
        "seed": sc.seed,
        "schema": {
            "type_precision": round(sc.schema.type_prf.precision, 3),
            "type_recall": round(sc.schema.type_prf.recall, 3),
            "type_f1": round(sc.schema.type_prf.f1, 3),
            "type_accuracy": round(sc.schema.type_accuracy, 3),
            "pii_f1": round(sc.schema.pii_prf.f1, 3),
            "n_truth": sc.schema.n_truth,
            "n_inferred": sc.schema.n_inferred,
        },
        "drift": {
            "precision": round(sc.drift.prf.precision, 3),
            "recall": round(sc.drift.prf.recall, 3),
            "f1": round(sc.drift.prf.f1, 3),
            "detection_latency_events": sc.drift.detection_latency_events,
            "fpr_null": round(sc.drift.fpr_null or 0.0, 3),
            "scenarios": [
                {"label": label, "f1": f1, "caught": f1 >= 0.99}
                for label, f1 in sc.scenarios
            ],
        },
        "calibration": {
            "ece": round(sc.calibration.ece, 3),
            "n_samples": sc.calibration.n_samples,
            "rating": (
                "well-calibrated" if sc.calibration.ece <= 0.10
                else "fair" if sc.calibration.ece <= 0.20 else "poor"
            ),
        },
    }


@router.get("/eval")
async def eval_list():
    """List streams that have a labeled benchmark."""
    return {"benchmarks": available_benchmarks()}


@router.get("/eval/{stream}")
async def eval_stream(stream: str):
    """Scorecard for one benchmarked stream."""
    if stream not in available_benchmarks():
        raise HTTPException(status_code=404, detail=f"No benchmark for {stream!r}")
    if stream not in _CACHE:
        _CACHE[stream] = _payload(run_benchmark(stream, seed=42))
    return _CACHE[stream]
