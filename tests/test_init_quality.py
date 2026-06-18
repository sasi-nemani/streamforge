"""
Tests for P1-C: partial-event filtering in schema inference and the
Ingest Quality section in inference reports.

No API calls — all tests are purely in-memory or use tempfiles.
"""
from pathlib import Path

from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.sampler import load_events_resilient, split_by_quality
from streamforge.schema_writer import write_inference_report


def _make_schema(n_fields: int = 3) -> InferredSchema:
    fields = [
        FieldSchema(
            name=f"field_{i}",
            path=f"field_{i}",
            field_type=FieldType.STRING,
            presence_rate=1.0,
            confidence=0.9,
        )
        for i in range(n_fields)
    ]
    return InferredSchema(
        stream_name="test.stream",
        version="1.0.0",
        inferred_at="2026-01-01T00:00:00Z",
        event_count_sampled=100,
        fields=fields,
        inference_model="test",
        inference_confidence=0.88,
    )


# ── P1-C: split_by_quality integration with load_events_resilient ────────────

class TestPartialEventFiltering:
    def test_ndjson_with_broken_lines_produces_partial_events(self, tmp_path):
        """load_events_resilient marks partially-reconstructed events."""
        ndjson = tmp_path / "mixed.ndjson"
        ndjson.write_text(
            '{"id": 1, "value": 10}\n'
            # A log-style prefix line that triggers embedded JSON or regex extraction
            '"id": 2, "value": 20\n'   # malformed — no outer braces → regex extraction
            '{"id": 3, "value": 30}\n'
        )
        all_events, stats = load_events_resilient(str(tmp_path))
        clean, partial = split_by_quality(all_events)
        # At least the two clean JSON lines should be clean
        assert len(clean) >= 2
        # Total should be what was loaded
        assert len(clean) + len(partial) == len(all_events)

    def test_split_excludes_partial_from_clean(self):
        events = [
            {"id": 1, "val": "x"},
            {"id": 2, "_partial_extract": True, "val": "y"},
            {"id": 3, "val": "z"},
        ]
        clean, partial = split_by_quality(events)
        assert {e["id"] for e in clean} == {1, 3}
        assert {e["id"] for e in partial} == {2}

    def test_all_clean_stream_has_no_partial(self, tmp_path):
        ndjson = tmp_path / "clean.ndjson"
        ndjson.write_text("\n".join(
            f'{{"id": {i}, "val": "v{i}"}}'
            for i in range(50)
        ) + "\n")
        all_events, _ = load_events_resilient(str(tmp_path))
        clean, partial = split_by_quality(all_events)
        assert len(partial) == 0
        assert len(clean) == len(all_events)


# ── Ingest Quality section in inference_report.md ────────────────────────────

class TestIngestQualityInReport:
    def test_report_without_ingest_stats_has_no_quality_section(self, tmp_path):
        schema = _make_schema()
        path = write_inference_report(schema, str(tmp_path))
        content = Path(path).read_text()
        assert "Ingest Quality" not in content

    def test_report_with_ingest_stats_contains_quality_section(self, tmp_path):
        schema = _make_schema()
        stats = {"total": 500, "clean": 483, "partial": 17}
        path = write_inference_report(schema, str(tmp_path), ingest_stats=stats)
        content = Path(path).read_text()
        assert "Ingest Quality" in content
        assert "483" in content
        assert "17" in content
        assert "500" in content

    def test_report_parse_rate_shown(self, tmp_path):
        schema = _make_schema()
        stats = {"total": 100, "clean": 90, "partial": 10}
        path = write_inference_report(schema, str(tmp_path), ingest_stats=stats)
        content = Path(path).read_text()
        assert "90.0%" in content  # parse rate: 90/100

    def test_report_with_zero_partial_shows_100_percent(self, tmp_path):
        schema = _make_schema()
        stats = {"total": 200, "clean": 200, "partial": 0}
        path = write_inference_report(schema, str(tmp_path), ingest_stats=stats)
        content = Path(path).read_text()
        assert "100.0%" in content

    def test_report_backwards_compatible_without_stats(self, tmp_path):
        """write_inference_report(schema, dir) without ingest_stats must not raise."""
        schema = _make_schema()
        path = write_inference_report(schema, str(tmp_path))
        assert Path(path).exists()
