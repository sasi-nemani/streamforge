"""CLI tests for `streamforge eval` (streamforge.cli.eval_cmd.evaluate)."""
from __future__ import annotations

import json
import logging

import pytest
from typer.testing import CliRunner

from streamforge.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _quiet_and_offline(monkeypatch):
    monkeypatch.setenv("STREAMFORGE_AUDIT", "0")
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def test_eval_payments_writes_json(tmp_path):
    out = tmp_path / "out.json"
    result = runner.invoke(app, ["eval", "payments", "--json", str(out)])

    assert result.exit_code == 0, result.output
    assert "payments" in result.output
    assert "Drift detection" in result.output

    # JSON file exists and parses with the expected shape.
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["seed"] == 42
    assert isinstance(payload["streams"], list)
    assert payload["streams"]

    stream = payload["streams"][0]
    assert stream["stream"] == "payments"
    assert stream["inference_path"] == "statistical"
    # Headline metric the demo/CI read.
    f1 = stream["drift"]["f1"]
    assert 0.0 <= f1 <= 1.0
    assert "type_f1" in stream["schema"]
    assert "ece" in stream["calibration"]


def test_eval_bad_stream_exits_nonzero():
    result = runner.invoke(app, ["eval", "does_not_exist"])
    assert result.exit_code != 0


def test_eval_seed_is_reflected_in_json(tmp_path):
    out = tmp_path / "seeded.json"
    result = runner.invoke(
        app, ["eval", "payments", "--seed", "7", "--json", str(out)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["seed"] == 7
    assert payload["streams"][0]["seed"] == 7
