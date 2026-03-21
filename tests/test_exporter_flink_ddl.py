"""
Snapshot tests for streamforge/exporters/flink_ddl.py — schema_to_flink_ddl()

Strategy: each "snapshot" test calls schema_to_flink_ddl() against a fixed,
deterministic InferredSchema and asserts the full output string. Structural
property tests follow, checking individual behaviours that the snapshot would
not clearly communicate on its own.
"""

from __future__ import annotations

import pytest

from streamforge.exporters.flink_ddl import schema_to_flink_ddl
from streamforge.models import FieldSchema, FieldType, InferredSchema, PIICategory

# ── canonical test schemas ────────────────────────────────────────────────────

def _minimal_schema() -> InferredSchema:
    """Three fields: UUID, FLOAT, TIMESTAMP_EPOCH_MS."""
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
    """Realistic payments schema: epoch timestamp, COMMENT, nullable optional field."""
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
    """Exercises every Flink type mapping including ISO8601 timestamp watermark."""
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


def _no_timestamp_schema() -> InferredSchema:
    """Schema with no timestamp fields at all — no WATERMARK clause."""
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


def _nested_schema() -> InferredSchema:
    """Dot-notation field paths → underscores; stream name with dots → table name."""
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


# ── snapshot: full output equality ───────────────────────────────────────────

SNAPSHOT_MINIMAL = (
    "-- Generated by StreamForge\n"
    "-- Source: kafka://payments  Schema: v1.0.0\n"
    "-- Fields: 3  Confidence: 95%\n"
    "-- Inferred: 2026-03-21\n"
    "\n"
    "CREATE TABLE payments (\n"
    "    id                              STRING,\n"
    "    amount                          DOUBLE,\n"
    "    created_at                      TIMESTAMP(3) METADATA FROM 'timestamp' VIRTUAL,\n"
    "    WATERMARK FOR created_at AS created_at - INTERVAL '5' SECOND\n"
    ") WITH (\n"
    "    'connector'                          = 'kafka',\n"
    "    'topic'                              = 'payments',\n"
    "    'properties.bootstrap.servers'       = 'localhost:9092',\n"
    "    'properties.group.id'                = 'streamforge-flink',\n"
    "    'scan.startup.mode'                  = 'earliest-offset',\n"
    "    'format'                             = 'json',\n"
    "    'json.ignore-parse-errors'           = 'true',\n"
    "    'json.timestamp-format.standard'     = 'ISO-8601'\n"
    ");"
)

SNAPSHOT_PAYMENTS = (
    "-- Generated by StreamForge\n"
    "-- Source: kafka://payments  Schema: v1.0.0\n"
    "-- Fields: 5  Confidence: 93%\n"
    "-- Inferred: 2026-03-21\n"
    "\n"
    "CREATE TABLE payments (\n"
    "    id                              STRING COMMENT 'Payment UUID',\n"
    "    amount                          DOUBLE,\n"
    "    currency                        STRING,\n"
    "    email                           STRING NULL COMMENT 'Customer email',\n"
    "    created_at                      TIMESTAMP(3) METADATA FROM 'timestamp' VIRTUAL,\n"
    "    WATERMARK FOR created_at AS created_at - INTERVAL '5' SECOND\n"
    ") WITH (\n"
    "    'connector'                          = 'kafka',\n"
    "    'topic'                              = 'payments',\n"
    "    'properties.bootstrap.servers'       = 'localhost:9092',\n"
    "    'properties.group.id'                = 'streamforge-flink',\n"
    "    'scan.startup.mode'                  = 'earliest-offset',\n"
    "    'format'                             = 'json',\n"
    "    'json.ignore-parse-errors'           = 'true',\n"
    "    'json.timestamp-format.standard'     = 'ISO-8601'\n"
    ");"
)

SNAPSHOT_ALL_TYPES = (
    "-- Generated by StreamForge\n"
    "-- Source: kafka://sensor_data  Schema: v2.0.0\n"
    "-- Fields: 9  Confidence: 88%\n"
    "-- Inferred: 2026-03-21\n"
    "\n"
    "CREATE TABLE sensor_data (\n"
    "    sensor_id                       STRING,\n"
    "    reading                         DOUBLE,\n"
    "    count                           BIGINT,\n"
    "    active                          BOOLEAN,\n"
    "    recorded_at                     TIMESTAMP(3),\n"
    "    tags                            ARRAY<STRING> NULL,\n"
    "    metadata                        ROW<> NULL,\n"
    "    `value`                         STRING NULL,\n"
    "    raw                             STRING NULL,\n"
    "    WATERMARK FOR recorded_at AS recorded_at - INTERVAL '5' SECOND\n"
    ") WITH (\n"
    "    'connector'                          = 'kafka',\n"
    "    'topic'                              = 'sensor_data',\n"
    "    'properties.bootstrap.servers'       = 'localhost:9092',\n"
    "    'properties.group.id'                = 'streamforge-flink',\n"
    "    'scan.startup.mode'                  = 'earliest-offset',\n"
    "    'format'                             = 'json',\n"
    "    'json.ignore-parse-errors'           = 'true',\n"
    "    'json.timestamp-format.standard'     = 'ISO-8601'\n"
    ");"
)

SNAPSHOT_NO_TIMESTAMP = (
    "-- Generated by StreamForge\n"
    "-- Source: kafka://cfg  Schema: v1.0.0\n"
    "-- Fields: 2  Confidence: 99%\n"
    "-- Inferred: 2026-03-21\n"
    "\n"
    "CREATE TABLE config_updates (\n"
    "    `key`                           STRING,\n"
    "    `value`                         STRING\n"
    ") WITH (\n"
    "    'connector'                          = 'kafka',\n"
    "    'topic'                              = 'cfg',\n"
    "    'properties.bootstrap.servers'       = 'broker1:9092,broker2:9092',\n"
    "    'properties.group.id'                = 'streamforge-flink',\n"
    "    'scan.startup.mode'                  = 'earliest-offset',\n"
    "    'format'                             = 'json',\n"
    "    'json.ignore-parse-errors'           = 'true',\n"
    "    'json.timestamp-format.standard'     = 'ISO-8601'\n"
    ");"
)

SNAPSHOT_NESTED = (
    "-- Generated by StreamForge\n"
    "-- Source: kafka://user.events  Schema: v1.0.0\n"
    "-- Fields: 3  Confidence: 90%\n"
    "-- Inferred: 2026-03-21\n"
    "\n"
    "CREATE TABLE user_events (\n"
    "    user_id                         STRING,\n"
    "    user_email                      STRING,\n"
    "    event_ts                        TIMESTAMP(3),\n"
    "    WATERMARK FOR event_ts AS event_ts - INTERVAL '5' SECOND\n"
    ") WITH (\n"
    "    'connector'                          = 'kafka',\n"
    "    'topic'                              = 'user.events',\n"
    "    'properties.bootstrap.servers'       = 'localhost:9092',\n"
    "    'properties.group.id'                = 'streamforge-flink',\n"
    "    'scan.startup.mode'                  = 'earliest-offset',\n"
    "    'format'                             = 'json',\n"
    "    'json.ignore-parse-errors'           = 'true',\n"
    "    'json.timestamp-format.standard'     = 'ISO-8601'\n"
    ");"
)


class TestFlinkDDLSnapshots:
    def test_minimal_schema(self):
        assert schema_to_flink_ddl(_minimal_schema()) == SNAPSHOT_MINIMAL

    def test_payments_schema(self):
        assert schema_to_flink_ddl(_payments_schema()) == SNAPSHOT_PAYMENTS

    def test_all_types_schema(self):
        assert schema_to_flink_ddl(_all_types_schema()) == SNAPSHOT_ALL_TYPES

    def test_no_timestamp_schema_with_custom_brokers_and_topic(self):
        result = schema_to_flink_ddl(
            _no_timestamp_schema(),
            brokers=["broker1:9092", "broker2:9092"],
            topic="cfg",
        )
        assert result == SNAPSHOT_NO_TIMESTAMP

    def test_nested_dot_notation_schema(self):
        assert schema_to_flink_ddl(_nested_schema()) == SNAPSHOT_NESTED


# ── structural property tests ─────────────────────────────────────────────────

class TestFlinkDDLHeader:
    def test_header_starts_with_generated_by_comment(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert out.startswith("-- Generated by StreamForge")

    def test_header_includes_kafka_source_url(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "-- Source: kafka://payments" in out

    def test_header_includes_schema_version(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "Schema: v1.0.0" in out

    def test_header_includes_field_count(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "Fields: 3" in out

    def test_header_includes_confidence_percentage(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "Confidence: 95%" in out

    def test_header_includes_inferred_date(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "Inferred: 2026-03-21" in out


class TestFlinkDDLTableName:
    def test_stream_name_becomes_table_name(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "CREATE TABLE payments (" in out

    def test_dots_in_stream_name_become_underscores(self):
        out = schema_to_flink_ddl(_nested_schema())
        assert "CREATE TABLE user_events (" in out

    def test_dashes_in_stream_name_become_underscores(self):
        out = schema_to_flink_ddl(_no_timestamp_schema())
        assert "CREATE TABLE config_updates (" in out


class TestFlinkDDLTypeMapping:
    def test_uuid_maps_to_string(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "id                              STRING" in out

    def test_float_maps_to_double(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "amount                          DOUBLE" in out

    def test_integer_maps_to_bigint(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "count                           BIGINT" in out

    def test_boolean_maps_to_boolean(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "active                          BOOLEAN" in out

    def test_string_maps_to_string(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "sensor_id                       STRING" in out

    def test_email_maps_to_string(self):
        out = schema_to_flink_ddl(_payments_schema())
        assert "email                           STRING" in out

    def test_array_maps_to_array_string(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "ARRAY<STRING>" in out

    def test_object_maps_to_row(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "ROW<>" in out

    def test_mixed_maps_to_string(self):
        out = schema_to_flink_ddl(_all_types_schema())
        # `value` is MIXED → STRING (backtick-quoted because "value" is reserved)
        assert "STRING NULL" in out

    def test_null_maps_to_string(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "raw                             STRING NULL" in out

    def test_iso8601_maps_to_timestamp3(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "recorded_at                     TIMESTAMP(3)" in out

    def test_epoch_ms_maps_to_metadata_virtual_column(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "TIMESTAMP(3) METADATA FROM 'timestamp' VIRTUAL" in out


class TestFlinkDDLNullability:
    def test_required_non_nullable_has_no_null_suffix(self):
        out = schema_to_flink_ddl(_payments_schema())
        # id is required, non-nullable → no NULL
        assert "id                              STRING COMMENT" in out
        assert "id                              STRING NULL" not in out

    def test_optional_nullable_gets_null_suffix(self):
        out = schema_to_flink_ddl(_payments_schema())
        assert "email                           STRING NULL" in out


class TestFlinkDDLComments:
    def test_notes_become_comment_clause(self):
        out = schema_to_flink_ddl(_payments_schema())
        assert "COMMENT 'Payment UUID'" in out

    def test_customer_email_comment(self):
        out = schema_to_flink_ddl(_payments_schema())
        assert "COMMENT 'Customer email'" in out

    def test_no_notes_produces_no_comment(self):
        out = schema_to_flink_ddl(_payments_schema())
        assert "amount                          DOUBLE," in out
        assert "amount                          DOUBLE COMMENT" not in out


class TestFlinkDDLReservedWords:
    def test_reserved_column_name_backtick_quoted(self):
        out = schema_to_flink_ddl(_no_timestamp_schema())
        assert "`key`" in out
        assert "`value`" in out

    def test_non_reserved_column_name_not_quoted(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "`id`" not in out
        assert "`amount`" not in out


class TestFlinkDDLWatermark:
    def test_epoch_ts_field_generates_watermark(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "WATERMARK FOR created_at AS created_at - INTERVAL '5' SECOND" in out

    def test_iso8601_ts_field_generates_watermark(self):
        out = schema_to_flink_ddl(_all_types_schema())
        assert "WATERMARK FOR recorded_at AS recorded_at - INTERVAL '5' SECOND" in out

    def test_no_timestamp_field_produces_no_watermark(self):
        out = schema_to_flink_ddl(_no_timestamp_schema())
        assert "WATERMARK" not in out

    def test_epoch_ts_appears_as_metadata_column_before_watermark(self):
        out = schema_to_flink_ddl(_minimal_schema())
        metadata_pos = out.index("METADATA FROM 'timestamp' VIRTUAL")
        watermark_pos = out.index("WATERMARK FOR")
        assert metadata_pos < watermark_pos


class TestFlinkDDLWithClause:
    def test_with_clause_present(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert ") WITH (" in out
        assert ");" in out

    def test_default_broker_is_localhost(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'properties.bootstrap.servers'       = 'localhost:9092'" in out

    def test_custom_brokers_joined_by_comma(self):
        out = schema_to_flink_ddl(
            _no_timestamp_schema(),
            brokers=["broker1:9092", "broker2:9092"],
        )
        assert "'properties.bootstrap.servers'       = 'broker1:9092,broker2:9092'" in out

    def test_topic_defaults_to_stream_name(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'topic'                              = 'payments'" in out

    def test_custom_topic_overrides_stream_name(self):
        out = schema_to_flink_ddl(_no_timestamp_schema(), topic="cfg")
        assert "'topic'                              = 'cfg'" in out

    def test_connector_is_kafka(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'connector'                          = 'kafka'" in out

    def test_format_is_json(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'format'                             = 'json'" in out

    def test_scan_startup_mode_is_earliest(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'scan.startup.mode'                  = 'earliest-offset'" in out

    def test_json_ignore_parse_errors_true(self):
        out = schema_to_flink_ddl(_minimal_schema())
        assert "'json.ignore-parse-errors'           = 'true'" in out


class TestFlinkDDLDotNotationFields:
    def test_dot_in_field_path_converted_to_underscore(self):
        out = schema_to_flink_ddl(_nested_schema())
        assert "user_id" in out
        assert "user_email" in out
        assert "event_ts" in out

    def test_original_dot_path_not_in_output(self):
        out = schema_to_flink_ddl(_nested_schema())
        # field paths with dots should not appear literally in column names
        assert "user.id" not in out
        assert "user.email" not in out
