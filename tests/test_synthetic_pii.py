"""Tests for format-preserving PII pseudonymization.

The LLM needs structurally valid values to infer correct types.
"[REDACTED:email]" → LLM infers "string" (WRONG)
"user_001@streamforge.synthetic" → LLM infers "email" (CORRECT)

Every synthetic value must:
1. Match the format of the original PII category
2. Be obviously fake (not a real person's data)
3. Be deterministic for the same input (reproducible)
4. Enable correct type inference by the LLM
"""

import re

import pytest


class TestSyntheticPiiGenerator:
    """Each PII category must produce a format-valid synthetic value."""

    def test_synthetic_email(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("email", "alice@stripe.com")
        assert "@" in val, f"Synthetic email must contain @: {val}"
        assert "." in val.split("@")[1], f"Synthetic email must have domain: {val}"
        assert "alice" not in val.lower(), f"Must not contain original name: {val}"
        assert "stripe" not in val.lower(), f"Must not contain original domain: {val}"

    def test_synthetic_phone(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("phone", "+44 7700 900123")
        # Must contain digits and formatting
        assert any(c.isdigit() for c in val), f"Synthetic phone must have digits: {val}"
        assert "7700" not in val, f"Must not contain original digits: {val}"

    def test_synthetic_name(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("name", "Alice Johnson")
        assert isinstance(val, str) and len(val) > 2, f"Synthetic name too short: {val}"
        assert "alice" not in val.lower(), f"Must not contain original: {val}"

    def test_synthetic_card_number(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("card_number", "4242424242424242")
        digits = re.sub(r'\D', '', val)
        assert len(digits) >= 13, f"Synthetic card must have 13+ digits: {val}"
        assert "4242" not in val, f"Must not contain original: {val}"

    def test_synthetic_ssn(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("national_id", "123-45-6789")
        assert re.match(r'\d{3}-\d{2}-\d{4}', val), f"SSN must match ###-##-####: {val}"
        assert val != "123-45-6789", f"Must not be the original: {val}"

    def test_synthetic_ip(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("ip_address", "192.168.1.100")
        parts = val.split(".")
        assert len(parts) == 4, f"IP must have 4 octets: {val}"
        assert all(p.isdigit() for p in parts), f"Octets must be numeric: {val}"
        assert val != "192.168.1.100"

    def test_synthetic_passport(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("passport", "AB1234567")
        assert re.match(r'[A-Z]{1,2}\d+', val), f"Passport must match format: {val}"
        assert val != "AB1234567"

    def test_synthetic_dob(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("date_of_birth", "1990-05-15")
        assert re.match(r'\d{4}-\d{2}-\d{2}', val), f"DOB must match YYYY-MM-DD: {val}"
        assert val != "1990-05-15"

    def test_synthetic_is_deterministic(self):
        """Same input → same output (reproducible for testing)."""
        from streamforge.inference import _synthetic_pii_value
        v1 = _synthetic_pii_value("email", "alice@stripe.com")
        v2 = _synthetic_pii_value("email", "alice@stripe.com")
        assert v1 == v2

    def test_different_inputs_different_outputs(self):
        """Different real values should produce different synthetics."""
        from streamforge.inference import _synthetic_pii_value
        v1 = _synthetic_pii_value("email", "alice@stripe.com")
        v2 = _synthetic_pii_value("email", "bob@google.com")
        assert v1 != v2

    def test_unknown_category_returns_masked_string(self):
        """Unknown PII category should return a safe string, not crash."""
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("unknown_pii", "secret data")
        assert isinstance(val, str)
        assert "secret" not in val.lower()


class TestSyntheticLengthPreservation:
    """Synthetic values must preserve the length of the original for numeric/fixed types."""

    def test_card_4_digits_stays_4(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("card_number", "4242")
        assert len(val) == 4, f"Expected 4 chars, got {len(val)}: {val}"
        assert val.isdigit(), f"Card synthetic must be all digits: {val}"

    def test_card_16_digits_stays_16(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("card_number", "4242424242424242")
        assert len(val) == 16, f"Expected 16 chars, got {len(val)}: {val}"
        assert val.isdigit()

    def test_card_19_digits_with_dashes(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("card_number", "4242-4242-4242-4242")
        # 19 chars including dashes — preserve total length
        assert len(val) == len("4242-4242-4242-4242"), f"Expected 19, got {len(val)}: {val}"

    def test_phone_preserves_length(self):
        from streamforge.inference import _synthetic_pii_value
        original = "+44 7700 900123"
        val = _synthetic_pii_value("phone", original)
        assert len(val) == len(original), f"Expected {len(original)}, got {len(val)}: {val}"

    def test_passport_preserves_length(self):
        from streamforge.inference import _synthetic_pii_value
        for orig in ["AB1234567", "C12345678", "XY123456789"]:
            val = _synthetic_pii_value("passport", orig)
            assert len(val) == len(orig), f"Passport '{orig}' ({len(orig)}) -> '{val}' ({len(val)})"

    def test_ssn_preserves_format(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("national_id", "123-45-6789")
        assert len(val) == 11, f"SSN must be 11 chars: {val}"
        assert val[3] == "-" and val[6] == "-", f"SSN must have dashes at 3,6: {val}"

    def test_ip_preserves_data_type(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("ip_address", "192.168.1.100")
        parts = val.split(".")
        assert len(parts) == 4
        assert all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def test_dob_preserves_length(self):
        from streamforge.inference import _synthetic_pii_value
        val = _synthetic_pii_value("date_of_birth", "1990-05-15")
        assert len(val) == 10, f"DOB must be 10 chars: {val}"

    def test_name_preserves_approximate_length(self):
        from streamforge.inference import _synthetic_pii_value
        for orig in ["Al", "Alice Johnson", "Alexandra Bartholomew-Richardson III"]:
            val = _synthetic_pii_value("name", orig)
            # Name length should be within 50% of original (structure varies)
            assert len(val) >= max(2, len(orig) // 3), f"Name too short: '{orig}' -> '{val}'"
            assert len(val) <= len(orig) * 2 + 5, f"Name too long: '{orig}' -> '{val}'"

    def test_email_preserves_structure_not_exact_length(self):
        """Email must have @ and domain. Exact length match is not required."""
        from streamforge.inference import _synthetic_pii_value
        for orig in ["a@b.co", "alice.johnson@enterprise-corp.com"]:
            val = _synthetic_pii_value("email", orig)
            assert "@" in val
            assert "." in val.split("@")[1]


class TestScrubEventUsesSynthetic:
    """_scrub_event_for_prompt must use synthetic values, not [REDACTED]."""

    def test_scrubbed_email_is_valid_email_format(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"user_email": "alice@stripe.com", "status": "ok"}
        scrubbed = _scrub_event_for_prompt(event)
        val = scrubbed.get("user_email", "")
        assert "@" in val, f"Scrubbed email must be email-shaped: {val}"
        assert "[REDACTED" not in val, f"Must not use REDACTED placeholder: {val}"
        assert "alice" not in val.lower()

    def test_scrubbed_event_preserves_non_pii(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"user_email": "alice@stripe.com", "status": "ok", "amount": 99.99}
        scrubbed = _scrub_event_for_prompt(event)
        assert scrubbed["status"] == "ok"
        assert scrubbed["amount"] == 99.99

    def test_prompt_field_stats_use_synthetic(self):
        """Field stats in the prompt must use synthetic PII, not [REDACTED]."""
        from streamforge.inference import build_inference_prompt
        field_stats = {"email": ["alice@stripe.com", "bob@test.com"]}
        presence = {"email": 1.0}
        events = [{"email": "alice@stripe.com"}]
        prompt = build_inference_prompt(field_stats, presence, events)
        assert "[REDACTED]" not in prompt, f"Prompt should not contain [REDACTED]"
        assert "alice@stripe.com" not in prompt, f"Prompt must not contain real email"
        # Should contain a synthetic email-like value
        assert "@" in prompt, f"Prompt must contain synthetic email with @"
