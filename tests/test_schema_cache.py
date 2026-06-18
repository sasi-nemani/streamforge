"""Structural-fingerprint cache: identical shapes skip the LLM."""
from __future__ import annotations

import random

from streamforge.models import FieldSchema, FieldType
from streamforge.schema_cache import (
    SchemaFingerprintCache,
    cache_enabled,
    structural_fingerprint,
)


def _fields() -> list[FieldSchema]:
    return [
        FieldSchema(name="id", path="id", field_type=FieldType.UUID, required=True),
        FieldSchema(name="email", path="user.email", field_type=FieldType.EMAIL, required=True),
        FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT, required=False),
    ]


def test_fingerprint_is_stable_and_order_independent():
    f = _fields()
    shuffled = list(f)
    random.Random(7).shuffle(shuffled)
    assert structural_fingerprint(f) == structural_fingerprint(shuffled)


def test_fingerprint_changes_on_type_change():
    f = _fields()
    fp0 = structural_fingerprint(f)
    changed = list(f)
    changed[2] = changed[2].model_copy(update={"field_type": FieldType.STRING})
    assert structural_fingerprint(changed) != fp0


def test_fingerprint_changes_on_added_field():
    f = _fields()
    fp0 = structural_fingerprint(f)
    f2 = [*f, FieldSchema(name="new", path="new", field_type=FieldType.INTEGER)]
    assert structural_fingerprint(f2) != fp0


def test_cache_roundtrips_through_disk(tmp_path):
    p = tmp_path / "sc.json"
    cache = SchemaFingerprintCache.load(p)
    fp = structural_fingerprint(_fields())
    assert cache.get(fp) is None
    cache.put(fp, _fields())
    cache.save(p)

    reloaded = SchemaFingerprintCache.load(p)
    got = reloaded.get(fp)
    assert got is not None
    assert [x.field_type for x in got] == [x.field_type for x in _fields()]


def test_corrupt_entry_is_treated_as_miss():
    cache = SchemaFingerprintCache({"deadbeef": [{"not": "a valid field"}]})
    assert cache.get("deadbeef") is None  # no exception, just a miss


def test_load_missing_file_is_empty(tmp_path):
    cache = SchemaFingerprintCache.load(tmp_path / "does_not_exist.json")
    assert len(cache) == 0


def test_cache_can_be_disabled(monkeypatch):
    monkeypatch.setenv("STREAMFORGE_SCHEMA_CACHE", "0")
    assert cache_enabled() is False
    monkeypatch.setenv("STREAMFORGE_SCHEMA_CACHE", "1")
    assert cache_enabled() is True


def test_infer_sub_schema_cache_hit_skips_llm(monkeypatch):
    """A fingerprint cache hit must short-circuit before any LLM call."""
    from streamforge import inference

    cached = [FieldSchema(name="x", path="x", field_type=FieldType.STRING)]

    class _HitCache:
        def get(self, _fp):
            return cached

        def put(self, _fp, _fields):
            pass

        def save(self, *_a):
            pass

    monkeypatch.setattr(
        "streamforge.schema_cache.SchemaFingerprintCache.load",
        staticmethod(lambda path=None: _HitCache()),
    )

    def _boom(**_kwargs):
        raise AssertionError("LLM (infer_schema) must not be called on a cache hit")

    monkeypatch.setattr(inference, "infer_schema", _boom)

    from streamforge import metrics
    metrics._reset_for_testing()

    # 60 events (well above the LLM threshold) so only the cache prevents an LLM call.
    events = [{"a": i, "b": f"v{i}"} for i in range(60)]
    sub = inference.infer_sub_schema(
        cluster_id="c",
        events=events,
        detection_method="single",
        total_stream_events=60,
        api_key="dummy",
    )
    assert sub.inference_source == "fingerprint_cache"
    assert metrics.SCHEMA_CACHE_HITS.value == 1.0
    assert metrics.LLM_CALLS.value == 0.0


def test_metrics_snapshot_has_inference_source_split():
    from streamforge.metrics import metrics_snapshot

    snap = metrics_snapshot()
    for key in (
        "inference_llm_calls_total",
        "schema_cache_hits_total",
        "inference_statistical_total",
    ):
        assert key in snap


def test_offline_mode_skips_llm_without_key(monkeypatch):
    """offline=True must use the deterministic statistical path and never call
    the LLM — even with enough events to otherwise trigger it, and no API key."""
    from streamforge import inference

    # Disable the fingerprint cache so we exercise the statistical branch directly.
    monkeypatch.setenv("STREAMFORGE_SCHEMA_CACHE", "0")

    def _boom(**_kwargs):
        raise AssertionError("LLM must not be called in offline mode")

    monkeypatch.setattr(inference, "infer_schema", _boom)

    events = [{"amount": float(i), "currency": "USD", "ok": True} for i in range(60)]
    sub = inference.infer_sub_schema(
        cluster_id="c",
        events=events,
        detection_method="single",
        total_stream_events=60,
        api_key="",  # no key
        offline=True,
    )
    assert sub.inference_source == "statistical"
    assert {f.path for f in sub.fields} == {"amount", "currency", "ok"}
