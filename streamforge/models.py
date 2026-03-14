from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum


class FieldType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    TIMESTAMP_EPOCH_MS = "timestamp_epoch_ms"
    TIMESTAMP_ISO8601 = "timestamp_iso8601"
    TIMESTAMP_RFC2822 = "timestamp_rfc2822"
    DATE = "date"
    UUID = "uuid"
    EMAIL = "email"
    PHONE = "phone"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"
    MIXED = "mixed"


class PIICategory(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    NAME = "name"
    PASSPORT = "passport"
    CARD_NUMBER = "card_number"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"
    NATIONAL_ID = "national_id"
    ADDRESS = "address"
    LOYALTY_NUMBER = "loyalty_number"


class DriftTier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class FieldSchema(BaseModel):
    name: str
    path: str
    field_type: FieldType
    nullable: bool = False
    required: bool = True
    presence_rate: float = 1.0
    sample_values: list[Any] = []
    enum_values: Optional[list[str]] = None
    pii_categories: list[PIICategory] = []
    confidence: float = 1.0
    notes: Optional[str] = None


class InferredSchema(BaseModel):
    stream_name: str
    version: str = "1.0.0"
    inferred_at: str
    event_count_sampled: int
    fields: list[FieldSchema]
    top_level_event_types: Optional[list[str]] = None
    inference_model: str
    inference_confidence: float


class FieldDrift(BaseModel):
    field_path: str
    drift_type: str
    previous_type: Optional[FieldType] = None
    observed_type: Optional[FieldType] = None
    previous_presence_rate: Optional[float] = None
    observed_presence_rate: Optional[float] = None
    previous_enum_values: Optional[list[str]] = None
    observed_enum_values: Optional[list[str]] = None
    affected_event_rate: float
    tier: DriftTier
    auto_correctable: bool
    proposed_correction: Optional[str] = None
    correction_confidence: Optional[float] = None


class DriftReport(BaseModel):
    stream_name: str
    detected_at: str
    schema_version: str
    events_sampled: int
    drifts: list[FieldDrift]
    highest_tier: DriftTier
    summary: str
