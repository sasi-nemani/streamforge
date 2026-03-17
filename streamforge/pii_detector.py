import re
from typing import Any

from .models import PIICategory

EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
CARD_PATTERN = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')
PASSPORT_PATTERN = re.compile(r'\b[A-Z]{1,2}\d{7,9}\b')
IP_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
DOB_PATTERN = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
# Strip formatting chars — what remains must be all digits for a real phone number.
# Excludes UUIDs (hex letters), IP addresses (dots kept → not all-digit), etc.
# Note: dots intentionally NOT stripped — "192.168.1.1" must not become "19216811".
_PHONE_STRIP = re.compile(r'[\s\-\+\(\)]+')


def _looks_like_phone(val: str) -> bool:
    # Must have at least one phone formatting character (+, space, dash, parens)
    # to distinguish from numeric IDs. Bare digit strings like "35234567890" are
    # ambiguous — we don't flag them unless the field name says phone.
    if not _PHONE_STRIP.search(val):
        return False
    stripped = _PHONE_STRIP.sub('', val)
    return stripped.isdigit() and 7 <= len(stripped) <= 15

PII_NAME_HINTS: dict[PIICategory, list[str]] = {
    PIICategory.EMAIL: ["email", "e_mail", "mail"],
    PIICategory.PHONE: ["phone", "mobile", "tel", "contact_number"],
    PIICategory.NAME: ["first_name", "last_name", "full_name", "passenger_name", "name"],
    PIICategory.PASSPORT: ["passport", "document_number"],
    PIICategory.CARD_NUMBER: ["card", "pan", "card_last_four", "card_number"],
    PIICategory.IP_ADDRESS: ["ip_address", "ip", "client_ip"],
    PIICategory.DATE_OF_BIRTH: ["dob", "date_of_birth", "birth_date", "birthdate"],
    PIICategory.LOYALTY_NUMBER: ["loyalty", "frequent_flyer", "rewards"],
}


def _path_segments(path: str) -> list[str]:
    """Split dot-notation path into individual segments, stripping array brackets."""
    return [s for s in re.split(r'[.\[\]]+', path.lower()) if s]


def detect_pii(field_path: str, sample_values: list[Any]) -> list[PIICategory]:
    """Returns list of PII categories detected for this field."""
    detected: set[PIICategory] = set()
    segments = _path_segments(field_path)

    # Field name heuristics — match against individual path segments.
    # Short hints (≤4 chars, e.g. "ip"): exact segment match only.
    # Longer hints (e.g. "frequent_flyer"): substring of any segment is fine.
    # This prevents "ip" matching "subscriptions_url" while allowing
    # "frequent_flyer" to match "frequent_flyer_number".
    for category, hints in PII_NAME_HINTS.items():
        for hint in hints:
            if len(hint) <= 4:
                matched = hint in segments
            else:
                matched = any(hint in seg for seg in segments)
            if matched:
                detected.add(category)
                break

    # Pattern matching on sample values — only run on actual strings, not coerced numbers
    str_values = [v for v in sample_values if isinstance(v, str)][:20]

    for val in str_values:
        if PIICategory.EMAIL not in detected and EMAIL_PATTERN.search(val):
            detected.add(PIICategory.EMAIL)
        if PIICategory.PHONE not in detected and _looks_like_phone(val):
            detected.add(PIICategory.PHONE)
        if PIICategory.CARD_NUMBER not in detected and CARD_PATTERN.search(val):
            detected.add(PIICategory.CARD_NUMBER)
        if PIICategory.PASSPORT not in detected and PASSPORT_PATTERN.search(val):
            detected.add(PIICategory.PASSPORT)
        if PIICategory.IP_ADDRESS not in detected and IP_PATTERN.search(val):
            detected.add(PIICategory.IP_ADDRESS)
        if PIICategory.DATE_OF_BIRTH not in detected and DOB_PATTERN.search(val):
            # Only flag as DOB if field name also suggests it
            dob_hints = ["dob", "birth", "born"]
            if any(h in seg for seg in segments for h in dob_hints):
                detected.add(PIICategory.DATE_OF_BIRTH)

    return list(detected)
