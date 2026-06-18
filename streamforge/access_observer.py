"""Runtime field-access observation — observed lineage, not declared.

The moat move: instead of asking teams to *declare* which fields they consume
(a fragile manifest a competitor can match), StreamForge *observes* which fields
a consumer actually reads from each message at runtime, and compounds that into a
per-company access graph that gets more valuable every day it runs and that no
competitor can bootstrap.

Mechanism: wrap an event in a transparent proxy that records every field path the
consumer touches (``event["amount"]``, ``event["user"]["email"]``,
``event["passengers"][0]["name"]`` → records ``amount``, ``user``, ``user.email``,
``passengers``, ``passengers[].name``). The consumer's code is unchanged; it just
reads fields. Accesses are accumulated per (topic, consumer, field) with counts
and last-seen, persisted to a fail-safe JSON store.

Paths use the same dot / ``[]`` convention as the schema/dependency graph, so
observed lineage lines up with the inferred schema and the blast radius.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ACCESS_PATH = Path(".streamforge") / "access_graph.json"


# ── Transparent access-recording proxies ─────────────────────────────────────
def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _wrap(value: Any, path: str, sink: set[str]) -> Any:
    """Wrap dicts/lists so field access is recorded; scalars pass through."""
    if isinstance(value, dict):
        return _TrackedMapping(value, path, sink)
    if isinstance(value, list):
        return _TrackedSequence(value, path, sink)
    return value


class _TrackedMapping(Mapping):
    __slots__ = ("_d", "_prefix", "_sink")

    def __init__(self, data: dict, prefix: str, sink: set[str]) -> None:
        self._d = data
        self._prefix = prefix
        self._sink = sink

    def __getitem__(self, key: str) -> Any:
        path = _join(self._prefix, str(key))
        self._sink.add(path)
        return _wrap(self._d[key], path, self._sink)

    def get(self, key: str, default: Any = None) -> Any:
        path = _join(self._prefix, str(key))
        self._sink.add(path)
        return _wrap(self._d.get(key, default), path, self._sink)

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def __contains__(self, key: object) -> bool:  # membership is not "access"
        return key in self._d


class _TrackedSequence(Sequence):
    __slots__ = ("_l", "_prefix", "_sink")

    def __init__(self, data: list, prefix: str, sink: set[str]) -> None:
        self._l = data
        self._prefix = prefix
        self._sink = sink

    def __getitem__(self, idx: Any) -> Any:
        # Array-element access collapses to the `[]` path convention.
        elem_path = f"{self._prefix}[]"
        return _wrap(self._l[idx], elem_path, self._sink)

    def __iter__(self):
        elem_path = f"{self._prefix}[]"
        for item in self._l:
            yield _wrap(item, elem_path, self._sink)

    def __len__(self) -> int:
        return len(self._l)


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Persisted, compounding access graph ──────────────────────────────────────
class ObservedAccessStore:
    """{topic: {consumer: {field: {"count": int, "last_seen": iso}}}}.

    Fail-safe: any I/O error degrades to an empty store, never raises. Records
    accumulate (compound) across runs via load → record → save.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._d: dict[str, dict[str, dict[str, dict]]] = data or {}

    def record(self, topic: str, consumer: str, fields: Iterable[str], *, ts: str | None = None) -> None:
        ts = ts or _now()
        c = self._d.setdefault(topic, {}).setdefault(consumer, {})
        for f in fields:
            e = c.setdefault(f, {"count": 0, "last_seen": ""})
            e["count"] = int(e.get("count", 0)) + 1
            e["last_seen"] = ts

    def consumers_of_field(self, field: str, topics: Iterable[str] | None = None) -> list[dict]:
        """Observed consumers that have read ``field`` (optionally limited to
        ``topics``), aggregated across topics, hottest first."""
        agg: dict[tuple[str, str], dict] = {}
        topic_iter = list(topics) if topics is not None else list(self._d.keys())
        for topic in topic_iter:
            for consumer, fmap in self._d.get(topic, {}).items():
                if field in fmap:
                    key = (consumer, topic)
                    entry = agg.setdefault(key, {"consumer": consumer, "topic": topic, "count": 0, "last_seen": ""})
                    entry["count"] += int(fmap[field]["count"])
                    if fmap[field]["last_seen"] > entry["last_seen"]:
                        entry["last_seen"] = fmap[field]["last_seen"]
        return sorted(agg.values(), key=lambda e: -e["count"])

    def topic_consumers(self, topic: str) -> list[str]:
        return sorted(self._d.get(topic, {}).keys())

    def stats(self) -> dict:
        topics = len(self._d)
        consumers = len({c for t in self._d.values() for c in t})
        edges = sum(len(f) for t in self._d.values() for f in t.values())
        return {"topics": topics, "consumers": consumers, "field_edges": edges}

    def as_dict(self) -> dict:
        return self._d

    # ── persistence (fail-safe, atomic, compounding) ─────────────────────────
    @staticmethod
    def load(path: Path | str | None = None) -> ObservedAccessStore:
        path = Path(path) if path is not None else DEFAULT_ACCESS_PATH
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return ObservedAccessStore(data)
        except Exception as exc:  # noqa: BLE001 — never break the consumer
            logger.warning("Could not load access graph %s: %s", path, exc)
        return ObservedAccessStore()

    def save(self, path: Path | str | None = None) -> None:
        path = Path(path) if path is not None else DEFAULT_ACCESS_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._d, indent=2), encoding="utf-8")
            tmp.replace(path)  # atomic
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not save access graph %s: %s", path, exc)


# ── Ergonomic consumer-side wrapper ──────────────────────────────────────────
class ConsumerObserver:
    """Wrap a consumer's message handling to record observed field access.

    Usage (the consumer's logic is unchanged — it just reads fields):

        obs = ConsumerObserver("fraud-detection", "events.payments")
        for event in stream:
            obs.observe(event, handle)     # handle(e) reads e["amount"], ...
        obs.save()

    or as a context manager (auto-saves on exit):

        with ConsumerObserver("fraud-detection", "events.payments") as obs:
            for event in stream:
                obs.observe(event, handle)
    """

    def __init__(
        self,
        consumer: str,
        topic: str,
        *,
        store: ObservedAccessStore | None = None,
        store_path: Path | None = None,
    ) -> None:
        self.consumer = consumer
        self.topic = topic
        self._path = store_path
        self._store = store or ObservedAccessStore.load(store_path)

    def observe(self, event: dict, process: Any) -> Any:
        """Run ``process(tracked_event)`` and record every field it touched."""
        sink: set[str] = set()
        tracked = _wrap(event, "", sink)
        try:
            return process(tracked)
        finally:
            self._store.record(self.topic, self.consumer, sink)

    def track(self, event: dict) -> tuple[Mapping, set[str]]:
        """Lower-level: return (tracked_event, sink). Call record_sink(sink)
        after the consumer has read what it needs."""
        sink: set[str] = set()
        return _wrap(event, "", sink), sink

    def record_sink(self, sink: set[str]) -> None:
        self._store.record(self.topic, self.consumer, sink)

    def save(self) -> None:
        self._store.save(self._path)

    def __enter__(self) -> ConsumerObserver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.save()
