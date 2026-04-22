import pytest

from streamforge.models import PIICategory
from streamforge.pii_detector import PIIDetection, detect_pii, detect_pii_scored


def test_detects_email_by_value():
    result = detect_pii("contact", ["alice@example.com", "bob@test.org"])
    assert PIICategory.EMAIL in result


def test_detects_email_by_field_name():
    result = detect_pii("user.email", ["not-an-email-value"])
    assert PIICategory.EMAIL in result


def test_detects_passport_pattern():
    result = detect_pii("document", ["AB1234567", "CD9876543"])
    assert PIICategory.PASSPORT in result


def test_detects_card_last_four_by_name():
    result = detect_pii("card_last_four", ["4242", "1234"])
    assert PIICategory.CARD_NUMBER in result


def test_detects_phone_by_name():
    result = detect_pii("user.mobile", ["some-value"])
    assert PIICategory.PHONE in result


def test_detects_ip_address_by_name():
    result = detect_pii("metadata.ip_address", ["192.168.1.1"])
    assert PIICategory.IP_ADDRESS in result


def test_detects_name_by_field_name():
    result = detect_pii("passenger_name", ["Alice Smith"])
    assert PIICategory.NAME in result


def test_no_false_positive_on_generic_field():
    result = detect_pii("event_id", ["abc-123", "def-456"])
    assert result == []


def test_detects_loyalty_number_by_name():
    result = detect_pii("frequent_flyer_number", ["FF12345"])
    assert PIICategory.LOYALTY_NUMBER in result


# --- Confidence scoring tests ---


def test_detect_pii_scored_returns_confidence():
    """detect_pii_scored returns PIIDetection with confidence and source."""
    result = detect_pii_scored("user.email", ["alice@example.com"])
    assert len(result) > 0
    email_det = [d for d in result if d.category == PIICategory.EMAIL][0]
    assert email_det.confidence == 0.95  # both name_hint and pattern
    assert email_det.source == "both"


def test_detect_pii_scored_name_only():
    """Name hint only gives 0.6 confidence."""
    result = detect_pii_scored("user.email", ["not-an-email"])
    email_det = [d for d in result if d.category == PIICategory.EMAIL][0]
    assert email_det.confidence == 0.6
    assert email_det.source == "name_hint"


def test_detect_pii_scored_pattern_only():
    """Pattern match only gives 0.7 confidence."""
    result = detect_pii_scored("some_field", ["alice@example.com"])
    email_det = [d for d in result if d.category == PIICategory.EMAIL][0]
    assert email_det.confidence == 0.7
    assert email_det.source == "pattern"


# --- Phone detection improvements ---


def test_phone_rejects_plain_digits():
    """Plain digit sequences without formatting should NOT be flagged as phone."""
    result = detect_pii("some_number", ["1234567890", "9876543210"])
    assert PIICategory.PHONE not in result


def test_phone_accepts_international_format():
    """International format with + prefix IS flagged."""
    result = detect_pii("contact", ["+1-555-123-4567"])
    assert PIICategory.PHONE in result


def test_phone_accepts_parenthesized():
    """US format with parenthesized area code IS flagged."""
    result = detect_pii("contact", ["(555) 123-4567"])
    assert PIICategory.PHONE in result


def test_phone_accepts_grouped():
    """Dash-separated groups IS flagged."""
    result = detect_pii("contact", ["555-123-4567"])
    assert PIICategory.PHONE in result


# --- DOB improvements ---


def test_dob_requires_field_name_hint():
    """ISO date string alone without DOB field name should NOT be flagged."""
    result = detect_pii("created_at", ["2024-01-15", "2024-06-20"])
    assert PIICategory.DATE_OF_BIRTH not in result


def test_dob_detected_with_field_name():
    """ISO date WITH DOB field name IS flagged."""
    result = detect_pii("date_of_birth", ["1990-05-15"])
    assert PIICategory.DATE_OF_BIRTH in result


# --- SSN and AADHAAR detection ---


def test_ssn_detected():
    """SSN pattern with matching field name IS flagged."""
    result = detect_pii("user.ssn", ["123-45-6789"])
    assert PIICategory.NATIONAL_ID in result


def test_ssn_pattern_only():
    """SSN pattern without field hint still detects via pattern."""
    result = detect_pii("some_id", ["123-45-6789"])
    assert PIICategory.NATIONAL_ID in result


def test_aadhaar_detected():
    """AADHAAR pattern with matching field name IS flagged."""
    result = detect_pii("aadhaar_number", ["1234 5678 9012"])
    assert PIICategory.NATIONAL_ID in result


# --- UUID detection (production bug fix) ---


def test_uuid_not_flagged_as_pii_in_id_field():
    """UUIDs in ID fields should NOT be flagged as PII."""
    uuids = ["550e8400-e29b-41d4-a716-446655440000"] * 5
    assert detect_pii("event_id", uuids) == []
    assert detect_pii("transaction_id", uuids) == []
    assert detect_pii("request_uuid", uuids) == []


def test_uuid_in_non_id_field_still_safe():
    """UUIDs in non-ID fields are also not PII (UUIDs are never PII)."""
    uuids = ["550e8400-e29b-41d4-a716-446655440000"]
    # UUIDs don't match any PII pattern (email, phone, SSN, etc.)
    result = detect_pii("some_data", uuids)
    assert PIICategory.EMAIL not in result
    assert PIICategory.PHONE not in result
    assert PIICategory.NATIONAL_ID not in result


def test_mixed_uuid_and_other_values():
    """If values are mixed (not all UUIDs), don't suppress PII checks."""
    mixed = ["550e8400-e29b-41d4-a716-446655440000", "alice@example.com"]
    result = detect_pii("event_id", mixed)
    # Email should still be detected since not all values are UUIDs
    assert PIICategory.EMAIL in result
