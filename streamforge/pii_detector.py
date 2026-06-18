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
UUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

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


def _is_rfc1918_or_special(octets: list[int]) -> bool:
    """Check if octets match RFC 1918 private ranges, loopback, or link-local.

    Private:    10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    Loopback:   127.0.0.0/8
    Link-local: 169.254.0.0/16
    """
    a = octets[0]
    if a == 10:             # 10.0.0.0/8
        return True
    if a == 172 and 16 <= octets[1] <= 31:  # 172.16.0.0/12
        return True
    if a == 192 and octets[1] == 168:       # 192.168.0.0/16
        return True
    if a == 127:            # loopback
        return True
    return a == 169 and octets[1] == 254       # link-local


def _is_uuid(val: str) -> bool:
    """Check if value is a UUID (v1-v5 format)."""
    return bool(UUID_PATTERN.match(val))


def _looks_like_ip(val: str) -> bool:
    """Check if a string looks like an IP address, not a version string.

    Strategy:
    1. All octets must be 0-255.
    2. Accept if ANY of these hold:
       a. RFC 1918 private range or loopback (10.x, 172.16-31.x, 192.168.x, 127.x)
       b. At least one octet > 100 (real public IPs almost always have this)
    3. Reject otherwise (version strings like "1.2.3.4" or "2.0.1.3").
    """
    m = _IP_RAW_PATTERN.search(val)
    if not m:
        return False
    octets = [int(m.group(i)) for i in range(1, 5)]
    # All octets must be 0-255
    if not all(0 <= o <= 255 for o in octets):
        return False
    # Accept RFC 1918 / loopback / link-local unconditionally
    if _is_rfc1918_or_special(octets):
        return True
    # For public IPs, require at least one high octet to reject version strings
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
        if (
            PIICategory.DATE_OF_BIRTH not in matched
            and DOB_PATTERN.search(val)
            and any(h in seg for seg in segments for h in _DOB_FIELD_HINTS)
        ):
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

    # Skip PII checks for ID fields containing only UUIDs — UUIDs are never PII
    _all_parts = [p for seg in segments for p in seg.split("_")]
    is_id_field = any(p in _ID_FIELD_SEGMENTS for p in _all_parts)
    if is_id_field and str_values and all(_is_uuid(v) for v in str_values):
        return []

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
