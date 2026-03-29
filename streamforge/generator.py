"""
Synthetic event generator — produces NDJSON events that conform to a schema.

Reconstructs nested JSON from dot-notation paths:
  "user.email"     → {"user": {"email": "..."}}
  "items[].id"     → {"items": [{"id": "..."}]}
  "meta.tags[]"    → {"meta": {"tags": ["..."]}}

Usage:
    from streamforge.generator import generate_events
    events = generate_events(schema, count=20)
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import FieldType, InferredSchema

# Realistic word banks for string values
_WORDS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "sigma",
    "primary", "secondary", "active", "pending", "complete", "failed",
    "north", "south", "east", "west", "central",
]
_FIRST_NAMES = ["alice", "bob", "carol", "dave", "eve", "frank", "grace", "henry"]
_DOMAINS = ["example.com", "testco.io", "acme.org", "demo.net"]
_CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"]
_STATUS = ["active", "inactive", "pending", "completed", "failed", "cancelled"]


def _random_value(
    field_type: FieldType,
    enum_values: list[str] | None = None,
    field_path: str = "",
    nullable: bool = False,
    *,
    ref_time: datetime | None = None,
) -> Any:
    """
    Generate a realistic synthetic value for the given field type.
    Uses enum_values when provided (takes precedence over type-based generation).
    """
    if enum_values:
        return random.choice(enum_values)

    if nullable and random.random() < 0.05:
        return None

    path_lower = field_path.lower()

    if field_type == FieldType.STRING:
        # Use field name hints for more realistic values
        if any(h in path_lower for h in ("status", "state")):
            return random.choice(_STATUS)
        if any(h in path_lower for h in ("currency",)):
            return random.choice(_CURRENCIES)
        if any(h in path_lower for h in ("country",)):
            return random.choice(["US", "GB", "DE", "FR", "CA", "AU", "JP"])
        if any(h in path_lower for h in ("name", "title")):
            return f"{random.choice(_FIRST_NAMES)}_{random.randint(100, 999)}"
        return f"{random.choice(_WORDS)}_{random.randint(1, 999)}"

    if field_type == FieldType.INTEGER:
        if any(h in path_lower for h in ("count", "total", "num", "quantity")):
            return random.randint(1, 1000)
        if any(h in path_lower for h in ("age",)):
            return random.randint(18, 90)
        if any(h in path_lower for h in ("port",)):
            return random.randint(1024, 65535)
        return random.randint(1, 99_999)

    if field_type == FieldType.FLOAT:
        if any(h in path_lower for h in ("amount", "price", "cost", "fee", "rate")):
            return round(random.uniform(0.01, 9_999.99), 2)
        if any(h in path_lower for h in ("lat", "latitude")):
            return round(random.uniform(-90.0, 90.0), 6)
        if any(h in path_lower for h in ("lon", "longitude", "lng")):
            return round(random.uniform(-180.0, 180.0), 6)
        if any(h in path_lower for h in ("confidence", "score", "probability")):
            return round(random.uniform(0.0, 1.0), 4)
        return round(random.uniform(0.01, 9_999.99), 2)

    if field_type == FieldType.BOOLEAN:
        return random.choice([True, False])

    if field_type == FieldType.UUID:
        # Build a v4-format UUID from Python's seeded random so output is
        # reproducible when a seed is provided.
        return (
            f"{random.getrandbits(32):08x}-"
            f"{random.getrandbits(16):04x}-"
            f"{(random.getrandbits(12) | 0x4000):04x}-"
            f"{(random.getrandbits(14) | 0x8000):04x}-"
            f"{random.getrandbits(48):012x}"
        )

    if field_type == FieldType.EMAIL:
        name = random.choice(_FIRST_NAMES)
        n = random.randint(10, 9999)
        domain = random.choice(_DOMAINS)
        return f"{name}{n}@{domain}"

    if field_type == FieldType.PHONE:
        area = random.randint(200, 999)
        rest = random.randint(1_000_000, 9_999_999)
        return f"+1{area}{rest}"

    if field_type == FieldType.TIMESTAMP_EPOCH_MS:
        _now = ref_time or datetime.now(UTC)
        now_ms = int(_now.timestamp() * 1000)
        jitter_ms = random.randint(-7 * 86_400_000, 0)  # up to 7 days before now
        return now_ms + jitter_ms

    if field_type == FieldType.TIMESTAMP_ISO8601:
        _now = ref_time or datetime.now(UTC)
        dt = _now + timedelta(seconds=random.randint(-604_800, 0))
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    if field_type == FieldType.TIMESTAMP_RFC2822:
        _now = ref_time or datetime.now(UTC)
        dt = _now + timedelta(seconds=random.randint(-604_800, 0))
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

    if field_type == FieldType.DATE:
        _now = ref_time or datetime.now(UTC)
        dt = _now + timedelta(days=random.randint(-365, 0))
        return dt.strftime("%Y-%m-%d")

    if field_type == FieldType.ARRAY:
        # Leaf array with no typed children — generate a short list of strings
        return [f"{random.choice(_WORDS)}_{random.randint(1, 99)}" for _ in range(random.randint(1, 3))]

    if field_type == FieldType.OBJECT:
        return {}  # children are populated by the path-reconstruction step

    if field_type == FieldType.NULL:
        return None

    if field_type == FieldType.MIXED:
        # Alternate between string and integer
        return random.choice([
            random.randint(1, 1000),
            f"{random.choice(_WORDS)}_{random.randint(1, 99)}",
        ])

    # Fallback
    return f"value_{random.randint(1, 9999)}"


def _set_nested(obj: dict, path: str, value: Any) -> None:
    """
    Set a value at a dot-notation path in a nested dict, creating intermediate
    dicts and single-element arrays as needed.

    Supported notations:
      "user.email"      → obj["user"]["email"] = value
      "items[].id"      → obj["items"][0]["id"] = value
      "meta.tags[]"     → obj["meta"]["tags"] = [value]  (leaf array)
    """
    parts = path.split(".")
    current = obj

    for part in parts[:-1]:
        if part.endswith("[]"):
            # Intermediate array — ensure it exists with at least one element
            key = part[:-2]
            if key not in current or not isinstance(current[key], list):
                current[key] = [{}]
            elif not current[key]:
                current[key].append({})
            elif not isinstance(current[key][0], dict):
                current[key][0] = {}
            current = current[key][0]
        else:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]

    last = parts[-1]
    if last.endswith("[]"):
        # Leaf array path — wrap value in a list
        key = last[:-2]
        if isinstance(value, list):
            current[key] = value
        else:
            current[key] = [value] if value is not None else []
    else:
        current[last] = value


def generate_events(
    schema: InferredSchema,
    count: int = 10,
    include_optional: bool = True,
    seed: int | None = None,
) -> list[dict]:
    """
    Generate synthetic NDJSON events that conform to the given InferredSchema.

    - Required fields (required=True) are always present.
    - Optional fields are sampled at their presence_rate when include_optional=True.
    - Nested paths are reconstructed into proper JSON nesting.
    - Array-child paths (e.g. "items[].id") produce single-element arrays.
    - Enum values are always respected.

    Args:
        schema:           The schema to generate from.
        count:            Number of events to produce.
        include_optional: When True, optional fields appear at their presence_rate.
                          When False, only required fields are included.
        seed:             Optional random seed for reproducible output.

    Returns:
        List of event dicts (ready for json.dumps per line → NDJSON).
    """
    if seed is not None:
        random.seed(seed)

    # Pin reference time when seeded so timestamps are reproducible
    _ref_time = datetime(2026, 1, 1, tzinfo=UTC) if seed is not None else None

    # Pre-sort: object-type parent fields last so leaf values win on path conflicts
    leaf_fields = [f for f in schema.fields if f.field_type != FieldType.OBJECT]
    # Sort by path depth so parents are set before children (although _set_nested handles this)
    leaf_fields_sorted = sorted(leaf_fields, key=lambda f: f.path.count("."))

    events: list[dict] = []
    for _ in range(count):
        event: dict = {}
        for field in leaf_fields_sorted:
            # Decide whether to include this field
            if field.required:
                include = True
            elif include_optional:
                include = random.random() <= field.presence_rate
            else:
                include = False

            if not include:
                continue

            value = _random_value(
                field.field_type,
                enum_values=field.enum_values,
                field_path=field.path,
                nullable=field.nullable,
                ref_time=_ref_time,
            )
            _set_nested(event, field.path, value)

        events.append(event)

    return events


def generate_from_cluster(
    profile: dict,
    cluster_id: str,
    count: int = 10,
    include_optional: bool = True,
    seed: int | None = None,
) -> list[dict]:
    """
    Generate events for a specific sub-schema cluster from profile.yaml.

    If the profile has a routing_field (e.g. "event_type"), the generated events
    will have that field set to the cluster_id so they route correctly in watch mode.
    """
    from .drift_detector import _sub_schema_to_inferred_schema

    sub = next(
        (s for s in profile.get("sub_schemas", []) if s["cluster_id"] == cluster_id),
        None,
    )
    if sub is None:
        raise ValueError(f"Cluster '{cluster_id}' not found in profile. "
                         f"Available: {[s['cluster_id'] for s in profile.get('sub_schemas', [])]}")

    inferred = _sub_schema_to_inferred_schema(sub, profile.get("stream", ""))
    events = generate_events(inferred, count=count, include_optional=include_optional, seed=seed)

    # Ensure the routing field is set correctly so generated events route to this cluster
    routing_field = profile.get("routing_field")
    if routing_field and not cluster_id.startswith("struct:"):
        for event in events:
            # Only inject if not already set by schema inference
            if routing_field not in event:
                event[routing_field] = cluster_id

    return events
