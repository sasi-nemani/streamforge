import re
from dataclasses import dataclass
from typing import Any

from .models import PIICategory


@dataclass(frozen=True)
class PIIDetection:
    category: PIICategory
    confidence: float  # 0.0-1.0
    source: str  # "name_hint", "pattern", "both"


EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
CARD_PATTERN = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')
PASSPORT_PATTERN = re.compile(r'\b[A-Z]{1,2}\d{7,9}\b')
_IP_RAW_PATTERN = re.compile(r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b')
DOB_PATTERN = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
AADHAAR_PATTERN = re.compile(r'\b\d{4}\s\d{4}\s\d{4}\b')

# Phone patterns: require explicit formatting (+ prefix, parenthesized area code,
# or dash/space-separated groups). Plain digit sequences are rejected.
PHONE_INTL_PATTERN = re.compile(r'\+\d{1,3}[\s-]?\d{3,14}')
PHONE_US_PATTERN = re.compile(r'\(\d{3}\)\s?\d{3}[\s-]?\d{4}')
PHONE_GROUPED_PATTERN = re.compile(r'\b\d{3}[\s-]\d{3}[\s-]\d{4}\b')


def _looks_like_phone(val: str) -> bool:
    """Check if a string value looks like a formatted phone number.

    Requires explicit formatting characters: + prefix, parenthesized area code,
    or dash/space-separated digit groups. Plain digit sequences like "1234567890"
    are NOT matched.
    """
    return bool(
        PHONE_INTL_PATTERN.search(val)
        or PHONE_US_PATTERN.search(val)
        or PHONE_GROUPED_PATTERN.search(val)
    )


def _looks_like_ip(val: str) -> bool:
    """Check if a string looks like an IP address, not a version string.

    Validates that each octet is 0-255 and at least one octet exceeds 100.
    This eliminates false positives on version strings like "1.2.3.4" or
    "2024.1.15.3" while catching real IPs like "192.168.1.1".
    """
    m = _IP_RAW_PATTERN.search(val)
    if not m:
        return False
    octets = [int(m.group(i)) for i in range(1, 5)]
    # All octets must be 0-255
    if not all(0 <= o <= 255 for o in octets):
        return False
    # At least one octet > 100 — real IPs almost always have this,
    # version strings almost never do (1.2.3.4 → max octet is 4)
    return max(octets) > 100


PII_NAME_HINTS: dict[PIICategory, list[str]] = {
    PIICategory.EMAIL: ["email", "e_mail", "mail"],
    PIICategory.PHONE: ["phone", "mobile", "tel", "contact_number"],
    PIICategory.NAME: ["first_name", "last_name", "full_name", "passenger_name", "name"],
    PIICategory.PASSPORT: ["passport", "document_number"],
    PIICategory.CARD_NUMBER: ["card", "pan", "card_last_four", "card_number"],
    PIICategory.IP_ADDRESS: ["ip_address", "ip", "client_ip"],
    PIICategory.DATE_OF_BIRTH: ["dob", "date_of_birth", "birth_date", "birthdate", "born", "birthday"],
    PIICategory.LOYALTY_NUMBER: ["loyalty", "frequent_flyer", "rewards"],
    PIICategory.NATIONAL_ID: ["ssn", "social_security", "social_security_number", "aadhaar", "aadhar"],
}

# Mapping from PIICategory to pattern-check functions. Each returns True if the
# value matches the pattern for that category.
_PATTERN_CHECKS: dict[PIICategory, Any] = {
    PIICategory.EMAIL: lambda val: bool(EMAIL_PATTERN.search(val)),
    PIICategory.PHONE: _looks_like_phone,
    PIICategory.CARD_NUMBER: lambda val: bool(CARD_PATTERN.search(val)),
    PIICategory.PASSPORT: lambda val: bool(PASSPORT_PATTERN.search(val)),
    PIICategory.IP_ADDRESS: lambda val: _looks_like_ip(val),
    PIICategory.NATIONAL_ID: lambda val: bool(SSN_PATTERN.search(val) or AADHAAR_PATTERN.search(val)),
}

# DOB requires field name hint -- pattern alone is not sufficient since
# \d{4}-\d{2}-\d{2} matches all ISO dates.
_DOB_FIELD_HINTS = {"dob", "birth", "born", "birthday", "birthdate", "date_of_birth"}


def _path_segments(path: str) -> list[str]:
    """Split dot-notation path into individual segments, stripping array brackets."""
    return [s for s in re.split(r'[.\[\]]+', path.lower()) if s]


def _check_name_hints(segments: list[str]) -> set[PIICategory]:
    """Check field path segments against name hints, return matched categories."""
    matched: set[PIICategory] = set()
    for category, hints in PII_NAME_HINTS.items():
        for hint in hints:
            if len(hint) <= 4:
                if hint in segments:
                    matched.add(category)
                    break
            else:
                if any(hint in seg for seg in segments):
                    matched.add(category)
                    break
    return matched


# Field name segments that indicate identifiers (not card numbers)
_ID_FIELD_SEGMENTS = {"id", "uuid", "ref", "key", "hash", "token", "code", "number"}
# But these ARE card-related even with "number" in the name
_CARD_FIELD_SEGMENTS = {"card", "pan", "credit", "debit"}


def _check_patterns(str_values: list[str], segments: list[str]) -> set[PIICategory]:
    """Run pattern matching on sample values, return matched categories."""
    matched: set[PIICategory] = set()

    # Suppress card_number pattern on identifier fields (event_id, transaction_id, etc.)
    # unless the field name explicitly mentions card/pan/credit
    _all_parts = [p for seg in segments for p in seg.split("_")]
    suppress_card = (
        any(p in _ID_FIELD_SEGMENTS for p in _all_parts)
        and not any(p in _CARD_FIELD_SEGMENTS for p in _all_parts)
    )

    for val in str_values:
        for category, check_fn in _PATTERN_CHECKS.items():
            if category not in matched:
                if category == PIICategory.CARD_NUMBER and suppress_card:
                    continue
                if check_fn(val):
                    matched.add(category)

        # DOB: only flag if field name also suggests date-of-birth
        if PIICategory.DATE_OF_BIRTH not in matched and DOB_PATTERN.search(val):
            if any(h in seg for seg in segments for h in _DOB_FIELD_HINTS):
                matched.add(PIICategory.DATE_OF_BIRTH)

    return matched


def detect_pii_scored(field_path: str, sample_values: list[Any]) -> list[PIIDetection]:
    """Returns list of PIIDetection with category, confidence, and source.

    Confidence scoring:
    - name_hint only: 0.6
    - pattern match only: 0.7
    - both name_hint AND pattern: 0.95
    """
    segments = _path_segments(field_path)
    str_values = [v for v in sample_values if isinstance(v, str)][:20]

    name_matches = _check_name_hints(segments)
    pattern_matches = _check_patterns(str_values, segments)

    all_categories = name_matches | pattern_matches
    detections: list[PIIDetection] = []

    for category in sorted(all_categories, key=lambda c: c.value):
        has_name = category in name_matches
        has_pattern = category in pattern_matches

        if has_name and has_pattern:
            detections.append(PIIDetection(category=category, confidence=0.95, source="both"))
        elif has_name:
            detections.append(PIIDetection(category=category, confidence=0.6, source="name_hint"))
        else:
            detections.append(PIIDetection(category=category, confidence=0.7, source="pattern"))

    return detections


def detect_pii(field_path: str, sample_values: list[Any]) -> list[PIICategory]:
    """Returns list of PII categories detected for this field.

    Backward-compatible wrapper around detect_pii_scored().
    """
    return [d.category for d in detect_pii_scored(field_path, sample_values)]
