"""Tests for the deterministic drift injector (streamforge.eval.inject)."""
from __future__ import annotations

import copy

import pytest

from streamforge.eval.inject import inject
from streamforge.eval.types import DRIFT_TYPES, DriftLabel, DriftSpec
from streamforge.pii_detector import detect_pii
from streamforge.sampler import flatten_nested


def _events(n: int = 20) -> list[dict]:
    """A clean batch with a flat scalar field and a nested object field."""
    return [
        {
            "status": 200,
            "amount": i,
            "user": {"name": f"u{i}", "email_id": "plainstring"},
        }
        for i in range(n)
    ]


# ── Determinism & purity ─────────────────────────────────────────────────────────
def test_determinism_same_seed_identical():
    events = _events()
    specs = [
        DriftSpec(kind="type_flip", field_path="status", rate=0.5),
        DriftSpec(kind="enum_add", field_path="amount", rate=0.3, params={"new_value": "X"}),
    ]
    e1, l1 = inject(events, specs, seed=42)
    e2, l2 = inject(events, specs, seed=42)
    assert e1 == e2
    assert l1 == l2


def test_different_seed_may_differ_but_label_set_stable():
    events = _events()
    specs = [DriftSpec(kind="type_flip", field_path="status", rate=0.5)]
    _, l1 = inject(events, specs, seed=1)
    _, l2 = inject(events, specs, seed=2)
    # Labels (path/type) are seed-independent; only affected indices vary.
    assert l1 == l2


def test_purity_input_not_mutated():
    events = _events()
    snapshot = copy.deepcopy(events)
    specs = [
        DriftSpec(kind="presence_drop", field_path="status", rate=1.0),
        DriftSpec(kind="field_removed", field_path="amount"),
        DriftSpec(kind="nesting_change", field_path="status", params={"parent": "meta"}),
    ]
    inject(events, specs, seed=42)
    assert events == snapshot


# ── Per-kind behavior ────────────────────────────────────────────────────────────
def test_type_flip_changes_type_on_fraction():
    events = _events(20)
    spec = DriftSpec(kind="type_flip", field_path="status", rate=0.5, params={"to": "string"})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="status", drift_type="type_changed")]
    flipped = [e for e in out if isinstance(e["status"], str)]
    assert len(flipped) == 10  # round(0.5 * 20)
    assert all(f["status"] == "200" for f in flipped)


def test_type_flip_default_number_to_str():
    events = _events(4)
    spec = DriftSpec(kind="type_flip", field_path="status", rate=1.0)
    out, _ = inject(events, [spec], seed=42)
    assert all(isinstance(e["status"], str) for e in out)


def test_enum_add_sets_novel_value():
    events = _events(10)
    spec = DriftSpec(kind="enum_add", field_path="status", rate=0.4, params={"new_value": "BLOCKED"})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="status", drift_type="enum_changed")]
    blocked = [e for e in out if e["status"] == "BLOCKED"]
    assert len(blocked) == 4


def test_presence_drop_deletes_field():
    events = _events(10)
    spec = DriftSpec(kind="presence_drop", field_path="status", rate=0.5)
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="status", drift_type="presence_drop")]
    missing = [e for e in out if "status" not in e]
    assert len(missing) == 5


def test_field_added_adds_new_field():
    events = _events(10)
    spec = DriftSpec(kind="field_added", field_path="fraud_score", rate=0.6, params={"value": 0.9})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="fraud_score", drift_type="field_added")]
    added = [e for e in out if "fraud_score" in e]
    assert len(added) == 6
    assert all(e["fraud_score"] == 0.9 for e in added)


def test_field_added_nested_path():
    events = _events(4)
    spec = DriftSpec(kind="field_added", field_path="user.risk", rate=1.0, params={"value": 1})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="user.risk", drift_type="field_added")]
    assert all(e["user"]["risk"] == 1 for e in out)
    # Path matches how the detector flattens it.
    assert "user.risk" in flatten_nested(out[0])


def test_field_removed_deletes_from_all_ignoring_rate():
    events = _events(10)
    spec = DriftSpec(kind="field_removed", field_path="amount", rate=0.1)
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="amount", drift_type="field_removed")]
    assert all("amount" not in e for e in out)


def test_pii_add_value_flagged_by_detector():
    events = _events(10)
    spec = DriftSpec(kind="pii_add", field_path="user.email_id", rate=1.0, params={"value": "a@b.com"})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="user.email_id", drift_type="new_pii")]
    # The injected value must actually trip the PII detector.
    cats = detect_pii("user.email_id", [e["user"]["email_id"] for e in out])
    assert cats  # non-empty => detector flags it


def test_pii_add_default_value_is_pii():
    events = _events(3)
    spec = DriftSpec(kind="pii_add", field_path="status", rate=1.0)
    out, _ = inject(events, [spec], seed=42)
    cats = detect_pii("status", [e["status"] for e in out])
    assert cats


# ── nesting_change ───────────────────────────────────────────────────────────────
def test_nesting_change_emits_two_labels_and_moves_value():
    events = _events(4)
    spec = DriftSpec(kind="nesting_change", field_path="status", rate=1.0, params={"parent": "meta"})
    out, labels = inject(events, [spec], seed=42)
    assert labels == [
        DriftLabel(field_path="status", drift_type="field_removed"),
        DriftLabel(field_path="meta.status", drift_type="field_added"),
    ]
    for e in out:
        assert "status" not in e
        assert e["meta"]["status"] == 200
    # New nested path matches detector's flattened view.
    assert "meta.status" in flatten_nested(out[0])


def test_nesting_change_default_parent_meta():
    events = _events(2)
    spec = DriftSpec(kind="nesting_change", field_path="amount", rate=1.0)
    _, labels = inject(events, [spec], seed=42)
    assert DriftLabel(field_path="meta.amount", drift_type="field_added") in labels


# ── No-op cases: field present in 0 events => no label ────────────────────────────
def test_missing_field_produces_no_label():
    events = _events(10)
    spec = DriftSpec(kind="type_flip", field_path="does_not_exist", rate=1.0)
    out, labels = inject(events, [spec], seed=42)
    assert labels == []
    assert out == events  # nothing changed


def test_rate_zero_produces_no_label():
    events = _events(10)
    spec = DriftSpec(kind="presence_drop", field_path="status", rate=0.0)
    _, labels = inject(events, [spec], seed=42)
    assert labels == []


def test_field_removed_missing_field_no_label():
    events = _events(5)
    spec = DriftSpec(kind="field_removed", field_path="nope")
    _, labels = inject(events, [spec], seed=42)
    assert labels == []


def test_nesting_change_missing_field_no_label():
    events = _events(5)
    spec = DriftSpec(kind="nesting_change", field_path="nope", params={"parent": "meta"})
    _, labels = inject(events, [spec], seed=42)
    assert labels == []


def test_empty_events_no_labels():
    out, labels = inject([], [DriftSpec(kind="type_flip", field_path="x", rate=1.0)], seed=42)
    assert out == []
    assert labels == []


# ── Contract sanity ──────────────────────────────────────────────────────────────
def test_all_emitted_labels_use_valid_drift_types():
    events = _events(10)
    specs = [
        DriftSpec(kind="type_flip", field_path="status", rate=0.5),
        DriftSpec(kind="enum_add", field_path="amount", rate=0.5),
        DriftSpec(kind="presence_drop", field_path="status", rate=0.5),
        DriftSpec(kind="field_added", field_path="newf", rate=0.5, params={"value": 1}),
        DriftSpec(kind="field_removed", field_path="amount"),
        DriftSpec(kind="pii_add", field_path="user.email_id", rate=0.5),
        DriftSpec(kind="nesting_change", field_path="status", rate=0.5),
    ]
    _, labels = inject(events, specs, seed=42)
    assert labels  # produced something
    assert all(lab.drift_type in DRIFT_TYPES for lab in labels)


def test_round_half_min_one_affected():
    # rate * n rounds to 0 but field applies => still at least 1 affected.
    events = _events(10)
    spec = DriftSpec(kind="presence_drop", field_path="status", rate=0.01)
    out, labels = inject(events, [spec], seed=42)
    assert labels == [DriftLabel(field_path="status", drift_type="presence_drop")]
    assert sum(1 for e in out if "status" not in e) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
