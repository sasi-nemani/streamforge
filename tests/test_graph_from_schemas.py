"""SchemaGraph.from_schemas + the cockpit graph API (cross-topic blast radius)."""
from __future__ import annotations


def _write_schema(path, fields_yaml: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fields_yaml, encoding="utf-8")


def _schema_doc(stream: str, rows: list[tuple[str, str]]) -> str:
    fields = "\n".join(
        f"- {{ path: {p}, type: {t}, required: true, nullable: false, "
        f"presence_rate: 1.0, confidence: 0.99 }}"
        for p, t in rows
    )
    return f"stream: {stream}\nversion: \"1.0.0\"\nfields:\n{fields}\n"


def test_from_schemas_detects_cross_topic_inconsistency(tmp_path):
    from streamforge.dependency_graph import SchemaGraph

    # Same field `amount` typed differently across two topics → an inconsistency.
    _write_schema(tmp_path / "payments" / "schema.yaml",
                  _schema_doc("payments", [("amount", "float"), ("user_id", "uuid")]))
    _write_schema(tmp_path / "bookings" / "schema.yaml",
                  _schema_doc("bookings", [("amount", "integer"), ("user_id", "uuid")]))

    g = SchemaGraph.from_schemas(str(tmp_path))
    assert g.meta.stream_count == 2

    inc = g.inconsistencies()
    paths = {n.field_path for n in inc}
    assert "amount" in paths        # float vs integer → flagged
    assert "user_id" not in paths   # uuid in both → consistent

    amount = g.field_usage("amount")
    assert amount is not None
    assert {u.field_type for u in amount.usages} == {"float", "integer"}
    assert sorted(u.stream_name for u in amount.usages) == ["bookings", "payments"]


def test_graph_api_returns_overview_and_field_detail(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    _write_schema(tmp_path / "a" / "schema.yaml",
                  _schema_doc("a", [("ts", "timestamp_iso8601")]))
    _write_schema(tmp_path / "b" / "schema.yaml",
                  _schema_doc("b", [("ts", "timestamp_epoch_ms")]))
    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))

    # eval route imports run_benchmark at module import; ensure app builds fine.
    from streamforge.api.main import app

    client = TestClient(app)
    overview = client.get("/api/graph").json()
    assert overview["overview"]["inconsistencies"] >= 1
    assert any(i["field_path"] == "ts" for i in overview["inconsistencies"])

    detail = client.get("/api/graph/field", params={"path": "ts"}).json()
    assert detail["found"] is True
    assert detail["is_inconsistent"] is True
    assert len(detail["usages"]) == 2
    assert isinstance(detail["consumers"], list)  # may be empty (no consumers registered)


def test_field_blast_radius_is_field_level_and_cross_topic(tmp_path):
    from streamforge.consumer_registry import field_blast_radius

    # `amount` lives in two topics; consumers in BOTH read it (one required).
    _write_schema(tmp_path / "payments" / "schema.yaml", _schema_doc("payments", [("amount", "float")]))
    _write_schema(tmp_path / "refunds" / "schema.yaml", _schema_doc("refunds", [("amount", "float")]))
    (tmp_path / "payments" / "consumers.yaml").write_text(
        "consumers:\n"
        "  - name: ledger\n    team: finance\n    criticality: tier1\n"
        "    fields_used:\n      - { path: amount, required: true }\n"
        "  - name: dashboards\n    team: data\n    criticality: tier3\n"
        "    fields_used:\n      - { path: other, required: false }\n",  # does NOT read amount
        encoding="utf-8",
    )
    (tmp_path / "refunds" / "consumers.yaml").write_text(
        "consumers:\n"
        "  - name: analytics\n    team: data\n    criticality: tier2\n"
        "    fields_used:\n      - { path: amount, required: false }\n",
        encoding="utf-8",
    )

    impact = field_blast_radius(str(tmp_path), "amount", ["payments", "refunds"])
    names = {i["consumer"] for i in impact}
    assert names == {"ledger", "analytics"}        # 'dashboards' excluded (doesn't read amount)
    assert impact[0]["consumer"] == "ledger"       # hard break (required) sorts first
    assert impact[0]["required"] is True
    assert {i["stream"] for i in impact} == {"payments", "refunds"}  # cross-topic


def test_graph_field_api_returns_consumer_impact(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    _write_schema(tmp_path / "payments" / "schema.yaml", _schema_doc("payments", [("amount", "float")]))
    (tmp_path / "payments" / "consumers.yaml").write_text(
        "consumers:\n  - name: ledger\n    team: finance\n    criticality: tier1\n"
        "    fields_used:\n      - { path: amount, required: true }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STREAMFORGE_SCHEMA_DIR", str(tmp_path))
    from streamforge.api.main import app

    d = TestClient(app).get("/api/graph/field", params={"path": "amount"}).json()
    assert d["hard_breaks"] == 1
    assert d["consumers"][0]["consumer"] == "ledger"
    assert d["consumers"][0]["required"] is True
