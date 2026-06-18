"""End-to-end lifecycle test: init → plan (clean) → inject drift → plan (block).

This tests the module SEAMS — the integration points that unit tests miss.
A Stripe engineer will ask: "does it actually work end-to-end?"
"""

import json

import pytest


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with sample event data."""
    # Create clean events
    events_dir = tmp_path / "events" / "payments" / "stream"
    events_dir.mkdir(parents=True)

    clean_events = []
    for i in range(200):
        clean_events.append(json.dumps({
            "event_id": f"evt-{i:04d}",
            "event_type": "payment.completed",
            "timestamp": 1775000000000 + i * 1000,
            "amount": round(10.0 + i * 0.5, 2),
            "currency": "USD",
            "status": "completed",
            "user_email": f"user{i}@example.com",
            "merchant_id": f"merch_{i % 5}",
        }))

    (events_dir / "events_0001.ndjson").write_text("\n".join(clean_events[:100]))
    (events_dir / "events_0002.ndjson").write_text("\n".join(clean_events[100:]))

    # Create drifted events (amount removed, card_last_four added)
    drift_dir = tmp_path / "events" / "payments" / "drifted"
    drift_dir.mkdir(parents=True)

    drifted_events = []
    for i in range(100):
        drifted_events.append(json.dumps({
            "event_id": f"evt-d{i:04d}",
            "event_type": "payment.completed",
            "timestamp": f"2026-04-01T{10+i//60:02d}:{i%60:02d}:00Z",  # ISO8601 (type change)
            # "amount" intentionally missing (field removed)
            "amount_minor_units": 1000 + i * 50,  # new field
            "currency": "USD",
            "status": "completed",
            "user_email": f"user{i}@example.com",
            "merchant_id": f"merch_{i % 5}",
            "card_last_four": f"{1000 + i}",  # new PII field
        }))

    (drift_dir / "events_drift.ndjson").write_text("\n".join(drifted_events))

    return tmp_path


class TestE2ELifecycle:
    """Full init → plan → drift → plan lifecycle."""

    def test_init_produces_valid_schema(self, workspace):
        """Init on clean data produces a schema with correct field types."""
        from streamforge.cli.schema_cmd import profile

        stream_path = str(workspace / "events" / "payments" / "stream")

        # Profile (no LLM needed)
        profile(
            stream_path=stream_path,
            sample_size=100,
            top=30,
            show_values=False,
        )

        # Verify init can run (uses statistical inference)
        from streamforge.inference import infer_sub_schema
        from streamforge.sampler import get_all_field_paths
        from streamforge.sampler import load_events_resilient as load_events

        events, _ = load_events(stream_path)
        field_stats, presence = get_all_field_paths(events[:100])

        sub = infer_sub_schema(
            cluster_id="payment.completed",
            events=events[:100],
            detection_method="single",
            total_stream_events=100,
            api_key="dummy",  # will fall through to statistical
        )

        assert len(sub.fields) >= 6
        # Check field types are reasonable
        field_types = {f.path: f.field_type.value for f in sub.fields}
        assert "event_id" in field_types
        assert field_types.get("timestamp") in ("timestamp_epoch_ms", "integer")
        assert field_types.get("currency") == "string"

    def test_plan_clean_returns_no_drift(self, workspace):
        """Plan against clean data with matching schema = no drift."""
        from streamforge.drift_detector import detect_drift
        from streamforge.inference import infer_sub_schema
        from streamforge.models import InferredSchema
        from streamforge.sampler import load_events_resilient as load_events
        from streamforge.sampler import reservoir_sample

        events, _ = load_events(str(workspace / "events" / "payments" / "stream"))
        sub = infer_sub_schema(
            cluster_id="payment.completed",
            events=events[:100],
            detection_method="single",
            total_stream_events=100,
            api_key="dummy",
        )

        schema = InferredSchema(
            stream_name="payments",
            version="1.0.0",
            inferred_at="2026-04-01T00:00:00Z",
            event_count_sampled=100,
            fields=sub.fields,
            inference_model="statistical",
            inference_confidence=0.8,
        )

        # Plan against same clean data
        sample = reservoir_sample(events[100:], 50)
        report = detect_drift(schema, sample, "payments")

        # Should be clean (or only minor presence variations)
        if report is not None:
            assert report.highest_tier.value <= 2, (
                f"Unexpected Tier-3 drift on clean data: "
                f"{[(d.field_path, d.drift_type) for d in report.drifts]}"
            )

    def test_plan_drifted_detects_breaking_changes(self, workspace):
        """Plan against drifted data catches field removal and PII."""
        from streamforge.drift_detector import detect_drift
        from streamforge.inference import infer_sub_schema
        from streamforge.models import InferredSchema
        from streamforge.sampler import load_events_resilient as load_events

        # Build baseline from clean data
        clean_events, _ = load_events(str(workspace / "events" / "payments" / "stream"))
        sub = infer_sub_schema(
            cluster_id="payment.completed",
            events=clean_events[:100],
            detection_method="single",
            total_stream_events=100,
            api_key="dummy",
        )
        schema = InferredSchema(
            stream_name="payments",
            version="1.0.0",
            inferred_at="2026-04-01T00:00:00Z",
            event_count_sampled=100,
            fields=sub.fields,
            inference_model="statistical",
            inference_confidence=0.8,
        )

        # Load drifted data
        drifted, _ = load_events(str(workspace / "events" / "payments" / "drifted"))
        report = detect_drift(schema, drifted, "payments")

        assert report is not None, "Expected drift but got None"
        assert report.highest_tier.value == 3, (
            f"Expected Tier 3, got Tier {report.highest_tier.value}"
        )

        drift_types = {d.field_path: d.drift_type for d in report.drifts}
        # amount was removed
        assert "amount" in drift_types, f"Expected 'amount' field_removed, got: {drift_types}"
        # card_last_four is new PII
        assert "card_last_four" in drift_types, f"Expected 'card_last_four' drift, got: {drift_types}"
