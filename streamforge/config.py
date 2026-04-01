"""
streamforge/config.py — Central Configuration System
=====================================================

Design decisions:
  ADR-001: Layered resolution — CLI > env vars > config.yaml > defaults.
  ADR-002: Flat dataclass surface — callers get cfg.kafka.bootstrap_servers,
           not deeply nested dict lookups that blow up at runtime.
  ADR-003: No singleton. Config is constructed once in __main__ and passed
           through call stacks. Makes testing trivial (just pass a different
           Config object). No global state.
  ADR-004: Secrets (API keys, SASL passwords) are NEVER read from config.yaml.
           They must come from env vars or CLI flags. The config file is
           safe to commit.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ── Env-var overrides ──────────────────────────────────────────────────────────
# These are the canonical env vars StreamForge reads. All have STREAMFORGE_ prefix
# except well-known ones (GROQ_API_KEY, SLACK_WEBHOOK_URL) that follow their
# platform's own naming convention.
_ENV = {
    "log_level":            "STREAMFORGE_LOG_LEVEL",
    "log_format":           "STREAMFORGE_LOG_FORMAT",
    "schemas_dir":          "STREAMFORGE_SCHEMAS_DIR",
    "drift_reports_dir":    "STREAMFORGE_DRIFT_REPORTS_DIR",
    "inference_model":      "STREAMFORGE_MODEL",
    "inference_base_url":   "STREAMFORGE_BASE_URL",
    "kafka_bootstrap":      "KAFKA_BOOTSTRAP_SERVERS",
    "kafka_security":       "KAFKA_SECURITY_PROTOCOL",
    "kafka_sasl_mechanism": "KAFKA_SASL_MECHANISM",
    "kafka_sasl_username":  "KAFKA_SASL_USERNAME",
    "kafka_sasl_password":  "KAFKA_SASL_PASSWORD",
    "slack_webhook":        "SLACK_WEBHOOK_URL",
    "slack_channel":        "SLACK_CHANNEL",
    "pagerduty_key":        "PAGERDUTY_ROUTING_KEY",
    "api_key":              "GROQ_API_KEY",          # primary
    "api_key_openai":       "OPENAI_API_KEY",        # fallback
    "api_key_generic":      "LLM_API_KEY",           # generic fallback
}


@dataclass
class InferenceConfig:
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"
    max_prompt_chars: int = 20_000
    max_retries: int = 3


@dataclass
class KafkaConfig:
    bootstrap_servers: list[str] = field(default_factory=list)
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    ssl_ca_location: str | None = None
    ssl_cert_location: str | None = None
    ssl_key_location: str | None = None
    consumer_group: str = "streamforge-profiler"
    auto_offset_reset: str = "earliest"
    max_poll_records: int = 500
    session_timeout_ms: int = 30_000
    request_timeout_ms: int = 40_000  # must be > session_timeout_ms (kafka-python requirement)
    sample_target: int = 1_000


@dataclass
class DriftConfig:
    type_change_threshold: float = 0.05
    presence_drop_threshold: float = 0.15
    enum_new_value_threshold: float = 0.05
    statistical_alpha: float = 0.01
    min_sample_for_stats: int = 30
    psi_threshold_low: float = 0.10
    psi_threshold_high: float = 0.20


@dataclass
class SamplingConfig:
    init_sample_size: int = 500
    watch_sample_size: int = 200
    watch_interval_seconds: int = 30


@dataclass
class PIIConfig:
    enabled: bool = True
    patterns_enabled: bool = True
    field_hints_enabled: bool = True
    flag_email_values: bool = True
    flag_internal_ips: bool = False


@dataclass
class SlackConfig:
    enabled: bool = False
    webhook_url: str | None = None
    channel: str | None = None
    mention_on_tier3: str = "<!here>"
    min_tier: int = 2


@dataclass
class PagerDutyConfig:
    enabled: bool = False
    routing_key: str | None = None
    escalate_on_tier: int = 3
    severity_map: dict[str, str] = field(
        default_factory=lambda: {
            "tier_1": "info",
            "tier_2": "warning",
            "tier_3": "critical",
        }
    )


@dataclass
class NotificationsConfig:
    slack: SlackConfig = field(default_factory=SlackConfig)
    pagerduty: PagerDutyConfig = field(default_factory=PagerDutyConfig)


@dataclass
class OutputConfig:
    schemas_dir: str = "schemas"
    drift_reports_dir: str = "drift_reports"
    consumers_dir: str = "schemas"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "human"      # "human" | "structured"
    log_file: str | None = None


@dataclass
class DashboardConfig:
    port: int = 8501
    refresh_interval: int = 0
    theme: str = "apple"


@dataclass
class Config:
    """
    Top-level configuration object.

    Constructed once at startup by load(). Immutable by convention — treat
    all fields as read-only after construction. Pass the Config object
    explicitly through call stacks instead of using a module-level singleton.
    """
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    drift: DriftConfig = field(default_factory=DriftConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    pii: PIIConfig = field(default_factory=PIIConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    # ── Secret resolution ────────────────────────────────────────────────────
    # Resolved at load-time from env vars. Not in config.yaml.
    _api_key: str | None = field(default=None, repr=False)

    @property
    def api_key(self) -> str | None:
        """LLM API key. Resolved from GROQ_API_KEY, OPENAI_API_KEY, or LLM_API_KEY."""
        return self._api_key


def load(config_path: str | Path | None = None) -> Config:
    """
    Build a Config by merging (lowest → highest priority):
      defaults → config.yaml → environment variables.

    Args:
        config_path: explicit path to config.yaml. If None, searches for
                     config.yaml in the current directory.

    Returns:
        Fully resolved Config ready for use.
    """
    # 1. Start with defaults
    cfg = Config()

    # 2. Find and load config.yaml
    if config_path is None:
        candidates = [
            Path("config.yaml"),
            Path("streamforge.yaml"),
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    if config_path and Path(config_path).exists():
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        logger.debug("Loading config from %s", config_path)
        cfg = _merge_yaml(cfg, raw)
    else:
        logger.debug("No config.yaml found — using defaults and env vars only")

    # 3. Apply environment variable overrides
    cfg = _apply_env(cfg)

    return cfg


def _merge_yaml(cfg: Config, raw: dict) -> Config:
    """Apply values from parsed YAML onto a Config, section by section."""

    def _get(section: str, key: str, default=None):
        return raw.get(section, {}).get(key, default)

    # Inference
    inf = raw.get("inference", {})
    if inf:
        cfg.inference.provider        = inf.get("provider", cfg.inference.provider)
        cfg.inference.model           = inf.get("model", cfg.inference.model)
        cfg.inference.base_url        = inf.get("base_url", cfg.inference.base_url)
        cfg.inference.max_prompt_chars = inf.get("max_prompt_chars", cfg.inference.max_prompt_chars)
        cfg.inference.max_retries     = inf.get("max_retries", cfg.inference.max_retries)

    # Kafka
    k = raw.get("kafka", {})
    if k:
        servers = k.get("bootstrap_servers", cfg.kafka.bootstrap_servers)
        # Support both list and comma-separated string
        if isinstance(servers, str):
            servers = [s.strip() for s in servers.split(",") if s.strip()]
        cfg.kafka.bootstrap_servers  = servers
        cfg.kafka.security_protocol  = k.get("security_protocol", cfg.kafka.security_protocol)
        cfg.kafka.sasl_mechanism     = k.get("sasl_mechanism", cfg.kafka.sasl_mechanism)
        cfg.kafka.consumer_group     = k.get("consumer_group", cfg.kafka.consumer_group)
        cfg.kafka.auto_offset_reset  = k.get("auto_offset_reset", cfg.kafka.auto_offset_reset)
        cfg.kafka.max_poll_records   = k.get("max_poll_records", cfg.kafka.max_poll_records)
        cfg.kafka.session_timeout_ms = k.get("session_timeout_ms", cfg.kafka.session_timeout_ms)
        cfg.kafka.sample_target      = k.get("sample_target", cfg.kafka.sample_target)
        cfg.kafka.ssl_ca_location    = k.get("ssl_ca_location", cfg.kafka.ssl_ca_location)
        cfg.kafka.ssl_cert_location  = k.get("ssl_cert_location", cfg.kafka.ssl_cert_location)
        cfg.kafka.ssl_key_location   = k.get("ssl_key_location", cfg.kafka.ssl_key_location)

    # Drift
    d = raw.get("drift", {})
    if d:
        cfg.drift.type_change_threshold    = d.get("type_change_threshold", cfg.drift.type_change_threshold)
        cfg.drift.presence_drop_threshold  = d.get("presence_drop_threshold", cfg.drift.presence_drop_threshold)
        cfg.drift.enum_new_value_threshold = d.get("enum_new_value_threshold", cfg.drift.enum_new_value_threshold)
        cfg.drift.statistical_alpha        = d.get("statistical_alpha", cfg.drift.statistical_alpha)
        cfg.drift.min_sample_for_stats     = d.get("min_sample_for_stats", cfg.drift.min_sample_for_stats)
        cfg.drift.psi_threshold_low        = d.get("psi_threshold_low", cfg.drift.psi_threshold_low)
        cfg.drift.psi_threshold_high       = d.get("psi_threshold_high", cfg.drift.psi_threshold_high)

    # Sampling
    s = raw.get("sampling", {})
    if s:
        cfg.sampling.init_sample_size       = s.get("init_sample_size", cfg.sampling.init_sample_size)
        cfg.sampling.watch_sample_size      = s.get("watch_sample_size", cfg.sampling.watch_sample_size)
        cfg.sampling.watch_interval_seconds = s.get("watch_interval_seconds", cfg.sampling.watch_interval_seconds)

    # PII
    p = raw.get("pii", {})
    if p:
        cfg.pii.enabled              = p.get("enabled", cfg.pii.enabled)
        cfg.pii.patterns_enabled     = p.get("patterns_enabled", cfg.pii.patterns_enabled)
        cfg.pii.field_hints_enabled  = p.get("field_hints_enabled", cfg.pii.field_hints_enabled)
        cfg.pii.flag_email_values    = p.get("flag_email_values", cfg.pii.flag_email_values)
        cfg.pii.flag_internal_ips    = p.get("flag_internal_ips", cfg.pii.flag_internal_ips)

    # Notifications
    n = raw.get("notifications", {})
    sl = n.get("slack", {})
    if sl:
        cfg.notifications.slack.enabled         = sl.get("enabled", cfg.notifications.slack.enabled)
        cfg.notifications.slack.webhook_url      = sl.get("webhook_url", cfg.notifications.slack.webhook_url)
        cfg.notifications.slack.channel          = sl.get("channel", cfg.notifications.slack.channel)
        cfg.notifications.slack.mention_on_tier3 = sl.get("mention_on_tier3", cfg.notifications.slack.mention_on_tier3)
        cfg.notifications.slack.min_tier         = sl.get("min_tier", cfg.notifications.slack.min_tier)

    pd = n.get("pagerduty", {})
    if pd:
        cfg.notifications.pagerduty.enabled          = pd.get("enabled", cfg.notifications.pagerduty.enabled)
        cfg.notifications.pagerduty.routing_key       = pd.get("routing_key", cfg.notifications.pagerduty.routing_key)
        cfg.notifications.pagerduty.escalate_on_tier  = pd.get("escalate_on_tier", cfg.notifications.pagerduty.escalate_on_tier)

    # Output
    o = raw.get("output", {})
    if o:
        cfg.output.schemas_dir       = o.get("schemas_dir", cfg.output.schemas_dir)
        cfg.output.drift_reports_dir = o.get("drift_reports_dir", cfg.output.drift_reports_dir)
        cfg.output.consumers_dir     = o.get("consumers_dir", cfg.output.consumers_dir)

    # Logging
    lg = raw.get("logging", {})
    if lg:
        cfg.logging.level    = lg.get("level", cfg.logging.level)
        cfg.logging.format   = lg.get("format", cfg.logging.format)
        cfg.logging.log_file = lg.get("log_file", cfg.logging.log_file)

    # Dashboard
    db = raw.get("dashboard", {})
    if db:
        cfg.dashboard.port             = db.get("port", cfg.dashboard.port)
        cfg.dashboard.refresh_interval = db.get("refresh_interval", cfg.dashboard.refresh_interval)
        cfg.dashboard.theme            = db.get("theme", cfg.dashboard.theme)

    return cfg


def _apply_env(cfg: Config) -> Config:
    """Apply environment variable overrides onto an already-loaded Config."""

    def _env(key: str) -> str | None:
        return os.environ.get(_ENV.get(key, ""), "").strip() or None

    # Logging — checked early so subsequent log calls use the right level
    if v := _env("log_level"):
        cfg.logging.level = v.upper()
    if v := _env("log_format"):
        cfg.logging.format = v.lower()

    # Inference
    if v := _env("inference_model"):
        cfg.inference.model = v
    if v := _env("inference_base_url"):
        cfg.inference.base_url = v

    # Kafka
    if v := _env("kafka_bootstrap"):
        cfg.kafka.bootstrap_servers = [s.strip() for s in v.split(",") if s.strip()]
    if v := _env("kafka_security"):
        cfg.kafka.security_protocol = v
    if v := _env("kafka_sasl_mechanism"):
        cfg.kafka.sasl_mechanism = v
    # Secrets: never come from config.yaml — only from env
    cfg.kafka.sasl_username = _env("kafka_sasl_username") or cfg.kafka.sasl_username
    cfg.kafka.sasl_password = _env("kafka_sasl_password") or cfg.kafka.sasl_password

    # Output
    if v := _env("schemas_dir"):
        cfg.output.schemas_dir = v
    if v := _env("drift_reports_dir"):
        cfg.output.drift_reports_dir = v

    # Notifications
    if v := _env("slack_webhook"):
        cfg.notifications.slack.webhook_url = v
        cfg.notifications.slack.enabled = True
    if v := _env("slack_channel"):
        cfg.notifications.slack.channel = v
    if v := _env("pagerduty_key"):
        cfg.notifications.pagerduty.routing_key = v
        cfg.notifications.pagerduty.enabled = True

    # API key — resolved from multiple env vars in priority order
    api_key = (
        _env("api_key")           # GROQ_API_KEY
        or _env("api_key_generic") # LLM_API_KEY
        or _env("api_key_openai")  # OPENAI_API_KEY
    )
    # Use object.__setattr__ to write to the frozen-by-convention _api_key field
    object.__setattr__(cfg, "_api_key", api_key)

    return cfg


# ── Module-level convenience ───────────────────────────────────────────────────
# Lazy-loaded default config for use by submodules that don't receive a
# Config via dependency injection (e.g., the dashboard which is a Streamlit
# script, not a CLI entrypoint). Call load() explicitly in __main__.py.
_default: Config | None = None


def get() -> Config:
    """Return the default Config, loading it if not yet initialised."""
    global _default
    if _default is None:
        _default = load()
    return _default


# ── Startup validation ──────────────────────────────────────────────────────


class ConfigValidationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


def validate_config(
    kafka_brokers: str = "",
    stream_uri: str = "",
    schemas_dir: str = "schemas",
    kafka_security_protocol: str = "",
    env: str = "",
) -> None:
    """Validate configuration before entering watch/init loop.

    Fail fast with a clear error rather than failing mid-operation.

    Args:
        kafka_brokers: Kafka bootstrap servers (required for kafka:// URIs)
        stream_uri: Stream URI (kafka://topic or file path)
        schemas_dir: Output directory for schemas (must be writable)
        kafka_security_protocol: Kafka security protocol (PLAINTEXT rejected in prod)
        env: Environment name (dev/staging/prod)

    Raises:
        ConfigValidationError: If required config is missing or invalid.
    """
    effective_env = env or os.environ.get("STREAMFORGE_ENV", "")

    # Kafka brokers required for kafka:// URIs
    is_kafka = stream_uri.startswith("kafka://")
    if is_kafka and not kafka_brokers.strip():
        raise ConfigValidationError(
            "Kafka broker address is required for kafka:// streams. "
            "Set KAFKA_BOOTSTRAP_SERVERS or pass --brokers."
        )

    # Schemas directory must be writable (or creatable)
    schemas_path = Path(schemas_dir)
    if schemas_path.exists():
        if not os.access(schemas_path, os.W_OK):
            raise ConfigValidationError(
                f"Schemas directory '{schemas_dir}' is not writable. "
                f"Check permissions or set --output to a writable path."
            )
    else:
        # Check if parent exists and is writable (we'll need to create the dir)
        parent = schemas_path.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            raise ConfigValidationError(
                f"Schemas directory '{schemas_dir}' does not exist and parent "
                f"'{parent}' is not writable."
            )

    # Kafka security: reject PLAINTEXT in production
    if is_kafka and kafka_security_protocol.upper() == "PLAINTEXT":
        if effective_env and effective_env not in ("dev", "development", "local", "test"):
            raise ConfigValidationError(
                "PLAINTEXT Kafka is not allowed in production. "
                "Set KAFKA_SECURITY_PROTOCOL=SASL_SSL or STREAMFORGE_ENV=dev."
            )
