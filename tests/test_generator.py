"""
Tests for Feature 1 (nested structure tagging) and Feature 2 (example event generation).
All in-memory — no API calls, no filesystem writes.
"""
import json

import pytest

from streamforge.generator import _random_value, _set_nested, generate_events
from streamforge.models import FieldSchema, FieldType, InferredSchema, PIICategory
from streamforge.schema_writer import _inject_parent_objects

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_schema(fields: list[FieldSchema], stream_name: str = "test.stream") -> InferredSchema:
    return InferredSchema(
        stream_name=stream_name,
        version="1.0.0",
        inferred_at="2026-03-16T00:00:00Z",
        event_count_sampled=100,
        fields=fields,
        inference_model="test",
        inference_confidence=0.95,
    )


def _field(path: str, ftype: FieldType, required: bool = True,
           presence_rate: float = 1.0, nullable: bool = False,
           enum_values=None, pii=None) -> FieldSchema:
    return FieldSchema(
        name=path.split(".")[-1],
        path=path,
        field_type=ftype,
        required=required,
        nullable=nullable,
        presence_rate=presence_rate,
        confidence=0.95,
        enum_values=enum_values,
        pii_categories=pii or [],
    )


# ── _inject_parent_objects ────────────────────────────────────────────────────

class TestInjectParentObjects:
    def test_flat_fields_unchanged(self):
        fields = [
            _field("event_id", FieldType.UUID),
            _field("amount",   FieldType.FLOAT),
        ]
        result = _inject_parent_objects(fields)
        assert len(result) == 2
        assert result[0].path == "event_id"
        assert result[1].path == "amount"

    def test_injects_object_for_dot_path(self):
        fields = [
            _field("user.email", FieldType.EMAIL),
            _field("user.name",  FieldType.STRING),
        ]
        result = _inject_parent_objects(fields)
        paths = [f.path for f in result]
        assert "user" in paths
        user_field = next(f for f in result if f.path == "user")
        assert user_field.field_type == FieldType.OBJECT

    def test_parent_inserted_before_first_child(self):
        fields = [
            _field("amount",    FieldType.FLOAT),
            _field("user.email", FieldType.EMAIL),
            _field("user.name",  FieldType.STRING),
        ]
        result = _inject_parent_objects(fields)
        paths = [f.path for f in result]
        user_idx = paths.index("user")
        email_idx = paths.index("user.email")
        assert user_idx < email_idx

    def test_does_not_duplicate_existing_parent(self):
        fields = [
            _field("user",       FieldType.OBJECT),
            _field("user.email", FieldType.EMAIL),
        ]
        result = _inject_parent_objects(fields)
        user_entries = [f for f in result if f.path == "user"]
        assert len(user_entries) == 1

    def test_injects_array_type_for_bracket_paths(self):
        fields = [
            _field("items[].id",   FieldType.UUID),
            _field("items[].name", FieldType.STRING),
        ]
        result = _inject_parent_objects(fields)
        paths = [f.path for f in result]
        assert "items" in paths
        items_field = next(f for f in result if f.path == "items")
        assert items_field.field_type == FieldType.ARRAY

    def test_deeply_nested_injects_all_parents(self):
        fields = [_field("a.b.c", FieldType.STRING)]
        result = _inject_parent_objects(fields)
        paths = [f.path for f in result]
        assert "a" in paths
        assert "a.b" in paths
        assert "a.b.c" in paths

    def test_notes_list_direct_children(self):
        fields = [
            _field("user.email", FieldType.EMAIL),
            _field("user.name",  FieldType.STRING),
        ]
        result = _inject_parent_objects(fields)
        user = next(f for f in result if f.path == "user")
        assert "email" in (user.notes or "")
        assert "name"  in (user.notes or "")

    def test_presence_rate_derived_from_children(self):
        fields = [
            _field("user.email", FieldType.EMAIL, presence_rate=0.8),
            _field("user.name",  FieldType.STRING, presence_rate=0.6),
        ]
        result = _inject_parent_objects(fields)
        user = next(f for f in result if f.path == "user")
        # Should be min of children
        assert user.presence_rate == pytest.approx(0.6, abs=0.01)

    def test_empty_fields_list(self):
        assert _inject_parent_objects([]) == []

    def test_multiple_top_level_objects(self):
        fields = [
            _field("user.id",     FieldType.UUID),
            _field("payment.amount", FieldType.FLOAT),
        ]
        result = _inject_parent_objects(fields)
        paths = [f.path for f in result]
        assert "user" in paths
        assert "payment" in paths


# ── _set_nested ───────────────────────────────────────────────────────────────

class TestSetNested:
    def test_flat_path(self):
        obj = {}
        _set_nested(obj, "amount", 10.5)
        assert obj == {"amount": 10.5}

    def test_dot_notation_creates_nested_dict(self):
        obj = {}
        _set_nested(obj, "user.email", "x@y.com")
        assert obj == {"user": {"email": "x@y.com"}}

    def test_dot_notation_merges_siblings(self):
        obj = {}
        _set_nested(obj, "user.email", "x@y.com")
        _set_nested(obj, "user.name", "Alice")
        assert obj["user"]["email"] == "x@y.com"
        assert obj["user"]["name"] == "Alice"

    def test_deeply_nested(self):
        obj = {}
        _set_nested(obj, "a.b.c.d", 42)
        assert obj["a"]["b"]["c"]["d"] == 42

    def test_array_child_path(self):
        obj = {}
        _set_nested(obj, "items[].id", "uuid-1")
        assert isinstance(obj["items"], list)
        assert obj["items"][0]["id"] == "uuid-1"

    def test_array_child_merges_siblings(self):
        obj = {}
        _set_nested(obj, "items[].id",   "uuid-1")
        _set_nested(obj, "items[].name", "foo")
        assert obj["items"][0]["id"]   == "uuid-1"
        assert obj["items"][0]["name"] == "foo"

    def test_leaf_array_path(self):
        obj = {}
        _set_nested(obj, "tags[]", "alpha")
        assert obj["tags"] == ["alpha"]

    def test_leaf_array_with_list_value(self):
        obj = {}
        _set_nested(obj, "tags[]", ["a", "b", "c"])
        assert obj["tags"] == ["a", "b", "c"]

    def test_intermediate_array_then_field(self):
        obj = {}
        _set_nested(obj, "passengers[].name", "Alice")
        assert obj["passengers"][0]["name"] == "Alice"


# ── _random_value ─────────────────────────────────────────────────────────────

class TestRandomValue:
    def test_uuid_is_valid_format(self):
        import re
        v = _random_value(FieldType.UUID)
        assert re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', v)

    def test_email_contains_at(self):
        v = _random_value(FieldType.EMAIL)
        assert "@" in v
        assert "." in v.split("@")[1]

    def test_timestamp_epoch_ms_is_large_int(self):
        v = _random_value(FieldType.TIMESTAMP_EPOCH_MS)
        assert isinstance(v, int)
        assert 1_000_000_000_000 <= v <= 9_999_999_999_999

    def test_timestamp_iso8601_parseable(self):
        v = _random_value(FieldType.TIMESTAMP_ISO8601)
        assert isinstance(v, str)
        # Should be parseable — ends with Z
        assert "T" in v

    def test_boolean_is_bool(self):
        v = _random_value(FieldType.BOOLEAN)
        assert isinstance(v, bool)

    def test_enum_values_respected(self):
        choices = ["USD", "EUR", "GBP"]
        for _ in range(20):
            v = _random_value(FieldType.STRING, enum_values=choices)
            assert v in choices

    def test_null_type_returns_none(self):
        assert _random_value(FieldType.NULL) is None

    def test_float_is_numeric(self):
        v = _random_value(FieldType.FLOAT)
        assert isinstance(v, float)

    def test_date_matches_format(self):
        import re
        v = _random_value(FieldType.DATE)
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', v)


# ── generate_events ───────────────────────────────────────────────────────────

class TestGenerateEvents:
    def _payment_schema(self) -> InferredSchema:
        return _make_schema([
            _field("event_id",    FieldType.UUID),
            _field("event_type",  FieldType.STRING, enum_values=["purchase", "refund"]),
            _field("timestamp",   FieldType.TIMESTAMP_EPOCH_MS),
            _field("amount",      FieldType.FLOAT),
            _field("currency",    FieldType.STRING, enum_values=["USD", "EUR"]),
            _field("user.email",  FieldType.EMAIL,  pii=[PIICategory.EMAIL]),
            _field("user.name",   FieldType.STRING),
            _field("merchant_id", FieldType.STRING, required=False, presence_rate=0.7),
        ])

    def test_returns_correct_count(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=15)
        assert len(events) == 15

    def test_required_fields_always_present(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=50, seed=42)
        for event in events:
            assert "event_id" in event
            assert "amount" in event
            assert "timestamp" in event

    def test_nested_structure_reconstructed(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=20, seed=1)
        for event in events:
            # user.email and user.name should produce a nested user dict
            assert "user" in event
            assert isinstance(event["user"], dict)
            assert "email" in event["user"]

    def test_enum_values_respected(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=50, seed=7)
        for event in events:
            assert event["event_type"] in ["purchase", "refund"]
            assert event["currency"] in ["USD", "EUR"]

    def test_required_only_excludes_optionals(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=50, include_optional=False, seed=3)
        for event in events:
            assert "merchant_id" not in event

    def test_seed_produces_reproducible_output(self):
        schema = self._payment_schema()
        a = generate_events(schema, count=5, seed=99)
        b = generate_events(schema, count=5, seed=99)
        assert [json.dumps(e) for e in a] == [json.dumps(e) for e in b]

    def test_different_seeds_produce_different_output(self):
        schema = self._payment_schema()
        a = generate_events(schema, count=5, seed=1)
        b = generate_events(schema, count=5, seed=2)
        # With different seeds, at least some events should differ
        assert any(json.dumps(ea) != json.dumps(eb) for ea, eb in zip(a, b, strict=False))

    def test_array_fields_reconstructed(self):
        schema = _make_schema([
            _field("id",           FieldType.UUID),
            _field("tags[]",       FieldType.ARRAY),
            _field("items[].sku",  FieldType.STRING),
            _field("items[].qty",  FieldType.INTEGER),
        ])
        events = generate_events(schema, count=10, seed=5)
        for event in events:
            assert "items" in event
            assert isinstance(event["items"], list)
            assert len(event["items"]) >= 1
            assert "sku" in event["items"][0]

    def test_empty_schema_produces_empty_events(self):
        schema = _make_schema([])
        events = generate_events(schema, count=5)
        assert all(e == {} for e in events)

    def test_output_is_valid_json_serialisable(self):
        schema = self._payment_schema()
        events = generate_events(schema, count=20, seed=42)
        for event in events:
            # Should not raise
            json.dumps(event)

    def test_optional_field_included_at_roughly_correct_rate(self):
        # merchant_id has presence_rate=0.7 — with 200 events, should appear ~70%±10%
        schema = self._payment_schema()
        events = generate_events(schema, count=200, include_optional=True, seed=13)
        rate = sum(1 for e in events if "merchant_id" in e) / 200
        assert 0.5 <= rate <= 0.9  # broad tolerance for small sample
