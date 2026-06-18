"""
tests/test_history.py — History, Diff, Velocity, and Proposal tests

All in-memory / temp-directory: no LLM calls, no Kafka, no network.
Covers:
  - Snapshot write / read roundtrip
  - Diff: added, removed, type_changed, presence_changed, enum_changed
  - Significance classification (breaking / non-breaking / informational)
  - Trend computation: stable, rising, declining, volatile, insufficient_data
  - Enum growth rate calculation
  - Alert generation
  - Velocity report aggregation across multiple snapshots
  - Proposal generation: promote, demote, remove
  - Proposal confidence scoring
  - write_diff_report / write_velocity_report / write_proposal_report (smoke tests)
"""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from streamforge.history import (
    _classify_significance,
    _compute_enum_growth_rate,
    _compute_trend,
    _flatten_profile,
    _generate_alert,
    _proposal_confidence,
    _weeks_of_evidence,
    compute_velocity,
    diff_profiles,
    list_snapshots,
    load_snapshot_meta,
    load_snapshot_profile,
    propose_baseline_updates,
    write_diff_report,
    write_proposal_report,
    write_snapshot,
    write_velocity_report,
)
from streamforge.models import (
    ProposalAction,
    TrendStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_profile(
    stream_name: str = "payments",
    cluster_id: str = "purchase",
    fields: list[dict] | None = None,
    routing_field: str | None = None,
    event_count: int = 1000,
) -> dict:
    """Build a minimal profile.yaml raw dict for testing."""
    if fields is None:
        fields = [
            {"path": "event_id", "type": "uuid", "required": True, "presence_rate": 1.0, "confidence": 0.99},
            {"path": "amount", "type": "float", "required": True, "presence_rate": 0.98, "confidence": 0.97},
            {"path": "currency", "type": "string", "required": True, "presence_rate": 0.99,
             "confidence": 0.99, "enum_values": ["USD", "EUR"]},
            {"path": "user.email", "type": "email", "required": True, "presence_rate": 0.95,
             "confidence": 0.99, "pii": ["email"]},
            {"path": "merchant_id", "type": "string", "required": False, "presence_rate": 0.70,
             "confidence": 0.90},
        ]
    return {
        "stream_name": stream_name,
        "profiled_at": "2026-03-16T00:00:00Z",
        "total_events_sampled": event_count,
        "parse_success_rate": 0.99,
        "discovery_method": "event_type_field",
        "routing_field": routing_field,
        "sub_schemas": [
            {
                "cluster_id": cluster_id,
                "detection_method": "event_type_field",
                "event_count": event_count,
                "sample_rate": 1.0,
                "fields": fields,
                "inference_confidence": 0.95,
                "top_keys": [f["path"].split(".")[0] for f in fields],
            }
        ],
        "profile_model": "test",
    }


@pytest.fixture
def tmp_schema_dir(tmp_path: Path) -> Path:
    """Create a clean schemas/ directory in a temp folder."""
    d = tmp_path / "schemas"
    d.mkdir()
    return d


@pytest.fixture
def two_snapshots(tmp_schema_dir: Path):
    """
    Write two dated snapshots for 'payments' stream.
    Left (older): baseline schema
    Right (newer): modified schema (amount removed, new_field added, currency enum expanded)
    """
    output_dir = str(tmp_schema_dir)

    left_profile = _make_profile(stream_name="payments")
    write_snapshot(left_profile, "payments", output_dir, date="2026-03-09")

    right_fields = [
        {"path": "event_id", "type": "uuid", "required": True, "presence_rate": 1.0, "confidence": 0.99},
        # "amount" removed
        {"path": "currency", "type": "string", "required": True, "presence_rate": 0.99,
         "confidence": 0.99, "enum_values": ["USD", "EUR", "GBP"]},  # GBP added
        {"path": "user.email", "type": "email", "required": True, "presence_rate": 0.72,  # dropped
         "confidence": 0.99, "pii": ["email"]},
        {"path": "merchant_id", "type": "string", "required": False, "presence_rate": 0.70,
         "confidence": 0.90},
        {"path": "new_field", "type": "string", "required": False, "presence_rate": 0.40,
         "confidence": 0.85},  # added
    ]
    right_profile = _make_profile(stream_name="payments", fields=right_fields)
    right_profile["profiled_at"] = "2026-03-16T00:00:00Z"
    write_snapshot(right_profile, "payments", output_dir, date="2026-03-16")

    history_dir = tmp_schema_dir / "payments" / "history"
    left_path = history_dir / "2026-03-09"
    right_path = history_dir / "2026-03-16"
    return left_path, right_path, output_dir


# ---------------------------------------------------------------------------
# Snapshot I/O
# ---------------------------------------------------------------------------

class TestSnapshotIO:
    def test_write_creates_profile_and_meta(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        snap_path, meta_path = write_snapshot(profile, "payments", output_dir, date="2026-03-16")

        assert Path(snap_path).exists()
        assert Path(meta_path).exists()

    def test_profile_roundtrip(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")

        snap_dir = tmp_schema_dir / "payments" / "history" / "2026-03-16"
        loaded = load_snapshot_profile(snap_dir)
        assert loaded["stream_name"] == "payments"
        assert len(loaded["sub_schemas"]) == 1

    def test_meta_roundtrip(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile(stream_name="payments", event_count=2500)
        write_snapshot(profile, "payments", output_dir, date="2026-03-16", triggered_by="cron")

        snap_dir = tmp_schema_dir / "payments" / "history" / "2026-03-16"
        meta = load_snapshot_meta(snap_dir)
        assert meta.stream_name == "payments"
        assert meta.total_events_sampled == 2500
        assert meta.triggered_by == "cron"
        assert meta.snapshot_date == "2026-03-16"
        assert "purchase" in meta.cluster_ids

    def test_list_snapshots_chronological(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-02")
        write_snapshot(profile, "payments", output_dir, date="2026-03-09")
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")

        snaps = list_snapshots(output_dir, "payments")
        names = [s.name for s in snaps]
        assert names == ["2026-03-02", "2026-03-09", "2026-03-16"]

    def test_list_snapshots_empty(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        snaps = list_snapshots(output_dir, "nonexistent")
        assert snaps == []

    def test_overwrite_same_day_does_not_raise(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")
        # Second write to same date — should not raise
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")
        snaps = list_snapshots(output_dir, "payments")
        assert len(snaps) == 1  # still one snapshot

    def test_load_snapshot_profile_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_snapshot_profile(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# Profile flattening
# ---------------------------------------------------------------------------

class TestFlattenProfile:
    def test_flat_profile_uses_flat_cluster(self):
        profile = _make_profile()
        flat = _flatten_profile(profile)
        keys = list(flat.keys())
        assert all(cid == "purchase" for cid, _ in keys)

    def test_all_leaf_fields_present(self):
        profile = _make_profile()
        flat = _flatten_profile(profile)
        paths = {path for _, path in flat}
        assert "event_id" in paths
        assert "amount" in paths
        assert "user.email" in paths

    def test_skips_pure_object_parents(self):
        fields = [
            {"path": "user", "type": "object", "required": True, "presence_rate": 1.0, "confidence": 1.0},
            {"path": "user.email", "type": "email", "required": True, "presence_rate": 0.99, "confidence": 0.99},
        ]
        profile = _make_profile(fields=fields)
        flat = _flatten_profile(profile)
        paths = {path for _, path in flat}
        assert "user.email" in paths
        assert "user" not in paths  # pure parent skipped


# ---------------------------------------------------------------------------
# Significance classification
# ---------------------------------------------------------------------------

class TestClassifySignificance:
    def test_required_field_removed_is_breaking(self):
        before = {"required": True, "type": "float"}
        assert _classify_significance("removed", before, None) == "breaking"

    def test_optional_field_removed_is_non_breaking(self):
        before = {"required": False, "type": "string"}
        assert _classify_significance("removed", before, None) == "non_breaking"

    def test_added_is_non_breaking(self):
        assert _classify_significance("added", None, {"type": "string"}) == "non_breaking"

    def test_type_widening_is_non_breaking(self):
        before = {"type": "integer"}
        after = {"type": "float"}
        assert _classify_significance("type_changed", before, after) == "non_breaking"

    def test_type_narrowing_is_breaking(self):
        before = {"type": "string"}
        after = {"type": "integer"}
        assert _classify_significance("type_changed", before, after) == "breaking"

    def test_timestamp_format_swap_is_non_breaking(self):
        before = {"type": "timestamp_epoch_ms"}
        after = {"type": "timestamp_iso8601"}
        assert _classify_significance("type_changed", before, after) == "non_breaking"

    def test_enum_value_removed_is_breaking(self):
        before = {"enum_values": ["USD", "EUR", "GBP"]}
        after = {"enum_values": ["USD", "EUR"]}  # GBP removed
        assert _classify_significance("enum_changed", before, after) == "breaking"

    def test_enum_value_added_is_non_breaking(self):
        before = {"enum_values": ["USD", "EUR"]}
        after = {"enum_values": ["USD", "EUR", "GBP"]}
        assert _classify_significance("enum_changed", before, after) == "non_breaking"

    def test_small_presence_change_is_informational(self):
        before = {"presence_rate": 0.90}
        after = {"presence_rate": 0.92}
        assert _classify_significance("presence_changed", before, after) == "informational"

    def test_large_presence_change_is_non_breaking(self):
        before = {"presence_rate": 0.95}
        after = {"presence_rate": 0.60}
        assert _classify_significance("presence_changed", before, after) == "non_breaking"

    def test_pii_added_is_informational(self):
        assert _classify_significance("pii_added", {}, {"pii": ["email"]}) == "informational"


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

class TestDiffProfiles:
    def test_detects_field_removal(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        removals = [c for c in diff.changes if c.change_type == "removed"]
        assert any(c.field_path == "amount" for c in removals)

    def test_removed_required_field_is_breaking(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        amount_removal = next(
            c for c in diff.changes if c.change_type == "removed" and c.field_path == "amount"
        )
        assert amount_removal.significance == "breaking"

    def test_detects_field_added(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        additions = [c for c in diff.changes if c.change_type == "added"]
        assert any(c.field_path == "new_field" for c in additions)

    def test_detects_enum_change(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        enum_changes = [c for c in diff.changes if c.change_type == "enum_changed"]
        assert any(c.field_path == "currency" for c in enum_changes)
        currency_diff = next(c for c in enum_changes if c.field_path == "currency")
        assert "GBP" in (currency_diff.enum_added or [])

    def test_detects_presence_change(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        presence_changes = [c for c in diff.changes if c.change_type == "presence_changed"]
        assert any(c.field_path == "user.email" for c in presence_changes)

    def test_stable_field_not_in_changes(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        changed_paths = {c.field_path for c in diff.changes}
        assert "merchant_id" not in changed_paths

    def test_breaking_count_correct(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        assert diff.breaking_count >= 1  # at least amount removal

    def test_days_between_correct(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        assert diff.days_between == 7

    def test_summary_non_empty(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        assert len(diff.summary) > 10

    def test_identical_profiles_produce_no_changes(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-09")
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")
        history_dir = tmp_schema_dir / "payments" / "history"
        diff = diff_profiles(history_dir / "2026-03-09", history_dir / "2026-03-16")
        assert diff.changes == []
        assert diff.breaking_count == 0

    def test_write_diff_report_creates_file(self, two_snapshots):
        left_path, right_path, _ = two_snapshots
        diff = diff_profiles(left_path, right_path)
        report_path = write_diff_report(diff, left_path)
        assert Path(report_path).exists()
        content = Path(report_path).read_text()
        assert "Breaking" in content or "Non-Breaking" in content or "Informational" in content


# ---------------------------------------------------------------------------
# Trend computation
# ---------------------------------------------------------------------------

class TestComputeTrend:
    def test_insufficient_data_below_min_snapshots(self):
        trend, slope = _compute_trend(["2026-03-01", "2026-03-08"], [0.9, 0.85])
        assert trend == TrendStatus.INSUFFICIENT_DATA
        assert slope is None

    def test_stable_flat_series(self):
        dates = [f"2026-0{i}-01" for i in range(1, 7)]
        rates = [0.90, 0.91, 0.90, 0.89, 0.91, 0.90]
        trend, slope = _compute_trend(dates, rates)
        assert trend == TrendStatus.STABLE
        assert slope is not None
        assert abs(slope) < 0.005

    def test_declining_series(self):
        dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
        rates = [0.90, 0.82, 0.74, 0.66, 0.58]
        trend, slope = _compute_trend(dates, rates)
        assert trend == TrendStatus.DECLINING
        assert slope is not None and slope < 0

    def test_rising_series(self):
        dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
        rates = [0.30, 0.45, 0.60, 0.75, 0.90]
        trend, slope = _compute_trend(dates, rates)
        assert trend == TrendStatus.RISING
        assert slope is not None and slope > 0

    def test_volatile_oscillating_series(self):
        dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
        rates = [0.90, 0.30, 0.85, 0.25, 0.80]
        trend, slope = _compute_trend(dates, rates)
        assert trend == TrendStatus.VOLATILE

    def test_returns_float_slope_for_sufficient_data(self):
        dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
        rates = [0.80, 0.78, 0.76, 0.74]
        trend, slope = _compute_trend(dates, rates)
        assert isinstance(slope, float)


# ---------------------------------------------------------------------------
# Enum growth rate
# ---------------------------------------------------------------------------

class TestEnumGrowthRate:
    def test_returns_none_for_non_enum_field(self):
        series = [("2026-03-01", None), ("2026-03-08", None)]
        assert _compute_enum_growth_rate(series) is None

    def test_zero_growth_for_stable_enum(self):
        series = [
            ("2026-01-01", ["USD", "EUR"]),
            ("2026-02-01", ["USD", "EUR"]),
            ("2026-03-01", ["USD", "EUR"]),
        ]
        rate = _compute_enum_growth_rate(series)
        assert rate == 0.0

    def test_detects_new_enum_values(self):
        series = [
            ("2026-01-01", ["USD"]),
            ("2026-02-01", ["USD", "EUR"]),
            ("2026-03-01", ["USD", "EUR", "GBP"]),
        ]
        rate = _compute_enum_growth_rate(series)
        assert rate is not None and rate > 0

    def test_rate_per_30_days(self):
        # 2 new values over 30 days → rate = 2.0 per 30 days
        series = [
            ("2026-01-01", ["A"]),
            ("2026-02-01", ["A", "B", "C"]),  # 2 new values in 31 days
        ]
        rate = _compute_enum_growth_rate(series)
        assert rate is not None
        assert 1.5 <= rate <= 2.5  # roughly 2 per 30 days


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------

class TestGenerateAlert:
    def test_declining_near_removal_triggers_alert(self):
        alert = _generate_alert(
            "user.loyalty_number", TrendStatus.DECLINING,
            current_rate=0.25, slope=-0.008, enum_growth_rate=None,
        )
        assert alert is not None
        assert "ALERT" in alert
        assert "user.loyalty_number" in alert

    def test_stable_healthy_field_no_alert(self):
        alert = _generate_alert(
            "event_id", TrendStatus.STABLE,
            current_rate=0.99, slope=0.0, enum_growth_rate=None,
        )
        assert alert is None

    def test_rapid_enum_growth_triggers_alert(self):
        alert = _generate_alert(
            "payment.currency", TrendStatus.STABLE,
            current_rate=0.95, slope=0.0, enum_growth_rate=3.5,
        )
        assert alert is not None
        assert "enum" in alert.lower()

    def test_volatile_near_removal_triggers_watch(self):
        alert = _generate_alert(
            "promo_code", TrendStatus.VOLATILE,
            current_rate=0.22, slope=None, enum_growth_rate=None,
        )
        assert alert is not None
        assert "WATCH" in alert or "ALERT" in alert

    def test_fast_declining_field_triggers_alert(self):
        alert = _generate_alert(
            "card.token", TrendStatus.DECLINING,
            current_rate=0.60, slope=-0.015, enum_growth_rate=None,
        )
        assert alert is not None
        assert "fast" in alert.lower() or "dropping" in alert.lower()


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

class TestComputeVelocity:
    def _write_weekly_snapshots(self, output_dir: str, rates_by_date: dict[str, dict[str, float]]) -> None:
        """Write one snapshot per date with per-field presence_rates."""
        for date_str, field_rates in sorted(rates_by_date.items()):
            fields = [
                {"path": path, "type": "string", "required": True,
                 "presence_rate": rate, "confidence": 0.95}
                for path, rate in field_rates.items()
            ]
            profile = _make_profile(stream_name="payments", fields=fields)
            profile["profiled_at"] = f"{date_str}T00:00:00Z"
            write_snapshot(profile, "payments", output_dir, date=date_str)

    def test_empty_snapshots_returns_empty_report(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        report = compute_velocity(output_dir, "payments")
        assert report.snapshot_count == 0
        assert report.fields == []

    def test_single_snapshot_insufficient_data(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")
        report = compute_velocity(output_dir, "payments")
        assert report.snapshot_count == 1
        for fv in report.fields:
            assert fv.trend == TrendStatus.INSUFFICIENT_DATA

    def test_detects_declining_field(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        self._write_weekly_snapshots(output_dir, {
            "2026-01-01": {"loyalty_number": 0.90},
            "2026-02-01": {"loyalty_number": 0.75},
            "2026-03-01": {"loyalty_number": 0.60},
            "2026-04-01": {"loyalty_number": 0.45},
        })
        report = compute_velocity(output_dir, "payments")
        loyalty_fv = next((fv for fv in report.fields if fv.field_path == "loyalty_number"), None)
        assert loyalty_fv is not None
        assert loyalty_fv.trend == TrendStatus.DECLINING

    def test_detects_rising_field(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        self._write_weekly_snapshots(output_dir, {
            "2026-01-01": {"new_feature": 0.20},
            "2026-02-01": {"new_feature": 0.45},
            "2026-03-01": {"new_feature": 0.70},
            "2026-04-01": {"new_feature": 0.90},
        })
        report = compute_velocity(output_dir, "payments")
        fv = next((fv for fv in report.fields if fv.field_path == "new_feature"), None)
        assert fv is not None
        assert fv.trend == TrendStatus.RISING

    def test_alert_generated_for_declining_near_threshold(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        self._write_weekly_snapshots(output_dir, {
            "2026-01-01": {"danger_field": 0.50},
            "2026-02-01": {"danger_field": 0.38},
            "2026-03-01": {"danger_field": 0.28},
            "2026-04-01": {"danger_field": 0.18},
        })
        report = compute_velocity(output_dir, "payments")
        assert len(report.alerts) > 0

    def test_stability_score_perfect_for_stable_stream(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        self._write_weekly_snapshots(output_dir, {
            "2026-01-01": {"event_id": 1.0, "amount": 0.98},
            "2026-02-01": {"event_id": 1.0, "amount": 0.97},
            "2026-03-01": {"event_id": 1.0, "amount": 0.98},
            "2026-04-01": {"event_id": 1.0, "amount": 0.99},
        })
        report = compute_velocity(output_dir, "payments")
        assert report.schema_stability_score >= 0.90

    def test_write_velocity_report_creates_file(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile()
        write_snapshot(profile, "payments", output_dir, date="2026-03-16")
        report = compute_velocity(output_dir, "payments")
        path = write_velocity_report(report, output_dir)
        assert Path(path).exists()
        raw = yaml.safe_load(Path(path).read_text())
        assert raw["stream"] == "payments"

    def test_type_change_recorded_in_velocity(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        for date_str, ftype in [
            ("2026-01-01", "integer"),
            ("2026-02-01", "float"),
            ("2026-03-01", "float"),
            ("2026-04-01", "float"),
        ]:
            fields = [{"path": "score", "type": ftype, "required": True, "presence_rate": 0.90,
                       "confidence": 0.95}]
            profile = _make_profile(stream_name="payments", fields=fields)
            profile["profiled_at"] = f"{date_str}T00:00:00Z"
            write_snapshot(profile, "payments", output_dir, date=date_str)

        report = compute_velocity(output_dir, "payments")
        score_fv = next(fv for fv in report.fields if fv.field_path == "score")
        assert len(score_fv.type_changes) >= 1
        assert "integer" in score_fv.type_changes[0]
        assert "float" in score_fv.type_changes[0]


# ---------------------------------------------------------------------------
# Proposal confidence scoring
# ---------------------------------------------------------------------------

class TestProposalConfidence:
    def test_zero_weeks_low_confidence(self):
        conf = _proposal_confidence(0, TrendStatus.STABLE, [0.9])
        assert conf <= 0.40

    def test_eight_weeks_stable_high_confidence(self):
        conf = _proposal_confidence(8, TrendStatus.STABLE, [0.9] * 8)
        assert conf >= 0.90

    def test_volatile_penalized(self):
        stable_conf = _proposal_confidence(6, TrendStatus.STABLE, [0.9] * 6)
        volatile_conf = _proposal_confidence(6, TrendStatus.VOLATILE, [0.9] * 6)
        assert volatile_conf < stable_conf

    def test_noisy_field_penalized(self):
        clean = _proposal_confidence(6, TrendStatus.STABLE, [0.90, 0.91, 0.89, 0.90, 0.91, 0.90])
        noisy = _proposal_confidence(6, TrendStatus.STABLE, [0.90, 0.50, 0.95, 0.20, 0.85, 0.60])
        assert clean > noisy

    def test_max_confidence_capped_at_095(self):
        conf = _proposal_confidence(100, TrendStatus.STABLE, [0.99] * 20)
        assert conf <= 0.95


# ---------------------------------------------------------------------------
# Weeks of evidence
# ---------------------------------------------------------------------------

class TestWeeksOfEvidence:
    def test_no_dates_returns_zero(self):
        assert _weeks_of_evidence([]) == 0

    def test_single_date_returns_zero(self):
        assert _weeks_of_evidence(["2026-03-16"]) == 0

    def test_seven_days_is_one_week(self):
        assert _weeks_of_evidence(["2026-03-09", "2026-03-16"]) == 1

    def test_28_days_is_four_weeks(self):
        assert _weeks_of_evidence(["2026-01-01", "2026-01-29"]) == 4


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

class TestProposeBaselineUpdates:
    def _write_n_snapshots(
        self, output_dir: str, n: int, field_path: str, rates: list[float], ftype: str = "string"
    ) -> None:
        """Write n weekly snapshots with the given presence rates for a single field."""
        from datetime import timedelta
        base = datetime(2026, 1, 1)
        for i, rate in enumerate(rates[:n]):
            date_str = (base + timedelta(weeks=i)).strftime("%Y-%m-%d")
            fields = [{"path": field_path, "type": ftype, "required": True,
                       "presence_rate": rate, "confidence": 0.95}]
            profile = _make_profile(stream_name="test", fields=fields)
            profile["profiled_at"] = f"{date_str}T00:00:00Z"
            write_snapshot(profile, "test", output_dir, date=date_str)

    def test_no_proposals_for_stable_stream(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        self._write_n_snapshots(output_dir, 6, "event_id", [1.0] * 6)
        report = propose_baseline_updates(output_dir, "test", min_weeks=4)
        # No schema.yaml → proposals based on velocity only
        # Stable required field with high presence → no changes needed
        demotions = [p for p in report.proposals if p.action == ProposalAction.DEMOTE_TO_OPTIONAL]
        assert len(demotions) == 0

    def test_remove_proposal_for_declining_below_threshold(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        # Write a schema.yaml so proposals can reference it
        schema_yaml = (
            "stream: test\nversion: '1.0.0'\n"
            "inferred_at: '2026-01-01T00:00:00Z'\n"
            "inference_confidence: 0.9\n"
            "fields:\n"
            "  - path: dying_field\n    type: string\n    required: true\n"
            "    nullable: false\n    presence_rate: 0.90\n    confidence: 0.95\n"
        )
        schema_dir = tmp_schema_dir / "test"
        schema_dir.mkdir(parents=True, exist_ok=True)
        (schema_dir / "schema.yaml").write_text(schema_yaml)

        # Write declining snapshots below removal threshold
        self._write_n_snapshots(
            output_dir, 6, "dying_field",
            [0.90, 0.60, 0.35, 0.20, 0.12, 0.08],  # well below 0.20 by the end
        )
        report = propose_baseline_updates(output_dir, "test", min_weeks=3)
        removals = [p for p in report.proposals if p.action == ProposalAction.REMOVE_FIELD]
        assert len(removals) >= 1
        assert removals[0].field_path == "dying_field"

    def test_summary_populated(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile(stream_name="test")
        write_snapshot(profile, "test", output_dir, date="2026-03-16")
        report = propose_baseline_updates(output_dir, "test")
        assert len(report.summary) > 5

    def test_write_proposal_report_creates_file(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile(stream_name="test")
        write_snapshot(profile, "test", output_dir, date="2026-03-16")
        report = propose_baseline_updates(output_dir, "test")
        path = write_proposal_report(report, output_dir)
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "Baseline Update Proposals" in content

    def test_auto_appliable_subset_of_all(self, tmp_schema_dir):
        output_dir = str(tmp_schema_dir)
        profile = _make_profile(stream_name="test")
        for _i, date in enumerate(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]):
            write_snapshot(profile, "test", output_dir, date=date)
        report = propose_baseline_updates(output_dir, "test")
        # auto_appliable ⊆ proposals
        auto_ids = {id(p) for p in report.auto_appliable}
        all_ids = {id(p) for p in report.proposals}
        assert auto_ids <= all_ids
