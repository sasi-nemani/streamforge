"""
streamforge/topic_config.py — 3-Layer Configuration Loader
===========================================================

Resolution order (highest → lowest priority):
  config/topics/<topic>.yaml   topic-specific overrides
  config/<env>.yaml            environment overrides (dev / staging / prod)
  config/default.yaml          project baseline

Environment is selected via:
  - STREAMFORGE_ENV env var   (e.g.  export STREAMFORGE_ENV=staging)
  - --env CLI flag            (passed through to load_topic_config)
  Defaults to "dev" if neither is set.

Usage:
    from streamforge.topic_config import load_topic_config

    cfg = load_topic_config("events.payments")        # uses STREAMFORGE_ENV
    cfg = load_topic_config("events.payments", "prod") # explicit env

    # Use cfg as a drop-in replacement for StreamPolicy:
    cfg.sample_size
    cfg.poll_interval_seconds
    cfg.alert_tier
    cfg.action_for(2)         # → "alert"
    cfg.should_block(3)       # → True

    # Extra fields not in StreamPolicy:
    cfg.kafka_brokers         # → "localhost:9092"
    cfg.init_sample_size      # → 500
    cfg.drift.type_change_threshold
"""

from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Root of the config/ directory — relative to the CWD at call time.
# Supports running streamforge from any directory that has a config/ folder.
_CONFIG_ROOT = Path("config")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge override on top of base.
    Scalar values in override replace base. Nested dicts are merged recursively.
    Lists in override replace (not extend) base lists — keeps behaviour predictable.
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        elif val is not None:
            result[key] = val
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file. Returns empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("Could not parse %s: %s — skipping", path, e)
        return {}


def _resolve_raw(topic: str | None, env: str, root: Path) -> dict:
    """
    Build the fully-merged raw config dict for a given topic + env.
    Merge order: default → env → topic (topic is highest priority).
    """
    raw = _load_yaml(root / "default.yaml")
    env_cfg = _load_yaml(root / f"{env}.yaml")
    raw = _deep_merge(raw, env_cfg)

    if topic:
        topic_cfg = _load_yaml(root / "topics" / f"{topic}.yaml")
        if topic_cfg:
            logger.debug("Loaded topic config for %s", topic)
        raw = _deep_merge(raw, topic_cfg)

    return raw


# ── Public config object ───────────────────────────────────────────────────────

@dataclass
class DriftThresholds:
    type_change_threshold: float = 0.05
    presence_drop_threshold: float = 0.15
    enum_new_value_threshold: float = 0.05
    min_sample_for_stats: int = 30
    psi_threshold_low: float = 0.10
    psi_threshold_high: float = 0.20


@dataclass
class NotifSlack:
    enabled: bool = False
    webhook_url: str | None = None
    channel: str | None = None
    min_tier: int = 2


@dataclass
class NotifPagerDuty:
    enabled: bool = False
    routing_key: str | None = None
    escalate_on_tier: int = 3


@dataclass
class StabilityConfig:
    """
    Parameters that govern the LEARNING → STABILIZING → STABLE state machine
    in the watch loop.

    All fields can be overridden per-topic in config/topics/<topic>.yaml under
    a ``stability:`` key, or globally in config/default.yaml.
    Env vars (STREAMFORGE_WARMUP_CYCLES etc.) remain as a fallback when no
    StabilityConfig is present (backward-compat for GCP deploys).
    """
    warmup_cycles: int = 10
    stability_cycles: int = 3
    consecutive_drift_threshold: int = 2
    new_cluster_threshold: float = 0.12
    new_cluster_is_evolution: bool = False


@dataclass
class TopicConfig:
    """
    Unified, resolved configuration for a specific topic + environment.

    Drop-in replacement for StreamPolicy — exposes the same interface plus
    Kafka and drift threshold access.
    """
    topic: str
    env: str

    # Watch settings (mirrors StreamPolicy for backward compat)
    sample_size: int = 200
    poll_interval_seconds: int = 30
    window_capacity: int = 2000
    alert_tier: int = 2
    actions: dict[str, str] = field(default_factory=lambda: {
        "tier_1": "log",
        "tier_2": "alert",
        "tier_3": "block",
    })
    webhook_url: str | None = None

    # Init settings
    init_sample_size: int = 500

    # Kafka
    kafka_brokers: str = "localhost:9092"
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_consumer_group: str = "streamforge-profiler"
    kafka_auto_offset_reset: str = "earliest"
    kafka_session_timeout_ms: int = 30000
    kafka_request_timeout_ms: int = 40000

    # Drift thresholds
    drift: DriftThresholds = field(default_factory=DriftThresholds)

    # Notifications
    slack: NotifSlack = field(default_factory=NotifSlack)
    pagerduty: NotifPagerDuty = field(default_factory=NotifPagerDuty)

    # Stability state-machine parameters
    stability: StabilityConfig = field(default_factory=StabilityConfig)

    # Inference
    inference_model: str = "llama-3.3-70b-versatile"
    inference_base_url: str = "https://api.groq.com/openai/v1"

    # VCS integration (populated from config vcs section)
    vcs_enabled: bool = False
    vcs_backend: str = "git"
    vcs_remote: str = "origin"
    vcs_default_branch: str = "main"
    vcs_auto_commit: bool = True
    vcs_auto_push: bool = True
    vcs_auto_pr: bool = True
    vcs_pr_base_branch: str = "main"
    vcs_pr_reviewers: list[str] = field(default_factory=list)
    vcs_pr_labels: list[str] = field(default_factory=lambda: ["schema-change"])
    vcs_commit_author_name: str = "StreamForge Bot"
    vcs_commit_author_email: str = "streamforge-bot@noreply.local"
    vcs_github_repo: str = ""
    vcs_gitlab_url: str = "https://gitlab.com"
    vcs_gitlab_repo: str = ""

    # Registry integration
    registry_enabled: bool = False
    registry_backend: str = "confluent"
    registry_url: str = "http://localhost:8081"
    registry_format: str = "avro"
    registry_subject_suffix: str = "-value"
    registry_glue_registry_name: str = "StreamForge"

    # ── StreamPolicy compat interface ──────────────────────────────────────────

    def action_for(self, tier: int) -> str:
        """Return the configured action string for a drift tier (1/2/3)."""
        return self.actions.get(f"tier_{tier}", "alert")

    def should_alert(self, tier: int) -> bool:
        return tier >= self.alert_tier

    def should_block(self, tier: int) -> bool:
        return self.action_for(tier) == "block"

    @property
    def kafka_broker_list(self) -> list[str]:
        """Return brokers as a list (split on comma)."""
        if not self.kafka_brokers:
            return []
        return [b.strip() for b in self.kafka_brokers.split(",") if b.strip()]

    @property
    def registry_config(self):
        """Return a RegistryConfig constructed from this TopicConfig's registry_* fields."""
        from .registries import RegistryConfig
        return RegistryConfig(
            enabled=self.registry_enabled,
            backend=self.registry_backend,
            url=self.registry_url,
            format=self.registry_format,
            subject_suffix=self.registry_subject_suffix,
            glue_registry_name=self.registry_glue_registry_name,
        )

    @property
    def vcs_config(self):
        """Return a VCSConfig constructed from this TopicConfig's vcs_* fields."""
        from .vcs import VCSConfig
        return VCSConfig(
            enabled=self.vcs_enabled,
            backend=self.vcs_backend,
            remote=self.vcs_remote,
            default_branch=self.vcs_default_branch,
            auto_commit=self.vcs_auto_commit,
            auto_push=self.vcs_auto_push,
            auto_pr=self.vcs_auto_pr,
            pr_base_branch=self.vcs_pr_base_branch,
            pr_reviewers=self.vcs_pr_reviewers,
            pr_labels=self.vcs_pr_labels,
            commit_author_name=self.vcs_commit_author_name,
            commit_author_email=self.vcs_commit_author_email,
            github_repo=self.vcs_github_repo,
            gitlab_url=self.vcs_gitlab_url,
            gitlab_repo=self.vcs_gitlab_repo,
        )


# ── Public loader ──────────────────────────────────────────────────────────────

def load_topic_config(
    topic: str | None = None,
    env: str | None = None,
    config_root: Path | None = None,
) -> TopicConfig:
    """
    Load and merge config for a topic + environment.

    Args:
        topic:       Kafka topic name (e.g. "events.payments") or file stream name.
                     If None, only default + env config is loaded.
        env:         Environment name ("dev", "staging", "prod").
                     Defaults to STREAMFORGE_ENV env var, then "dev".
        config_root: Override the config/ directory path (useful in tests).

    Returns:
        Fully resolved TopicConfig.
    """
    root = Path(config_root) if config_root is not None else _CONFIG_ROOT
    resolved_env = env or os.environ.get("STREAMFORGE_ENV", "dev")
    raw = _resolve_raw(topic, resolved_env, root)

    w = raw.get("watch", {})
    i = raw.get("init", {})
    d = raw.get("drift", {})
    k = raw.get("kafka", {})
    n = raw.get("notifications", {})
    sl = n.get("slack", {})
    pd = n.get("pagerduty", {})
    inf = raw.get("inference", {})
    v = raw.get("vcs", {})
    reg = raw.get("registry", {})
    stab_raw = raw.get("stability", {})

    actions_raw = w.get("actions", {})
    actions = {
        "tier_1": actions_raw.get("tier_1", "log"),
        "tier_2": actions_raw.get("tier_2", "alert"),
        "tier_3": actions_raw.get("tier_3", "block"),
    }

    # Kafka brokers: topic config → env var → config file
    kafka_brokers_from_env = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    kafka_brokers = kafka_brokers_from_env or k.get("brokers") or "localhost:9092"

    # Notification secrets from env vars take precedence over config
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL") or sl.get("webhook_url")
    pd_key = os.environ.get("PAGERDUTY_ROUTING_KEY") or pd.get("routing_key")

    return TopicConfig(
        topic=topic or "",
        env=resolved_env,
        # Watch
        sample_size=int(w.get("sample_size", 200)),
        poll_interval_seconds=int(w.get("interval_seconds", 30)),
        window_capacity=int(w.get("window_capacity", 2000)),
        alert_tier=int(w.get("alert_tier", 2)),
        actions=actions,
        webhook_url=w.get("webhook_url"),
        # Init
        init_sample_size=int(i.get("sample_size", 500)),
        # Kafka
        kafka_brokers=kafka_brokers,
        kafka_security_protocol=k.get("security_protocol", "PLAINTEXT"),
        kafka_consumer_group=k.get("consumer_group", "streamforge-profiler"),
        kafka_auto_offset_reset=k.get("auto_offset_reset", "earliest"),
        kafka_session_timeout_ms=int(k.get("session_timeout_ms", 30000)),
        kafka_request_timeout_ms=int(k.get("request_timeout_ms", 40000)),
        # Drift
        drift=DriftThresholds(
            type_change_threshold=float(d.get("type_change_threshold", 0.05)),
            presence_drop_threshold=float(d.get("presence_drop_threshold", 0.15)),
            enum_new_value_threshold=float(d.get("enum_new_value_threshold", 0.05)),
            min_sample_for_stats=int(d.get("min_sample_for_stats", 30)),
            psi_threshold_low=float(d.get("psi_threshold_low", 0.10)),
            psi_threshold_high=float(d.get("psi_threshold_high", 0.20)),
        ),
        # Notifications
        slack=NotifSlack(
            enabled=bool(sl.get("enabled", False)) or bool(slack_webhook),
            webhook_url=slack_webhook,
            channel=sl.get("channel"),
            min_tier=int(sl.get("min_tier", 2)),
        ),
        pagerduty=NotifPagerDuty(
            enabled=bool(pd.get("enabled", False)) or bool(pd_key),
            routing_key=pd_key,
            escalate_on_tier=int(pd.get("escalate_on_tier", 3)),
        ),
        # Inference
        inference_model=inf.get("model", "llama-3.3-70b-versatile"),
        inference_base_url=inf.get("base_url", "https://api.groq.com/openai/v1"),
        # VCS
        vcs_enabled=bool(v.get("enabled", False)),
        vcs_backend=v.get("backend", "git"),
        vcs_remote=v.get("remote", "origin"),
        vcs_default_branch=v.get("default_branch", "main"),
        vcs_auto_commit=bool(v.get("auto_commit", True)),
        vcs_auto_push=bool(v.get("auto_push", True)),
        vcs_auto_pr=bool(v.get("auto_pr", True)),
        vcs_pr_base_branch=v.get("pr_base_branch", "main"),
        vcs_pr_reviewers=v.get("pr_reviewers", []) or [],
        vcs_pr_labels=v.get("pr_labels", ["schema-change"]) or ["schema-change"],
        vcs_commit_author_name=v.get("commit_author_name", "StreamForge Bot"),
        vcs_commit_author_email=v.get("commit_author_email", "streamforge-bot@noreply.local"),
        vcs_github_repo=v.get("github_repo", ""),
        vcs_gitlab_url=v.get("gitlab_url", "https://gitlab.com"),
        vcs_gitlab_repo=v.get("gitlab_repo", ""),
        # Registry
        registry_enabled=bool(reg.get("enabled", False)),
        registry_backend=reg.get("backend", "confluent"),
        registry_url=os.environ.get("SCHEMA_REGISTRY_URL", reg.get("url", "http://localhost:8081")),
        registry_format=reg.get("format", "avro"),
        registry_subject_suffix=reg.get("subject_suffix", "-value"),
        registry_glue_registry_name=os.environ.get("GLUE_REGISTRY_NAME", reg.get("glue_registry_name", "StreamForge")),
        # Stability
        stability=StabilityConfig(
            warmup_cycles=int(stab_raw.get("warmup_cycles", 10)),
            stability_cycles=int(stab_raw.get("stability_cycles", 3)),
            consecutive_drift_threshold=int(stab_raw.get("consecutive_drift_threshold", 2)),
            new_cluster_threshold=float(stab_raw.get("new_cluster_threshold", 0.12)),
            new_cluster_is_evolution=bool(stab_raw.get("new_cluster_is_evolution", False)),
        ),
    )


# ── Scaffold helper ────────────────────────────────────────────────────────────

_SCAFFOLD_TEMPLATE = """\
# StreamForge — Topic Config: {topic}
# {bar}
# Override any default.yaml values here. Uncomment blocks to activate.
#
# Resolution order: this file > config/<env>.yaml > config/default.yaml

# watch:
#   interval_seconds: 30
#   sample_size: 200
#   window_capacity: 2000
#   alert_tier: 2

# stability:
#   warmup_cycles: 10        # Phase 1: observe this many cycles before alerting
#   stability_cycles: 3      # Phase 2: consecutive clean cycles needed for STABLE
#   consecutive_drift_threshold: 2  # Phase 3: flap suppression
#   new_cluster_threshold: 0.12     # fraction of events that form a new cluster
#   new_cluster_is_evolution: false # true = auto-accept new clusters as evolution

# drift:
#   type_change_threshold: 0.05
#   presence_drop_threshold: 0.15
"""


def scaffold_topic_config(topic: str, config_root: Path = _CONFIG_ROOT) -> Path | None:
    """
    Create ``config_root/topics/<topic>.yaml`` with commented-out defaults.

    Returns the Path of the created file, or None if the file already exists.
    This function is idempotent: safe to call multiple times.

    Args:
        topic:       Topic / stream name (e.g. "events.payments").
        config_root: Override the config/ directory (useful in tests).
    """
    topics_dir = Path(config_root) / "topics"
    target = topics_dir / f"{topic}.yaml"

    if target.exists():
        return None

    topics_dir.mkdir(parents=True, exist_ok=True)

    bar = "=" * (len("StreamForge — Topic Config: ") + len(topic))
    content = _SCAFFOLD_TEMPLATE.format(topic=topic, bar=bar)
    target.write_text(content, encoding="utf-8")
    logger.debug("Scaffolded topic config: %s", target)
    return target
