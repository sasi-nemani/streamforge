"""
Snapshot tests for streamforge/exporters/protobuf.py — schema_to_proto()

Each snapshot test asserts the full deterministic output string. Structural
property tests follow to document individual type-mapping and formatting rules.
"""

from __future__ import annotations

import pytest

from streamforge.exporters.protobuf import schema_to_proto, _to_pascal_case
from streamforge.models import FieldSchema, FieldType, InferredSchema, PIICategory

# ── canonical test schemas ────────────────────────────────────────────────────

def _minimal_schema() -> InferredSchema:
    """Three fields: UUID, FLOAT, TIMESTAMP_EPOCH_MS — timestamp import required."""
    return InferredSchema(
        stream_name="payments",
        version="1.0.0",
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=100,
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.95,
        fields=[
            FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                        required=True, nullable=False),
            FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                        required=True, nullable=False),
            FieldSchema(name="created_at", path="created_at",
                        field_type=FieldType.TIMESTAMP_EPOCH_MS,
                        required=True, nullable=False),
        ],
    )


def _payments_schema() -> InferredSchema:
    """Payments: PII annotation, optional fields, notes in comments."""
    return InferredSchema(
        stream_name="payments",
        version="1.0.0",
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=300,
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.93,
        fields=[
            FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                        required=True, nullable=False, notes="Payment UUID"),
            FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                        required=True, nullable=False),
            FieldSchema(name="currency", path="currency", field_type=FieldType.STRING,
                        required=True, nullable=False, enum_values=["USD", "EUR", "GBP"]),
            FieldSchema(name="created_at", path="created_at",
                        field_type=FieldType.TIMESTAMP_EPOCH_MS,
                        required=True, nullable=False),
            FieldSchema(name="email", path="email", field_type=FieldType.EMAIL,
                        required=False, nullable=True,
                        pii_categories=[PIICategory.EMAIL], notes="Customer email"),
        ],
    )


def _all_types_schema() -> InferredSchema:
    """Exercises every proto3 type mapping; required fields first, then optional."""
    return InferredSchema(
        stream_name="sensor_data",
        version="2.0.0",
        inferred_at="2026-03-21T12:00:00Z",
        event_count_sampled=500,
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.88,
        fields=[
            FieldSchema(name="sensor_id", path="sensor_id",
                        field_type=FieldType.STRING, required=True),
            FieldSchema(name="reading", path="reading",
                        field_type=FieldType.FLOAT, required=True),
            FieldSchema(name="count", path="count",
                        field_type=FieldType.INTEGER, required=True),
            FieldSchema(name="active", path="active",
                        field_type=FieldType.BOOLEAN, required=True),
            FieldSchema(name="recorded_at", path="recorded_at",
                        field_type=FieldType.TIMESTAMP_ISO8601, required=True),
            FieldSchema(name="tags", path="tags",
                        field_type=FieldType.ARRAY, required=False, nullable=True),
            FieldSchema(name="metadata", path="metadata",
                        field_type=FieldType.OBJECT, required=False, nullable=True),
            FieldSchema(name="value", path="value",
                        field_type=FieldType.MIXED, required=False, nullable=True),
            FieldSchema(name="raw", path="raw",
                        field_type=FieldType.NULL, required=False, nullable=True),
        ],
    )


def _nested_schema() -> InferredSchema:
    """Dot-notation paths → underscore field names; stream with dots → PascalCase."""
    return InferredSchema(
        stream_name="user.events",
        version="1.0.0",
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=50,
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.90,
        fields=[
            FieldSchema(name="user_id", path="user.id",
                        field_type=FieldType.UUID, required=True),
            FieldSchema(name="user_email", path="user.email",
                        field_type=FieldType.EMAIL, required=True,
                        pii_categories=[PIICategory.EMAIL]),
            FieldSchema(name="event_ts", path="event.ts",
                        field_type=FieldType.TIMESTAMP_ISO8601, required=True),
        ],
    )


def _no_timestamp_schema() -> InferredSchema:
    """No timestamp fields — no google/protobuf/timestamp.proto import."""
    return InferredSchema(
        stream_name="config-updates",
        version="1.0.0",
        inferred_at="2026-03-21T00:00:00Z",
        event_count_sampled=10,
        inference_model="claude-sonnet-4-6",
        inference_confidence=0.99,
        fields=[
            FieldSchema(name="key", path="key",
                        field_type=FieldType.STRING, required=True),
            FieldSchema(name="value", path="value",
                        field_type=FieldType.MIXED, required=True),
        ],
    )


# ── snapshot strings ──────────────────────────────────────────────────────────

SNAPSHOT_MINIMAL = (
    '// Generated by StreamForge\n'
    '// Source: payments  Schema: v1.0.0\n'
    '// Fields: 3  Confidence: 95%\n'
    '// Inferred: 2026-03-21\n'
    '\n'
    'syntax = "proto3";\n'
    '\n'
    'package io.streamforge.events;\n'
    '\n'
    'import "google/protobuf/timestamp.proto";\n'
    '\n'
    'message Payments {\n'
    '    double amount = 1;\n'
    '    google.protobuf.Timestamp created_at = 2;\n'
    '    string id = 3;\n'
    '}'
)

SNAPSHOT_PAYMENTS = (
    '// Generated by StreamForge\n'
    '// Source: payments  Schema: v1.0.0\n'
    '// Fields: 5  Confidence: 93%\n'
    '// Inferred: 2026-03-21\n'
    '\n'
    'syntax = "proto3";\n'
    '\n'
    'package io.streamforge.events;\n'
    '\n'
    'import "google/protobuf/timestamp.proto";\n'
    '\n'
    'message Payments {\n'
    '    double amount = 1;\n'
    '    google.protobuf.Timestamp created_at = 2;\n'
    '    string currency = 3;\n'
    '    string id = 4;  // Payment UUID\n'
    '    string email = 5;  // optional | PII:email | Customer email\n'
    '}'
)

SNAPSHOT_ALL_TYPES = (
    '// Generated by StreamForge\n'
    '// Source: sensor_data  Schema: v2.0.0\n'
    '// Fields: 9  Confidence: 88%\n'
    '// Inferred: 2026-03-21\n'
    '\n'
    'syntax = "proto3";\n'
    '\n'
    'package io.streamforge.events;\n'
    '\n'
    'import "google/protobuf/timestamp.proto";\n'
    '\n'
    'message SensorData {\n'
    '    bool active = 1;\n'
    '    int64 count = 2;\n'
    '    double reading = 3;\n'
    '    google.protobuf.Timestamp recorded_at = 4;\n'
    '    string sensor_id = 5;\n'
    '    bytes metadata = 6;  // optional\n'
    '    bytes raw = 7;  // optional\n'
    '    repeated string tags = 8;  // optional\n'
    '    bytes value = 9;  // optional\n'
    '}'
)

SNAPSHOT_NESTED = (
    '// Generated by StreamForge\n'
    '// Source: user.events  Schema: v1.0.0\n'
    '// Fields: 3  Confidence: 90%\n'
    '// Inferred: 2026-03-21\n'
    '\n'
    'syntax = "proto3";\n'
    '\n'
    'package io.streamforge.events;\n'
    '\n'
    'import "google/protobuf/timestamp.proto";\n'
    '\n'
    'message UserEvents {\n'
    '    google.protobuf.Timestamp event_ts = 1;\n'
    '    string user_email = 2;  // PII:email\n'
    '    string user_id = 3;\n'
    '}'
)


class TestProtobufSnapshots:
    def test_minimal_schema(self):
        assert schema_to_proto(_minimal_schema()) == SNAPSHOT_MINIMAL

    def test_payments_schema(self):
        assert schema_to_proto(_payments_schema()) == SNAPSHOT_PAYMENTS

    def test_all_types_schema(self):
        assert schema_to_proto(_all_types_schema()) == SNAPSHOT_ALL_TYPES

    def test_nested_dot_notation_schema(self):
        assert schema_to_proto(_nested_schema()) == SNAPSHOT_NESTED


# ── structural property tests ─────────────────────────────────────────────────

class TestProtobufHeader:
    def test_starts_with_generated_by_comment(self):
        out = schema_to_proto(_minimal_schema())
        assert out.startswith("// Generated by StreamForge")

    def test_includes_source_stream_name(self):
        out = schema_to_proto(_minimal_schema())
        assert "// Source: payments" in out

    def test_includes_schema_version(self):
        out = schema_to_proto(_minimal_schema())
        assert "Schema: v1.0.0" in out

    def test_includes_field_count(self):
        out = schema_to_proto(_minimal_schema())
        assert "// Fields: 3" in out

    def test_includes_confidence_percentage(self):
        out = schema_to_proto(_minimal_schema())
        assert "Confidence: 95%" in out

    def test_includes_inferred_date(self):
        out = schema_to_proto(_minimal_schema())
        assert "// Inferred: 2026-03-21" in out


class TestProtobufPreamble:
    def test_syntax_is_proto3(self):
        out = schema_to_proto(_minimal_schema())
        assert 'syntax = "proto3";' in out

    def test_package_is_streamforge_events(self):
        out = schema_to_proto(_minimal_schema())
        assert "package io.streamforge.events;" in out

    def test_timestamp_import_included_when_epoch_ms_field(self):
        out = schema_to_proto(_minimal_schema())
        assert 'import "google/protobuf/timestamp.proto";' in out

    def test_timestamp_import_included_when_iso8601_field(self):
        out = schema_to_proto(_all_types_schema())
        assert 'import "google/protobuf/timestamp.proto";' in out

    def test_timestamp_import_omitted_when_no_timestamp_field(self):
        out = schema_to_proto(_no_timestamp_schema())
        assert "google/protobuf/timestamp.proto" not in out


class TestProtobufMessageName:
    def test_simple_stream_name_pascal_case(self):
        out = schema_to_proto(_minimal_schema())
        assert "message Payments {" in out

    def test_dot_separated_stream_name_pascal_case(self):
        out = schema_to_proto(_nested_schema())
        assert "message UserEvents {" in out

    def test_dash_separated_stream_name_pascal_case(self):
        out = schema_to_proto(_no_timestamp_schema())
        assert "message ConfigUpdates {" in out

    def test_underscore_separated_stream_name_pascal_case(self):
        out = schema_to_proto(_all_types_schema())
        assert "message SensorData {" in out


class TestProtobufTypeMapping:
    def test_uuid_maps_to_string(self):
        out = schema_to_proto(_minimal_schema())
        assert "string id = " in out

    def test_float_maps_to_double(self):
        out = schema_to_proto(_minimal_schema())
        assert "double amount = " in out

    def test_integer_maps_to_int64(self):
        out = schema_to_proto(_all_types_schema())
        assert "int64 count = " in out

    def test_boolean_maps_to_bool(self):
        out = schema_to_proto(_all_types_schema())
        assert "bool active = " in out

    def test_string_maps_to_string(self):
        out = schema_to_proto(_all_types_schema())
        assert "string sensor_id = " in out

    def test_email_maps_to_string(self):
        out = schema_to_proto(_payments_schema())
        assert "string email = " in out

    def test_timestamp_epoch_ms_maps_to_protobuf_timestamp(self):
        out = schema_to_proto(_minimal_schema())
        assert "google.protobuf.Timestamp created_at = " in out

    def test_timestamp_iso8601_maps_to_protobuf_timestamp(self):
        out = schema_to_proto(_all_types_schema())
        assert "google.protobuf.Timestamp recorded_at = " in out

    def test_array_maps_to_repeated_string(self):
        out = schema_to_proto(_all_types_schema())
        assert "repeated string tags = " in out

    def test_object_maps_to_bytes(self):
        out = schema_to_proto(_all_types_schema())
        assert "bytes metadata = " in out

    def test_mixed_maps_to_bytes(self):
        out = schema_to_proto(_all_types_schema())
        assert "bytes value = " in out

    def test_null_maps_to_bytes(self):
        out = schema_to_proto(_all_types_schema())
        assert "bytes raw = " in out

    def test_date_maps_to_string(self):
        schema = InferredSchema(
            stream_name="events",
            version="1.0.0",
            inferred_at="2026-03-21T00:00:00Z",
            event_count_sampled=10,
            inference_model="claude-sonnet-4-6",
            inference_confidence=0.9,
            fields=[
                FieldSchema(name="dob", path="dob",
                            field_type=FieldType.DATE, required=True)
            ],
        )
        out = schema_to_proto(schema)
        assert "string dob = " in out

    def test_rfc2822_maps_to_string(self):
        schema = InferredSchema(
            stream_name="events",
            version="1.0.0",
            inferred_at="2026-03-21T00:00:00Z",
            event_count_sampled=10,
            inference_model="claude-sonnet-4-6",
            inference_confidence=0.9,
            fields=[
                FieldSchema(name="sent_at", path="sent_at",
                            field_type=FieldType.TIMESTAMP_RFC2822, required=True)
            ],
        )
        out = schema_to_proto(schema)
        assert "string sent_at = " in out


class TestProtobufFieldOrdering:
    def test_required_fields_get_lower_field_numbers_than_optional(self):
        """Required fields are sorted first; optional fields follow."""
        out = schema_to_proto(_payments_schema())
        lines = [l for l in out.splitlines() if "=" in l and ";" in l]
        # email is optional; it should have a higher number than amount/currency/created_at/id
        email_line = next(l for l in lines if "email" in l)
        email_num = int(email_line.split("=")[1].split(";")[0].strip())
        # all required fields should have numbers ≤ (total_required count)
        assert email_num == 5  # 4 required + 1 optional

    def test_required_fields_sorted_by_path_then_presence_rate(self):
        """Within required: sorted by (-presence_rate, path); all have rate 1.0 here
        so sorted purely alphabetically by path."""
        out = schema_to_proto(_minimal_schema())
        lines = [l.strip() for l in out.splitlines() if l.strip().startswith(("string", "double", "google", "bool", "int64", "repeated", "bytes"))]
        field_names = [l.split()[-3] for l in lines]  # e.g. "id", "amount", "created_at"
        # Alphabetical order: amount(1), created_at(2), id(3)
        assert field_names == ["amount", "created_at", "id"]

    def test_optional_fields_appear_after_required_in_output(self):
        out = schema_to_proto(_payments_schema())
        required_ids = []
        optional_ids = []
        for line in out.splitlines():
            # Field lines are indented: "    <type> <name> = <n>;"
            stripped = line.strip()
            if not stripped or not stripped[0].isalpha():
                continue
            if "=" not in stripped or not any(
                stripped.startswith(t) for t in ("string", "double", "int64", "bool",
                                                  "google", "bytes", "repeated")
            ):
                continue
            num = int(stripped.split("=")[1].split(";")[0].strip())
            if "// optional" in line or "// PII" in line:
                optional_ids.append(num)
            else:
                required_ids.append(num)
        assert all(r < o for r in required_ids for o in optional_ids)


class TestProtobufFieldNumbers:
    def test_field_numbers_are_sequential_from_1(self):
        out = schema_to_proto(_minimal_schema())
        numbers = []
        for line in out.splitlines():
            if "= " in line and line.strip().endswith(";"):
                try:
                    num = int(line.split("= ")[1].rstrip(";").strip())
                    numbers.append(num)
                except ValueError:
                    pass
        assert numbers == list(range(1, len(numbers) + 1))

    def test_field_count_matches_schema_fields(self):
        schema = _payments_schema()
        out = schema_to_proto(schema)
        # Count lines that are field definitions (indented, start with a known proto type)
        proto_types = ("string ", "double ", "int64 ", "bool ", "bytes ",
                       "google.", "repeated ")
        count = sum(
            1 for line in out.splitlines()
            if line.startswith("    ") and any(line.lstrip().startswith(t) for t in proto_types)
        )
        assert count == len(schema.fields)


class TestProtobufDotNotationFields:
    def test_dot_in_path_becomes_underscore_in_field_name(self):
        out = schema_to_proto(_nested_schema())
        assert "user_id" in out
        assert "user_email" in out
        assert "event_ts" in out

    def test_original_dot_path_not_in_field_names(self):
        out = schema_to_proto(_nested_schema())
        # dot-notation should not appear literally inside the message body
        body = out[out.index("{"):]
        assert "user.id" not in body
        assert "user.email" not in body


class TestProtobufInlineComments:
    def test_notes_appear_in_comment(self):
        out = schema_to_proto(_payments_schema())
        assert "// Payment UUID" in out

    def test_optional_field_has_optional_in_comment(self):
        out = schema_to_proto(_payments_schema())
        assert "// optional" in out

    def test_pii_field_has_pii_in_comment(self):
        out = schema_to_proto(_payments_schema())
        assert "PII:email" in out

    def test_required_field_without_notes_has_no_comment(self):
        out = schema_to_proto(_minimal_schema())
        # amount is required, no notes, no PII → no trailing comment
        amount_line = next(l for l in out.splitlines() if "double amount" in l)
        assert "//" not in amount_line

    def test_pii_annotation_in_nested_schema(self):
        out = schema_to_proto(_nested_schema())
        email_line = next(l for l in out.splitlines() if "user_email" in l)
        assert "PII:email" in email_line


class TestProtobufMessageStructure:
    def test_message_block_has_opening_and_closing_brace(self):
        out = schema_to_proto(_minimal_schema())
        assert "message Payments {" in out
        assert out.strip().endswith("}")

    def test_no_trailing_newline_after_closing_brace(self):
        out = schema_to_proto(_minimal_schema())
        assert out.endswith("}")
        assert not out.endswith("\n")

    def test_all_field_lines_indented_with_four_spaces(self):
        out = schema_to_proto(_minimal_schema())
        inside = False
        for line in out.splitlines():
            if line.startswith("message "):
                inside = True
                continue
            if line == "}":
                inside = False
                continue
            if inside and line.strip():
                assert line.startswith("    "), f"Unindented field line: {line!r}"


# ── _to_pascal_case unit tests ────────────────────────────────────────────────

class TestToPascalCase:
    def test_simple_name(self):
        assert _to_pascal_case("payments") == "Payments"

    def test_dot_separated(self):
        assert _to_pascal_case("user.events") == "UserEvents"

    def test_dash_separated(self):
        assert _to_pascal_case("config-updates") == "ConfigUpdates"

    def test_underscore_separated(self):
        assert _to_pascal_case("sensor_data") == "SensorData"

    def test_mixed_separators(self):
        assert _to_pascal_case("my-user.stream_data") == "MyUserStreamData"

    def test_empty_string_returns_schema(self):
        assert _to_pascal_case("") == "Schema"

    def test_single_word(self):
        assert _to_pascal_case("events") == "Events"
