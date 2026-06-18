"""Runtime field-access observation — observed lineage, not declared."""
from __future__ import annotations

import json

from streamforge.access_observer import ConsumerObserver, ObservedAccessStore


def test_records_only_fields_actually_read():
    store = ObservedAccessStore()
    obs = ConsumerObserver("svc", "topic", store=store)
    event = {
        "amount": 1, "currency": "USD",
        "user": {"user_id": "U1", "email": "a@b.com"},
        "passengers": [{"name": "X", "passport": "P"}],
        "ignored": "x",
    }

    def handle(e):
        _ = e["amount"]
        _ = e["user"]["user_id"]
        _ = e.get("currency")
        for p in e["passengers"]:
            _ = p["name"]

    obs.observe(event, handle)
    recorded = set(store.as_dict()["topic"]["svc"].keys())
    assert recorded == {"amount", "currency", "user", "user.user_id", "passengers", "passengers[].name"}
    assert "user.email" not in recorded   # accessed user, not user.email
    assert "ignored" not in recorded
    assert "passengers[].passport" not in recorded


def test_counts_compound_across_events():
    store = ObservedAccessStore()
    obs = ConsumerObserver("svc", "topic", store=store)
    for _ in range(5):
        obs.observe({"amount": 1}, lambda e: e["amount"])
    assert store.as_dict()["topic"]["svc"]["amount"]["count"] == 5


def test_consumers_of_field_is_cross_topic_hottest_first():
    store = ObservedAccessStore()
    store.record("payments", "ledger", ["amount"])
    for _ in range(3):
        store.record("payments", "fraud", ["amount"])
    store.record("refunds", "analytics", ["amount"])

    rows = store.consumers_of_field("amount")
    assert rows[0]["consumer"] == "fraud" and rows[0]["count"] == 3  # hottest first
    assert {r["consumer"] for r in rows} == {"fraud", "ledger", "analytics"}
    assert {r["topic"] for r in rows} == {"payments", "refunds"}     # cross-topic
    # scoping by topic
    assert {r["consumer"] for r in store.consumers_of_field("amount", topics=["refunds"])} == {"analytics"}


def test_persistence_roundtrip_and_compounds(tmp_path):
    p = tmp_path / "access.json"
    s1 = ObservedAccessStore()
    s1.record("t", "c", ["f"])
    s1.save(str(p))                      # accepts str
    assert json.loads(p.read_text())["t"]["c"]["f"]["count"] == 1

    s2 = ObservedAccessStore.load(p)     # accepts Path; compounds
    s2.record("t", "c", ["f"])
    s2.save(p)
    assert ObservedAccessStore.load(p).as_dict()["t"]["c"]["f"]["count"] == 2


def test_input_event_is_not_mutated():
    store = ObservedAccessStore()
    obs = ConsumerObserver("svc", "topic", store=store)
    event = {"a": 1, "nested": {"b": 2}}
    obs.observe(event, lambda e: (e["a"], e["nested"]["b"]))
    assert event == {"a": 1, "nested": {"b": 2}}  # untouched, plain dict


def test_graph_api_surfaces_observed_lineage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    # a schema with the field + a seeded observed access graph
    sd = tmp_path / "events.payments"
    sd.mkdir()
    (sd / "schema.yaml").write_text(
        'stream: events.payments\nfields:\n- { path: amount, type: float, required: true }\n',
        encoding="utf-8",
    )
    graph = tmp_path / "access.json"
    store = ObservedAccessStore()
    for _ in range(42):
        store.record("events.payments", "fraud-detection", ["amount"])
    store.save(graph)

    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))
    monkeypatch.setenv("STREAMFORGE_ACCESS_GRAPH", str(graph))
    from streamforge.api.main import app

    d = TestClient(app).get("/api/graph/field", params={"path": "amount"}).json()
    assert d["observed"][0]["consumer"] == "fraud-detection"
    assert d["observed"][0]["count"] == 42
