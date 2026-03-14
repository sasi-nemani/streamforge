import json
import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_events_from_folder(folder_path: str) -> list[dict]:
    """Load all .ndjson and .json files from folder (recursive), sorted by filename."""
    folder = Path(folder_path)
    files = sorted(
        [f for f in folder.rglob("*") if f.suffix in (".ndjson", ".json") and f.is_file()]
    )

    events = []
    skipped = 0

    for file_path in files:
        file_events = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
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


def reservoir_sample(events: list[dict], n: int = 500) -> list[dict]:
    """Algorithm R reservoir sampling. Returns n events sampled uniformly at random."""
    if len(events) <= n:
        return list(events)

    reservoir = events[:n]
    for i in range(n, len(events)):
        j = random.randint(0, i)
        if j < n:
            reservoir[j] = events[i]
    return reservoir


def flatten_nested(obj: dict, prefix: str = "", sep: str = ".") -> dict:
    """Flatten nested dicts to dot-notation. Arrays: flatten first element, mark as array."""
    result = {}
    for key, value in obj.items():
        full_key = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_nested(value, full_key, sep))
        elif isinstance(value, list):
            result[full_key] = value  # keep as list so callers can detect array type
            if value and isinstance(value[0], dict):
                # Flatten first element with [] notation
                result.update(flatten_nested(value[0], f"{full_key}[]", sep))
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
