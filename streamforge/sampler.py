import json
import logging
import random
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_resilient(line: str) -> tuple[dict, float]:
    """
    Extract a dict from any raw line with a confidence score.
    Returns (event_dict, confidence):
      1.0 — clean JSON object
      0.7 — JSON fragment found inside a log-style prefix (e.g. "2024-01-01 INFO {...}")
      0.5 — partial key:value extraction via regex
      0.0 — unparseable (returns empty dict)
    """
    line = line.strip()
    if not line:
        return {}, 0.0

    # Guard: reject oversized lines before regex (prevents ReDoS)
    _MAX_LINE_BYTES = 65_536  # 64KB
    if len(line) > _MAX_LINE_BYTES:
        return {}, 0.0

    # 1. Clean JSON
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            return obj, 1.0
    except json.JSONDecodeError:
        pass

    # 2. Embedded JSON object — find the outermost {...} in a log-prefixed line
    m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', line)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and len(obj) >= 2:
                return obj, 0.7
        except json.JSONDecodeError:
            pass

    # 3. Partial key:value extraction: match "key": value patterns
    pairs: dict = {}
    for kv in re.finditer(
        r'"([^"]{1,60})"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+\.?\d*|true|false|null)',
        line
    ):
        try:
            pairs[kv.group(1)] = json.loads(kv.group(2))
        except json.JSONDecodeError:
            pairs[kv.group(1)] = kv.group(2)
    if len(pairs) >= 2:
        return pairs, 0.5

    return {}, 0.0


def load_events_resilient(folder_path: str) -> tuple[list[dict], dict]:
    """
    Load events from folder using the resilient parser.
    Returns (events, parse_stats) where parse_stats keys:
      total_lines, parsed_clean, parsed_partial, skipped
    Partial events get a '_partial_extract' flag (stripped before LLM calls).
    """
    folder = Path(folder_path)
    files = sorted(
        [f for f in folder.rglob("*") if f.suffix in (".ndjson", ".json") and f.is_file() and not f.name.startswith("._")]
    )
    events: list[dict] = []
    stats = {"total_lines": 0, "parsed_clean": 0, "parsed_partial": 0, "skipped": 0}

    for file_path in files:
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if len(stripped) > 65_536:
                        stats["skipped"] += 1
                        continue
                    stats["total_lines"] += 1
                    obj, confidence = parse_resilient(stripped)
                    if confidence == 1.0:
                        events.append(obj)
                        stats["parsed_clean"] += 1
                    elif confidence >= 0.5:
                        obj["_partial_extract"] = True
                        events.append(obj)
                        stats["parsed_partial"] += 1
                        logger.debug("Partial extract from %s: %.60s", file_path, stripped)
                    else:
                        stats["skipped"] += 1
                        logger.debug("Unparseable line in %s: %.60s", file_path, stripped)
        except OSError as e:
            logger.warning("Could not read file %s: %s", file_path, e)

    logger.info(
        "Resilient load: %d clean, %d partial, %d skipped from %d files",
        stats["parsed_clean"], stats["parsed_partial"], stats["skipped"], len(files),
    )
    return events, stats


def split_by_quality(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split events by parse quality.
    Returns (clean_events, partial_events).
    Clean events have no _partial_extract flag (confidence 1.0 parse).
    Partial events carry _partial_extract=True (regex key:value fallback, confidence ~0.5).
    Partial events are excluded from schema inference by default because their field
    structure is reconstructed rather than authoritative.
    """
    clean = [e for e in events if not e.get("_partial_extract")]
    partial = [e for e in events if e.get("_partial_extract")]
    return clean, partial


def load_events_from_folder(folder_path: str) -> list[dict]:
    """Load all .ndjson and .json files from folder (recursive), sorted by filename."""
    folder = Path(folder_path)
    files = sorted(
        [f for f in folder.rglob("*") if f.suffix in (".ndjson", ".json") and f.is_file() and not f.name.startswith("._")]
    )

    events = []
    skipped = 0

    for file_path in files:
        file_events = 0
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                            file_events += 1
                        else:
                            skipped += 1
                    except json.JSONDecodeError:
                        skipped += 1
                        logger.debug("Skipped malformed JSON at %s line %d", file_path, line_num)
        except OSError as e:
            logger.warning("Could not read file %s: %s", file_path, e)

        logger.debug("Loaded %d events from %s", file_events, file_path)

    logger.info("Loaded %d events from %d files (skipped %d malformed lines)", len(events), len(files), skipped)
    return events


def reservoir_sample(events: list[dict], n: int = 500, seed: int | None = None) -> list[dict]:
    """Algorithm R reservoir sampling. Returns n events sampled uniformly at random.

    Args:
        events: Full event list to sample from.
        n: Reservoir size (number of events to keep).
        seed: Optional random seed for reproducible sampling (used by quorum voting
              to get independent but deterministic samples).
    """
    if len(events) <= n:
        return list(events)

    rng = random.Random(seed) if seed is not None else random

    reservoir = list(events[:n])
    for i in range(n, len(events)):
        j = rng.randint(0, i)
        if j < n:
            reservoir[j] = events[i]
    return reservoir


def _iter_events_from_folder(folder_path: str):
    """Yield (event_dict,) from all NDJSON/JSON files in folder. No buffering."""
    folder = Path(folder_path)
    files = sorted(
        [f for f in folder.rglob("*") if f.suffix in (".ndjson", ".json") and f.is_file() and not f.name.startswith("._")]
    )
    for file_path in files:
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            yield event
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass


def streaming_reservoir_sample_from_folder(
    folder_path: str,
    n: int = 500,
) -> tuple[list[dict], int]:
    """Load and sample in one pass — O(n) memory instead of O(total).

    Returns (sampled_events, total_event_count).
    Uses Algorithm R: maintain a reservoir of size n, replacing elements
    with decreasing probability as more events stream in.
    """
    reservoir: list[dict] = []
    count = 0
    for event in _iter_events_from_folder(folder_path):
        count += 1
        if count <= n:
            reservoir.append(event)
        else:
            j = random.randint(0, count - 1)
            if j < n:
                reservoir[j] = event

    logger.info(
        "Streaming sample: %d events selected from %d total (folder: %s)",
        len(reservoir), count, folder_path,
    )
    return reservoir, count


def streaming_resilient_sample_from_folder(
    folder_path: str,
    n: int = 500,
) -> tuple[list[dict], list[dict], int, dict]:
    """Streaming resilient load + sample — O(n) memory.

    Returns (clean_sample, partial_sample, total_count, parse_stats).
    Clean and partial events are sampled independently into separate reservoirs.
    """
    folder = Path(folder_path)
    files = sorted(
        f for f in folder.rglob("*")
        if f.suffix in (".ndjson", ".json") and f.is_file()
        and not f.name.startswith("._")  # skip macOS resource forks
    )

    clean_reservoir: list[dict] = []
    partial_reservoir: list[dict] = []
    clean_count = 0
    partial_count = 0
    stats = {"total_lines": 0, "parsed_clean": 0, "parsed_partial": 0, "skipped": 0}

    for file_path in files:
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if len(stripped) > 65_536:
                        stats["skipped"] += 1
                        continue
                    stats["total_lines"] += 1
                    obj, confidence = parse_resilient(stripped)
                    if confidence == 1.0:
                        stats["parsed_clean"] += 1
                        clean_count += 1
                        if clean_count <= n:
                            clean_reservoir.append(obj)
                        else:
                            j = random.randint(0, clean_count - 1)
                            if j < n:
                                clean_reservoir[j] = obj
                    elif confidence >= 0.5:
                        stats["parsed_partial"] += 1
                        obj["_partial_extract"] = True
                        partial_count += 1
                        if partial_count <= n:
                            partial_reservoir.append(obj)
                        else:
                            j = random.randint(0, partial_count - 1)
                            if j < n:
                                partial_reservoir[j] = obj
                    else:
                        stats["skipped"] += 1
        except OSError as e:
            logger.warning("Could not read file %s: %s", file_path, e)

    logger.info(
        "Streaming resilient sample: %d clean + %d partial from %d lines (%d files)",
        len(clean_reservoir), len(partial_reservoir), stats["total_lines"], len(files),
    )
    total = clean_count + partial_count
    return clean_reservoir, partial_reservoir, total, stats


_MAX_FLATTEN_DEPTH = 10
_MAX_FLATTEN_KEYS = 500


def flatten_nested(obj: dict, prefix: str = "", sep: str = ".", _depth: int = 0) -> dict:
    """Flatten nested dicts to dot-notation. Arrays: flatten first element, mark as array.

    Safety bounds:
      MAX_DEPTH = 10 — prevents stack overflow on pathological nesting
      MAX_KEYS = 500 — prevents OOM on events with thousands of fields
    """
    if _depth > _MAX_FLATTEN_DEPTH:
        return {}

    result = {}
    for key, value in obj.items():
        if len(result) >= _MAX_FLATTEN_KEYS:
            break
        full_key = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_nested(value, full_key, sep, _depth + 1))
        elif isinstance(value, list):
            result[full_key] = value
            if value and isinstance(value[0], dict):
                result.update(flatten_nested(value[0], f"{full_key}[]", sep, _depth + 1))
        else:
            result[full_key] = value
    return result


def get_all_field_paths(events: list[dict]) -> tuple[dict[str, list[Any]], dict[str, float]]:
    """
    Return (field_values, presence_rates) where:
    - field_values: field_path → list of all observed non-null values
    - presence_rates: field_path → fraction of events where field appears
    """
    field_values: dict[str, list[Any]] = {}
    field_counts: dict[str, int] = {}
    total = len(events)

    if total == 0:
        return {}, {}

    for event in events:
        flat = flatten_nested(event)
        for path, value in flat.items():
            if path not in field_counts:
                field_counts[path] = 0
                field_values[path] = []
            field_counts[path] += 1
            if value is not None:
                field_values[path].append(value)

    presence_rates = {path: count / total for path, count in field_counts.items()}
    return field_values, presence_rates


def compute_value_stats(values: list, field_type: str = "") -> dict:
    """Compute summary statistics for a field's observed values.

    Returns a dict with:
      cardinality: number of distinct non-null values
      min/max: for numeric types (int, float, timestamp_epoch_ms)
      (no min/max for strings — not meaningful)

    Used to enrich schema.yaml with value metadata for data engineering tooling.
    """
    if not values:
        return {"cardinality": 0}

    non_null = [v for v in values if v is not None]
    distinct = len(set(str(v) for v in non_null))
    stats: dict = {"cardinality": distinct}

    # Numeric min/max
    numeric = [v for v in non_null if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if numeric and field_type in ("float", "integer", "timestamp_epoch_ms", ""):
        stats["min"] = min(numeric)
        stats["max"] = max(numeric)

    return stats
