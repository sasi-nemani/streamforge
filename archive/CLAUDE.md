# CLAUDE.md — StreamForge MVP Build Instructions

## What You Are Building

StreamForge is an AI-native schema inference and drift detection tool for event streams.
Think "Terraform for data schemas" — declarative, version-controlled, AI-inferred.

This MVP uses a **local folder of NDJSON files** as the event source (simulating Kafka).
The architecture is designed so the file reader can be swapped for a real Kafka consumer
with zero changes to the inference, schema writing, or drift detection layers.

## MVP Scope — Build Exactly This, Nothing More

### Three commands, that's the entire MVP:

```
python -m streamforge init <stream_path>     # Infer schema from event files → schema.yaml
python -m streamforge watch <stream_path>    # Continuous drift detection vs schema.yaml
python -m streamforge report <stream_path>   # Print current schema + drift history
```

### What each command produces:

**init** produces:
```
schemas/
  <stream_name>/
    schema.yaml          ← inferred schema, human-readable, git-committable
    inference_report.md  ← confidence per field, PII flags, anomalies found
    .samples/
      latest.json        ← the events used for inference (for reproducibility)
```

**watch** produces (continuously):
```
drift_reports/
  <stream_name>/
    YYYY-MM-DD-HHMM.md   ← structured drift report when drift detected
```
Console output: live status ticker, highlighted drift events

**report** produces:
Console: formatted schema + drift history summary

---

## Project Structure

```
streamforge-mvp/
├── CLAUDE.md                    ← this file
├── generate_events.py           ← generates test data (already run)
├── events/                      ← test event streams (NDJSON files)
│   ├── payments/
│   │   ├── stream_v1/           ← clean-ish payments (300 events)
│   │   └── stream_v2_drift/     ← drifted payments (200 events) — use to test drift
│   ├── flights/stream/          ← flight events (400 events)
│   ├── bookings/stream/         ← booking events with PII (250 events)
│   └── iot/stream/              ← sensor events (500 events)
├── schemas/                     ← git-committable schema output (created by init)
├── drift_reports/               ← drift report output (created by watch)
├── streamforge/                 ← the package
│   ├── __init__.py
│   ├── __main__.py              ← CLI entry point
│   ├── sampler.py               ← event file reader + reservoir sampler
│   ├── inference.py             ← LLM schema inference engine
│   ├── schema_writer.py         ← JSON Schema → schema.yaml writer
│   ├── drift_detector.py        ← continuous drift detection engine
│   ├── report_writer.py         ← markdown report generator
│   ├── pii_detector.py          ← PII field detection
│   └── models.py                ← Pydantic models for all internal types
├── tests/
│   ├── test_sampler.py
│   ├── test_inference.py
│   ├── test_drift_detector.py
│   └── fixtures/                ← small static event fixtures for unit tests
├── pyproject.toml
└── README.md
```

---

## Implementation — Build In This Exact Order

### Step 1: models.py — Define All Data Structures First

```python
# All internal types. Build these before anything else.
# Every module imports from here — no ad-hoc dicts.

from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum

class FieldType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    TIMESTAMP_EPOCH_MS = "timestamp_epoch_ms"
    TIMESTAMP_ISO8601 = "timestamp_iso8601"
    TIMESTAMP_RFC2822 = "timestamp_rfc2822"
    DATE = "date"
    UUID = "uuid"
    EMAIL = "email"
    PHONE = "phone"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"
    MIXED = "mixed"  # type inconsistency detected

class PIICategory(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    NAME = "name"
    PASSPORT = "passport"
    CARD_NUMBER = "card_number"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"
    NATIONAL_ID = "national_id"
    ADDRESS = "address"
    LOYALTY_NUMBER = "loyalty_number"

class DriftTier(int, Enum):
    TIER_1 = 1  # Trivial — non-breaking
    TIER_2 = 2  # Manageable — breaking but auto-correctable
    TIER_3 = 3  # Critical — data integrity risk, human required

class FieldSchema(BaseModel):
    name: str
    path: str                        # dot-notation path e.g. "user.email"
    field_type: FieldType
    nullable: bool = False
    required: bool = True            # present in >80% of events
    presence_rate: float = 1.0       # 0.0-1.0
    sample_values: list[Any] = []    # up to 5 distinct examples
    enum_values: Optional[list[str]] = None   # if <15 distinct values
    pii_categories: list[PIICategory] = []
    confidence: float = 1.0          # 0.0-1.0 — how confident the inference is
    notes: Optional[str] = None      # LLM-generated field description

class InferredSchema(BaseModel):
    stream_name: str
    version: str = "1.0.0"
    inferred_at: str
    event_count_sampled: int
    fields: list[FieldSchema]
    top_level_event_types: Optional[list[str]] = None  # if event_type field exists
    inference_model: str
    inference_confidence: float      # overall schema confidence

class FieldDrift(BaseModel):
    field_path: str
    drift_type: str                  # type_changed | field_added | field_removed | enum_changed | format_changed
    previous_type: Optional[FieldType] = None
    observed_type: Optional[FieldType] = None
    previous_presence_rate: Optional[float] = None
    observed_presence_rate: Optional[float] = None
    previous_enum_values: Optional[list[str]] = None
    observed_enum_values: Optional[list[str]] = None
    affected_event_rate: float       # fraction of sampled events showing this drift
    tier: DriftTier
    auto_correctable: bool
    proposed_correction: Optional[str] = None
    correction_confidence: Optional[float] = None

class DriftReport(BaseModel):
    stream_name: str
    detected_at: str
    schema_version: str
    events_sampled: int
    drifts: list[FieldDrift]
    highest_tier: DriftTier
    summary: str                     # LLM-generated human-readable summary
```

---

### Step 2: sampler.py — Event File Reader

```python
# Reads NDJSON files from a folder. Implements reservoir sampling.
# This is the ONLY module that knows about the file source.
# Everything else works on List[dict] — swap this for Kafka later.

# Key functions to implement:

def load_events_from_folder(folder_path: str) -> list[dict]:
    """
    Load all .ndjson and .json files from folder (recursive).
    Each line in NDJSON = one event.
    Skip malformed lines, log count of skipped.
    Return flat list of parsed dicts.
    """

def reservoir_sample(events: list[dict], n: int = 500) -> list[dict]:
    """
    Algorithm R reservoir sampling.
    Returns n events sampled uniformly at random.
    If len(events) <= n, return all events.
    """

def flatten_nested(obj: dict, prefix: str = "", sep: str = ".") -> dict:
    """
    Flatten nested dicts to dot-notation for type analysis.
    e.g. {"user": {"email": "x"}} → {"user.email": "x"}
    Arrays: flatten first element only, mark path as array.
    """

def get_all_field_paths(events: list[dict]) -> dict[str, list[Any]]:
    """
    Given a list of events, return dict of:
      field_path → list of all observed non-null values across events
    Include presence_rate (fraction of events where field appears).
    """
```

**Important sampler behaviour:**
- Files in a folder are sorted by filename before reading (chronological order matters for drift simulation)
- Log how many events were loaded and from how many files
- Handle gracefully: empty files, malformed JSON, files that are not NDJSON
- `flatten_nested` should handle arrays by flattening index 0 and noting it's an array type

---

### Step 3: pii_detector.py — PII Detection (Pattern-First)

```python
# Stage 1: regex/pattern matching (fast, no API call)
# Stage 2: field name heuristics (email → likely email PII etc)
# Do NOT call LLM for PII detection in MVP — patterns are sufficient

# Patterns to implement:
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
PHONE_PATTERN = r'\+?[1-9]\d{6,14}'  # E.164-ish
CARD_PATTERN = r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'
PASSPORT_PATTERN = r'\b[A-Z]{1,2}\d{7,9}\b'
IP_PATTERN = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
DOB_PATTERN = r'\b\d{4}-\d{2}-\d{2}\b'  # combine with field name check

# Field name heuristics (check if field path contains these substrings):
PII_NAME_HINTS = {
    PIICategory.EMAIL: ["email", "e_mail", "mail"],
    PIICategory.PHONE: ["phone", "mobile", "tel", "contact_number"],
    PIICategory.NAME: ["first_name", "last_name", "full_name", "passenger_name", "name"],
    PIICategory.PASSPORT: ["passport", "document_number"],
    PIICategory.CARD_NUMBER: ["card", "pan", "card_last_four", "card_number"],
    PIICategory.IP_ADDRESS: ["ip_address", "ip", "client_ip"],
    PIICategory.DATE_OF_BIRTH: ["dob", "date_of_birth", "birth_date", "birthdate"],
    PIICategory.LOYALTY_NUMBER: ["loyalty", "frequent_flyer", "rewards"],
}

def detect_pii(field_path: str, sample_values: list[Any]) -> list[PIICategory]:
    """
    Returns list of PII categories detected for this field.
    Check field name hints first (fast), then run patterns on sample values.
    """
```

---

### Step 4: inference.py — The Core Engine

This is the most important module. Get this right.

```python
# Uses Anthropic SDK to infer schema from sampled events.
# Structured output via tool_use — non-negotiable.
# Falls back to statistical inference if LLM fails 3 times.

import anthropic
from .models import InferredSchema, FieldSchema, FieldType
from .pii_detector import detect_pii

INFERENCE_TOOL = {
    "name": "submit_inferred_schema",
    "description": "Submit the inferred schema for the event stream",
    "input_schema": {
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
                            "type": "array", "items": {"type": "string"},
                            "description": "Include only if field has <15 distinct values"
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
- In notes: describe what the field likely represents based on its name and values"""

def infer_schema(
    stream_name: str,
    field_stats: dict[str, list],   # output of get_all_field_paths()
    sample_events: list[dict],
    presence_rates: dict[str, float],
    api_key: str,
    max_retries: int = 3
) -> InferredSchema:
    """
    Main inference function.
    
    Strategy:
    1. Build a compact representation of field stats to stay within context
       (show up to 8 distinct sample values per field, not all values)
    2. Call Claude with tool_use, force tool response
    3. Validate Pydantic model from tool input
    4. If validation fails, retry with error context added to messages
    5. After 3 failures, fall back to statistical_inference()
    6. Post-process: run pii_detector on all fields, add presence_rates
    """

def build_inference_prompt(field_stats: dict, presence_rates: dict, sample_events: list[dict]) -> str:
    """
    Build the user message for the inference call.
    Include:
    - Field statistics table (path, sample_values, presence_rate)
    - Up to 10 full sample events (verbatim JSON) for context
    Keep total under 80k tokens.
    """

def statistical_inference(field_stats: dict, presence_rates: dict) -> list[FieldSchema]:
    """
    Fallback: pure statistical type inference without LLM.
    Uses majority vote on observed Python types.
    Lower confidence scores (max 0.7).
    Called only if LLM inference fails 3 times.
    """
```

**Critical implementation notes for inference.py:**
- Use `client.messages.create(..., tools=[INFERENCE_TOOL], tool_choice={"type": "tool", "name": "submit_inferred_schema"})`
- Force the tool call — do not let the model respond in text
- The `field_stats` input should be pre-compressed: max 8 sample values per field, truncate long strings to 100 chars
- Add `presence_rate` to each field after getting LLM response (LLM doesn't see raw counts)
- Run `detect_pii()` on every field after inference and merge results

---

### Step 5: schema_writer.py — Schema YAML Output

```python
# Converts InferredSchema → schema.yaml (human-readable, git-committable)
# Also writes inference_report.md

SCHEMA_YAML_TEMPLATE = """
# StreamForge Schema — {stream_name}
# Version: {version}
# Inferred: {inferred_at}
# Events sampled: {event_count}
# Overall confidence: {confidence:.0%}
# 
# This file is the source of truth for stream: {stream_name}
# Edit this file to declare corrections. Run 'streamforge watch' to detect future drift.

stream: {stream_name}
version: "{version}"
inferred_at: "{inferred_at}"
inference_confidence: {confidence}

fields:
{fields_yaml}
"""

# Each field block should look like:
# - path: user.email
#   type: email
#   required: true
#   nullable: false
#   pii: [email]
#   confidence: 0.99
#   notes: "User email address. PII — handle per GDPR."
#   # enum_values: [VAL1, VAL2]   ← only if enum detected

def write_schema(schema: InferredSchema, output_dir: str) -> str:
    """Write schema.yaml. Returns path written."""

def write_inference_report(schema: InferredSchema, output_dir: str) -> str:
    """
    Write inference_report.md.
    Include:
    - Summary table: field | type | required | confidence | PII
    - PII section: all flagged fields with category
    - Low confidence section: fields with confidence < 0.8
    - Mixed type section: any MIXED type fields with explanation
    - Anomalies: fields that appeared in <10% of events
    Returns path written.
    """

def load_schema(schema_path: str) -> InferredSchema:
    """Load a schema.yaml back into InferredSchema model."""
```

---

### Step 6: drift_detector.py — The Watch Engine

```python
# Runs continuously, detects drift vs declared schema.yaml
# This is what makes StreamForge operationally useful

import time
from .models import InferredSchema, FieldDrift, DriftReport, DriftTier, FieldType

# Thresholds — make these configurable via env vars
TYPE_DRIFT_THRESHOLD = 0.05         # >5% of events showing different type = drift
PRESENCE_DRIFT_THRESHOLD = 0.15     # presence rate changed by >15 percentage points
ENUM_DRIFT_THRESHOLD = 0.05         # new enum values in >5% of events

def detect_drift(
    baseline_schema: InferredSchema,
    new_sample: list[dict],
    stream_name: str
) -> Optional[DriftReport]:
    """
    Compare new_sample against baseline_schema.
    Returns DriftReport if any drift detected, None if clean.
    
    Check for:
    1. Type changes: was string, now integer in >5% of events
    2. New fields: field appears in >20% of new events, not in baseline
    3. Removed fields: field in baseline, present in <5% of new events  
    4. Enum drift: new values appearing in existing enum field
    5. Presence rate change: field was required (>80%), now optional (<65%)
    6. Format change: timestamp was epoch, now ISO (detectable from type inference)
    """

def classify_drift_tier(drift: FieldDrift) -> DriftTier:
    """
    Classify drift into Tier 1/2/3:
    
    Tier 1 (trivial, silent):
    - New optional field added (presence_rate < 0.5 in new sample)
    - Presence rate increased (more data, not less)
    
    Tier 2 (breaking but manageable):
    - Type changed but semantically equivalent (epoch→ISO timestamp)
    - Field renamed (old field gone, new similar-named field appears)
    - Enum values expanded (new values added)
    - Type widened (integer→float, string→mixed)
    
    Tier 3 (critical, block):
    - Required field removed (was >80% presence, now <20%)
    - Type narrowed incompatibly (string→integer, mixed→enum)
    - PII field newly appears (card number, passport in new events)
    - Presence rate drops >50 percentage points on required field
    """

def watch_stream(
    stream_path: str,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    webhook_url: Optional[str] = None
):
    """
    Main watch loop.
    
    Every poll_interval_seconds:
    1. Load new events from stream_path (only files modified since last check)
    2. Reservoir sample
    3. Run detect_drift() against loaded schema
    4. If drift: write drift report, print alert, optionally POST to webhook
    5. If no drift: print clean tick with timestamp
    
    Console output format:
    [14:23:01] ✓ payments.stream_v1 — 200 events sampled — schema clean
    [14:28:01] ⚠ payments.stream_v1 — DRIFT DETECTED — 1 field, Tier 2
               → created_at: type changed epoch_ms → ISO8601 (34% of events)
               → Report: drift_reports/payments.stream_v1/2026-03-11-1428.md
    [14:28:01] 🔴 payments.stream_v1 — TIER 3 DRIFT — human action required
               → amount: field removed (was 98% present, now 2%)
    """

def post_webhook(drift_report: DriftReport, webhook_url: str):
    """POST drift report as JSON to webhook URL. Fire and forget."""
```

---

### Step 7: report_writer.py — Drift Report Markdown

```python
# Writes human-readable drift reports
# These should be readable by a data engineer who didn't build StreamForge

DRIFT_REPORT_TEMPLATE = """
# Drift Report — {stream_name}
**Detected:** {detected_at}  
**Schema Version:** {schema_version}  
**Events Sampled:** {events_sampled}  
**Highest Severity:** {highest_tier_label}

---

## Summary
{summary}

---

## Drift Events ({count})

{drift_details}

---

## Affected Consumers
> Run `streamforge consumers {stream_name}` to see subscribed consumers.
> Consumers with auto_correct enabled will be notified automatically.

---

## Recommended Actions
{recommendations}
"""

def write_drift_report(report: DriftReport, output_dir: str) -> str:
    """Write dated drift report markdown. Returns path."""

def format_drift_detail(drift: FieldDrift) -> str:
    """
    Format a single drift event block:
    
    ### user.created_at
    - **Type**: `timestamp_epoch_ms` → `timestamp_iso8601`
    - **Tier**: 2 — Auto-correctable
    - **Affected events**: 34%
    - **Proposed correction**: `timestamp_parse(source.created_at)`
    - **Confidence**: 94%
    """
```

---

### Step 8: __main__.py — CLI Entry Point

```python
# Use Typer. Clean, typed, auto-generates --help.

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

app = typer.Typer(
    name="streamforge",
    help="StreamForge — AI-native schema inference and drift detection for event streams"
)
console = Console()

@app.command()
def init(
    stream_path: str = typer.Argument(..., help="Path to folder containing NDJSON event files"),
    sample_size: int = typer.Option(500, "--sample-size", "-n", help="Number of events to sample"),
    output_dir: str = typer.Option("schemas", "--output", "-o", help="Output directory for schema files"),
    api_key: str = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
):
    """Infer schema from event stream. Produces schema.yaml and inference_report.md"""

@app.command()
def watch(
    stream_path: str = typer.Argument(...),
    schema_path: str = typer.Option(None, "--schema", help="Path to schema.yaml (auto-detected if not set)"),
    interval: int = typer.Option(30, "--interval", "-i", help="Poll interval in seconds"),
    sample_size: int = typer.Option(200, "--sample-size", "-n"),
    webhook: str = typer.Option(None, "--webhook", "-w", help="Webhook URL for drift notifications"),
    api_key: str = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
):
    """Watch stream for schema drift. Runs continuously until Ctrl+C."""

@app.command()
def report(
    stream_path: str = typer.Argument(...),
):
    """Print current schema and drift history for a stream."""

@app.command()
def plan(
    stream_path: str = typer.Argument(...),
    schema_path: str = typer.Option(None, "--schema"),
    api_key: str = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
):
    """One-shot drift check. Like 'terraform plan' — shows drift without persisting."""

if __name__ == "__main__":
    app()
```

---

### Step 9: pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "streamforge-cli"
version = "0.1.0"
description = "AI-native schema inference and drift detection for event streams"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.25.0",
    "pydantic>=2.0.0",
    "typer>=0.12.0",
    "rich>=13.0.0",
    "pyyaml>=6.0",
    "python-dateutil>=2.9.0",
    "httpx>=0.27.0",    # for webhook delivery
    "watchdog>=4.0.0",  # optional: file system events for smarter watch
]

[project.scripts]
streamforge = "streamforge.__main__:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## Testing Approach

### Unit tests — no API calls, use fixtures

```python
# tests/fixtures/ should contain:
# - 20 payment events (clean)
# - 20 payment events (drifted)
# - 5 edge case events (nulls, mixed types, deeply nested)

# tests/test_sampler.py
def test_reservoir_sampling_correct_size()
def test_flatten_nested_handles_arrays()
def test_flatten_nested_deep_nesting()
def test_load_events_skips_malformed_lines()

# tests/test_drift_detector.py  
def test_detects_type_change_tier2()
def test_detects_field_removal_tier3()
def test_detects_new_optional_field_tier1()
def test_no_false_positive_on_clean_data()
def test_enum_drift_detected()

# tests/test_pii_detector.py
def test_detects_email_by_value()
def test_detects_email_by_field_name()
def test_detects_passport_pattern()
def test_detects_card_last_four_by_name()
```

### Integration test — uses real API (mark as slow)

```python
# tests/test_integration.py
# @pytest.mark.slow — skip in CI unless ANTHROPIC_API_KEY set

def test_init_on_payments_stream():
    """Run full init on events/payments/stream_v1. Verify schema.yaml produced and accurate."""
    
def test_drift_detected_between_v1_and_v2():
    """Init on stream_v1, then run detect_drift with stream_v2_drift events. 
    Verify: timestamp drift detected (Tier 2), amount→amount_minor_units (Tier 3)."""
```

---

## Demo Script — Verify Everything Works

After building, this sequence should work end-to-end:

```bash
# 1. Install
pip install -e .

# 2. Infer schema from clean payments stream
streamforge init events/payments/stream_v1 --sample-size 300

# Expected output:
# ✓ Loaded 300 events from 6 files
# ✓ Sampled 300 events (all)
# 🤖 Inferring schema with Claude...
# ✓ Schema inferred — 12 fields, confidence 0.91
# ⚠ PII detected: user.email (email), user.name (name), metadata.ip_address (ip_address)
# ✓ Written: schemas/payments.stream_v1/schema.yaml
# ✓ Written: schemas/payments.stream_v1/inference_report.md

# 3. Check what was inferred
cat schemas/payments.stream_v1/schema.yaml

# 4. Run a one-shot drift check against the drifted stream
streamforge plan events/payments/stream_v2_drift --schema schemas/payments.stream_v1/schema.yaml

# Expected output:
# ⚠ DRIFT DETECTED — 3 issues found
# 
# [TIER 3] amount — field removed (was 98% present, now 0%)
# [TIER 3] amount_minor_units — new required field (not in baseline schema)  
# [TIER 2] timestamp — format changed: timestamp_epoch_ms → timestamp_iso8601 (100% of events)
# [TIER 1] merchant_id — new optional field added
# [TIER 3] card_last_four — new PII field detected (card_number)

# 5. Run watch mode on flights stream (will poll every 10s for demo)
streamforge watch events/flights/stream --interval 10
```

---

## Success Criteria for MVP

The MVP is complete when all of the following are true:

1. `streamforge init events/payments/stream_v1` produces a `schema.yaml` where a senior data engineer reviewing it manually would rate it >85% accurate without needing to edit it
2. `streamforge plan events/payments/stream_v2_drift --schema ...` detects the timestamp drift AND the amount rename AND the new PII field (card_last_four)
3. PII detection correctly flags: `user.email`, `user.name`, `contact_email`, `contact_phone`, `passengers[].passport_number`, `card_last_four`
4. All four streams (payments, flights, bookings, iot) can be initialised without errors
5. Unit tests pass with no API calls
6. Total `streamforge init` runtime on 300 events is under 60 seconds

---

## Environment Variables

```bash
ANTHROPIC_API_KEY=sk-ant-...          # Required for init and plan commands
STREAMFORGE_LOG_LEVEL=INFO            # DEBUG | INFO | WARNING
STREAMFORGE_SAMPLE_SIZE=500           # Default sample size
STREAMFORGE_WATCH_INTERVAL=30         # Default watch poll interval (seconds)
STREAMFORGE_DRIFT_TYPE_THRESHOLD=0.05 # Fraction of events before type drift fires
STREAMFORGE_WEBHOOK_URL=              # Optional webhook for drift notifications
```

---

## What NOT to Build

Do not build any of the following — they are post-MVP:

- Kafka connector (the file reader IS the connector for now)
- Consumer transformation (the Cleaner engine)
- Marketplace UI or API
- Auto-correct mode
- HCL schema format (YAML is fine)
- Authentication or multi-user support
- Web UI of any kind
- Database/persistence layer
- Docker image or deployment config
- Rust CLI rewrite
- Any cloud integration

If you find yourself building any of the above, stop and focus on the success criteria above first.

---

## Notes on LLM Usage

- Always use `claude-sonnet-4-6` (fast, accurate, cost-effective for this use case)
- Always use `tool_use` with `tool_choice` forced — never parse free text
- Always validate LLM output with Pydantic before using it
- The inference prompt works best when you provide both field statistics AND sample events
- If the LLM is struggling with a field, it is usually because the sample values are too few — ensure at least 5 distinct values per field where possible
- Token budget: a 500-event sample with field stats fits comfortably in a single call
- Cost estimate: ~$0.02 per `streamforge init` call at Sonnet pricing
