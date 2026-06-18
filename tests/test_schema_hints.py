"""
TDD tests for schema_hints.yaml + _apply_schema_hints() + small-cluster thresholds.

RED phase: these tests are written before implementation and must FAIL first.
"""

from streamforge.models import FieldSchema, FieldType, PIICategory

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_field(path: str, field_type: FieldType, confidence: float = 0.75,
                pii: list | None = None, samples: list | None = None) -> FieldSchema:
    return FieldSchema(
        name=path.split(".")[-1],
        path=path,
        field_type=field_type,
        confidence=confidence,
        pii_categories=pii or [],
        sample_values=samples or [],
    )


# ── load_schema_hints ──────────────────────────────────────────────────────────

def test_load_schema_hints_returns_dict():
    """schema_hints.yaml loads without error and returns a non-empty dict."""
    from streamforge.inference import _load_schema_hints
    hints = _load_schema_hints()
    assert isinstance(hints, dict)
    assert "type_patterns" in hints
    assert len(hints["type_patterns"]) > 0


def test_schema_hints_has_pii_name_floors():
    """hints dict includes pii_name_floors with at least passport and card entries."""
    from streamforge.inference import _load_schema_hints
    hints = _load_schema_hints()
    assert "pii_name_floors" in hints
    substrings = [e["substring"] for e in hints["pii_name_floors"]]
    assert "passport" in substrings
    assert "card_last_four" in substrings


# ── _apply_schema_hints — type override ───────────────────────────────────────

def test_hints_overrides_epoch_ms_type():
    """
    Field typed as timestamp_iso8601 by LLM but samples are 13-digit integers
    → type forced to timestamp_epoch_ms, confidence floored to ≥0.99.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field(
        "created_at",
        FieldType.TIMESTAMP_ISO8601,   # LLM got it wrong
        confidence=0.65,
        samples=[1711066800000, 1711153200000, 1711239600000, 1711326000000],
    )
    field_stats = {"created_at": [1711066800000, 1711153200000, 1711239600000, 1711326000000]}
    result = _apply_schema_hints([field], field_stats, hints)
    assert len(result) == 1
    assert result[0].field_type == FieldType.TIMESTAMP_EPOCH_MS
    assert result[0].confidence >= 0.99


def test_hints_overrides_iso8601_type():
    """
    Field typed as timestamp_epoch_ms by LLM but samples are ISO8601 strings
    → type forced to timestamp_iso8601, confidence floored to ≥0.99.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field(
        "updated_at",
        FieldType.TIMESTAMP_EPOCH_MS,  # LLM got it wrong
        confidence=0.70,
        samples=["2024-03-21T00:00:00Z", "2024-03-22T12:30:00Z", "2024-03-23T08:00:00Z"],
    )
    field_stats = {
        "updated_at": ["2024-03-21T00:00:00Z", "2024-03-22T12:30:00Z", "2024-03-23T08:00:00Z"]
    }
    result = _apply_schema_hints([field], field_stats, hints)
    assert result[0].field_type == FieldType.TIMESTAMP_ISO8601
    assert result[0].confidence >= 0.99


def test_hints_overrides_uuid_type():
    """
    Field typed as string by LLM but samples are UUID v4
    → type forced to uuid, confidence floored to ≥0.99.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    samples = [
        "550e8400-e29b-41d4-a716-446655440000",
        "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
        "6ba7b811-9dad-41d1-80b4-00c04fd430c8",
    ]
    field = _make_field("event_id", FieldType.STRING, confidence=0.70, samples=samples)
    field_stats = {"event_id": samples}
    result = _apply_schema_hints([field], field_stats, hints)
    assert result[0].field_type == FieldType.UUID
    assert result[0].confidence >= 0.99


def test_hints_no_override_when_samples_mixed():
    """
    When fewer than 60% of samples match a pattern, type is NOT overridden.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    # Only 2 of 5 samples are epoch_ms; the other 3 are small ints
    samples = [1711066800000, 1711153200000, 42, 7, 100]
    field = _make_field("mixed_ts", FieldType.INTEGER, confidence=0.70, samples=samples)
    field_stats = {"mixed_ts": samples}
    result = _apply_schema_hints([field], field_stats, hints)
    # Type should remain INTEGER — mixed samples don't meet the 60% threshold
    assert result[0].field_type == FieldType.INTEGER


def test_hints_no_override_when_no_samples():
    """
    When there are no sample values, confidence is not changed.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field("ts", FieldType.TIMESTAMP_ISO8601, confidence=0.70, samples=[])
    result = _apply_schema_hints([field], {}, hints)
    assert result[0].confidence == 0.70  # unchanged


def test_hints_correct_type_keeps_confidence_if_already_correct():
    """
    When LLM type is already correct AND matches pattern, confidence is floored UP not down.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    samples = [1711066800000, 1711153200000, 1711239600000, 1711326000000]
    field = _make_field("ts", FieldType.TIMESTAMP_EPOCH_MS, confidence=0.95, samples=samples)
    field_stats = {"ts": samples}
    result = _apply_schema_hints([field], field_stats, hints)
    assert result[0].field_type == FieldType.TIMESTAMP_EPOCH_MS
    assert result[0].confidence >= 0.99  # floored UP to 0.99


# ── _apply_schema_hints — PII floor ───────────────────────────────────────────

def test_hints_adds_passport_pii_if_llm_missed_it():
    """
    Field path contains 'passport' but LLM returned no PII categories
    → PIICategory.PASSPORT is added.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field(
        "passengers[].passport_number",
        FieldType.STRING,
        confidence=0.90,
        pii=[],   # LLM missed it
    )
    result = _apply_schema_hints([field], {"passengers[].passport_number": ["AB1234567"]}, hints)
    assert PIICategory.PASSPORT in result[0].pii_categories


def test_hints_adds_card_pii_if_llm_missed_it():
    """
    Field path contains 'card_last_four' but LLM returned no PII categories
    → PIICategory.CARD_NUMBER is added.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field("card_last_four", FieldType.STRING, confidence=0.90, pii=[])
    result = _apply_schema_hints([field], {"card_last_four": ["4242", "1234"]}, hints)
    assert PIICategory.CARD_NUMBER in result[0].pii_categories


def test_hints_adds_dob_pii_if_llm_missed_it():
    """
    Field path contains 'dob' but LLM returned no PII categories
    → PIICategory.DATE_OF_BIRTH is added.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field("passenger_dob", FieldType.STRING, confidence=0.90, pii=[])
    result = _apply_schema_hints([field], {"passenger_dob": ["1990-01-01"]}, hints)
    assert PIICategory.DATE_OF_BIRTH in result[0].pii_categories


def test_hints_does_not_duplicate_existing_pii():
    """
    If LLM already set PASSPORT, the floor should not add a duplicate.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field(
        "passport_number", FieldType.STRING, pii=[PIICategory.PASSPORT]
    )
    result = _apply_schema_hints([field], {"passport_number": ["AB1234567"]}, hints)
    assert result[0].pii_categories.count(PIICategory.PASSPORT) == 1


def test_hints_no_false_pii_on_unrelated_field():
    """
    A plain 'amount' field should not get any PII categories added.
    """
    from streamforge.inference import _apply_schema_hints, _load_schema_hints
    hints = _load_schema_hints()
    field = _make_field("amount", FieldType.FLOAT, pii=[])
    result = _apply_schema_hints([field], {"amount": [100.0, 200.0]}, hints)
    assert result[0].pii_categories == []


# ── small-cluster LLM inference threshold ─────────────────────────────────────

def test_min_events_for_llm_constant_is_50():
    """MIN_EVENTS_FOR_LLM_INFERENCE constant must be 50."""
    from streamforge.inference import MIN_EVENTS_FOR_LLM_INFERENCE
    assert MIN_EVENTS_FOR_LLM_INFERENCE == 50


# ── sparse-cluster drift skip ──────────────────────────────────────────────────

def test_min_cluster_events_constant_is_200():
    """MIN_CLUSTER_EVENTS_FOR_DRIFT constant must be 200."""
    from streamforge.drift_detector import MIN_CLUSTER_EVENTS_FOR_DRIFT
    assert MIN_CLUSTER_EVENTS_FOR_DRIFT == 200


def test_sparse_cluster_skips_drift_check():
    """
    detect_drift_multi_schema returns no DriftReport for a cluster that has fewer
    than MIN_CLUSTER_EVENTS_FOR_DRIFT events in the new sample (not a routing
    regression — the cluster is simply under-sampled in this watch window).
    """
    from streamforge.drift_detector import detect_drift_multi_schema

    # Build a minimal profile with one cluster that was 50% of stream at init
    profile = {
        "sub_schemas": [
            {
                "cluster_id": "payment.completed",
                "sample_rate": 0.50,
                "fields": [
                    {"path": "amount", "field_type": "float", "required": True,
                     "nullable": False, "presence_rate": 1.0, "confidence": 0.95,
                     "pii_categories": [], "sample_values": []},
                ],
                "routing_key": "event_type",
                "routing_value": "payment.completed",
                "inference_confidence": 0.90,
            }
        ]
    }

    # Sample has only 10 events for this cluster (below 200 threshold)
    new_sample = [
        {"event_type": "payment.completed", "amount": float(i)}
        for i in range(10)
    ]

    reports = detect_drift_multi_schema(profile, new_sample, "test.stream")

    # Should emit NO drift reports — sparse window, not a true regression
    drift_types = [d.drift_type for r in reports for d in r.drifts]
    assert "cluster_routing_regression" not in drift_types
    # No field-level drift either (not enough data to check)
    field_drifts = [d for r in reports for d in r.drifts if d.field_path != "__cluster__"]
    assert len(field_drifts) == 0


def test_sparse_cluster_not_skipped_when_zero_events():
    """
    A cluster with 0 events in a large sample (≥30) still fires
    cluster_routing_regression — that is a different, real signal.
    """
    from streamforge.drift_detector import detect_drift_multi_schema

    profile = {
        "sub_schemas": [
            {
                "cluster_id": "payment.completed",
                "sample_rate": 0.50,
                "fields": [
                    {"path": "amount", "field_type": "float", "required": True,
                     "nullable": False, "presence_rate": 1.0, "confidence": 0.95,
                     "pii_categories": [], "sample_values": []},
                ],
                "routing_key": "event_type",
                "routing_value": "payment.completed",
                "inference_confidence": 0.90,
            }
        ]
    }

    # 30 events, none for our cluster
    new_sample = [{"event_type": "other.event", "x": i} for i in range(30)]

    reports = detect_drift_multi_schema(profile, new_sample, "test.stream")
    drift_types = [d.drift_type for r in reports for d in r.drifts]
    assert "cluster_routing_regression" in drift_types
