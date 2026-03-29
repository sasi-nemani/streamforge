import json
import os
import tempfile
from pathlib import Path

import pytest

from streamforge.sampler import (
    flatten_nested,
    get_all_field_paths,
    load_events_from_folder,
    reservoir_sample,
    split_by_quality,
    streaming_reservoir_sample_from_folder,
    streaming_resilient_sample_from_folder,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_reservoir_sampling_correct_size():
    events = [{"id": i} for i in range(1000)]
    sample = reservoir_sample(events, 100)
    assert len(sample) == 100


def test_reservoir_sampling_returns_all_when_small():
    events = [{"id": i} for i in range(50)]
    sample = reservoir_sample(events, 500)
    assert len(sample) == 50


def test_flatten_nested_handles_arrays():
    obj = {"user": {"tags": ["a", "b", "c"]}}
    flat = flatten_nested(obj)
    assert "user.tags" in flat
    assert isinstance(flat["user.tags"], list)


def test_flatten_nested_deep_nesting():
    obj = {"a": {"b": {"c": {"d": 42}}}}
    flat = flatten_nested(obj)
    assert flat["a.b.c.d"] == 42


def test_flatten_nested_array_of_dicts():
    obj = {"passengers": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}
    flat = flatten_nested(obj)
    assert "passengers" in flat
    # First element flattened with [] prefix
    assert "passengers[].name" in flat
    assert flat["passengers[].name"] == "Alice"


def test_load_events_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "test.ndjson"
        f.write_text(
            '{"id": 1}\n'
            'not json\n'
            '{"id": 2}\n'
            '\n'
            '{"id": 3}\n'
        )
        events = load_events_from_folder(tmpdir)
    assert len(events) == 3
    assert all("id" in e for e in events)


def test_load_events_sorted_by_filename():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in [3, 1, 2]:
            f = Path(tmpdir) / f"events_{i:04d}.ndjson"
            f.write_text(f'{{"order": {i}}}\n')
        events = load_events_from_folder(tmpdir)
    # Should be in filename-sorted order
    assert [e["order"] for e in events] == [1, 2, 3]


def test_get_all_field_paths_presence_rates():
    events = [
        {"a": 1, "b": 2},
        {"a": 2},
        {"a": 3, "b": 4},
        {"a": 4},
    ]
    values, rates = get_all_field_paths(events)
    assert rates["a"] == 1.0
    assert rates["b"] == 0.5
    assert set(values["a"]) == {1, 2, 3, 4}


# ── split_by_quality tests ────────────────────────────────────────────────────

def test_split_by_quality_separates_partial():
    events = [
        {"id": 1},
        {"id": 2, "_partial_extract": True},
        {"id": 3},
        {"id": 4, "_partial_extract": True},
    ]
    clean, partial = split_by_quality(events)
    assert len(clean) == 2
    assert len(partial) == 2
    assert all("_partial_extract" not in e for e in clean)
    assert all(e.get("_partial_extract") for e in partial)


def test_split_by_quality_all_clean():
    events = [{"id": i} for i in range(5)]
    clean, partial = split_by_quality(events)
    assert len(clean) == 5
    assert len(partial) == 0


def test_split_by_quality_all_partial():
    events = [{"id": i, "_partial_extract": True} for i in range(5)]
    clean, partial = split_by_quality(events)
    assert len(clean) == 0
    assert len(partial) == 5


def test_split_by_quality_preserves_other_fields():
    events = [
        {"a": 1, "b": 2},
        {"a": 3, "_partial_extract": True, "c": 4},
    ]
    clean, partial = split_by_quality(events)
    assert clean[0] == {"a": 1, "b": 2}
    assert partial[0] == {"a": 3, "_partial_extract": True, "c": 4}


def test_split_by_quality_empty():
    clean, partial = split_by_quality([])
    assert clean == []
    assert partial == []


# ── P1 regression: streaming reservoir sampler ──────────────────────────────


def test_streaming_reservoir_sample_bounds_memory(tmp_path):
    """P1 regression: streaming sampler holds at most n events in memory."""
    # Write 1000 events to folder
    ndjson = tmp_path / "events.ndjson"
    lines = [json.dumps({"id": i}) for i in range(1000)]
    ndjson.write_text("\n".join(lines))

    # Sample 50 — should return exactly 50, never load all 1000
    sample, total = streaming_reservoir_sample_from_folder(str(tmp_path), n=50)
    assert len(sample) == 50
    assert total == 1000


def test_streaming_reservoir_sample_small_file(tmp_path):
    """When file has fewer events than n, all are returned."""
    ndjson = tmp_path / "events.ndjson"
    lines = [json.dumps({"id": i}) for i in range(10)]
    ndjson.write_text("\n".join(lines))

    sample, total = streaming_reservoir_sample_from_folder(str(tmp_path), n=500)
    assert len(sample) == 10
    assert total == 10


def test_streaming_reservoir_sample_empty_folder(tmp_path):
    """Empty folder returns empty sample."""
    sample, total = streaming_reservoir_sample_from_folder(str(tmp_path), n=50)
    assert sample == []
    assert total == 0


def test_streaming_resilient_separates_clean_and_partial(tmp_path):
    """Streaming resilient sampler separates clean and partial events."""
    ndjson = tmp_path / "events.ndjson"
    lines = [
        '{"id": 1, "name": "clean"}',
        'NOT_JSON but has "id": 2',  # will be partial extracted
        '{"id": 3, "name": "also_clean"}',
    ]
    ndjson.write_text("\n".join(lines))

    clean, partial, total, stats = streaming_resilient_sample_from_folder(str(tmp_path), n=100)
    assert len(clean) == 2
    assert stats["parsed_clean"] == 2
    assert total == len(clean) + len(partial)
