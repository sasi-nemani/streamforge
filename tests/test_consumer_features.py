"""Tests for consumer-facing features: Markdown export, enum distributions, sliding window.

Stripe data engineering validation: can consumers get meaningful,
simple-to-read outputs from this system?
"""

import json
import time
from collections import deque
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MARKDOWN DATA DICTIONARY
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkdownExport:
    """Consumers want a one-page data dictionary, not YAML or JSON Schema."""

    def test_markdown_export_exists(self):
        from streamforge.exporters.markdown import schema_to_markdown
        assert callable(schema_to_markdown)

    def test_markdown_has_table_header(self):
        from streamforge.exporters.markdown import schema_to_markdown
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="events.payments", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=500,
            fields=[
                FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                            required=True, presence_rate=1.0, confidence=0.9,
                            value_stats={"min": 1.49, "max": 996.92, "cardinality": 500}),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        md = schema_to_markdown(schema)
        assert "| Field" in md
        assert "| Type" in md
        assert "amount" in md

    def test_markdown_shows_enums(self):
        from streamforge.exporters.markdown import schema_to_markdown
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="status", path="status", field_type=FieldType.STRING,
                            required=True, presence_rate=1.0, confidence=0.9,
                            enum_values=["pending", "completed", "failed"]),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        md = schema_to_markdown(schema)
        assert "pending" in md
        assert "completed" in md

    def test_markdown_shows_value_ranges(self):
        from streamforge.exporters.markdown import schema_to_markdown
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                            required=True, presence_rate=1.0, confidence=0.9,
                            value_stats={"min": 1.49, "max": 996.92, "cardinality": 500}),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        md = schema_to_markdown(schema)
        assert "1.49" in md
        assert "996.92" in md

    def test_markdown_shows_pii(self):
        from streamforge.exporters.markdown import schema_to_markdown
        from streamforge.models import FieldSchema, FieldType, InferredSchema, PIICategory

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="email", path="email", field_type=FieldType.EMAIL,
                            required=True, presence_rate=1.0, confidence=0.9,
                            pii_categories=[PIICategory.EMAIL]),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        md = schema_to_markdown(schema)
        assert "email" in md.lower()
        assert "PII" in md or "pii" in md

    def test_markdown_auto_export(self, tmp_path):
        """write_schema_with_exports should produce a .md file."""
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema_with_exports

        schema = InferredSchema(
            stream_name="test_stream", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        paths = write_schema_with_exports(schema, str(tmp_path))
        assert "markdown" in paths
        assert Path(paths["markdown"]).exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ENUM DISTRIBUTION PERCENTAGES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnumDistribution:
    """Consumers need to know not just WHAT values exist, but HOW OFTEN."""

    def test_compute_value_stats_includes_distribution(self):
        from streamforge.sampler import compute_value_stats
        values = ["USD", "EUR", "GBP", "USD", "EUR", "USD", "USD", "EUR", "GBP", "JPY"]
        stats = compute_value_stats(values, "string")
        assert "distribution" in stats
        assert stats["distribution"]["USD"] == 0.4  # 4/10
        assert stats["distribution"]["EUR"] == 0.3  # 3/10

    def test_distribution_only_for_low_cardinality(self):
        """Don't compute distribution for high-cardinality fields (e.g. user_id)."""
        from streamforge.sampler import compute_value_stats
        values = [f"user_{i}" for i in range(200)]
        stats = compute_value_stats(values, "string")
        assert "distribution" not in stats  # too many unique values


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TIME-BASED SLIDING WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeSlidingWindow:
    """Window should evict by time, not just count. Configurable per topic."""

    def test_time_window_evicts_old_events(self):
        from streamforge.detector.window import EventWindow

        w = EventWindow(capacity=10000, max_age_seconds=2)
        w.add([{"id": "old", "ts": 1}])
        time.sleep(2.5)
        w.add([{"id": "new", "ts": 2}])
        w.evict_expired()
        # Old event should be gone
        ids = [e.get("id") for e in w.events]
        assert "new" in ids
        assert "old" not in ids

    def test_time_window_keeps_recent(self):
        from streamforge.detector.window import EventWindow

        w = EventWindow(capacity=10000, max_age_seconds=60)
        w.add([{"id": "recent"}])
        w.evict_expired()
        assert len(w) == 1

    def test_time_window_default_no_eviction(self):
        """When max_age_seconds=0 (default), no time eviction — count-based only."""
        from streamforge.detector.window import EventWindow

        w = EventWindow(capacity=5)
        for i in range(10):
            w.add([{"id": i}])
        assert len(w) == 5  # count-based eviction still works

    def test_sample_does_not_materialize_full_window(self):
        """sample(200) from a 10K window should NOT allocate 10K elements."""
        import sys
        from streamforge.detector.window import EventWindow

        w = EventWindow(capacity=10000)
        w.add([{"id": i, "data": "x" * 100} for i in range(10000)])
        assert len(w) == 10000

        # Sample 200 — should return exactly 200, not 10000
        result = w.sample(200)
        assert len(result) == 200

        # Each result element should be a dict, not a tuple
        assert isinstance(result[0], dict)
        assert "id" in result[0]

    def test_sample_uniform_distribution(self):
        """Reservoir sampling must give uniform probability to all events."""
        from collections import Counter
        from streamforge.detector.window import EventWindow

        w = EventWindow(capacity=1000)
        w.add([{"id": i} for i in range(1000)])

        # Sample 100 events 1000 times and check distribution
        counts = Counter()
        for _ in range(1000):
            for e in w.sample(100):
                counts[e["id"]] += 1

        # Each of the 1000 events should be sampled ~100 times (100/1000 * 1000 = 100)
        # Allow 50% variance for randomness
        for event_id in range(1000):
            assert 30 < counts.get(event_id, 0) < 200, (
                f"Event {event_id} sampled {counts.get(event_id, 0)} times, expected ~100"
            )

    def test_window_config_in_stream_policy(self):
        """stream_policy.yaml should support window_max_age_seconds."""
        import yaml
        policy = {
            "stream": "events.payments",
            "sample_size": 200,
            "poll_interval_seconds": 30,
            "window_capacity": 5000,
            "window_max_age_seconds": 300,  # 5 minutes
        }
        text = yaml.dump(policy)
        loaded = yaml.safe_load(text)
        assert loaded["window_max_age_seconds"] == 300
        assert loaded["window_capacity"] == 5000
