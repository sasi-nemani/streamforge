import pytest

from streamforge.models import PIICategory
from streamforge.pii_detector import detect_pii


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
