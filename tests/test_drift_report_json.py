"""Drift reports persist structured JSON so the API/cockpit can show evidence."""
from __future__ import annotations

import json
from pathlib import Path

from streamforge.models import DriftReport, DriftTier, FieldDrift
from streamforge.report_writer import write_drift_report


def _report() -> DriftReport:
    return DriftReport(
        stream_name="s",
        detected_at="2026-01-01T00:00:00Z",
        schema_version="1.0.0",
        events_sampled=100,
        highest_tier=DriftTier.TIER_2,
        summary="x",
        drifts=[
            FieldDrift(
                field_path="amount", drift_type="type_changed", affected_event_rate=0.4,
                tier=DriftTier.TIER_2, auto_correctable=True,
                test_name="chi_squared", p_value=0.0003, effect_size=0.42,
            )
        ],
    )


def test_write_drift_report_emits_json_sibling_with_evidence(tmp_path):
    write_drift_report(_report(), str(tmp_path))
    json_files = list(tmp_path.rglob("*.json"))
    assert len(json_files) == 1
    data = json.loads(json_files[0].read_text())
    d = data["drifts"][0]
    assert d["test_name"] == "chi_squared"
    assert d["p_value"] == 0.0003
    assert d["effect_size"] == 0.42


def test_store_surfaces_findings_with_evidence(tmp_path, monkeypatch):
    # Build the layout the API store expects: schemas/<stream>/{schema.yaml,drift_reports/*}
    sd = tmp_path / "s"
    sd.mkdir()
    (sd / "schema.yaml").write_text("fields: []\n", encoding="utf-8")
    dr = sd / "drift_reports"
    dr.mkdir()
    (dr / "2026-01-01-1200.md").write_text("# report", encoding="utf-8")
    (dr / "2026-01-01-1200.json").write_text(_report().model_dump_json(), encoding="utf-8")

    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))
    from streamforge.api.store import Store

    drifts = Store().get_active_drifts()
    assert len(drifts) == 1
    finding = drifts[0]["findings"][0]
    assert finding["drift_type"] == "type_changed"
    assert finding["test_name"] == "chi_squared"
    assert finding["p_value"] == 0.0003


def test_metrics_summary_has_source_split(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    sd.mkdir()
    (sd / "schema.yaml").write_text("fields: []\n", encoding="utf-8")
    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))
    from streamforge.api.store import Store

    m = Store().get_metrics_summary()
    for key in ("inference_llm_calls", "schema_cache_hits", "inference_statistical", "deterministic_pct"):
        assert key in m


def test_missing_json_sibling_yields_empty_findings(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    sd.mkdir()
    (sd / "schema.yaml").write_text("fields: []\n", encoding="utf-8")
    dr = sd / "drift_reports"
    dr.mkdir()
    (dr / "old-report.md").write_text("# legacy report, no json", encoding="utf-8")
    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))
    from streamforge.api.store import Store

    drifts = Store().get_active_drifts()
    assert drifts[0]["findings"] == []
    assert Path(dr / "old-report.md").exists()
