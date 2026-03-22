"""
Tests for the local-first inference cascade:
  1. Ollama (local)  → if confidence >= 0.80: done
  2. Groq            → if Ollama failed or confidence < 0.80
  3. OpenRouter      → if Groq failed
  4. Statistical     → last resort
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from streamforge.inference import (
    LOCAL_CONFIDENCE_THRESHOLD,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    _is_ollama_available,
    infer_schema,
)
from streamforge.models import FieldType


# ── helpers ───────────────────────────────────────────────────────────────────

FIELD_STATS = {"event_id": ["abc123", "def456"], "amount": [100, 200]}
PRESENCE_RATES = {"event_id": 1.0, "amount": 0.95}
SAMPLE_EVENTS = [{"event_id": "abc123", "amount": 100}]


def _make_tool_response(confidence: float, fields=None):
    """Build a mock OpenAI ChatCompletion response with a tool call."""
    if fields is None:
        fields = [
            {"path": "event_id", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.95, "notes": "test"},
            {"path": "amount", "field_type": "integer", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "test"},
        ]
    tool_input = json.dumps({
        "fields": fields,
        "overall_confidence": confidence,
        "event_type_values": [],
    })
    mock_tool_call = MagicMock()
    mock_tool_call.function.arguments = tool_input
    mock_choice = MagicMock()
    mock_choice.message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _make_json_response(confidence: float, fields=None):
    """Build a mock OpenAI ChatCompletion response with raw JSON content (json-mode)."""
    if fields is None:
        fields = [
            {"path": "event_id", "field_type": "string", "nullable": False,
             "required": True, "confidence": 0.90, "notes": "test"},
        ]
    content = json.dumps({
        "fields": fields,
        "overall_confidence": confidence,
        "event_type_values": [],
    })
    mock_choice = MagicMock()
    mock_choice.message.tool_calls = None
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ── _is_ollama_available ───────────────────────────────────────────────────────

def test_ollama_available_returns_true_on_200():
    with patch("streamforge.inference.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        assert _is_ollama_available() is True


def test_ollama_available_returns_false_on_connection_error():
    import httpx
    with patch("streamforge.inference.httpx.get", side_effect=httpx.ConnectError("refused")):
        assert _is_ollama_available() is False


def test_ollama_available_returns_false_on_timeout():
    import httpx
    with patch("streamforge.inference.httpx.get", side_effect=httpx.TimeoutException("timeout")):
        assert _is_ollama_available() is False


# ── constants ─────────────────────────────────────────────────────────────────

def test_local_confidence_threshold_is_0_80():
    assert LOCAL_CONFIDENCE_THRESHOLD == 0.80


def test_ollama_base_url_points_to_localhost():
    assert "127.0.0.1:11434" in OLLAMA_BASE_URL or "localhost:11434" in OLLAMA_BASE_URL


def test_ollama_model_constant_exists():
    assert OLLAMA_MODEL  # non-empty string


# ── cascade: Ollama succeeds with high confidence ────────────────────────────

def test_ollama_high_confidence_skips_remote_models():
    """When Ollama returns confidence >= 0.80, Groq should NOT be called."""
    with patch("streamforge.inference._is_ollama_available", return_value=True), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        # All OpenAI client instances share the same mock completions
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_json_response(confidence=0.92)

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    # Ollama was tried (OpenAI client instantiated for local URL)
    calls = mock_openai_cls.call_args_list
    base_urls = [c.kwargs.get("base_url", "") or c.args[1] if len(c.args) > 1 else "" for c in calls]
    base_urls = [mock_openai_cls.call_args_list[i][1].get("base_url", "") for i in range(len(calls))]
    assert any("11434" in url for url in base_urls), "Ollama client was not created"

    # Only ONE client should have been created (Ollama only — Groq skipped)
    assert mock_openai_cls.call_count == 1, (
        f"Expected 1 client (Ollama only), got {mock_openai_cls.call_count}"
    )
    assert result.inference_confidence >= LOCAL_CONFIDENCE_THRESHOLD


# ── cascade: Ollama low confidence → escalate to Groq ────────────────────────

def test_ollama_low_confidence_escalates_to_groq():
    """When Ollama confidence < 0.80, Groq must be called next."""
    with patch("streamforge.inference._is_ollama_available", return_value=True), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        # First call (Ollama, json-mode) → low confidence
        # Second call (Groq, tool-call) → high confidence
        ollama_client = MagicMock()
        groq_client = MagicMock()
        mock_openai_cls.side_effect = [ollama_client, groq_client]

        ollama_client.chat.completions.create.return_value = _make_json_response(confidence=0.65)
        groq_client.chat.completions.create.return_value = _make_tool_response(confidence=0.91)

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    assert mock_openai_cls.call_count == 2, "Expected Ollama + Groq clients"
    assert result.inference_confidence >= 0.80


# ── cascade: Ollama unavailable → go straight to Groq ────────────────────────

def test_ollama_unavailable_goes_to_groq():
    """When Ollama is not running, Groq is tried without delay."""
    with patch("streamforge.inference._is_ollama_available", return_value=False), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        groq_client = MagicMock()
        mock_openai_cls.return_value = groq_client
        groq_client.chat.completions.create.return_value = _make_tool_response(confidence=0.88)

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    # Only Groq client should be created
    assert mock_openai_cls.call_count == 1
    calls = mock_openai_cls.call_args_list
    groq_url = calls[0][1].get("base_url", "")
    assert "groq" in groq_url, f"Expected Groq URL, got: {groq_url}"


# ── cascade: Ollama + Groq fail → OpenRouter ─────────────────────────────────

def test_openrouter_used_when_groq_fails(monkeypatch):
    """When Ollama is down and Groq fails, OpenRouter is tried."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    with patch("streamforge.inference._is_ollama_available", return_value=False), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        groq_client = MagicMock()
        or_client = MagicMock()
        mock_openai_cls.side_effect = [groq_client, or_client]

        # Groq fails on all retries
        groq_client.chat.completions.create.side_effect = Exception("quota exceeded")

        # OpenRouter succeeds
        or_client.chat.completions.create.return_value = _make_json_response(confidence=0.85)

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    assert mock_openai_cls.call_count == 2
    or_url = mock_openai_cls.call_args_list[1][1].get("base_url", "")
    assert "openrouter" in or_url, f"Expected OpenRouter URL, got: {or_url}"
    assert len(result.fields) > 0


# ── cascade: all LLMs fail → statistical fallback ────────────────────────────

def test_statistical_fallback_when_all_llms_fail(monkeypatch):
    """When all LLM providers fail, statistical inference is used."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with patch("streamforge.inference._is_ollama_available", return_value=False), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        groq_client = MagicMock()
        mock_openai_cls.return_value = groq_client
        groq_client.chat.completions.create.side_effect = Exception("all failed")

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    assert result.inference_confidence <= 0.7
    assert "statistical" in result.inference_model.lower() or len(result.fields) > 0


# ── cascade: Ollama fails (exception) → escalate ─────────────────────────────

def test_ollama_exception_escalates_to_groq():
    """If Ollama is available but raises during inference, escalate to Groq."""
    with patch("streamforge.inference._is_ollama_available", return_value=True), \
         patch("streamforge.inference.OpenAI") as mock_openai_cls:

        ollama_client = MagicMock()
        groq_client = MagicMock()
        mock_openai_cls.side_effect = [ollama_client, groq_client]

        ollama_client.chat.completions.create.side_effect = Exception("model not found")
        groq_client.chat.completions.create.return_value = _make_tool_response(confidence=0.88)

        result = infer_schema(
            stream_name="test",
            field_stats=FIELD_STATS,
            sample_events=SAMPLE_EVENTS,
            presence_rates=PRESENCE_RATES,
            api_key="groq-key",
        )

    assert mock_openai_cls.call_count == 2
    assert len(result.fields) > 0
