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
