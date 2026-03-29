import math
from enum import Enum, StrEnum
from typing import Any

from pydantic import BaseModel, field_validator


class DriftClass(StrEnum):
    DRIFT     = "drift"      # breaking change — alert path
    EVOLUTION = "evolution"  # additive/non-breaking — schema PR path
    NOISE     = "noise"      # below threshold or low confidence — suppress


class FieldType(StrEnum):
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


class PIICategory(StrEnum):
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
    enum_values: list[str] | None = None
    pii_categories: list[PIICategory] = []
    confidence: float = 1.0
    notes: str | None = None

    @field_validator("presence_rate", "confidence", mode="before")
    @classmethod
    def _clamp_unit_float(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


class InferredSchema(BaseModel):
    stream_name: str
    version: str = "1.0.0"
    inferred_at: str
    event_count_sampled: int
    fields: list[FieldSchema]
    top_level_event_types: list[str] | None = None
    inference_model: str
    inference_confidence: float

    @field_validator("inference_confidence", mode="before")
    @classmethod
    def _clamp_unit_float(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


class FieldDrift(BaseModel):
    field_path: str
    drift_type: str
    previous_type: FieldType | None = None
    observed_type: FieldType | None = None
    previous_presence_rate: float | None = None
    observed_presence_rate: float | None = None
    previous_enum_values: list[str] | None = None
    observed_enum_values: list[str] | None = None
    affected_event_rate: float
    tier: DriftTier
    auto_correctable: bool
    proposed_correction: str | None = None
    correction_confidence: float | None = None
    cluster_id: str | None = None  # sub-schema cluster this drift belongs to; None = flat schema path
    drift_class: DriftClass = DriftClass.DRIFT  # classification: drift | evolution | noise


class DriftReport(BaseModel):
    stream_name: str
    detected_at: str
    schema_version: str
    events_sampled: int
    drifts: list[FieldDrift]
    highest_tier: DriftTier
    summary: str
    evolution_count: int = 0  # number of EVOLUTION-class drifts in this report
    noise_count: int = 0      # number of NOISE-class drifts in this report


class SubSchema(BaseModel):
    cluster_id: str
    detection_method: str        # "event_type_field" | "structural_fingerprint" | "single"
    event_count: int
    sample_rate: float           # fraction of total stream events this cluster represents
    fields: list[FieldSchema]
    inference_confidence: float
    top_keys: list[str]          # top-level keys seen in this cluster


class StreamProfile(BaseModel):
    stream_name: str
    profiled_at: str
    total_events_sampled: int
    parse_success_rate: float    # (clean + partial) / total lines attempted
    discovery_method: str        # "event_type_field" | "structural_fingerprint" | "single"
    routing_field: str | None = None  # explicit field name used for event routing (e.g. "event_type")
    sub_schemas: list[SubSchema]
    profile_model: str


# ---------------------------------------------------------------------------
# History, Velocity, and Proposal models
# ---------------------------------------------------------------------------

class TrendStatus(StrEnum):
    STABLE            = "stable"
    RISING            = "rising"
    DECLINING         = "declining"
    VOLATILE          = "volatile"
    INSUFFICIENT_DATA = "insufficient_data"


class SnapshotMeta(BaseModel):
    stream_name: str
    snapshot_date: str           # YYYY-MM-DD
    profiled_at: str             # original profile.profiled_at
    total_events_sampled: int
    cluster_ids: list[str]
    field_count: int
    triggered_by: str = "manual" # "manual" | "cron" | "watch"


class FieldDiffEntry(BaseModel):
    field_path: str
    cluster_id: str | None = None
    # "added" | "removed" | "type_changed" | "presence_changed"
    # | "enum_changed" | "pii_added" | "pii_removed" | "required_changed"
    # | "new_cluster" | "cluster_removed"
    change_type: str
    before: dict | None = None   # serialised snapshot of the left-side field
    after: dict | None = None    # serialised snapshot of the right-side field
    # Pre-computed deltas for quick consumption
    delta_presence_rate: float | None = None  # after - before
    delta_confidence: float | None = None
    enum_added: list[str] | None = None
    enum_removed: list[str] | None = None
    # "breaking" | "non_breaking" | "informational"
    significance: str = "informational"


class ProfileDiff(BaseModel):
    stream_name: str
    left_date: str
    right_date: str
    days_between: int
    changes: list[FieldDiffEntry]
    breaking_count: int = 0
    non_breaking_count: int = 0
    informational_count: int = 0
    fields_stable_count: int = 0
    summary: str = ""


class FieldVelocity(BaseModel):
    field_path: str
    cluster_id: str | None = None
    trend: TrendStatus = TrendStatus.INSUFFICIENT_DATA
    trend_slope: float | None = None  # presence_rate change per day (+ = rising)
    current_presence_rate: float = 0.0
    baseline_presence_rate: float = 0.0
    presence_rates: list[float] = []     # chronological, oldest first
    snapshot_dates: list[str] = []       # matching dates
    confidence_history: list[float] = []
    type_changes: list[str] = []         # ["YYYY-MM-DD: string → integer", ...]
    enum_history: list[dict] = []        # [{"date": ..., "values": [...]}, ...]
    enum_growth_rate: float | None = None  # new distinct values per 30 days
    alert: str | None = None          # non-None = alert message
    weeks_of_data: int = 0


class VelocityReport(BaseModel):
    stream_name: str
    computed_at: str
    snapshot_count: int
    snapshot_dates: list[str] = []
    fields: list[FieldVelocity] = []
    alerts: list[str] = []              # consolidated for quick CI/grep scanning
    schema_stability_score: float = 1.0 # 0.0 (chaotic) – 1.0 (perfectly stable)


class ProposalAction(StrEnum):
    PROMOTE_TO_REQUIRED = "promote_to_required"
    DEMOTE_TO_OPTIONAL  = "demote_to_optional"
    REMOVE_FIELD        = "remove_field"
    FLAG_NEW_PII        = "flag_new_pii"
    WIDEN_TYPE          = "widen_type"


class BaselineProposal(BaseModel):
    field_path: str
    cluster_id: str | None = None
    action: ProposalAction
    current_schema_value: str | None = None  # human description of current state
    proposed_value: str | None = None        # human description of proposed state
    evidence: str = ""
    confidence: float = 0.0
    weeks_of_evidence: int = 0


class ProposalReport(BaseModel):
    stream_name: str
    generated_at: str
    weeks_of_history: int
    proposals: list[BaselineProposal] = []
    auto_appliable: list[BaselineProposal] = []   # confidence >= threshold, non-breaking
    requires_review: list[BaselineProposal] = []
    summary: str = ""


# ---------------------------------------------------------------------------
# Drift incident lifecycle
# ---------------------------------------------------------------------------

class DriftIncidentStatus(StrEnum):
    OPEN       = "open"       # detected, not yet acted on
    ACCEPTED   = "accepted"   # schema updated to reflect new state
    SUPPRESSED = "suppressed" # muted until suppressed_until date
    RESOLVED   = "resolved"   # drift cleared on its own (no action taken)


class DriftIncident(BaseModel):
    id: str                              # "drift-YYYY-MM-DD-HHMM-<field>"
    field_path: str
    cluster_id: str | None = None
    drift_type: str
    tier: int                            # 1 | 2 | 3
    first_detected: str                  # ISO8601
    last_seen: str                       # ISO8601
    occurrences: int = 1
    status: DriftIncidentStatus = DriftIncidentStatus.OPEN
    resolved_at: str | None = None
    resolution_note: str | None = None
    suppressed_until: str | None = None  # ISO8601 — only set when status=suppressed


class DriftState(BaseModel):
    stream_name: str
    updated_at: str
    incidents: list[DriftIncident] = []
