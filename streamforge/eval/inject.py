"""Deterministic drift injector for the StreamForge eval harness.

Given a clean batch of events and a list of :class:`DriftSpec`, produce a
*new* batch with the requested drifts applied plus the :class:`DriftLabel`
ground-truth the detector is expected to emit.

Design contract (see ``runner.py`` caller):
  * Pure & deterministic — the input ``events`` are never mutated (deep-copied
    up front) and all randomness comes from ``random.Random(seed)``. No global
    ``random``, no wall-clock. Same inputs + same seed => identical output.
  * Field paths use dot notation for nesting (``"user.email"``) and must match
    how :func:`streamforge.sampler.flatten_nested` forms paths so that the
    injected drift lines up with what the detector observes.

Data shapes (``DriftSpec``, ``DriftLabel``, ``DRIFT_TYPES``) are imported from
the frozen contract in :mod:`streamforge.eval.types` — never redefined here.
"""
from __future__ import annotations

import copy
import random
from typing import Any

from streamforge.eval.types import DriftLabel, DriftSpec

# Map each injection ``kind`` to the detector ``drift_type`` label it produces.
# ``nesting_change`` is special-cased (emits two labels) and is not listed here.
_KIND_TO_DRIFT_TYPE: dict[str, str] = {
    "type_flip": "type_changed",
    "enum_add": "enum_changed",
    "presence_drop": "presence_drop",
    "field_added": "field_added",
    "field_removed": "field_removed",
    "pii_add": "new_pii",
}


# ── Dot-path helpers (operate on nested dicts, matching flatten_nested) ──────────
def _split(path: str) -> list[str]:
    return path.split(".")


def _has_path(event: dict, path: str) -> bool:
    """True if ``path`` resolves to an existing key in the nested event."""
    parts = _split(path)
    cur: Any = event
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _get_path(event: dict, path: str) -> Any:
    cur: Any = event
    for part in _split(path):
        cur = cur[part]
    return cur


def _set_path(event: dict, path: str, value: Any) -> None:
    """Set ``path`` to ``value``, creating intermediate dicts as needed."""
    parts = _split(path)
    cur = event
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _del_path(event: dict, path: str) -> bool:
    """Delete ``path`` from the nested event. Returns True if removed."""
    parts = _split(path)
    cur: Any = event
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return True
    return False


# ── Affected-index selection ─────────────────────────────────────────────────────
def _choose_indices(eligible: list[int], rate: float, rng: random.Random) -> list[int]:
    """Deterministically pick a ``rate`` fraction of ``eligible`` indices.

    ``n_affected = max(1, round(rate * len(eligible)))`` when ``rate > 0``.
    Returns a sorted list so downstream mutation order is stable.
    """
    if rate <= 0 or not eligible:
        return []
    n_affected = max(1, round(rate * len(eligible)))
    n_affected = min(n_affected, len(eligible))
    chosen = rng.sample(eligible, n_affected)
    return sorted(chosen)


# ── Per-kind type conversion ────────────────────────────────────────────────────
def _convert_type(value: Any, to: str | None) -> Any:
    """Flip ``value`` to a different runtime type for ``type_flip``.

    ``to`` selects the target type; when unset we pick a sensible default that
    is guaranteed to differ from the current type (numbers -> str, else -> str).
    """
    if to == "string":
        return str(value)
    if to == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if to == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if to == "bool":
        return bool(value)
    # Default: if it's a number, flip to bool; otherwise stringify.
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


# ── Spec application ─────────────────────────────────────────────────────────────
def _apply_spec(
    events: list[dict], spec: DriftSpec, rng: random.Random
) -> list[DriftLabel]:
    """Apply one spec in place to ``events`` (already a deep copy).

    Returns the list of labels actually produced (empty if the spec affected
    no events).
    """
    kind = spec.kind
    path = spec.field_path
    params = spec.params or {}

    # ── field_removed: delete from ALL events, rate ignored (treated as 1.0) ──
    if kind == "field_removed":
        removed_any = False
        for event in events:
            if _del_path(event, path):
                removed_any = True
        if removed_any:
            return [DriftLabel(field_path=path, drift_type="field_removed")]
        return []

    # ── field_added: add a NEW field to a rate fraction of events ──
    if kind == "field_added":
        eligible = list(range(len(events)))
        indices = _choose_indices(eligible, spec.rate, rng)
        if not indices:
            return []
        value = params.get("value")
        for i in indices:
            _set_path(events[i], path, value)
        return [DriftLabel(field_path=path, drift_type="field_added")]

    # ── nesting_change: move scalar ``path`` under ``params["parent"]`` ──
    if kind == "nesting_change":
        parent = params.get("parent", "meta")
        leaf = _split(path)[-1]
        new_path = f"{parent}.{leaf}"
        eligible = [i for i, e in enumerate(events) if _has_path(e, path)]
        indices = _choose_indices(eligible, spec.rate, rng)
        if not indices:
            return []
        for i in indices:
            value = _get_path(events[i], path)
            _del_path(events[i], path)
            _set_path(events[i], new_path, value)
        return [
            DriftLabel(field_path=path, drift_type="field_removed"),
            DriftLabel(field_path=new_path, drift_type="field_added"),
        ]

    # ── Remaining kinds operate on events that currently HAVE the field ──
    eligible = [i for i, e in enumerate(events) if _has_path(e, path)]
    indices = _choose_indices(eligible, spec.rate, rng)
    if not indices:
        return []

    if kind == "type_flip":
        to = params.get("to")
        for i in indices:
            cur = _get_path(events[i], path)
            _set_path(events[i], path, _convert_type(cur, to))
        return [DriftLabel(field_path=path, drift_type="type_changed")]

    if kind == "enum_add":
        new_value = params.get("new_value", "BLOCKED")
        for i in indices:
            _set_path(events[i], path, new_value)
        return [DriftLabel(field_path=path, drift_type="enum_changed")]

    if kind == "presence_drop":
        for i in indices:
            _del_path(events[i], path)
        return [DriftLabel(field_path=path, drift_type="presence_drop")]

    if kind == "pii_add":
        value = params.get("value", "a@b.com")
        for i in indices:
            _set_path(events[i], path, value)
        return [DriftLabel(field_path=path, drift_type="new_pii")]

    # Unknown kind — no-op, no label.
    return []


def inject(
    events: list[dict], specs: list[DriftSpec], *, seed: int = 42
) -> tuple[list[dict], list[DriftLabel]]:
    """Inject drifts into a clean event batch, deterministically.

    Args:
        events: Clean events (list of nested/flat JSON-like dicts). Not mutated.
        specs: Drift specs to apply, in order.
        seed: Seed for the local RNG; same seed => identical output.

    Returns:
        ``(new_events, expected_labels)`` where ``new_events`` is a deep copy of
        ``events`` with all drifts applied, and ``expected_labels`` are the
        :class:`DriftLabel` the detector is expected to report. A label is only
        emitted when the spec actually affected >=1 event.
    """
    new_events = copy.deepcopy(events)
    rng = random.Random(seed)
    labels: list[DriftLabel] = []
    for spec in specs:
        labels.extend(_apply_spec(new_events, spec, rng))
    return new_events, labels
