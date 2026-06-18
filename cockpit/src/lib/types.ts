export interface Source {
  name: string
  type: 'kafka' | 'file' | 'sftp'
  uri: string
  status: 'active' | 'inactive' | 'error' | 'unknown'
  last_seen: string | null
  messages_sampled: number
}

export interface Connector {
  type: string
  name: string
  description: string
  available: boolean
  configured: boolean
  formats: string[]
}

export interface MetricsSummary {
  messages_sampled: number
  fields_detected: number
  schemas_inferred: number
  pii_fields: number
  active_drifts: number
  inference_llm_calls?: number
  schema_cache_hits?: number
  inference_statistical?: number
  deterministic_pct?: number | null
}

export interface DriftFinding {
  field_path: string
  drift_type: string
  tier: number | null
  test_name: string | null
  p_value: number | null
  effect_size: number | null
  affected_event_rate: number | null
}

export interface DriftAlert {
  stream: string
  report: string
  detected_at: string
  highest_tier?: number | null
  findings?: DriftFinding[]
}

export interface PiiSummary {
  total: number
  by_category: Record<string, number>
}

export interface HealthComponent {
  name: string
  status: 'ok' | 'error' | 'degraded' | 'unavailable'
  latency_ms: number
  error?: string | null
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error'
  components: HealthComponent[]
}

export interface EnumValue {
  value: string
  count: number
}

export interface FieldRange {
  min: number
  max: number
}

export interface FieldDetail {
  path: string
  type: string
  required: boolean
  nullable: boolean
  presence_rate: number
  confidence: number
  pii: string[]
  notes: string
  sample_values: unknown[]
  enum_values: EnumValue[] | null
  range: FieldRange | null
}

export interface SubSchema {
  cluster_id: string
  event_count: number
  detection_method: string
}

export interface StreamDetail {
  stream: string
  version: string
  inferred_at: string
  inference_model: string
  event_count_sampled: number
  fields: FieldDetail[]
  sub_schemas: SubSchema[]
  sample_count: number
}

export interface SearchResult {
  stream: string
  path: string
  type: string
  required: boolean
  nullable: boolean
  presence_rate: number
  pii: string[]
  notes: string
}

export interface SearchResponse {
  query: string
  filters: { type: string | null; pii_only: boolean }
  count: number
  results: SearchResult[]
}

export interface EvalScenario {
  label: string
  f1: number
  caught: boolean
}

export interface EvalScorecard {
  stream: string
  inference_path: string
  seed: number
  schema: {
    type_precision: number
    type_recall: number
    type_f1: number
    type_accuracy: number
    pii_f1: number
    n_truth: number
    n_inferred: number
  }
  drift: {
    precision: number
    recall: number
    f1: number
    detection_latency_events: number | null
    fpr_null: number
    scenarios: EvalScenario[]
  }
  calibration: {
    ece: number
    n_samples: number
    rating: string
  }
}
