import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from .models import FieldSchema, FieldType, InferredSchema
from .pii_detector import detect_pii

logger = logging.getLogger(__name__)

# Defaults — override via CLI flags or env vars
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# OpenAI function-calling format (works for Groq, OpenAI, Ollama)
INFERENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_inferred_schema",
        "description": "Submit the inferred schema for the event stream",
        "parameters": {
            "type": "object",
            "required": ["fields", "overall_confidence", "event_type_values"],
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path", "field_type", "nullable", "required", "confidence", "notes"],
                        "properties": {
                            "path": {"type": "string", "description": "dot-notation field path"},
                            "field_type": {
                                "type": "string",
                                "enum": [
                                    "string", "integer", "float", "boolean",
                                    "timestamp_epoch_ms", "timestamp_iso8601", "timestamp_rfc2822",
                                    "date", "uuid", "email", "phone", "array", "object", "null", "mixed"
                                ]
                            },
                            "nullable": {"type": "boolean"},
                            "required": {"type": "boolean", "description": "present in >80% of events"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "enum_values": {
                                "anyOf": [
                                    {"type": "array", "items": {"type": "string"}},
                                    {"type": "null"}
                                ],
                                "description": "ONLY include if field has <15 distinct values. Omit or set null otherwise."
                            },
                            "notes": {"type": "string", "description": "Brief description of this field"}
                        }
                    }
                },
                "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "event_type_values": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Distinct values of event_type field if it exists"
                }
            }
        }
    }
}

SYSTEM_PROMPT = """You are a data schema expert specialising in event stream analysis.
Analyse the provided JSON events and infer a precise schema.

Rules:
- Examine ALL provided events, not just the first few
- If a field is absent in >20% of events, set required=false
- If a field has ≤15 distinct values across all samples, include enum_values
- Identify timestamps precisely: unix epoch ms (large integer ~13 digits), ISO8601 string, RFC2822 string
- If the SAME field has different types across events (e.g. sometimes string, sometimes integer), use "mixed" type and explain in notes
- UUID fields: recognise standard UUID v4 format
- For nested objects: analyse each leaf field separately using dot-notation paths
- Arrays: note the array type and analyse the structure of array elements
- Be conservative with confidence scores — messy real-world data rarely deserves >0.95
- In notes: describe what the field likely represents based on its name and values
- For enum_values: ONLY include the key when the field has <15 distinct values. Otherwise omit the key entirely — do NOT set it to null
- You MUST call the submit_inferred_schema function with your analysis"""


MAX_PROMPT_CHARS = 20_000  # ~5k tokens; leaves headroom for system prompt + response within 12k TPM


def build_inference_prompt(
    field_stats: dict[str, list],
    presence_rates: dict[str, float],
    sample_events: list[dict]
) -> str:
    # Sort fields: required fields first (high presence), then optional
    sorted_paths = sorted(field_stats.keys(), key=lambda p: -presence_rates.get(p, 0))

    stat_lines = ["## Field Statistics\n"]
    stat_lines.append(f"{'Field Path':<50} {'Presence':>8}  Sample Values")
    stat_lines.append("-" * 100)

    stats_budget = MAX_PROMPT_CHARS // 2  # half the budget for field stats
    stats_chars = 0
    included = 0
    for path in sorted_paths:
        values = field_stats[path]
        rate = presence_rates.get(path, 0.0)
        seen = []
        for v in values:
            sv = str(v)[:60] if isinstance(v, str) else v
            if sv not in seen:
                seen.append(sv)
            if len(seen) >= 4:
                break
        row = f"{path:<50} {rate:>7.0%}  {json.dumps(seen)}"
        if stats_chars + len(row) > stats_budget:
            stat_lines.append(f"... ({len(sorted_paths) - included} more fields omitted — presence rate < {rate:.0%})")
            break
        stat_lines.append(row)
        stats_chars += len(row)
        included += 1

    stats_block = "\n".join(stat_lines)

    # Add sample events with remaining budget
    event_lines = ["\n## Sample Events\n"]
    budget = MAX_PROMPT_CHARS - len(stats_block)
    for i, event in enumerate(sample_events):
        serialised = json.dumps(event, indent=2)
        if len(serialised) > budget:
            break
        event_lines.append(f"Event {i + 1}:\n{serialised}\n")
        budget -= len(serialised)

    if len(event_lines) == 1 and sample_events:
        truncated = json.dumps(sample_events[0])[:max(200, budget - 50)] + "\n... (truncated)"
        event_lines.append(f"Event 1 (truncated):\n{truncated}\n")

    return stats_block + "\n".join(event_lines)


def _compress_field_stats(field_stats: dict[str, list]) -> dict[str, list]:
    compressed = {}
    for path, values in field_stats.items():
        seen = []
        for v in values:
            sv = str(v)[:100] if isinstance(v, str) else v
            if sv not in seen:
                seen.append(sv)
            if len(seen) >= 8:
                break
        compressed[path] = seen
    return compressed


def statistical_inference(field_stats: dict, presence_rates: dict) -> list[FieldSchema]:
    """Fallback: pure statistical type inference without LLM."""
    fields = []
    for path, values in field_stats.items():
        if not values:
            ft = FieldType.NULL
        else:
            type_counts: dict[str, int] = {}
            for v in values:
                if isinstance(v, bool):
                    t = "boolean"
                elif isinstance(v, int):
                    t = "integer"
                elif isinstance(v, float):
                    t = "float"
                elif isinstance(v, str):
                    t = "string"
                elif isinstance(v, list):
                    t = "array"
                elif isinstance(v, dict):
                    t = "object"
                else:
                    t = "null"
                type_counts[t] = type_counts.get(t, 0) + 1

            majority = max(type_counts, key=lambda k: type_counts[k])
            if len(type_counts) > 1:
                ft = FieldType.MIXED
            else:
                ft = FieldType(majority) if majority in FieldType._value2member_map_ else FieldType.STRING

        presence = presence_rates.get(path, 0.0)
        pii = detect_pii(path, values[:20])

        fields.append(FieldSchema(
            name=path.split(".")[-1],
            path=path,
            field_type=ft,
            nullable=None in values,
            required=presence >= 0.8,
            presence_rate=presence,
            sample_values=values[:5],
            pii_categories=pii,
            confidence=min(0.7, 0.5 + presence * 0.2),
            notes="Statistically inferred (LLM fallback)"
        ))

    return fields


def infer_schema(
    stream_name: str,
    field_stats: dict[str, list],
    sample_events: list[dict],
    presence_rates: dict[str, float],
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_retries: int = 3,
) -> InferredSchema:
    """Main inference function using OpenAI-compatible tool calling."""
    client = OpenAI(api_key=api_key, base_url=base_url)
    compressed_stats = _compress_field_stats(field_stats)
    prompt = build_inference_prompt(compressed_stats, presence_rates, sample_events)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    llm_fields = None
    overall_confidence = 0.8
    event_type_values = []

    for attempt in range(max_retries):
        logger.info("Inference attempt %d/%d (model: %s)...", attempt + 1, max_retries, model)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[INFERENCE_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_inferred_schema"}},
                max_tokens=8192,
            )

            choice = response.choices[0]
            tool_calls = choice.message.tool_calls
            if not tool_calls:
                raise ValueError("No tool call in response")

            tool_input = json.loads(tool_calls[0].function.arguments)
            overall_confidence = tool_input.get("overall_confidence", 0.8)
            event_type_values = tool_input.get("event_type_values", [])
            raw_fields = tool_input.get("fields", [])

            llm_fields = []
            for f in raw_fields:
                path = f["path"]
                presence = presence_rates.get(path, 0.0)
                raw_values = field_stats.get(path, [])
                pii = detect_pii(path, raw_values[:20])

                enum_values = f.get("enum_values") or None  # treat null/[] as absent
                if enum_values:
                    enum_values = [str(v) for v in enum_values]

                llm_fields.append(FieldSchema(
                    name=path.split(".")[-1],
                    path=path,
                    field_type=FieldType(f["field_type"]),
                    nullable=f.get("nullable", False),
                    required=f.get("required", presence >= 0.8),
                    presence_rate=presence,
                    sample_values=raw_values[:5],
                    enum_values=enum_values,
                    pii_categories=pii,
                    confidence=f.get("confidence", 0.8),
                    notes=f.get("notes"),
                ))
            break  # success

        except Exception as e:
            logger.warning("Inference attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                messages.append({"role": "user", "content": f"Previous attempt failed: {e}. Please call submit_inferred_schema."})

    if llm_fields is None:
        logger.warning("All LLM attempts failed, falling back to statistical inference")
        llm_fields = statistical_inference(field_stats, presence_rates)
        overall_confidence = 0.6
        model = f"{model}(statistical-fallback)"

    now = datetime.now(timezone.utc).isoformat()
    return InferredSchema(
        stream_name=stream_name,
        version="1.0.0",
        inferred_at=now,
        event_count_sampled=len(sample_events),
        fields=llm_fields,
        top_level_event_types=event_type_values if event_type_values else None,
        inference_model=model,
        inference_confidence=overall_confidence,
    )
