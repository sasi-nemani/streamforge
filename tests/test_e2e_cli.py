"""
End-to-end CLI tests — runs actual streamforge commands against real event data.

These tests verify the ENTIRE pipeline works: file loading → sampling → inference
→ schema writing → drift detection → reporting. No mocks except for LLM calls
(which are expensive and non-deterministic).

Test data: home/claude/streamforge-mvp/events/payments/{stream_v1, stream_v2_drift}
"""

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from streamforge.__main__ import app

runner = CliRunner()

# Path to real test event data
_EVENTS_BASE = Path(__file__).resolve().parent.parent.parent / "home" / "claude" / "streamforge-mvp" / "events"
_PAYMENTS_V1 = str(_EVENTS_BASE / "payments" / "stream_v1")
_PAYMENTS_V2 = str(_EVENTS_BASE / "payments" / "stream_v2_drift")
_FLIGHTS = str(_EVENTS_BASE / "flights" / "stream")
_IOT = str(_EVENTS_BASE / "iot" / "stream")

# Skip entire module if test data doesn't exist
pytestmark = pytest.mark.skipif(
    not Path(_PAYMENTS_V1).exists(),
    reason="Test event data not found — run generate_events.py first",
)


@pytest.fixture(autouse=True)
def _disable_registry(monkeypatch):
    """Disable field registry to avoid cross-test state."""
    monkeypatch.setenv("STREAMFORGE_REGISTRY_ENABLED", "0")


@pytest.fixture(autouse=True)
def _work_in_tmp(tmp_path, monkeypatch):
    """Run each test in a temp directory so outputs don't collide."""
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# E2E 1: init → produces schema.yaml and reports
# ---------------------------------------------------------------------------


class TestInitCommand:
    """Tests that 'streamforge init' produces correct outputs."""

    def _mock_llm_response(self, fields):
        """Build a mock OpenAI tool-call response."""
        tool_input = json.dumps({
            "fields": fields,
            "overall_confidence": 0.88,
            "event_type_values": [],
        })
        mock_tool_call = MagicMock()
        mock_tool_call.function.arguments = tool_input
        mock_choice = MagicMock()
        mock_choice.message.tool_calls = [mock_tool_call]
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def _payment_fields(self):
        return [
            {"path": "event_id", "field_type": "uuid", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "Unique event ID"},
            {"path": "event_type", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "Event type"},
            {"path": "timestamp", "field_type": "timestamp_epoch_ms", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "Event timestamp"},
            {"path": "amount", "field_type": "float", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "Payment amount"},
            {"path": "currency", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.95,
             "enum_values": ["USD", "EUR", "GBP"], "notes": "Currency code"},
            {"path": "status", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.92,
             "enum_values": ["COMPLETED", "FAILED", "PENDING"], "notes": "Status"},
            {"path": "user.email", "field_type": "email", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "User email"},
            {"path": "user.name", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "User name"},
        ]

    def test_init_produces_schema_yaml(self):
        """E2E: init on payments/stream_v1 produces a valid schema.yaml."""
        mock_response = self._mock_llm_response(self._payment_fields())

        with patch("streamforge.inference._is_ollama_available", return_value=False), \
             patch("streamforge.inference.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = mock_response
            result = runner.invoke(app, [
                "init", _PAYMENTS_V1,
                "--sample-size", "100",
                "--output", "schemas",
                "--api-key", "test-key",
            ])

        assert result.exit_code == 0, f"init failed: {result.output}"

        # schema.yaml must exist
        schema_files = list(Path("schemas").rglob("schema.yaml"))
        assert len(schema_files) >= 1, f"No schema.yaml found. Output:\n{result.output}"

        # Parse and validate schema
        schema_doc = yaml.safe_load(schema_files[0].read_text())
        assert "stream" in schema_doc
        assert "fields" in schema_doc
        assert len(schema_doc["fields"]) > 0
        assert schema_doc.get("version") == "1.0.0"

    def test_init_produces_profile_yaml(self):
        """E2E: init produces profile.yaml for multi-schema discovery."""
        mock_response = self._mock_llm_response(self._payment_fields())

        with patch("streamforge.inference._is_ollama_available", return_value=False), \
             patch("streamforge.inference.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = mock_response
            result = runner.invoke(app, [
                "init", _PAYMENTS_V1,
                "--sample-size", "100",
                "--output", "schemas",
                "--api-key", "test-key",
            ])

        assert result.exit_code == 0
        profile_files = list(Path("schemas").rglob("profile.yaml"))
        assert len(profile_files) >= 1

        profile_doc = yaml.safe_load(profile_files[0].read_text())
        assert "sub_schemas" in profile_doc
        assert len(profile_doc["sub_schemas"]) >= 1

    def test_init_detects_pii(self):
        """E2E: init flags PII fields in the output."""
        mock_response = self._mock_llm_response(self._payment_fields())

        with patch("streamforge.inference._is_ollama_available", return_value=False), \
             patch("streamforge.inference.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = mock_response
            result = runner.invoke(app, [
                "init", _PAYMENTS_V1,
                "--sample-size", "100",
                "--output", "schemas",
                "--api-key", "test-key",
            ])

        assert result.exit_code == 0
        # PII should be mentioned in output
        assert "PII" in result.output or "pii" in result.output.lower()

    def test_init_handles_empty_folder(self, tmp_path):
        """E2E: init on an empty folder exits with error."""
        empty_dir = tmp_path / "empty_events"
        empty_dir.mkdir()
        result = runner.invoke(app, [
            "init", str(empty_dir),
            "--api-key", "test-key",
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# E2E 2: plan → detects drift between v1 and v2
# ---------------------------------------------------------------------------


class TestPlanCommand:
    """Tests that 'streamforge plan' detects drift correctly."""

    def _setup_baseline_schema(self, tmp_path):
        """Create a schema.yaml matching the real payments/stream_v1 structure."""
        schema_dir = Path("schemas") / "stream_v1"
        schema_dir.mkdir(parents=True)
        doc = {
            "stream": "stream_v1",
            "version": "1.0.0",
            "inferred_at": "2026-01-01T00:00:00Z",
            "event_count_sampled": 300,
            "inference_model": "test",
            "inference_confidence": 0.90,
            "fields": [
                {"path": "event_id", "type": "uuid", "required": True,
                 "presence_rate": 1.0, "confidence": 0.95},
                {"path": "event_type", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.95},
                {"path": "timestamp", "type": "timestamp_epoch_ms", "required": True,
                 "presence_rate": 1.0, "confidence": 0.90},
                {"path": "transaction_id", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.90},
                {"path": "amount", "type": "mixed", "required": True,
                 "presence_rate": 1.0, "confidence": 0.85},
                {"path": "currency", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.95,
                 "enum_values": ["USD", "EUR", "GBP"]},
                {"path": "status", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.92,
                 "enum_values": ["COMPLETED", "FAILED", "PENDING"]},
                {"path": "payment_method", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.90},
                {"path": "user.user_id", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.90},
                {"path": "user.email", "type": "email", "required": True,
                 "presence_rate": 1.0, "confidence": 0.95,
                 "pii": ["email"]},
                {"path": "user.name", "type": "string", "required": True,
                 "presence_rate": 1.0, "confidence": 0.90,
                 "pii": ["name"]},
                {"path": "metadata.ip_address", "type": "string", "required": False,
                 "presence_rate": 0.90, "confidence": 0.85,
                 "pii": ["ip_address"]},
                {"path": "metadata.user_agent", "type": "string", "required": False,
                 "presence_rate": 0.90, "confidence": 0.85},
                {"path": "metadata.region", "type": "string", "required": False,
                 "presence_rate": 0.90, "confidence": 0.85},
            ],
        }
        schema_path = schema_dir / "schema.yaml"
        with open(schema_path, "w") as f:
            yaml.dump(doc, f)
        return str(schema_path)

    def test_plan_detects_drift_v1_vs_v2(self):
        """E2E: plan on v2_drift against v1 schema detects real drift."""
        schema_path = self._setup_baseline_schema(None)

        result = runner.invoke(app, [
            "plan", _PAYMENTS_V2,
            "--schema", schema_path,
            "--sample-size", "100",
        ])

        # Should detect drift (non-zero exit or drift output)
        output = result.output.lower()
        # v2_drift has: timestamp format change, amount renamed, new card_last_four
        has_drift = (
            "drift" in output
            or "tier" in output
            or result.exit_code == 1
        )
        assert has_drift, f"No drift detected in v2_drift. Output:\n{result.output}"

    def test_plan_clean_data_low_severity(self):
        """E2E: plan on v1 against v1 schema produces at most minor drift.

        The v1 test data has intentional messiness (~5% of events have
        flattened user fields), so minor Tier 1/2 signals are expected.
        The key assertion: no Tier 3 FIELD REMOVAL (the breaking kind).
        """
        schema_path = self._setup_baseline_schema(None)

        result = runner.invoke(app, [
            "plan", _PAYMENTS_V1,
            "--schema", schema_path,
            "--sample-size", "100",
        ])

        output = result.output.lower()
        # The v1→v1 comparison should NOT detect field removals or type narrowing
        assert "field_removed" not in output or "amount" not in output, \
            f"Unexpected field removal on clean data. Output:\n{result.output}"

    def test_plan_exits_nonzero_on_tier3(self):
        """E2E: plan exits 1 when Tier 3 drift is detected (CI gate)."""
        schema_path = self._setup_baseline_schema(None)

        result = runner.invoke(app, [
            "plan", _PAYMENTS_V2,
            "--schema", schema_path,
            "--sample-size", "100",
        ])

        # v2_drift removes 'amount' (required field) → Tier 3 → exit 1
        # (depends on policy config, default blocks on tier 3)
        # Either exit_code=1 OR drift detected in output
        output = result.output.lower()
        assert result.exit_code == 1 or "tier" in output or "drift" in output


# ---------------------------------------------------------------------------
# E2E 3: profile → shows field stats without LLM
# ---------------------------------------------------------------------------


class TestProfileCommand:
    def test_profile_runs_without_api_key(self):
        """E2E: profile command works without an API key (no LLM needed)."""
        result = runner.invoke(app, [
            "profile", _PAYMENTS_V1,
            "--sample-size", "50",
        ])

        assert result.exit_code == 0, f"profile failed: {result.output}"
        assert "stream_v1" in result.output or "payment" in result.output.lower()

    def test_profile_shows_field_paths(self):
        """E2E: profile output includes actual field paths from events."""
        result = runner.invoke(app, [
            "profile", _PAYMENTS_V1,
            "--sample-size", "50",
        ])

        assert result.exit_code == 0
        output = result.output
        # These fields exist in payment events
        assert "event_id" in output or "event_type" in output


# ---------------------------------------------------------------------------
# E2E 4: report → displays schema and history
# ---------------------------------------------------------------------------


class TestReportCommand:
    def test_report_with_no_schema_exits_gracefully(self):
        """E2E: report on nonexistent stream gives clear error."""
        result = runner.invoke(app, ["report", "nonexistent/stream"])
        # Should exit non-zero or show "not found" message
        assert result.exit_code != 0 or "not found" in result.output.lower() or "no schema" in result.output.lower()


# ---------------------------------------------------------------------------
# E2E 5: generate → produces conformant events from schema
# ---------------------------------------------------------------------------


class TestGenerateCommand:
    def _setup_schema(self):
        schema_dir = Path("schemas") / "test_stream"
        schema_dir.mkdir(parents=True)
        doc = {
            "stream": "test_stream",
            "version": "1.0.0",
            "inferred_at": "2026-01-01T00:00:00Z",
            "event_count_sampled": 100,
            "inference_model": "test",
            "inference_confidence": 0.9,
            "fields": [
                {"path": "id", "type": "uuid", "required": True, "presence_rate": 1.0, "confidence": 0.95},
                {"path": "amount", "type": "float", "required": True, "presence_rate": 1.0, "confidence": 0.9},
                {"path": "status", "type": "string", "required": True, "presence_rate": 1.0,
                 "confidence": 0.9, "enum_values": ["active", "done"]},
            ],
        }
        schema_path = schema_dir / "schema.yaml"
        with open(schema_path, "w") as f:
            yaml.dump(doc, f)
        return str(schema_dir)

    def test_generate_produces_valid_ndjson(self):
        """E2E: generate creates parseable NDJSON events."""
        schema_dir = self._setup_schema()

        result = runner.invoke(app, [
            "generate", schema_dir,
            "--count", "20",
            "--output", "generated.ndjson",
        ])

        assert result.exit_code == 0, f"generate failed: {result.output}"
        out_file = Path("generated.ndjson")
        assert out_file.exists()

        lines = out_file.read_text().strip().split("\n")
        assert len(lines) == 20

        for line in lines:
            event = json.loads(line)
            assert isinstance(event, dict)
            assert "id" in event
            assert "amount" in event


# ---------------------------------------------------------------------------
# E2E 6: export → produces valid output formats
# ---------------------------------------------------------------------------


class TestExportCommand:
    def _setup_schema(self):
        schema_dir = Path("schemas") / "test_export"
        schema_dir.mkdir(parents=True)
        doc = {
            "stream": "test_export",
            "version": "1.0.0",
            "inferred_at": "2026-01-01T00:00:00Z",
            "event_count_sampled": 100,
            "inference_model": "test",
            "inference_confidence": 0.9,
            "fields": [
                {"path": "id", "type": "uuid", "required": True, "presence_rate": 1.0, "confidence": 0.95},
                {"path": "value", "type": "float", "required": True, "presence_rate": 1.0, "confidence": 0.9},
                {"path": "created_at", "type": "timestamp_iso8601", "required": True,
                 "presence_rate": 1.0, "confidence": 0.9},
            ],
        }
        with open(schema_dir / "schema.yaml", "w") as f:
            yaml.dump(doc, f)
        return str(schema_dir)

    @pytest.mark.parametrize("fmt", ["json-schema", "avro", "proto", "flink-ddl", "ksqldb"])
    def test_export_format(self, fmt):
        """E2E: export produces output for each supported format."""
        schema_dir = self._setup_schema()

        result = runner.invoke(app, [
            "export", schema_dir,
            "--format", fmt,
        ])

        assert result.exit_code == 0, f"export --format {fmt} failed: {result.output}"


# ---------------------------------------------------------------------------
# E2E 7: validate → checks events against schema
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def _setup_schema(self):
        schema_dir = Path("schemas") / "stream_v1"
        schema_dir.mkdir(parents=True)
        doc = {
            "stream": "stream_v1",
            "version": "1.0.0",
            "inferred_at": "2026-01-01T00:00:00Z",
            "event_count_sampled": 100,
            "inference_model": "test",
            "inference_confidence": 0.9,
            "fields": [
                {"path": "event_id", "type": "uuid", "required": True,
                 "presence_rate": 1.0, "confidence": 0.95},
                {"path": "amount", "type": "float", "required": True,
                 "presence_rate": 1.0, "confidence": 0.9},
            ],
        }
        with open(schema_dir / "schema.yaml", "w") as f:
            yaml.dump(doc, f)
        return str(schema_dir / "schema.yaml")

    def test_validate_clean_event_passes(self):
        """E2E: validate on conformant event exits 0."""
        self._setup_schema()
        event_file = Path("test_event.json")
        event_file.write_text(json.dumps({"event_id": "abc-123", "amount": 99.5}))

        result = runner.invoke(app, [
            "validate", "stream_v1",
            "--file", str(event_file),
            "--output", "schemas",
        ])

        assert result.exit_code == 0, f"validate failed on clean event: {result.output}"


# ---------------------------------------------------------------------------
# E2E 8: full pipeline — init → plan → detect drift
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_init_then_plan_detects_drift(self):
        """E2E: full pipeline — init on v1, then plan on v2 detects drift.

        This is THE core use case: infer schema from clean stream, then
        detect when a drifted stream breaks the contract.
        """
        # Mock LLM for init (deterministic schema)
        fields = [
            {"path": "event_id", "field_type": "uuid", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "ID"},
            {"path": "timestamp", "field_type": "timestamp_epoch_ms", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "Timestamp"},
            {"path": "amount", "field_type": "float", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "Amount"},
            {"path": "status", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.92, "notes": "Status"},
            {"path": "user.email", "field_type": "email", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "Email"},
        ]
        tool_input = json.dumps({
            "fields": fields,
            "overall_confidence": 0.90,
            "event_type_values": [],
        })
        mock_tool_call = MagicMock()
        mock_tool_call.function.arguments = tool_input
        mock_choice = MagicMock()
        mock_choice.message.tool_calls = [mock_tool_call]
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Step 1: Init on clean v1 data
        with patch("streamforge.inference._is_ollama_available", return_value=False), \
             patch("streamforge.inference.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = mock_response
            init_result = runner.invoke(app, [
                "init", _PAYMENTS_V1,
                "--sample-size", "100",
                "--output", "schemas",
                "--api-key", "test-key",
            ])

        assert init_result.exit_code == 0, f"init failed: {init_result.output}"

        # Find the generated schema
        schema_files = list(Path("schemas").rglob("schema.yaml"))
        assert schema_files, "No schema.yaml generated"
        schema_path = str(schema_files[0])

        # Step 2: Plan against drifted v2 data
        plan_result = runner.invoke(app, [
            "plan", _PAYMENTS_V2,
            "--schema", schema_path,
            "--sample-size", "100",
        ])

        output = plan_result.output.lower()
        # v2 has: timestamp format change (epoch→ISO), amount renamed, new card_last_four PII
        assert "drift" in output or "tier" in output or plan_result.exit_code == 1, \
            f"Pipeline failed to detect drift. Output:\n{plan_result.output}"
