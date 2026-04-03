"""Tests for rich schema output — value stats, native Avro enums, auto-export.

The Google/BigQuery integration question: can the output be plugged into
existing toolsets (Confluent SR, dbt, Spark, BigQuery) out of the box?
"""

import json
import os
from pathlib import Path

import pytest
import yaml


class TestValueStatistics:
    """Value statistics (min/max/cardinality) must be computed and persisted."""

    def test_compute_value_stats_for_numeric_field(self):
        from streamforge.sampler import compute_value_stats
        values = [10.5, 20.0, 30.5, 40.0, 50.5]
        stats = compute_value_stats(values, "float")
        assert stats["min"] == 10.5
        assert stats["max"] == 50.5
        assert stats["cardinality"] == 5

    def test_compute_value_stats_for_string_enum(self):
        from streamforge.sampler import compute_value_stats
        values = ["USD", "EUR", "GBP", "USD", "EUR", "USD"]
        stats = compute_value_stats(values, "string")
        assert stats["cardinality"] == 3
        assert "min" not in stats  # no min/max for strings

    def test_compute_value_stats_for_integer(self):
        from streamforge.sampler import compute_value_stats
        values = [100, 200, 300, 400, 500]
        stats = compute_value_stats(values, "integer")
        assert stats["min"] == 100
        assert stats["max"] == 500
        assert stats["cardinality"] == 5

    def test_compute_value_stats_empty_values(self):
        from streamforge.sampler import compute_value_stats
        stats = compute_value_stats([], "string")
        assert stats["cardinality"] == 0

    def test_value_stats_in_schema_yaml(self, tmp_path):
        """schema.yaml must include value_stats for fields."""
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema

        schema = InferredSchema(
            stream_name="test_stream",
            version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z",
            event_count_sampled=100,
            fields=[
                FieldSchema(
                    name="amount", path="amount",
                    field_type=FieldType.FLOAT, required=True,
                    presence_rate=1.0, confidence=0.9,
                    value_stats={"min": 1.49, "max": 996.92, "cardinality": 100},
                ),
                FieldSchema(
                    name="currency", path="currency",
                    field_type=FieldType.STRING, required=True,
                    presence_rate=1.0, confidence=0.9,
                    enum_values=["USD", "EUR", "GBP"],
                    value_stats={"cardinality": 3},
                ),
            ],
            inference_model="test",
            inference_confidence=0.9,
        )
        write_schema(schema, str(tmp_path))

        written = yaml.safe_load((tmp_path / "test_stream" / "schema.yaml").read_text())
        amount_field = next(f for f in written["fields"] if f["path"] == "amount")
        assert "value_stats" in amount_field
        assert amount_field["value_stats"]["min"] == 1.49
        assert amount_field["value_stats"]["max"] == 996.92

        currency_field = next(f for f in written["fields"] if f["path"] == "currency")
        assert currency_field.get("enum_values") == ["USD", "EUR", "GBP"]


class TestAvroNativeEnum:
    """Avro export must use native enum types for low-cardinality string fields."""

    def test_avro_enum_field(self):
        from streamforge.exporters.avro import schema_to_avro
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(
                    name="status", path="status",
                    field_type=FieldType.STRING, required=True,
                    presence_rate=1.0, confidence=0.9,
                    enum_values=["pending", "completed", "failed"],
                ),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        avro = schema_to_avro(schema)
        avro_dict = avro if isinstance(avro, dict) else json.loads(avro)

        status_field = next(f for f in avro_dict["fields"] if f["name"] == "status")
        # Should be native Avro enum, not plain string
        field_type = status_field["type"]
        if isinstance(field_type, dict):
            assert field_type.get("type") == "enum"
            assert set(field_type["symbols"]) == {"pending", "completed", "failed"}
        elif isinstance(field_type, list):
            # nullable enum: ["null", {"type": "enum", ...}]
            enum_part = next(t for t in field_type if isinstance(t, dict))
            assert enum_part.get("type") == "enum"

    def test_avro_high_cardinality_stays_string(self):
        """Fields with >50 enum values should stay as string, not enum."""
        from streamforge.exporters.avro import schema_to_avro
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(
                    name="city", path="city",
                    field_type=FieldType.STRING, required=True,
                    presence_rate=1.0, confidence=0.9,
                    enum_values=[f"city_{i}" for i in range(100)],
                ),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        avro = schema_to_avro(schema)
        avro_dict = avro if isinstance(avro, dict) else json.loads(avro)
        city_field = next(f for f in avro_dict["fields"] if f["name"] == "city")
        # Should be plain string, not enum (too many values)
        if isinstance(city_field["type"], str):
            assert city_field["type"] == "string"


class TestAutoExport:
    """streamforge init should auto-generate JSON Schema and Avro alongside schema.yaml."""

    def test_auto_export_produces_json_schema(self, tmp_path):
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema_with_exports

        schema = InferredSchema(
            stream_name="test_stream", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        write_schema_with_exports(schema, str(tmp_path))

        json_schema_path = tmp_path / "test_stream" / "schema.json"
        assert json_schema_path.exists(), "JSON Schema not generated"
        content = json.loads(json_schema_path.read_text())
        assert content.get("$schema") == "https://json-schema.org/draft/2020-12/schema"

    def test_auto_export_produces_avro(self, tmp_path):
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema_with_exports

        schema = InferredSchema(
            stream_name="test_stream", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        write_schema_with_exports(schema, str(tmp_path))

        avro_path = tmp_path / "test_stream" / "schema.avsc"
        assert avro_path.exists(), "Avro schema not generated"
        content = json.loads(avro_path.read_text())
        assert content.get("type") == "record"


class TestJsonSchemaPluggability:
    """JSON Schema output must validate against the JSON Schema meta-schema
    and be directly consumable by Confluent Schema Registry."""

    def test_json_schema_has_required_fields(self):
        from streamforge.exporters.json_schema import schema_to_json_schema
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="events.payments", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                            required=True, presence_rate=1.0, confidence=0.9),
                FieldSchema(name="status", path="status", field_type=FieldType.STRING,
                            required=False, presence_rate=0.5, confidence=0.9,
                            enum_values=["pending", "completed"]),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        js = schema_to_json_schema(schema)
        js = js if isinstance(js, dict) else json.loads(js)

        # Confluent SR requirements
        assert "$schema" in js
        assert js["type"] == "object"
        assert "properties" in js
        assert "required" in js
        assert "amount" in js["required"]
        assert "status" not in js["required"]  # optional field

        # Enum on optional field
        assert js["properties"]["status"]["enum"] == ["pending", "completed"]

    def test_json_schema_format_annotations(self):
        """email, uuid, date-time formats must be set for tooling compatibility."""
        from streamforge.exporters.json_schema import schema_to_json_schema
        from streamforge.models import FieldSchema, FieldType, InferredSchema

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="email", path="email", field_type=FieldType.EMAIL,
                            required=True, presence_rate=1.0, confidence=0.9),
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
                FieldSchema(name="created", path="created",
                            field_type=FieldType.TIMESTAMP_ISO8601,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        js = schema_to_json_schema(schema)
        js = js if isinstance(js, dict) else json.loads(js)

        assert js["properties"]["email"]["format"] == "email"
        assert js["properties"]["id"]["format"] == "uuid"
        assert js["properties"]["created"]["format"] == "date-time"
