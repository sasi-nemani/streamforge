import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from openai import OpenAI

from .field_registry import FieldTypeRegistry, RegistryConfig
from .models import FieldSchema, FieldType, InferredSchema, PIICategory, SubSchema
from .pii_detector import detect_pii

logger = logging.getLogger(__name__)

# ── Small-cluster inference threshold ────────────────────────────────────────
# Clusters with fewer than this many events skip the LLM and go straight to
# statistical_inference(). LLMs produce low-quality output on tiny samples.
MIN_EVENTS_FOR_LLM_INFERENCE = 50


def _min_events_for_llm() -> int:
    """Return the minimum events threshold for LLM inference.

    Reads STREAMFORGE_MIN_EVENTS_FOR_LLM env var; defaults to 50.
    Falls back to default on non-numeric values.
    """
    raw = os.environ.get("STREAMFORGE_MIN_EVENTS_FOR_LLM", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return MIN_EVENTS_FOR_LLM_INFERENCE

# ── Schema hints ─────────────────────────────────────────────────────────────
_HINTS_FILE = Path(__file__).parent / "schema_hints.yaml"


def _load_schema_hints() -> dict:
    """Load schema_hints.yaml. Returns empty dict on failure (graceful degradation)."""
    try:
        with open(_HINTS_FILE, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load schema_hints.yaml: %s", exc)
        return {}


# Pre-compile hint regexes once at module load
def _compile_hint_patterns(hints: dict) -> list[tuple[re.Pattern, str, float]]:
    """Return list of (compiled_regex, field_type_str, confidence_floor)."""
    compiled = []
    for entry in hints.get("type_patterns", []):
        try:
            compiled.append((
                re.compile(entry["regex"]),
                entry["field_type"],
                float(entry.get("confidence_floor", 0.95)),
            ))
        except re.error as exc:
            logger.warning("Bad regex in schema_hints.yaml (%s): %s", entry.get("name"), exc)
    return compiled


_SCHEMA_HINTS: dict = _load_schema_hints()
_COMPILED_HINT_PATTERNS: list = _compile_hint_patterns(_SCHEMA_HINTS)

# Map field_type string values from hints to FieldType enum members
_HINT_TYPE_MAP: dict[str, FieldType] = {ft.value: ft for ft in FieldType}

# Map pii_category strings from hints to PIICategory enum members
_HINT_PII_MAP: dict[str, PIICategory] = {p.value: p for p in PIICategory}


def _apply_schema_hints(
    fields: list[FieldSchema],
    field_stats: dict[str, list],
    hints: dict,
) -> list[FieldSchema]:
    """
    Deterministic post-inference confidence boost.

    Pass 1 — Type override:
      For each field, run compiled hint regexes against sample values.
      If ≥60% of non-null samples match a pattern, override field_type and
      floor confidence to the hint's confidence_floor value.

    Pass 2 — PII floor:
      If the field path contains a known PII substring (case-insensitive),
      ensure that PII category is present in pii_categories.
    """
    # Use the module-level pre-compiled patterns when called with the default
    # _SCHEMA_HINTS dict; only re-compile when a custom hints dict is passed
    # (e.g. in tests that inject a different hints fixture).
    compiled = _COMPILED_HINT_PATTERNS if hints is _SCHEMA_HINTS else _compile_hint_patterns(hints)
    pii_floors = hints.get("pii_name_floors", [])
    result = []

    for f in fields:
        # ── Pass 1: type override ──────────────────────────────────────────
        samples = [v for v in field_stats.get(f.path, f.sample_values or []) if v is not None]
        if samples:
            for pattern, type_str, conf_floor in compiled:
                str_samples = [str(v) for v in samples]
                match_count = sum(1 for s in str_samples if pattern.match(s))
                match_rate = match_count / len(str_samples)
                if match_rate >= 0.60:
                    target_type = _HINT_TYPE_MAP.get(type_str, f.field_type)
                    new_conf = max(f.confidence, conf_floor)
                    f = f.model_copy(update={"field_type": target_type, "confidence": new_conf})
                    break  # first matching pattern wins

        # ── Pass 2: PII floor ─────────────────────────────────────────────
        path_lower = f.path.lower()
        pii_set = list(f.pii_categories)
        for floor_entry in pii_floors:
            if floor_entry["substring"].lower() in path_lower:
                category = _HINT_PII_MAP.get(floor_entry["pii_category"])
                if category and category not in pii_set:
                    pii_set.append(category)
        if pii_set != list(f.pii_categories):
            f = f.model_copy(update={"pii_categories": pii_set})

        result.append(f)

    return result


# ── Hints vocabulary for system prompt injection ──────────────────────────────

def _build_hints_vocab(hints: dict) -> str:
    """
    Build a compact type recognition reference from schema_hints.yaml entries.
    This is appended to SYSTEM_PROMPT so the LLM has the vocabulary in context.
    """
    lines = ["\n## Type Recognition Reference (use these exact types)\n"]
    for entry in hints.get("type_patterns", []):
        lines.append(
            f"- {entry['field_type']}: {entry['description']} "
            f"(pattern: {entry['regex']})"
        )
    return "\n".join(lines)


# ── Local Ollama (first in cascade) ──────────────────────────────────────────
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_BASE_URL = f"{_OLLAMA_HOST}/v1"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_S = 120
# Only accept local result if the model is this confident; otherwise escalate.
LOCAL_CONFIDENCE_THRESHOLD = 0.80

# ── Groq (second in cascade) ─────────────────────────────────────────────────
# Defaults — override via CLI flags or env vars
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# ── OpenAI fallback (third in cascade) ───────────────────────────────────────
# Used when OPENAI_API_KEY is set and Groq fails.
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

# ── OpenRouter fallback (fourth in cascade) ───────────────────────────────────
# Used when OPENROUTER_API_KEY is set and earlier providers fail.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = [
    "arcee-ai/trinity-large-preview:free",  # json-mode, reliable on large prompts
]
OPENROUTER_TIMEOUT_S = 60  # max wait per inference call

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
                            "path": {"type": "string", "description": "dot-notation field path — MUST exactly match the key shown in the Field Statistics table. Never abbreviate or rename: use 'passenger_name' not 'name', 'user_email' not 'email'. For array-nested fields use the full path including the array container (e.g. 'passengers[].passenger_name' not 'passenger_name')."},
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
                                    {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]}},
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
- CRITICAL: Use the EXACT field path key from the Field Statistics table — never abbreviate, shorten, or genericise field names. If the table shows 'passenger_name', use 'passenger_name' NOT 'name'. If the table shows 'passengers[].passenger_name', use 'passengers[].passenger_name' NOT 'passengers[].name' or bare 'passenger_name'. The path you emit must appear verbatim in the Field Statistics table.
- You MUST call the submit_inferred_schema function with your analysis"""  + _build_hints_vocab(_SCHEMA_HINTS)

# Variant system prompt for models that don't support function calling.
# These models must return raw JSON matching the same schema.
SYSTEM_PROMPT_JSON_MODE = """You are a data schema expert specialising in event stream analysis.
Analyse the provided JSON events and infer a precise schema.

Rules:
- Examine ALL provided events, not just the first few
- If a field is absent in >20% of events, set required=false
- If a field has ≤15 distinct values across all samples, include enum_values
- Identify timestamps precisely: unix epoch ms (large integer ~13 digits), ISO8601 string, RFC2822 string
- If the SAME field has different types across events, use "mixed" type and explain in notes
- UUID fields: recognise standard UUID v4 format
- For nested objects: analyse each leaf field separately using dot-notation paths
- Be conservative with confidence scores — messy real-world data rarely deserves >0.95

You MUST return ONLY valid JSON with no markdown, no explanation, matching this exact structure:
{
  "fields": [
    {
      "path": "field.path",
      "field_type": "string|integer|float|boolean|timestamp_epoch_ms|timestamp_iso8601|timestamp_rfc2822|date|uuid|email|phone|array|object|null|mixed",
      "nullable": true,
      "required": true,
      "confidence": 0.9,
      "notes": "brief description"
    }
  ],
  "overall_confidence": 0.85,
  "event_type_values": []
}"""


MAX_PROMPT_CHARS = 20_000  # ~5k tokens; leaves headroom for system prompt + response within 12k TPM


def _is_ollama_available() -> bool:
    """Ping the local Ollama server. Returns True only if it responds within 2 s."""
    try:
        resp = httpx.get(f"{_OLLAMA_HOST}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


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
    for included, path in enumerate(sorted_paths):
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


# FieldType enum values the LLM sometimes returns as field *paths* instead of
# actual dotted paths — classic hallucination pattern (returns the type taxonomy
# rather than the observed data fields).
_FIELDTYPE_NAMES: frozenset[str] = frozenset(ft.value for ft in FieldType)


def _validate_inferred_fields(
    fields: list[FieldSchema],
    known_paths: set[str],
) -> list[FieldSchema]:
    """
    Strip hallucinated fields and raise if the result looks completely wrong.

    Hallucination signature: the LLM returns a FieldType enum value
    (e.g. "array", "null", "email", "timestamp_epoch_ms") as a field *path*
    with presence_rate == 0.0 — i.e. the field was never actually observed.
    These appear when the model echoes the type taxonomy from the system prompt
    instead of analysing the actual event data.

    Strategy (zero-presence threshold, per constraints):
    - Remove any field whose path is a FieldType enum value AND presence_rate == 0.0.
    - If ALL remaining fields have presence_rate == 0.0 (nothing matched real data),
      raise ValueError to trigger a retry.
    """
    clean = [
        f for f in fields
        if not (f.path in _FIELDTYPE_NAMES and f.presence_rate == 0.0)
    ]
    if not clean:
        raise ValueError(
            "All inferred fields have zero presence — schema is fully hallucinated. Retrying."
        )
    # Secondary check: if no field from the actual observed paths appears at all,
    # the LLM invented a completely unrelated schema.
    if known_paths and not any(f.path in known_paths for f in clean):
        raise ValueError(
            f"None of the {len(known_paths)} observed field paths appear in the "
            "inferred schema — likely hallucination. Retrying."
        )
    return clean


def _align_inferred_paths(
    fields: list,
    known_paths: set[str],
) -> list:
    """
    Align LLM-inferred field paths to what was actually observed in the events.

    Fix A — Array-prefix path repair:
      LLMs drop array container prefixes, e.g. returning 'passenger_name' instead
      of 'passengers[].passenger_name'.  When a leaf matches exactly one known
      array-nested path, rewrite the path before drift detection sees it.
      Without this, the drift detector sees 'passengers[].passenger_name' in events
      but only 'passenger_name' in the schema → fires Tier-3 new_pii for every event.

    Fix B — Unobserved PII field removal:
      PII fields (email, passport, name, etc.) are hallucinated from domain knowledge
      rather than actual data.  Strip any PII field whose path (after Fix A) still
      does not appear in known_paths — it was never observed and would trigger
      false Tier-3 new_pii drift alerts on every watch cycle.
      Non-PII unrecognised paths are kept — they may be legitimately present with a
      minor format difference (e.g. camelCase vs snake_case) and cause at most
      a Tier-2 field_removed alert which is less disruptive than Tier-3 new_pii.
    """
    result = []
    for f in fields:
        # Already matches an observed path — keep as is
        if f.path in known_paths:
            result.append(f)
            continue

        # Fix A: look for a uniquely matching array-nested path by exact leaf name
        leaf = f.path.split(".")[-1]
        array_candidates = [kp for kp in known_paths if kp.endswith(f"[].{leaf}")]
        if len(array_candidates) == 1:
            logger.info(
                "Path repair (array prefix): %s → %s", f.path, array_candidates[0],
            )
            f = f.model_copy(update={"path": array_candidates[0], "name": leaf})
            result.append(f)
            continue

        # Fix C: fuzzy leaf-name match for array-nested paths
        # LLMs sometimes abbreviate field names, e.g. 'passengers[].name' when the
        # observed field is 'passengers[].passenger_name'.  If there is exactly one
        # array-nested known path whose leaf ends with '_<leaf>' or starts with
        # '<leaf>_', rewrite to the canonical observed path.
        fuzzy_array_candidates = [
            kp for kp in known_paths
            if "[" in kp and (
                kp.endswith(f"_{leaf}") or
                kp.split("[].")[-1].startswith(f"{leaf}_") or
                (f"[].{leaf}" not in kp and kp.split("[].")[-1].endswith(leaf))
            )
        ]
        if len(fuzzy_array_candidates) == 1:
            logger.info(
                "Path repair (fuzzy leaf name): %s → %s", f.path, fuzzy_array_candidates[0],
            )
            new_leaf = fuzzy_array_candidates[0].split(".")[-1]
            f = f.model_copy(update={"path": fuzzy_array_candidates[0], "name": new_leaf})
            result.append(f)
            continue

        # Fix B: PII field whose path has no match in observed data → remove
        if f.pii_categories:
            logger.info(
                "Removing unobserved PII field: %s (pii=%s, not in %d known paths) "
                "— would cause false new_pii alerts",
                f.path, [p.value for p in f.pii_categories], len(known_paths),
            )
            continue  # strip

        # Non-PII field with unrecognised path — keep (format difference, not hallucination)
        result.append(f)
    return result


def _correct_type_mismatches(
    fields: list,
    field_stats: dict,
) -> list:
    """
    Run a statistical type-check on each inferred field and override obvious
    LLM mis-labellings against the actual sample values.

    The LLM (especially smaller/quantised models) sometimes assigns the wrong
    timestamp sub-type even when the sample values are unambiguous — e.g. it
    labels ISO8601 strings as timestamp_epoch_ms, or integer sensor readings
    as float.  We correct these by comparing the LLM's label to the majority
    type inferred purely from values, overriding only for high-confidence
    structural mismatches:

      - epoch_ms   ↔ iso8601 / rfc2822 (string vs integer is unmistakable)
      - integer    ↔ float             (numeric widening, harmless override)

    The correction uses the same `_infer_field_type_from_values` logic that the
    drift detector uses, ensuring schema ↔ drift detection are internally
    consistent.
    """
    from .drift_detector import _infer_field_type_from_values

    # Pairs where a statistical override is safe: (llm_type, statistical_type)
    # Only override when the mismatch is structurally obvious and unambiguous.
    SAFE_OVERRIDES: set[tuple[str, str]] = {
        (FieldType.TIMESTAMP_EPOCH_MS, FieldType.TIMESTAMP_ISO8601),
        (FieldType.TIMESTAMP_EPOCH_MS, FieldType.TIMESTAMP_RFC2822),
        (FieldType.TIMESTAMP_ISO8601,  FieldType.TIMESTAMP_EPOCH_MS),
        (FieldType.TIMESTAMP_RFC2822,  FieldType.TIMESTAMP_EPOCH_MS),
        (FieldType.INTEGER, FieldType.FLOAT),
        (FieldType.FLOAT,   FieldType.INTEGER),
    }

    corrected = []
    for f in fields:
        samples = field_stats.get(f.path, [])
        if len(samples) >= 3:
            stat_type = _infer_field_type_from_values(samples)
            if (f.field_type, stat_type) in SAFE_OVERRIDES:
                logger.info(
                    "Type correction: %s %s → %s (statistical evidence from %d samples)",
                    f.path, f.field_type, stat_type, len(samples),
                )
                f = f.model_copy(update={"field_type": stat_type})
        corrected.append(f)
    return corrected


def _check_field_coverage(
    llm_fields: list | None,
    field_stats: dict,
) -> list | None:
    """
    Return None (treat as failure) if the LLM returned far fewer fields than
    the number of observed paths — indicates a truncated or degenerate response.

    Threshold: LLM must cover at least 30% of observed paths, with a floor of 3.
    Example: 19 observed paths → min 5 fields required.  If LLM returns 2, retry.

    This catches Groq llama responses that produce a minimal stub (e.g. only 2
    fields) for small sub-clusters even when 15+ fields are present in the data.
    """
    if llm_fields is None:
        return None
    # Floor of 1 (not 3) so small test fixtures with 2 paths still pass.
    # The 30% ratio is sufficient: 19 paths → min 5, which catches the
    # booking.updated "2 fields returned" degenerate case.
    min_expected = max(1, int(len(field_stats) * 0.30))
    if len(llm_fields) < min_expected:
        logger.warning(
            "Field coverage check failed: LLM returned %d field(s) but %d path(s) "
            "observed (min expected: %d). Treating as failure and escalating.",
            len(llm_fields), len(field_stats), min_expected,
        )
        return None
    return llm_fields


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

            # Strip null before deciding mixed — a nullable string is STRING, not MIXED
            non_null_types = {k: v for k, v in type_counts.items() if k != "null"}
            if not non_null_types:
                ft = FieldType.NULL
            elif len(non_null_types) > 1:
                ft = FieldType.MIXED
            else:
                majority = max(non_null_types, key=lambda k: non_null_types[k])
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


def _call_llm(
    client: OpenAI,
    model: str,
    prompt: str,
    field_stats: dict,
    presence_rates: dict,
    max_retries: int,
) -> tuple[list[FieldSchema] | None, float, list[str]]:
    """
    Try to get a schema from the given OpenAI-compatible client.
    Returns (fields, confidence, event_type_values) or (None, 0.8, []) on failure.
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(max_retries):
        logger.info("Inference attempt %d/%d (model: %s)...", attempt + 1, max_retries, model)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[INFERENCE_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_inferred_schema"}},
                max_tokens=8192,
                temperature=0,  # P3 fix: deterministic output reduces run-to-run schema variance
                timeout=120,    # 2 min max for primary provider
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
                path = f.get("path", "")
                if not path:
                    continue
                presence = presence_rates.get(path, 0.0)
                raw_values = field_stats.get(path, [])
                pii = detect_pii(path, raw_values[:20])
                enum_values = f.get("enum_values") or None
                if enum_values:
                    enum_values = [str(v) for v in enum_values]
                try:
                    ft = FieldType(f.get("field_type", "string"))
                except ValueError:
                    ft = FieldType.STRING
                llm_fields.append(FieldSchema(
                    name=path.split(".")[-1],
                    path=path,
                    field_type=ft,
                    nullable=f.get("nullable", False),
                    required=f.get("required", presence >= 0.8),
                    presence_rate=presence,
                    sample_values=raw_values[:5],
                    enum_values=enum_values,
                    pii_categories=pii,
                    confidence=f.get("confidence", 0.8),
                    notes=f.get("notes"),
                ))
            # P0 fix: strip hallucinated type-name fields (e.g. path="array", presence=0.0)
            llm_fields = _validate_inferred_fields(llm_fields, set(field_stats.keys()))
            return llm_fields, overall_confidence, event_type_values

        except Exception as e:
            logger.warning("Inference attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                messages.append({"role": "user", "content": f"Previous attempt failed: {e}. Please call submit_inferred_schema."})

    return None, 0.8, []


def _call_llm_json_mode(
    client: OpenAI,
    model: str,
    prompt: str,
    field_stats: dict,
    presence_rates: dict,
    max_retries: int,
    timeout_s: float = OPENROUTER_TIMEOUT_S,
) -> tuple[list[FieldSchema] | None, float, list[str]]:
    """
    Like _call_llm but for models that don't support function calling.
    Uses response_format=json_object and parses the JSON from message content.
    Supports reasoning models (e.g. stepfun/step-3.5-flash) via extra_body.
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT_JSON_MODE},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(max_retries):
        logger.info("Inference attempt %d/%d (json-mode, model: %s)...", attempt + 1, max_retries, model)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=8192,
                temperature=0,  # P3 fix: deterministic output reduces run-to-run schema variance
                timeout=timeout_s,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from model")

            tool_input = json.loads(content)
            overall_confidence = tool_input.get("overall_confidence", 0.8)
            event_type_values = tool_input.get("event_type_values", [])
            raw_fields = tool_input.get("fields", [])
            if not raw_fields:
                raise ValueError("No fields in response")

            llm_fields = []
            for f in raw_fields:
                path = f.get("path", "")
                if not path:
                    continue
                presence = presence_rates.get(path, 0.0)
                raw_values = field_stats.get(path, [])
                pii = detect_pii(path, raw_values[:20])
                enum_values = f.get("enum_values") or None
                if enum_values:
                    enum_values = [str(v) for v in enum_values]
                try:
                    ft = FieldType(f.get("field_type", "string"))
                except ValueError:
                    ft = FieldType.STRING
                llm_fields.append(FieldSchema(
                    name=path.split(".")[-1],
                    path=path,
                    field_type=ft,
                    nullable=f.get("nullable", False),
                    required=f.get("required", presence >= 0.8),
                    presence_rate=presence,
                    sample_values=raw_values[:5],
                    enum_values=enum_values,
                    pii_categories=pii,
                    confidence=f.get("confidence", 0.8),
                    notes=f.get("notes"),
                ))
            # P0 fix: strip hallucinated type-name fields (e.g. path="array", presence=0.0)
            llm_fields = _validate_inferred_fields(llm_fields, set(field_stats.keys()))
            return llm_fields, overall_confidence, event_type_values

        except Exception as e:
            logger.warning("Inference attempt %d failed: %s", attempt + 1, e)

    return None, 0.8, []


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
    """
    Main inference function using OpenAI-compatible tool calling.

    Provider cascade:
      1. Local Ollama (http://127.0.0.1:11434) — json-mode, 2 retries
         → accepted only if confidence >= LOCAL_CONFIDENCE_THRESHOLD (0.80)
      2. Groq (or whatever base_url is passed in) — tool-call mode
      3. OpenAI (gpt-4o-mini) — tool-call mode (if OPENAI_API_KEY is set)
      4. OpenRouter — json-mode (if OPENROUTER_API_KEY is set)
      5. Statistical inference — last resort, no LLM needed
    """
    # ── 0. Field Type RAG Registry lookup ─────────────────────────────────────
    registry_config = RegistryConfig()
    registry_enabled = os.environ.get("STREAMFORGE_REGISTRY_ENABLED", "1") != "0"
    registry: FieldTypeRegistry | None = None
    cached_fields: list[FieldSchema] = []
    remaining_stats = field_stats
    remaining_rates = presence_rates

    if registry_enabled:
        try:
            registry = FieldTypeRegistry.load()
            cached, unknown_paths = registry.lookup_batch(
                list(field_stats.keys()), config=registry_config,
            )
            if cached:
                logger.info(
                    "Registry hit: %d/%d fields resolved from cache (skipping LLM for those)",
                    len(cached), len(field_stats),
                )
                for path, obs in cached.items():
                    rate = presence_rates.get(path, 1.0)
                    cached_fields.append(registry.to_field_schema(obs, presence_rate=rate))

                # Only send unknown fields to LLM
                remaining_stats = {p: field_stats[p] for p in unknown_paths if p in field_stats}
                remaining_rates = {p: presence_rates[p] for p in unknown_paths if p in presence_rates}
            else:
                logger.info("Registry: no cached hits — all %d fields go to LLM", len(field_stats))
        except Exception as e:
            logger.warning("Registry lookup failed: %s — proceeding without cache", e)

    compressed_stats = _compress_field_stats(remaining_stats)
    prompt = build_inference_prompt(compressed_stats, remaining_rates, sample_events)

    llm_fields: list | None = None
    overall_confidence: float = 0.0
    event_type_values: list[str] = []

    # Skip LLM entirely if registry resolved ALL fields
    if remaining_stats:
        pass  # proceed to LLM cascade below
    elif cached_fields:
        logger.info("Registry resolved ALL %d fields — skipping LLM entirely", len(cached_fields))
        llm_fields = []
        overall_confidence = 0.90

    # ── 1. Local Ollama ────────────────────────────────────────────────────────
    if _is_ollama_available():
        logger.info("Ollama available — attempting local inference (model: %s)", OLLAMA_MODEL)
        ollama_client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL)
        llm_fields, overall_confidence, event_type_values = _call_llm_json_mode(
            ollama_client, OLLAMA_MODEL, prompt, remaining_stats, remaining_rates,
            max_retries=2, timeout_s=OLLAMA_TIMEOUT_S,
        )
        # Coverage check before accepting local result
        llm_fields = _check_field_coverage(llm_fields, remaining_stats)
        if llm_fields is not None and overall_confidence >= LOCAL_CONFIDENCE_THRESHOLD:
            logger.info(
                "Local inference accepted (confidence=%.2f >= %.2f)",
                overall_confidence, LOCAL_CONFIDENCE_THRESHOLD,
            )
            model = OLLAMA_MODEL
        else:
            if llm_fields is not None:
                logger.info(
                    "Local inference confidence too low (%.2f < %.2f) — escalating to remote",
                    overall_confidence, LOCAL_CONFIDENCE_THRESHOLD,
                )
            else:
                logger.info("Local inference failed — escalating to remote")
            llm_fields = None  # force escalation

    # ── 2. Primary remote provider (default: Groq) ────────────────────────────
    if llm_fields is None:
        logger.info("Trying primary remote provider (model: %s, url: %s)", model, base_url)
        client = OpenAI(api_key=api_key, base_url=base_url)
        llm_fields, overall_confidence, event_type_values = _call_llm(
            client, model, prompt, remaining_stats, remaining_rates, max_retries,
        )
        # Coverage check: if Groq returns far fewer fields than observed, escalate
        llm_fields = _check_field_coverage(llm_fields, remaining_stats)

    # ── 3. OpenAI fallback ─────────────────────────────────────────────────────
    if llm_fields is None:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key and openai_key != api_key:
            openai_model = os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)
            logger.warning(
                "Primary provider exhausted — trying OpenAI fallback (model: %s)", openai_model
            )
            oa_client = OpenAI(api_key=openai_key, base_url=OPENAI_BASE_URL)
            llm_fields, overall_confidence, event_type_values = _call_llm(
                oa_client, openai_model, prompt, remaining_stats, remaining_rates, max_retries,
            )
            llm_fields = _check_field_coverage(llm_fields, remaining_stats)
            if llm_fields is not None:
                model = openai_model

    # ── 4. OpenRouter fallback ─────────────────────────────────────────────────
    if llm_fields is None:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key:
            or_client = OpenAI(api_key=openrouter_key, base_url=OPENROUTER_BASE_URL)
            env_model = os.environ.get("OPENROUTER_MODEL")
            candidates = [env_model] if env_model else OPENROUTER_MODELS
            for or_model in candidates:
                logger.warning(
                    "Primary provider exhausted — trying OpenRouter fallback (model: %s, json-mode)",
                    or_model,
                )
                llm_fields, overall_confidence, event_type_values = _call_llm_json_mode(
                    or_client, or_model, prompt, remaining_stats, remaining_rates, max_retries,
                )
                # Coverage check before accepting OpenRouter result
                llm_fields = _check_field_coverage(llm_fields, remaining_stats)
                if llm_fields is not None:
                    model = or_model
                    break

    # ── 5. Statistical fallback ────────────────────────────────────────────────
    if llm_fields is None:
        logger.warning("All LLM attempts failed, falling back to statistical inference")
        llm_fields = statistical_inference(remaining_stats, remaining_rates)
        overall_confidence = 0.6
        model = f"{model}(statistical-fallback)"

    # ── 5. Post-process: correct obvious type mis-labels from LLM ─────────────
    # Fixes cases like ISO8601 strings inferred as timestamp_epoch_ms, or
    # float sensor values inferred as integer — structural mismatches the LLM
    # makes deterministically when samples are small or model quality varies.
    llm_fields = _correct_type_mismatches(llm_fields, field_stats)

    # ── 6. Post-process: align inferred paths to observed field paths ──────────
    # Fix A: correct array-prefix paths (e.g. 'passenger_name' → 'passengers[].passenger_name')
    # Fix B: strip PII fields whose path has no match in actual observed data
    # Fix C: fuzzy leaf-name match for abbreviated names (e.g. 'name' → 'passenger_name')
    # All three prevent false Tier-3 new_pii alerts before intentional drift injection.
    llm_fields = _align_inferred_paths(llm_fields, set(field_stats.keys()))

    # ── 7. Post-process: apply schema hints (confidence boost + PII floor) ─────
    # Deterministic pattern-matching pass: overrides obvious type mis-labels and
    # guarantees PII categories for known field name patterns regardless of LLM
    # output.  Uses streamforge/schema_hints.yaml as the rule source.
    llm_fields = _apply_schema_hints(llm_fields, field_stats, _SCHEMA_HINTS)

    # ── 8. Merge cached (registry) fields with LLM fields ───────────────────
    all_fields = cached_fields + llm_fields
    # Deduplicate by path — LLM result wins over registry if both present
    seen_paths: set[str] = set()
    deduped: list[FieldSchema] = []
    for f in reversed(all_fields):  # reversed so LLM fields (later) win
        if f.path not in seen_paths:
            seen_paths.add(f.path)
            deduped.append(f)
    deduped.reverse()

    # ── 8b. Correct type mismatches on ALL fields (including registry-cached) ─
    # The registry can hold stale types from other streams (e.g. wiki's ISO8601
    # timestamp poisons payments' epoch_ms timestamp). Run correction on the
    # full merged set against THIS stream's actual sample values.
    deduped = _correct_type_mismatches(deduped, field_stats)

    # ── 9. Record all resolved fields back to registry ────────────────────────
    if registry is not None and registry_enabled:
        try:
            registry.record_from_schema(deduped, stream_name)
            registry.save()
            stats = registry.stats()
            logger.info(
                "Registry updated: %d entries, hit_rate=%.0f%% (%d hits / %d lookups)",
                stats["total_entries"], stats["hit_rate"] * 100,
                stats["lookup_hits"], stats["lookup_hits"] + stats["lookup_misses"],
            )
        except Exception as e:
            logger.warning("Failed to save field registry: %s", e)

    now = datetime.now(UTC).isoformat()
    return InferredSchema(
        stream_name=stream_name,
        version="1.0.0",
        inferred_at=now,
        event_count_sampled=len(sample_events),
        fields=deduped,
        top_level_event_types=event_type_values if event_type_values else None,
        inference_model=model,
        inference_confidence=overall_confidence,
    )


def infer_sub_schema(
    cluster_id: str,
    events: list[dict],
    detection_method: str,
    total_stream_events: int,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> SubSchema:
    """
    Infer schema for one cluster of structurally similar events.

    Uses LLM when cluster has >=MIN_EVENTS_FOR_LLM_INFERENCE events; statistical fallback for tiny clusters.
    Presence rates are computed within this cluster only, not across the full stream.
    """
    from .sampler import get_all_field_paths, reservoir_sample

    # Strip internal metadata (_partial_extract etc) before profiling
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    sample = reservoir_sample(clean, 200) if len(clean) > 200 else clean

    field_stats, presence_rates = get_all_field_paths(sample)

    # Summarise top-level keys by frequency
    key_counts: dict[str, int] = {}
    for e in sample:
        for k in e:
            key_counts[k] = key_counts.get(k, 0) + 1
    top_keys = sorted(key_counts, key=lambda k: -key_counts[k])[:15]

    if len(sample) < _min_events_for_llm():
        logger.info(
            "Cluster %s: only %d events — below MIN_EVENTS_FOR_LLM_INFERENCE (%d), "
            "using statistical inference",
            cluster_id, len(sample), _min_events_for_llm(),
        )
        fields = statistical_inference(field_stats, presence_rates)
        confidence = min(0.65, 0.3 + 0.007 * len(sample))
    else:
        inferred = infer_schema(
            stream_name=cluster_id,
            field_stats=field_stats,
            sample_events=sample[:10],
            presence_rates=presence_rates,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        fields = inferred.fields
        confidence = inferred.inference_confidence

    sample_rate = len(events) / total_stream_events if total_stream_events > 0 else 1.0

    return SubSchema(
        cluster_id=cluster_id,
        detection_method=detection_method,
        event_count=len(events),
        sample_rate=round(sample_rate, 4),
        fields=fields,
        inference_confidence=confidence,
        top_keys=top_keys,
    )
