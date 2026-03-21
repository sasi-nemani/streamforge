import logging
import os
from datetime import UTC
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .drift_detector import detect_drift
from .inference import DEFAULT_BASE_URL, DEFAULT_MODEL, infer_sub_schema
from .models import DriftReport, DriftTier, StreamProfile
from .policy import StreamPolicy, load_policy, write_policy
from .profiler import discover_clusters, get_detection_method, get_routing_field
from .report_writer import write_drift_report
from .sampler import (
    get_all_field_paths,
    load_events_from_folder,
    load_events_resilient,
    reservoir_sample,
    split_by_quality,
)
from .schema_writer import (
    load_profile,
    load_schema,
    write_inference_report,
    write_profile,
    write_profile_report,
    write_samples,
    write_schema,
)
from .topic_config import load_topic_config

app = typer.Typer(
    name="streamforge",
    help="StreamForge — AI-native schema inference and drift detection for event streams",
    add_completion=True,
)
console = Console()
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("STREAMFORGE_LOG_LEVEL", "WARNING"),
    format="%(levelname)s %(name)s: %(message)s",
)

# Env vars checked in order: LLM_API_KEY, GROQ_API_KEY, OPENAI_API_KEY
_KEY_ENV_VARS = ["LLM_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"]


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key
    if not key:
        for var in _KEY_ENV_VARS:
            key = os.environ.get(var, "")
            if key:
                break
    if not key:
        console.print(
            "[red]Error:[/red] No API key found. Set GROQ_API_KEY (or OPENAI_API_KEY / LLM_API_KEY) "
            "or pass --api-key.\n"
            "  Get a free Groq key at: https://console.groq.com"
        )
        raise typer.Exit(1)
    return key


def _stream_name(stream_path: str) -> str:
    p = Path(stream_path).resolve()
    if p.name in ("stream", "events", "data", "logs"):
        return f"{p.parent.name}.{p.name}"
    return p.name


def _auto_detect_schema(stream_path: str, output_dir: str) -> str | None:
    """Try to find schema.yaml for the given stream path."""
    candidate = Path(output_dir) / _stream_name(stream_path) / "schema.yaml"
    if candidate.exists():
        return str(candidate)
    return None


@app.command()
def init(
    stream_path: str = typer.Argument(..., help="Folder path or kafka://topic URI"),
    sample_size: int = typer.Option(0, "--sample-size", "-n", help="Number of events to sample (0 = use config)"),
    output_dir: str = typer.Option("schemas", "--output", "-o", help="Output directory for schema files"),
    api_key: str | None = typer.Option(None, "--api-key", help="LLM API key (or set GROQ_API_KEY / OPENAI_API_KEY)"),
    model: str = typer.Option("", "--model", "-m", help="Model name (default from config)"),
    base_url: str = typer.Option("", "--base-url", help="OpenAI-compatible API base URL (default from config)"),
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Kafka broker list (e.g. localhost:9092). Only used for kafka:// URIs.",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
    env: str | None = typer.Option(
        None, "--env",
        help="Config environment to use (dev/staging/prod). Overrides STREAMFORGE_ENV env var.",
    ),
    allow_partial_inference: bool = typer.Option(
        False,
        "--allow-partial-inference",
        help=(
            "Include partially-reconstructed events (regex fallback parse) in schema inference. "
            "Off by default because partial events have degraded field fidelity and can skew "
            "the canonical schema. Use only when clean events are insufficient."
        ),
    ),
    push_to: str | None = typer.Option(
        None, "--push-to",
        help="Schema registry URL to push inferred schema (e.g. http://localhost:8081 for Confluent SR)",
    ),
):
    """Infer schema from event stream. Produces profile.yaml, profile_report.md, and schema.yaml.

    \b
    Supports two sources:
      streamforge init events/payments/stream_v1                         # NDJSON folder
      streamforge init kafka://events.payments --brokers localhost:9092  # Kafka topic
      streamforge init kafka://events.payments --env staging             # with env config
    """
    import asyncio
    from datetime import datetime

    _MIN_CLEAN_EVENTS = 20  # floor below which inference quality is unreliable

    is_kafka = stream_path.startswith("kafka://")
    key = _resolve_api_key(api_key)

    # Resolve topic name for config lookup
    _topic_for_cfg = stream_path[len("kafka://"):] if is_kafka else _stream_name(stream_path)
    tc = load_topic_config(_topic_for_cfg, env)

    # Apply config defaults for flags that weren't explicitly set
    effective_sample_size = sample_size if sample_size > 0 else tc.init_sample_size
    effective_model    = model    if model    else tc.inference_model
    effective_base_url = base_url if base_url else tc.inference_base_url

    # Early registry connectivity check — fail before inference if registry is unreachable
    _reg_backend_early = None
    if push_to or tc.registry_enabled:
        from .registries import get_registry_backend, subject_for_topic
        from .registries.confluent import ConfluentRegistryBackend
        if push_to:
            _reg_backend_early = ConfluentRegistryBackend(url=push_to)
        else:
            _reg_backend_early = get_registry_backend(tc.registry_config)
        if _reg_backend_early:
            ping_result = _reg_backend_early.ping()
            if not ping_result:
                console.print(f"[red]Registry not reachable:[/red] {ping_result.error}")
                console.print("[dim]Fix registry connectivity before running init.[/dim]")
                raise typer.Exit(1)
            console.print("[dim]Registry reachable — will push after inference[/dim]")

    if is_kafka:
        topic = stream_path[len("kafka://"):]
        stream_name = topic  # keep dots — matches what watch auto-detects

        from .config import KafkaConfig
        from .connectors.kafka import KafkaConnector, KafkaConnectorError

        # Brokers: CLI flag → config (which already checked KAFKA_BOOTSTRAP_SERVERS)
        broker_list = (
            [b.strip() for b in brokers.split(",") if b.strip()]
            if brokers
            else tc.kafka_broker_list
        )
        if not broker_list:
            console.print("[red]--brokers required for kafka:// URIs (or set KAFKA_BOOTSTRAP_SERVERS)[/red]")
            raise typer.Exit(1)

        kafka_cfg = KafkaConfig(
            bootstrap_servers=broker_list,
            security_protocol=tc.kafka_security_protocol,
            auto_offset_reset="earliest",
            consumer_group=f"streamforge-init-{topic}",
        )

        console.print(f"[bold]StreamForge[/bold] — profiling [cyan]{topic}[/cyan] (Kafka)")
        console.print(f"Consuming up to {effective_sample_size} events from [cyan]{topic}[/cyan]...")

        async def _consume() -> list[dict]:
            async with KafkaConnector(topic, kafka_cfg) as conn:
                return await conn.read_batch(max_messages=effective_sample_size, timeout_ms=15_000)

        try:
            all_events = asyncio.run(_consume())
        except KafkaConnectorError as e:
            console.print(f"[red]Kafka error:[/red] {e}")
            raise typer.Exit(1)

        if not all_events:
            console.print(f"[red]No events received from topic '{topic}' within 15s.[/red]")
            console.print("[dim]Make sure the feed is running: python3 kafka_docker_demo/feed_kafka.py[/dim]")
            raise typer.Exit(1)

        console.print(f"✓ Consumed [green]{len(all_events)}[/green] events from Kafka")
        clean_events = all_events
        inference_events = all_events
        ingest_stats = {"total": len(all_events), "clean": len(all_events), "partial": 0}
        parse_success_rate = 1.0

    else:
        stream_name = _stream_name(stream_path)
        console.print(f"[bold]StreamForge[/bold] — profiling [cyan]{stream_name}[/cyan]")

        # Load with resilient parser — handles broken JSON, log-prefixed lines, partial extracts
        all_events, parse_stats = load_events_resilient(stream_path)
        if not all_events:
            console.print(f"[red]No events found in {stream_path}[/red]")
            raise typer.Exit(1)

        # P1-C: split clean vs partial
        clean_events, partial_events = split_by_quality(all_events)

        total_lines = parse_stats["total_lines"] or 1
        parse_success_rate = (parse_stats["parsed_clean"] + parse_stats["parsed_partial"]) / total_lines
        skipped = parse_stats["skipped"]

        parse_color = "green" if parse_success_rate >= 0.95 else "yellow" if parse_success_rate >= 0.80 else "red"
        console.print(
            f"✓ Loaded [{parse_color}]{len(all_events)} events[/{parse_color}]"
            f" from {parse_stats['total_lines']} lines"
            f" — parse rate [{parse_color}]{parse_success_rate:.1%}[/{parse_color}]"
            + (f"  ({len(partial_events)} partial, {skipped} skipped)" if (partial_events or skipped) else "")
        )

        if len(clean_events) < _MIN_CLEAN_EVENTS:
            if not allow_partial_inference:
                console.print(
                    f"[red]Error:[/red] Only {len(clean_events)} clean (fully-parsed) events found — "
                    f"too few for reliable schema inference (minimum {_MIN_CLEAN_EVENTS}).\n"
                    f"  {len(partial_events)} partial events were excluded because they were reconstructed "
                    f"via regex fallback and may not reflect the true event schema.\n"
                    f"  To include them anyway, rerun with [bold]--allow-partial-inference[/bold]."
                )
                raise typer.Exit(1)
            console.print(
                f"[yellow]⚠ --allow-partial-inference set: using all {len(all_events)} events "
                f"({len(partial_events)} partial) — schema quality may be degraded.[/yellow]"
            )
            inference_events = all_events
        else:
            if partial_events:
                console.print(
                    f"✓ Using [green]{len(clean_events)}[/green] clean events for inference "
                    f"[dim]({len(partial_events)} partial excluded)[/dim]"
                )
            inference_events = clean_events

        ingest_stats = {
            "total": len(all_events),
            "clean": len(clean_events),
            "partial": len(partial_events),
        }

    # Sample from clean (or allowed) events only
    sample = reservoir_sample(inference_events, effective_sample_size)
    sampled_note = "(all)" if len(sample) == len(inference_events) else "reservoir sample"
    console.print(f"✓ Sampled [bold]{len(sample)}[/bold] events {sampled_note}")

    # Discover clusters
    clusters = discover_clusters(sample)
    method = get_detection_method(clusters)
    real_clusters = {k: v for k, v in clusters.items() if k not in ("_other", "_sparse")}
    noise_count = sum(len(v) for k, v in clusters.items() if k in ("_other", "_sparse"))

    console.print(f"\n✓ Discovered [bold]{len(real_clusters)}[/bold] sub-schema(s) via [cyan]{method}[/cyan]:")
    for cid, evts in list(real_clusters.items()):
        pct = len(evts) / len(sample) * 100
        console.print(f"    [cyan]{cid:<35}[/cyan] {len(evts):>5} events  ({pct:.1f}%)")
    if noise_count:
        console.print(f"    [dim]_other / _sparse               {noise_count:>5} events  (noise bucket, not inferred)[/dim]")

    # Infer sub-schemas — one LLM call per significant cluster
    console.print(f"\n🤖 Inferring sub-schemas with [bold]{effective_model}[/bold]...")
    sub_schemas = []
    all_pii = []

    for cid, cluster_events in real_clusters.items():
        console.print(f"   → [cyan]{cid}[/cyan] ({len(cluster_events)} events)...")
        sub = infer_sub_schema(
            cluster_id=cid,
            events=cluster_events,
            detection_method=method,
            total_stream_events=len(sample),
            api_key=key,
            model=effective_model,
            base_url=effective_base_url,
        )
        sub_schemas.append(sub)
        pii = [(f.path, f.pii_categories) for f in sub.fields if f.pii_categories]
        all_pii.extend([(cid, p, cats) for p, cats in pii])
        console.print(
            f"     ✓ {len(sub.fields)} fields, confidence {sub.inference_confidence:.0%}"
        )

    if all_pii:
        console.print("\n[yellow]⚠ PII detected:[/yellow]")
        for cid, path, cats in all_pii:
            cat_str = ", ".join(p.value for p in cats)
            console.print(f"   [yellow]{cid}[/yellow] → [cyan]{path}[/cyan] ({cat_str})")

    # Determine the explicit routing field so watch/plan don't need to re-derive it
    routing_field = get_routing_field(clusters, sample)

    # Assemble StreamProfile
    profile = StreamProfile(
        stream_name=stream_name,
        profiled_at=datetime.now(UTC).isoformat(),
        total_events_sampled=len(sample),
        parse_success_rate=round(parse_success_rate, 4),
        discovery_method=method,
        routing_field=routing_field,
        sub_schemas=sub_schemas,
        profile_model=effective_model,
    )

    # Write profile.yaml and profile_report.md
    profile_path = write_profile(profile, output_dir)
    profile_report_path = write_profile_report(profile, output_dir)
    write_samples(sample, output_dir, stream_name)

    # Write schema.yaml from the primary (largest) cluster for backwards compat with watch/plan
    if sub_schemas:
        primary = sub_schemas[0]
        from .models import InferredSchema
        compat_schema = InferredSchema(
            stream_name=stream_name,
            version="1.0.0",
            inferred_at=profile.profiled_at,
            event_count_sampled=len(sample),
            fields=primary.fields,
            top_level_event_types=[s.cluster_id for s in sub_schemas] if len(sub_schemas) > 1 else None,
            inference_model=effective_model,
            inference_confidence=primary.inference_confidence,
        )
        schema_path = write_schema(compat_schema, output_dir)
        write_inference_report(compat_schema, output_dir, ingest_stats=ingest_stats)
        console.print(f"\n✓ Written: [green]{profile_path}[/green]")
        console.print(f"✓ Written: [green]{profile_report_path}[/green]")
        console.print(f"✓ Written: [green]{schema_path}[/green] [dim](primary cluster — for watch/plan)[/dim]")

    # Write default policy
    policy = StreamPolicy(stream=stream_name, sample_size=effective_sample_size)
    policy_path = write_policy(policy, output_dir)
    console.print(f"✓ Written: [green]{policy_path}[/green]")

    # VCS: commit new schema files if enabled
    from .vcs import SchemaCommitContext, get_vcs_backend
    vcs = get_vcs_backend(tc.vcs_config)
    if vcs and vcs.is_available() and tc.vcs_auto_commit:
        schema_dir = Path(output_dir) / stream_name
        ctx = SchemaCommitContext(
            stream_name=stream_name,
            old_version=None,
            new_version="1.0.0",
            action="init",
            files=[
                schema_dir / "schema.yaml",
                schema_dir / "profile.yaml",
                schema_dir / "profile_report.md",
                schema_dir / "stream_policy.yaml",
            ],
        )
        result = vcs.commit_schema(ctx)
        if result.success:
            console.print(f"✓ VCS: [green]{result}[/green]")
        else:
            console.print(f"[yellow]⚠ VCS commit skipped:[/yellow] {result.error}")

    # Registry: push schema if --push-to provided or registry enabled in config
    if sub_schemas and (push_to or tc.registry_enabled):
        from .registries import get_registry_backend, subject_for_topic
        # Reuse the backend created during the early ping check
        reg_backend = _reg_backend_early
        if reg_backend:
            subject = subject_for_topic(stream_name, tc.registry_subject_suffix)
            reg_result = reg_backend.push_schema(subject, compat_schema, tc.registry_format)
            if reg_result:
                console.print(
                    f"✓ Registry: [green]{subject}[/green] "
                    f"id={reg_result.schema_id} v{reg_result.version}"
                )
            else:
                console.print(f"[yellow]⚠ Registry push failed:[/yellow] {reg_result.error}")


@app.command()
def watch(
    stream_path: str = typer.Argument(..., help="Folder path or kafka://topic URI"),
    schema_path: str | None = typer.Option(None, "--schema", help="Path to schema.yaml (auto-detected if not set)"),
    interval: int = typer.Option(0, "--interval", "-i", help="Poll interval in seconds (0 = use config)"),
    sample_size: int = typer.Option(0, "--sample-size", "-n", help="Events to sample per cycle (0 = use config)"),
    window_capacity: int = typer.Option(0, "--window", help="Rolling event window size (0 = use config)"),
    webhook: str | None = typer.Option(None, "--webhook", "-w", help="Webhook URL for drift notifications"),
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Comma-separated Kafka broker list (e.g. broker-1:9092,broker-2:9092). "
             "Only used when stream_path is a kafka:// URI. "
             "Overrides KAFKA_BOOTSTRAP_SERVERS env var.",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
    env: str | None = typer.Option(
        None, "--env",
        help="Config environment to use (dev/staging/prod). "
             "Overrides STREAMFORGE_ENV env var.",
    ),
):
    """Watch stream for schema drift. Runs continuously until Ctrl+C.

    Supports two sources:

    \b
      streamforge watch events/payments/stream_v1               # file-based
      streamforge watch kafka://events.payments --brokers b:9092  # Kafka topic
      streamforge watch kafka://events.payments --env prod        # with env config

    Config is loaded from config/topics/<topic>.yaml → config/<env>.yaml → config/default.yaml.
    CLI flags override config file values when explicitly provided.
    """
    is_kafka = stream_path.startswith("kafka://")

    # Schema auto-detection uses the topic name for kafka:// URIs
    schema_stream_path = stream_path[len("kafka://"):] if is_kafka else stream_path
    resolved_schema = schema_path or _auto_detect_schema(schema_stream_path, "schemas")
    if not resolved_schema:
        console.print(
            f"[red]No schema.yaml found for {schema_stream_path}. "
            "Run 'streamforge init' first or pass --schema.[/red]"
        )
        raise typer.Exit(1)

    # Load resolved config for this topic + env
    stream_name = schema_stream_path if is_kafka else Path(stream_path).name
    tc = load_topic_config(stream_name, env)

    # CLI flags take priority over config; 0 means "use config"
    effective_interval  = interval       if interval       > 0 else tc.poll_interval_seconds
    effective_sample    = sample_size    if sample_size    > 0 else tc.sample_size
    effective_window    = window_capacity if window_capacity > 0 else tc.window_capacity
    effective_webhook   = webhook or tc.webhook_url

    if is_kafka:
        topic = stream_path[len("kafka://"):]
        from .config import KafkaConfig
        from .drift_detector import watch_stream_kafka

        # Brokers: CLI flag → env var (inside tc via KAFKA_BOOTSTRAP_SERVERS) → topic config
        effective_brokers = (
            [b.strip() for b in brokers.split(",") if b.strip()]
            if brokers
            else tc.kafka_broker_list
        )
        if not effective_brokers:
            console.print(
                "[red]No Kafka brokers configured. "
                "Pass --brokers, set KAFKA_BOOTSTRAP_SERVERS, or add kafka.brokers to config/.[/red]"
            )
            raise typer.Exit(1)

        kafka_cfg = KafkaConfig(
            bootstrap_servers=effective_brokers,
            security_protocol=tc.kafka_security_protocol,
            consumer_group=tc.kafka_consumer_group,
            auto_offset_reset=tc.kafka_auto_offset_reset,
            session_timeout_ms=tc.kafka_session_timeout_ms,
            request_timeout_ms=tc.kafka_request_timeout_ms,
        )

        watch_stream_kafka(
            topic, kafka_cfg, resolved_schema,
            effective_interval, effective_sample, effective_window, effective_webhook,
        )
    else:
        from .drift_detector import watch_stream
        watch_stream(stream_path, resolved_schema, effective_interval, effective_sample, effective_window, effective_webhook)


@app.command(name="kafka-ping")
def kafka_ping(
    topic: str = typer.Argument(..., help="Kafka topic name to test"),
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Comma-separated broker list (e.g. broker-1:9092,broker-2:9092)",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
    sasl_username: str | None = typer.Option(None, "--sasl-username", envvar="KAFKA_SASL_USERNAME"),
    sasl_password: str | None = typer.Option(None, "--sasl-password", envvar="KAFKA_SASL_PASSWORD"),
    security_protocol: str = typer.Option("PLAINTEXT", "--security-protocol"),
    sasl_mechanism: str | None = typer.Option(None, "--sasl-mechanism"),
    timeout: int = typer.Option(10, "--timeout", help="Connection timeout in seconds"),
):
    """Test connectivity to a Kafka broker and topic.

    \b
    Example:
      streamforge kafka-ping payments --brokers broker-1:9092 --sasl-username sf --sasl-password secret
    """
    import asyncio
    import json as _json

    from .config import KafkaConfig
    from .connectors.kafka import KafkaConnector, KafkaConnectorError

    if not brokers:
        from .config import load as _load_config
        cfg_brokers = _load_config().kafka.bootstrap_servers
        if not cfg_brokers:
            console.print(
                "[red]No Kafka brokers configured. "
                "Pass --brokers or set KAFKA_BOOTSTRAP_SERVERS.[/red]"
            )
            raise typer.Exit(1)
        broker_list = cfg_brokers
    else:
        broker_list = [b.strip() for b in brokers.split(",") if b.strip()]

    kafka_cfg = KafkaConfig(
        bootstrap_servers=broker_list,
        security_protocol=security_protocol,
        sasl_mechanism=sasl_mechanism,
        sasl_username=sasl_username,
        sasl_password=sasl_password,
        auto_offset_reset="latest",
        consumer_group="streamforge-ping",
    )

    async def _ping() -> None:
        async with KafkaConnector(topic, kafka_cfg) as conn:
            console.print(f"✓ Connected: [green]{conn.source_id}[/green]")
            batch = await conn.read_batch(max_messages=5, timeout_ms=timeout * 1_000)
            if batch:
                console.print(f"✓ Received [bold]{len(batch)}[/bold] sample message(s) from [cyan]{topic}[/cyan]")
                preview = _json.dumps(batch[0])
                console.print(f"  Preview: {preview[:200]}{'…' if len(preview) > 200 else ''}")
            else:
                console.print(
                    f"○ Connected but no messages arrived within {timeout}s "
                    f"(topic may be empty or producing slowly — this is not an error)"
                )

    try:
        asyncio.run(_ping())
    except KafkaConnectorError as e:
        console.print(f"[red]Kafka not available:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def discover(
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Kafka broker list (e.g. localhost:9092)",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
    filter: str = typer.Option("*", "--filter", "-f", help="Glob pattern to filter topics (e.g. 'events.*')"),
    output_dir: str = typer.Option("schemas", "--output", "-o", help="Directory to check for existing schemas"),
    env: str | None = typer.Option(None, "--env", help="Config environment (dev/staging/prod)"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
):
    """Discover Kafka topics and check which ones have schemas.

    \b
    Connects to the Kafka broker, lists all topics matching the filter, then
    checks which ones have been initialised with 'streamforge init'.

    \b
    Examples:
      streamforge discover --brokers localhost:9092
      streamforge discover --brokers localhost:9092 --filter "events.*"
      streamforge discover --brokers localhost:9092 --format json | jq '.[] | select(.has_schema == false)'
    """
    import fnmatch
    import json as _json

    from .schema_writer import load_drift_state

    tc = load_topic_config(None, env)
    effective_brokers = (
        [b.strip() for b in brokers.split(",") if b.strip()]
        if brokers
        else tc.kafka_broker_list
    )
    if not effective_brokers:
        console.print("[red]No Kafka brokers configured. Pass --brokers or set KAFKA_BOOTSTRAP_SERVERS.[/red]")
        raise typer.Exit(1)

    broker_str = ",".join(effective_brokers)

    # List topics via confluent-kafka AdminClient or kafka-python
    try:
        try:
            from confluent_kafka.admin import AdminClient
            admin = AdminClient({"bootstrap.servers": broker_str})
            metadata = admin.list_topics(timeout=10)
            all_topics = list(metadata.topics.keys())
        except ImportError:
            from kafka import KafkaAdminClient  # type: ignore[import]
            admin_client = KafkaAdminClient(
                bootstrap_servers=effective_brokers,
                client_id="streamforge-discover",
                request_timeout_ms=10_000,
            )
            all_topics = admin_client.list_topics()
            admin_client.close()
    except Exception as e:
        console.print(f"[red]Could not list Kafka topics:[/red] {e}")
        raise typer.Exit(1)

    # Filter internal topics and apply user glob filter
    topics = [
        t for t in sorted(all_topics)
        if not t.startswith("_") and fnmatch.fnmatch(t, filter)
    ]

    schema_root = Path(output_dir)
    results: list[dict] = []
    for topic in topics:
        schema_yaml = schema_root / topic / "schema.yaml"
        has_schema = schema_yaml.exists()
        version = None
        open_incidents = 0
        if has_schema:
            try:
                s = load_schema(str(schema_yaml))
                version = s.version
                state = load_drift_state(schema_root / topic)
                from .models import DriftIncidentStatus
                open_incidents = sum(1 for i in state.incidents if i.status == DriftIncidentStatus.OPEN)
            except Exception:
                pass
        results.append({
            "topic": topic,
            "has_schema": has_schema,
            "version": version,
            "open_incidents": open_incidents,
        })

    if output_format == "json":
        print(_json.dumps(results, indent=2))
        return

    t = Table(title=f"Kafka Topics — {effective_brokers[0]}", show_header=True, header_style="bold")
    t.add_column("Topic", style="cyan")
    t.add_column("Schema", justify="center")
    t.add_column("Version", justify="center")
    t.add_column("Open Incidents", justify="right")
    for r in results:
        schema_str = "[green]✓[/green]" if r["has_schema"] else "[dim]—[/dim]"
        incidents_str = (
            f"[red]{r['open_incidents']}[/red]" if r["open_incidents"] > 0
            else "[dim]0[/dim]"
        )
        t.add_row(r["topic"], schema_str, r["version"] or "—", incidents_str)

    console.print(t)
    with_schema = sum(1 for r in results if r["has_schema"])
    console.print(
        f"\n[dim]{len(results)} topics | "
        f"[green]{with_schema} with schema[/green] | "
        f"[yellow]{len(results) - with_schema} without schema[/yellow][/dim]"
    )
    if len(results) - with_schema > 0:
        console.print(
            "[dim]Run 'streamforge init kafka://<topic> --brokers ...' to initialise a topic.[/dim]"
        )


@app.command()
def report(
    stream_path: str = typer.Argument(...),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
):
    """Print current schema and drift history for a stream."""
    stream_name = _stream_name(stream_path)
    schema_path = Path(output_dir) / stream_name / "schema.yaml"

    if not schema_path.exists():
        console.print(f"[red]No schema found at {schema_path}. Run 'streamforge init' first.[/red]")
        raise typer.Exit(1)

    schema = load_schema(str(schema_path))

    # Schema table
    table = Table(title=f"Schema — {stream_name} (v{schema.version})", show_header=True)
    table.add_column("Field", style="cyan")
    table.add_column("Type")
    table.add_column("Required")
    table.add_column("Confidence")
    table.add_column("PII")
    table.add_column("Notes")

    for f in schema.fields:
        pii_str = ", ".join(p.value for p in f.pii_categories) if f.pii_categories else "—"
        table.add_row(
            f.path,
            f.field_type.value,
            "✓" if f.required else "○",
            f"{f.confidence:.0%}",
            pii_str,
            (f.notes or "")[:60],
        )

    console.print(table)
    console.print(f"\nInferred: {schema.inferred_at}")
    console.print(f"Events sampled: {schema.event_count_sampled}")
    console.print(f"Overall confidence: {schema.inference_confidence:.0%}")

    # Drift history
    drift_dir = Path("drift_reports") / stream_name
    if drift_dir.exists():
        reports = sorted(drift_dir.glob("*.md"), reverse=True)
        if reports:
            console.print(f"\n[bold]Drift History[/bold] ({len(reports)} report(s)):")
            for r in reports[:10]:
                console.print(f"  • {r.name}")
        else:
            console.print("\n[green]No drift reports found — schema is clean.[/green]")
    else:
        console.print("\n[green]No drift reports found — schema is clean.[/green]")


@app.command()
def validate(
    stream_name: str = typer.Argument(..., help="Stream name or path (e.g. events.payments)"),
    event: str | None = typer.Option(None, "--event", "-e", help="Inline JSON event string"),
    file: str | None = typer.Option(None, "--file", "-f", help="Path to JSON event file"),
    schema_path: str | None = typer.Option(None, "--schema", "-s", help="Path to schema.yaml (auto-detected if omitted)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    strict: bool = typer.Option(False, "--strict", help="Fail on unknown fields not in schema"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
):
    """Validate an event against its schema. Exit 0=valid, 1=invalid (CI gate).

    \b
    Reads event from --event, --file, or stdin (pipe-friendly).

    \b
    Examples:
      echo '{"amount": 9.99}' | streamforge validate events.payments
      streamforge validate events.payments --file event.json
      streamforge validate events.payments --event '{"event_id":"x","amount":9.99}'
      cat events.ndjson | streamforge validate events.payments --strict
    """
    import json as _json
    import sys

    from .sampler import flatten_nested

    # Resolve schema
    resolved_schema = schema_path or _auto_detect_schema(stream_name, output_dir)
    if resolved_schema is None:
        # Also try stream_name directly as a schema directory name
        candidate = Path(output_dir) / stream_name / "schema.yaml"
        if candidate.exists():
            resolved_schema = str(candidate)
    if not resolved_schema:
        console.print(
            f"[red]No schema.yaml found for '{stream_name}'. Run 'streamforge init' first.[/red]"
        )
        raise typer.Exit(1)

    schema = load_schema(resolved_schema)
    field_map = {f.path: f for f in schema.fields}

    # Read event JSON
    raw_json: str
    if event:
        raw_json = event
    elif file:
        raw_json = Path(file).read_text(encoding="utf-8").strip()
    elif not sys.stdin.isatty():
        raw_json = sys.stdin.read().strip()
    else:
        console.print("[red]Provide event via --event, --file, or stdin.[/red]")
        raise typer.Exit(1)

    try:
        parsed = _json.loads(raw_json)
    except _json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON:[/red] {e}")
        raise typer.Exit(1)

    if not isinstance(parsed, dict):
        console.print("[red]Event must be a JSON object (dict).[/red]")
        raise typer.Exit(1)

    flat_event = flatten_nested(parsed)

    violations: list[dict] = []

    # Check required fields are present
    for field in schema.fields:
        if field.required and field.path not in flat_event:
            violations.append({
                "field": field.path,
                "rule": "required_missing",
                "message": f"Required field '{field.path}' is absent",
                "severity": "error",
            })

    # Check enum values
    for path, value in flat_event.items():
        if path not in field_map:
            if strict:
                violations.append({
                    "field": path,
                    "rule": "unknown_field",
                    "message": f"Unknown field '{path}' (--strict mode)",
                    "severity": "warning",
                })
            continue
        field_schema = field_map[path]
        if field_schema.enum_values and value is not None:
            str_val = str(value)
            if str_val not in field_schema.enum_values:
                violations.append({
                    "field": path,
                    "rule": "enum_violation",
                    "message": f"Value {str_val!r} not in allowed values: {field_schema.enum_values[:10]}",
                    "severity": "error",
                })

    is_valid = not any(v["severity"] == "error" for v in violations)

    if output_format == "json":
        print(_json.dumps({
            "valid": is_valid,
            "stream": schema.stream_name,
            "schema_version": schema.version,
            "violations": violations,
        }, indent=2))
    else:
        if is_valid and not violations:
            console.print(f"[green]✓ Valid[/green] — event matches [cyan]{schema.stream_name}[/cyan] v{schema.version}")
        else:
            status_str = "[red]✗ Invalid[/red]" if not is_valid else "[yellow]⚠ Warnings[/yellow]"
            console.print(f"{status_str} — [cyan]{schema.stream_name}[/cyan] v{schema.version}")
            t = Table(show_header=True, header_style="bold")
            t.add_column("Field", style="cyan")
            t.add_column("Rule")
            t.add_column("Message")
            t.add_column("Severity", justify="center")
            for v in violations:
                sev_color = "red" if v["severity"] == "error" else "yellow"
                t.add_row(v["field"], v["rule"], v["message"], f"[{sev_color}]{v['severity']}[/{sev_color}]")
            console.print(t)

    raise typer.Exit(0 if is_valid else 1)


@app.command()
def plan(
    stream_path: str = typer.Argument(...),
    schema_path: str | None = typer.Option(None, "--schema"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    sample_size: int = typer.Option(200, "--sample-size", "-n"),
    api_key: str | None = typer.Option(None, "--api-key"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url"),
):
    """One-shot drift check. Like 'terraform plan' — shows drift without persisting."""
    resolved_schema = schema_path or _auto_detect_schema(stream_path, output_dir)
    if not resolved_schema:
        console.print(
            "[red]No schema.yaml found. Run 'streamforge init' first or pass --schema.[/red]"
        )
        raise typer.Exit(1)

    baseline = load_schema(resolved_schema)
    stream_name = Path(stream_path).name
    policy = load_policy(output_dir, baseline.stream_name)

    console.print(f"[bold]StreamForge Plan[/bold] — checking [cyan]{stream_name}[/cyan] against schema v{baseline.version}")

    events = load_events_from_folder(stream_path)
    if not events:
        console.print(f"[red]No events found in {stream_path}[/red]")
        raise typer.Exit(1)

    effective_sample = sample_size if sample_size != 200 else policy.sample_size
    sample = reservoir_sample(events, effective_sample)
    console.print(f"Sampled {len(sample)} events from {stream_path}")

    # P1-A: use multi-schema drift detection when profile.yaml is available
    from .drift_detector import detect_drift_multi_schema
    schema_dir = Path(resolved_schema).parent
    profile = load_profile(schema_dir)
    multi_schema = profile is not None and len(profile.get("sub_schemas", [])) > 1

    tier_colors = {DriftTier.TIER_1: "yellow", DriftTier.TIER_2: "orange3", DriftTier.TIER_3: "red"}

    def _print_drifts(drift_report: "DriftReport") -> None:
        console.print(
            Panel(
                f"[bold]⚠ DRIFT DETECTED[/bold] — {len(drift_report.drifts)} issue(s) found\n"
                f"Highest severity: Tier {drift_report.highest_tier.value}",
                expand=False,
            )
        )
        for d in drift_report.drifts:
            color = tier_colors.get(d.tier, "white")
            tier_label = f"[{color}][TIER {d.tier.value}][/{color}]"
            cid_note = f" [{d.cluster_id}]" if d.cluster_id else ""

            if d.drift_type == "type_changed":
                detail = f"{d.previous_type.value} → {d.observed_type.value} ({d.affected_event_rate:.0%} of events)"
            elif d.drift_type == "field_removed":
                detail = f"field removed (was {d.previous_presence_rate:.0%} present, now {d.observed_presence_rate:.0%})"
            elif d.drift_type == "field_added":
                detail = f"new {'required' if (d.observed_presence_rate or 0) >= 0.8 else 'optional'} field (not in baseline schema)"
            elif d.drift_type == "new_pii":
                detail = "new PII field detected"
            elif d.drift_type == "enum_changed":
                detail = f"new enum values detected ({d.affected_event_rate:.0%} of events)"
            elif d.drift_type == "presence_drop":
                detail = f"presence rate dropped {d.previous_presence_rate:.0%} → {d.observed_presence_rate:.0%}"
            elif d.drift_type == "new_cluster":
                detail = d.proposed_correction or "new event family detected"
            else:
                detail = d.drift_type

            console.print(f"  {tier_label} [cyan]{d.field_path}[/cyan]{cid_note} — {detail}")

    if multi_schema:
        console.print(f"[dim]Multi-schema mode — {len(profile['sub_schemas'])} clusters from profile.yaml[/dim]")
        reports = detect_drift_multi_schema(profile, sample, stream_name)
        if not reports:
            console.print(Panel("[green]✓ No drift detected — all clusters clean.[/green]", expand=False))
            return
        all_highest = max(r.highest_tier for r in reports)
        for drift_report in reports:
            _print_drifts(drift_report)
            report_path = write_drift_report(drift_report, "drift_reports")
            console.print(f"\nReport saved: [green]{report_path}[/green]")
        highest = all_highest.value
    else:
        drift_report = detect_drift(baseline, sample, stream_name)
        if drift_report is None:
            console.print(Panel("[green]✓ No drift detected — schema is clean.[/green]", expand=False))
            return
        _print_drifts(drift_report)
        report_path = write_drift_report(drift_report, "drift_reports")
        console.print(f"\nReport saved: [green]{report_path}[/green]")
        highest = drift_report.highest_tier.value

    # Policy: block on Tier 3 if configured
    if policy.should_block(highest):
        console.print(
            f"\n[red]Policy action: BLOCK (tier_{highest}=block in stream_policy.yaml)[/red]\n"
            f"Fix the drift before merging or deploying."
        )
        raise typer.Exit(1)


@app.command()
def profile(
    stream_path: str = typer.Argument(..., help="Path to folder containing NDJSON event files"),
    sample_size: int = typer.Option(500, "--sample-size", "-n"),
    top: int = typer.Option(30, "--top", "-t", help="Show top N fields by presence rate"),
    show_values: bool = typer.Option(True, "--values/--no-values", help="Show sample values"),
):
    """Profile a stream: show field stats, types, presence rates — no LLM call."""

    stream_name = _stream_name(stream_path)
    console.print(f"[bold]StreamForge Profile[/bold] — [cyan]{stream_name}[/cyan]\n")

    # Resilient load — so profile also handles messy data
    events, parse_stats = load_events_resilient(stream_path)
    if not events:
        console.print(f"[red]No events found in {stream_path}[/red]")
        raise typer.Exit(1)

    sample = reservoir_sample(events, sample_size)

    # Parse quality banner
    total_lines = parse_stats["total_lines"] or 1
    parse_rate = (parse_stats["parsed_clean"] + parse_stats["parsed_partial"]) / total_lines
    parse_color = "green" if parse_rate >= 0.95 else "yellow" if parse_rate >= 0.80 else "red"
    console.print(
        Panel(
            f"[bold]{len(events)}[/bold] events from [bold]{parse_stats['total_lines']}[/bold] lines  •  "
            f"Parse rate [{parse_color}]{parse_rate:.1%}[/{parse_color}]  •  "
            f"[dim]{parse_stats['parsed_partial']} partial  •  {parse_stats['skipped']} skipped[/dim]",
            title="Ingest Quality",
            expand=False,
        )
    )

    # Discover clusters
    clusters = discover_clusters(sample)
    method = get_detection_method(clusters)
    real_clusters = {k: v for k, v in clusters.items() if k not in ("_other", "_sparse")}
    n_clusters = len(real_clusters)

    # Cluster summary table
    if n_clusters > 1:
        console.print(f"\n[bold]{n_clusters} sub-schemas discovered[/bold] via [cyan]{method}[/cyan]\n")
        ct = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        ct.add_column("Cluster", style="cyan", no_wrap=True, max_width=40)
        ct.add_column("Events", justify="right")
        ct.add_column("% Stream", justify="right")
        ct.add_column("Top Keys", max_width=50)
        for cid, evts in real_clusters.items():
            top_k = sorted(
                {k for e in evts[:20] for k in e if not k.startswith("_")},
                key=lambda k: sum(1 for e in evts if k in e),
                reverse=True,
            )[:6]
            ct.add_row(
                cid,
                str(len(evts)),
                f"{len(evts)/len(sample):.0%}",
                ", ".join(top_k),
            )
        console.print(ct)
    else:
        console.print("\n[dim]Single schema stream (no distinct event types detected)[/dim]")

    import re as _re

    def _quick_type(values: list) -> str:
        if not values:
            return "null"
        counts: dict[str, int] = {}
        for v in values[:50]:
            if isinstance(v, bool):
                t = "boolean"
            elif isinstance(v, int):
                t = "timestamp_epoch_ms" if 1_000_000_000_000 <= v <= 9_999_999_999_999 else "integer"
            elif isinstance(v, float):
                t = "float"
            elif isinstance(v, list):
                t = "array"
            elif isinstance(v, dict):
                t = "object"
            elif isinstance(v, str):
                if _re.match(r'^\d{4}-\d{2}-\d{2}T', v):
                    t = "timestamp_iso8601"
                elif _re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', v, _re.I):
                    t = "uuid"
                elif _re.match(r'^[^@]+@[^@]+\.[^@]+$', v):
                    t = "email"
                else:
                    t = "string"
            else:
                t = "null"
            counts[t] = counts.get(t, 0) + 1
        types = [k for k in counts if counts[k] > 0]
        if len(types) > 1:
            return "mixed(" + "/".join(sorted(types)) + ")"
        return max(counts, key=lambda k: counts[k])

    def _render_cluster_fields(field_values: dict, presence_rates: dict, label: str) -> None:
        sorted_fields = sorted(presence_rates.items(), key=lambda x: -x[1])
        total_fields = len(sorted_fields)
        required_count = sum(1 for _, r in sorted_fields if r >= 0.8)
        optional_count = sum(1 for _, r in sorted_fields if 0.1 <= r < 0.8)
        rare_count = sum(1 for _, r in sorted_fields if r < 0.1)

        console.print(
            Panel(
                f"[bold]{total_fields}[/bold] fields  •  "
                f"[green]{required_count} required[/green] (≥80%)  •  "
                f"[yellow]{optional_count} optional[/yellow] (10-80%)  •  "
                f"[dim]{rare_count} rare[/dim] (<10%)",
                title=f"[cyan]{label}[/cyan]",
                expand=False,
            )
        )

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("Field Path", style="cyan", no_wrap=True, max_width=50)
        table.add_column("Type", max_width=22)
        table.add_column("Presence", justify="right")
        table.add_column("Nulls", justify="right")
        table.add_column("Distinct", justify="right")
        if show_values:
            table.add_column("Sample Values", max_width=45)

        for path, rate in sorted_fields[:top]:
            vals = field_values.get(path, [])
            null_count = sum(1 for v in vals if v is None)
            non_null = [v for v in vals if v is not None]
            distinct = len({str(v) for v in non_null[:200]})
            inferred = _quick_type(non_null)

            rate_str = (
                f"[green]{rate:.0%}[/green]" if rate >= 0.8
                else f"[yellow]{rate:.0%}[/yellow]" if rate >= 0.5
                else f"[dim]{rate:.0%}[/dim]"
            )
            type_str = (
                f"[red]{inferred}[/red]" if "mixed" in inferred
                else f"[blue]{inferred}[/blue]" if inferred.startswith("timestamp")
                else inferred
            )
            row = [path, type_str, rate_str, str(null_count) if null_count else "—", str(distinct)]
            if show_values:
                previews = [repr(v)[:40] for v in non_null[:3]]
                row.append(", ".join(previews))
            table.add_row(*row)

        console.print(table)
        if total_fields > top:
            console.print(f"[dim]... {total_fields - top} more fields (use --top {total_fields} to see all)[/dim]")

        mixed = [
            (p, r) for p, r in sorted_fields
            if "mixed" in _quick_type([v for v in field_values.get(p, []) if v is not None])
        ]
        if mixed:
            console.print(f"\n[red]⚠ Mixed-type fields ({len(mixed)}):[/red]")
            for p, r in mixed[:10]:
                console.print(f"  [red]•[/red] [cyan]{p}[/cyan] ({r:.0%})")

    # Per-cluster field tables
    display_clusters = real_clusters if n_clusters > 1 else {stream_name: sample}
    for cid, cluster_events in display_clusters.items():
        clean_evts = [{k: v for k, v in e.items() if not k.startswith("_")} for e in cluster_events]
        field_values, presence_rates = get_all_field_paths(clean_evts)
        console.print()
        _render_cluster_fields(field_values, presence_rates, cid)


@app.command()
def ui(
    port: int = typer.Option(8501, "--port", "-p"),
):
    """Launch the visual dashboard (Streamlit)."""
    import subprocess
    import sys
    ui_script = Path(__file__).parent / "ui.py"
    if not ui_script.exists():
        console.print("[red]streamforge/ui.py not found.[/red]")
        raise typer.Exit(1)
    console.print(f"Opening dashboard at [cyan]http://localhost:{port}[/cyan]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ui_script), f"--server.port={port}", "--server.headless=false"])


@app.command()
def export(
    schema_dir: str = typer.Argument(..., help="Path to a schema directory (e.g. schemas/stream_v1) or schema.yaml file"),
    fmt: str = typer.Option("json-schema", "--format", "-f", help="Export format: json-schema | avro | flink-ddl | ksqldb | proto"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path (default: auto)"),
    brokers: str | None = typer.Option(None, "--brokers", help="Kafka broker(s) for connector DDL (optional)", envvar="KAFKA_BOOTSTRAP_SERVERS"),
):
    """Export schema to JSON Schema, Avro, Flink DDL, ksqlDB, or Protobuf format.

    \b
    Examples:
      streamforge export schemas/events.payments --format avro
      streamforge export schemas/events.payments --format flink-ddl --brokers localhost:9092
      streamforge export schemas/events.payments --format ksqldb
      streamforge export schemas/events.payments --format proto
    """
    import json

    # Resolve schema.yaml path
    p = Path(schema_dir)
    if p.is_dir():
        schema_yaml = p / "schema.yaml"
    elif p.suffix == ".yaml":
        schema_yaml = p
    else:
        schema_yaml = p / "schema.yaml"

    if not schema_yaml.exists():
        console.print(f"[red]No schema.yaml found at {schema_yaml}. Run 'streamforge init' first.[/red]")
        raise typer.Exit(1)

    schema = load_schema(str(schema_yaml))

    if fmt == "json-schema":
        from .exporters.json_schema import schema_to_json_schema
        doc = schema_to_json_schema(schema)
        result = json.dumps(doc, indent=2)
        suffix = ".schema.json"
    elif fmt == "avro":
        from .exporters.avro import schema_to_avro
        doc = schema_to_avro(schema)
        result = json.dumps(doc, indent=2)
        suffix = ".avsc"
    elif fmt == "flink-ddl":
        from .exporters.flink_ddl import schema_to_flink_ddl
        broker_list = [b.strip() for b in brokers.split(",") if b.strip()] if brokers else None
        result = schema_to_flink_ddl(schema, brokers=broker_list)
        suffix = ".sql"
    elif fmt == "ksqldb":
        from .exporters.ksqldb import schema_to_ksqldb
        result = schema_to_ksqldb(schema)
        suffix = ".ksql"
    elif fmt == "proto":
        from .exporters.protobuf import schema_to_proto
        result = schema_to_proto(schema)
        suffix = ".proto"
    else:
        console.print(f"[red]Unknown format '{fmt}'. Use: json-schema | avro | flink-ddl | ksqldb | proto[/red]")
        raise typer.Exit(1)

    if output:
        out_path = Path(output)
    else:
        safe_name = schema.stream_name.replace(".", "_")
        out_path = schema_yaml.parent / f"{safe_name}{suffix}"

    out_path.write_text(result)
    console.print(f"✓ Exported [{fmt}] → [green]{out_path}[/green]")
    console.print(f"  Stream: [cyan]{schema.stream_name}[/cyan]  Fields: {len(schema.fields)}")


@app.command()
def consumers(
    stream_path: str = typer.Argument(..., help="Stream path or stream name (e.g. events/payments/stream_v1 or stream_v1)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
):
    """Show consumer registry and blast radius for a stream."""
    from .consumer_registry import load_consumers as _load_consumers

    stream_name = _stream_name(stream_path)
    schema_dir  = Path(output_dir) / stream_name

    if not schema_dir.exists():
        console.print(f"[red]No schema directory found at {schema_dir}. Run 'streamforge init' first.[/red]")
        raise typer.Exit(1)

    consumer_list = _load_consumers(output_dir, stream_name)

    if not consumer_list:
        console.print(
            f"[yellow]No consumers.yaml found for {stream_name}.[/yellow]\n"
            f"  Create one at: {schema_dir / 'consumers.yaml'}\n"
            f"  Format: list of consumers with name, team, contact, criticality, fields_used"
        )
        raise typer.Exit(0)

    table = Table(
        title=f"Consumer Registry — {stream_name} ({len(consumer_list)} consumer(s))",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Consumer",    style="cyan", no_wrap=True)
    table.add_column("Team",        style="blue")
    table.add_column("Contact")
    table.add_column("Criticality", justify="center")
    table.add_column("Schema",      justify="center")
    table.add_column("Fields Used", justify="right")

    crit_color = {"tier1": "red", "tier2": "yellow", "tier3": "green"}
    for c in consumer_list:
        crit = getattr(c, "criticality", "tier3")
        color = crit_color.get(str(crit), "white")
        table.add_row(
            c.name,
            c.team,
            c.contact,
            f"[{color}]{str(crit).upper()}[/{color}]",
            getattr(c, "schema_version", "—"),
            str(len(getattr(c, "fields_used", []))),
        )

    console.print(table)

    # Check for active drift and compute blast radius
    drift_dir = Path("drift_reports") / stream_name
    if drift_dir.exists():
        recent = sorted(drift_dir.glob("*.md"), reverse=True)
        if recent:
            console.print(f"\n[yellow]⚠ {len(recent)} drift report(s) on file.[/yellow]")
            console.print(f"  Most recent: [cyan]{recent[0].name}[/cyan]")
            console.print(
                f"\n  Run [bold]streamforge plan {stream_path}[/bold] to recompute drift "
                f"and see live blast radius."
            )
    else:
        console.print("\n[green]✓ No drift reports — schema is clean.[/green]")


@app.command()
def generate(
    schema_path: str = typer.Argument(
        ...,
        help="Path to schema.yaml, a schema directory, or a profile.yaml directory",
    ),
    count: int = typer.Option(10, "--count", "-n", help="Number of events to generate"),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Output NDJSON file path. Default: stdout",
    ),
    cluster: str | None = typer.Option(
        None, "--cluster", "-c",
        help="Sub-schema cluster to generate for (from profile.yaml). "
             "Default: primary cluster. Use 'list' to see available clusters.",
    ),
    required_only: bool = typer.Option(
        False, "--required-only",
        help="Include only required fields. By default optional fields are included at their presence_rate.",
    ),
    seed: int | None = typer.Option(
        None, "--seed",
        help="Random seed for reproducible output.",
    ),
    pretty: bool = typer.Option(
        False, "--pretty",
        help="Pretty-print JSON (one indented object per line). Default: compact NDJSON.",
    ),
):
    """
    Generate synthetic NDJSON events that conform to a schema.

    Reads schema.yaml (or a specific sub-schema cluster from profile.yaml) and
    produces realistic fake events with proper nested JSON structure.

    Useful for:
      - Testing downstream consumers without a live stream
      - Seeding a new stream with representative events before real data arrives
      - Reproducing a specific schema shape for CI fixtures

    Examples:
      streamforge generate schemas/stream_v1            # 10 events to stdout
      streamforge generate schemas/stream_v1 -n 100 -o events/test/stream/out.ndjson
      streamforge generate schemas/stream_v1 --cluster purchase -n 50
      streamforge generate schemas/stream_v1 --cluster list     # show available clusters
      streamforge generate schemas/stream_v1 --required-only --seed 42
    """
    import json as _json
    import sys

    from .generator import generate_events, generate_from_cluster
    from .schema_writer import load_profile, load_schema

    # Resolve paths
    p = Path(schema_path)
    if p.is_dir():
        schema_yaml = p / "schema.yaml"
        profile_dir = p
    elif p.name == "schema.yaml":
        schema_yaml = p
        profile_dir = p.parent
    else:
        schema_yaml = p / "schema.yaml"
        profile_dir = p

    profile = load_profile(profile_dir)

    # Handle --cluster list
    if cluster == "list":
        if profile is None:
            console.print("[yellow]No profile.yaml found — single-schema stream.[/yellow]")
            console.print(f"  Schema: [cyan]{schema_yaml}[/cyan]")
        else:
            console.print(f"[bold]Clusters in {profile_dir}/profile.yaml:[/bold]")
            for sub in profile.get("sub_schemas", []):
                cid = sub["cluster_id"]
                pct = sub.get("sample_rate", 0)
                n = sub.get("event_count", "?")
                console.print(f"  [cyan]{cid:<40}[/cyan] {n:>5} events  ({pct:.0%})")
        return

    # Generate events
    if cluster and profile:
        try:
            events = generate_from_cluster(
                profile=profile,
                cluster_id=cluster,
                count=count,
                include_optional=not required_only,
                seed=seed,
            )
            source_label = f"cluster '{cluster}'"
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    else:
        if not schema_yaml.exists():
            console.print(
                f"[red]No schema.yaml found at {schema_yaml}. "
                "Run 'streamforge init' first or pass the path to a schema directory.[/red]"
            )
            raise typer.Exit(1)
        schema = load_schema(str(schema_yaml))
        events = generate_events(
            schema=schema,
            count=count,
            include_optional=not required_only,
            seed=seed,
        )
        source_label = f"schema '{schema.stream_name}'"

    # Serialise
    lines = []
    for event in events:
        if pretty:
            lines.append(_json.dumps(event, indent=2))
        else:
            lines.append(_json.dumps(event))
    output_text = "\n".join(lines) + "\n"

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        console.print(
            f"✓ Generated [bold]{len(events)}[/bold] events from {source_label} "
            f"→ [green]{out_path}[/green]"
        )
    else:
        sys.stdout.write(output_text)


@app.command()
def status(
    stream_path: str | None = typer.Argument(None, help="Stream path (omit to show all streams)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    show_resolved: bool = typer.Option(False, "--all", "-a", help="Include resolved/accepted incidents"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
):
    """Show open drift incidents for a stream (or all streams)."""
    import json as _json

    from .models import DriftIncidentStatus
    from .schema_writer import load_drift_state

    schema_root = Path(output_dir)
    if stream_path:
        dirs = [schema_root / _stream_name(stream_path)]
    else:
        dirs = sorted(d for d in schema_root.iterdir() if d.is_dir()) if schema_root.exists() else []

    all_results: list[dict] = []
    any_found = False
    for schema_dir in dirs:
        state = load_drift_state(schema_dir)
        incidents = state.incidents
        if not show_resolved:
            incidents = [i for i in incidents if i.status == DriftIncidentStatus.OPEN]
        if not incidents:
            continue
        any_found = True

        if output_format == "json":
            all_results.append({
                "stream": state.stream_name,
                "incidents": [
                    {
                        "id": inc.id,
                        "field": inc.field_path,
                        "drift_type": inc.drift_type,
                        "tier": inc.tier,
                        "occurrences": inc.occurrences,
                        "first_detected": inc.first_detected,
                        "status": inc.status,
                    }
                    for inc in incidents
                ],
            })
            continue

        console.print(f"\n[bold cyan]{state.stream_name}[/bold cyan]")
        t = Table(show_header=True, header_style="bold", show_lines=False)
        t.add_column("ID", style="dim", no_wrap=True)
        t.add_column("Field", style="cyan")
        t.add_column("Drift Type")
        t.add_column("Tier", justify="center")
        t.add_column("Occurrences", justify="right")
        t.add_column("First Detected")
        t.add_column("Status")
        for inc in incidents:
            tier_color = "red" if inc.tier == 3 else "yellow" if inc.tier == 2 else "green"
            status_color = {
                "open": "red", "accepted": "green",
                "suppressed": "yellow", "resolved": "dim",
            }.get(inc.status, "white")
            t.add_row(
                inc.id[-20:],
                inc.field_path + (f" [{inc.cluster_id}]" if inc.cluster_id else ""),
                inc.drift_type.replace("_", " "),
                f"[{tier_color}]T{inc.tier}[/{tier_color}]",
                str(inc.occurrences),
                inc.first_detected[:16].replace("T", " "),
                f"[{status_color}]{inc.status}[/{status_color}]",
            )
        console.print(t)

    if output_format == "json":
        print(_json.dumps(all_results, indent=2))
        return

    if not any_found:
        console.print("[green]✓ No open drift incidents.[/green]")
        if not show_resolved:
            console.print("[dim]Run with --all to include resolved/accepted incidents.[/dim]")


@app.command()
def accept(
    stream_path: str = typer.Argument(..., help="Stream path (e.g. events/bookings/stream)"),
    field: str | None = typer.Option(None, "--field", "-f", help="Accept only this field path (accepts all open if omitted)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Accept drift incidents — update schema.yaml and bump its version.

    \b
    Examples:
      streamforge accept events/bookings/stream                # accept all open incidents
      streamforge accept events/bookings/stream -f passenger_name  # accept one field
    """
    from .models import DriftIncidentStatus
    from .schema_writer import accept_drift, load_drift_state

    stream_name = _stream_name(stream_path)
    schema_dir = Path(output_dir) / stream_name
    schema_path = schema_dir / "schema.yaml"

    if not schema_path.exists():
        console.print(f"[red]No schema found at {schema_path}. Run 'streamforge init' first.[/red]")
        raise typer.Exit(1)

    state = load_drift_state(schema_dir)
    open_incidents = [i for i in state.incidents if i.status == DriftIncidentStatus.OPEN]

    if field:
        open_incidents = [i for i in open_incidents if i.field_path == field]
        if not open_incidents:
            console.print(f"[yellow]No open incidents found for field '{field}'.[/yellow]")
            raise typer.Exit(0)

    if not open_incidents:
        console.print("[green]✓ No open incidents to accept.[/green]")
        raise typer.Exit(0)

    # Show what will be accepted
    console.print(f"\n[bold]Accepting {len(open_incidents)} incident(s) for [cyan]{stream_name}[/cyan]:[/bold]")
    for inc in open_incidents:
        tier_color = "red" if inc.tier == 3 else "yellow" if inc.tier == 2 else "green"
        console.print(
            f"  [{tier_color}]T{inc.tier}[/{tier_color}] "
            f"[cyan]{inc.field_path}[/cyan] — {inc.drift_type.replace('_', ' ')} "
            f"({inc.occurrences} occurrence(s))"
        )

    if not yes:
        typer.confirm("\nThis will update schema.yaml and bump its version. Continue?", abort=True)

    from .schema_writer import load_schema as _load_schema
    current = _load_schema(str(schema_path))
    updated = accept_drift(schema_dir, open_incidents, drifts_by_id={})
    console.print(
        f"\n[green]✓ Schema updated:[/green] v{current.version} → v{updated.version}"
    )
    console.print(f"  Written: [dim]{schema_path}[/dim]")
    console.print(
        "\n[dim]Restart 'streamforge watch' to monitor against the updated schema.[/dim]"
    )

    # VCS: create PR for accepted schema changes
    from .vcs import SchemaCommitContext, get_vcs_backend
    tc = load_topic_config(stream_name)
    vcs = get_vcs_backend(tc.vcs_config)
    if vcs and vcs.is_available() and tc.vcs_enabled:
        highest_tier = max((i.tier for i in open_incidents), default=1)
        # Build a markdown drift summary for the PR body
        drift_lines = []
        for inc in open_incidents:
            drift_lines.append(
                f"- **{inc.field_path}** — {inc.drift_type.replace('_', ' ')} "
                f"(T{inc.tier}, {inc.occurrences} cycle(s))"
            )
        drift_summary = "\n".join(drift_lines)

        ctx = SchemaCommitContext(
            stream_name=stream_name,
            old_version=current.version,
            new_version=updated.version,
            action="accept",
            drift_summary=drift_summary,
            tier=highest_tier,
            files=[schema_dir / "schema.yaml", schema_dir / "drift_state.yaml"],
        )

        if tc.vcs_auto_pr:
            result = vcs.create_schema_pr(
                ctx=ctx,
                base_branch=tc.vcs_pr_base_branch,
                reviewers=tc.vcs_pr_reviewers,
                labels=tc.vcs_pr_labels + [f"tier-{highest_tier}"],
            )
        else:
            result = vcs.commit_schema(ctx)

        if result.success:
            msg = f"[green]✓ VCS:[/green] {result.message}"
            if result.url:
                msg += f"\n  PR: [link={result.url}]{result.url}[/link]"
            console.print(msg)
        else:
            console.print(f"[yellow]⚠ VCS:[/yellow] {result.error}")


@app.command()
def suppress(
    stream_path: str = typer.Argument(...),
    field: str = typer.Option(..., "--field", "-f", help="Field path to suppress"),
    days: int = typer.Option(7, "--days", "-d", help="Suppress for N days"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for suppression"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
):
    """Suppress a drift incident for N days (e.g. while upstream team fixes a known issue).

    \b
    Example:
      streamforge suppress events/bookings/stream -f passenger_name --days 7 --reason "PII scrubber fix ETA March 24"
    """
    from datetime import UTC, datetime, timedelta

    from .models import DriftIncidentStatus
    from .schema_writer import load_drift_state, save_drift_state

    schema_dir = Path(output_dir) / _stream_name(stream_path)
    state = load_drift_state(schema_dir)

    until = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    updated = []
    matched = 0
    for inc in state.incidents:
        if inc.field_path == field and inc.status == DriftIncidentStatus.OPEN:
            inc = inc.model_copy(update={
                "status": DriftIncidentStatus.SUPPRESSED,
                "suppressed_until": until,
                "resolution_note": reason or f"Suppressed for {days} day(s)",
            })
            matched += 1
        updated.append(inc)

    if not matched:
        console.print(f"[yellow]No open incidents found for field '{field}'.[/yellow]")
        raise typer.Exit(1)

    save_drift_state(schema_dir, state.model_copy(update={"incidents": updated}))
    console.print(
        f"[green]✓ Suppressed {matched} incident(s) for '{field}' until {until[:10]}.[/green]"
    )
    if reason:
        console.print(f"  Reason: {reason}")


@app.command()
def demo(
    baseline_size: int  = typer.Option(300, "--baseline", "-b", help="Baseline events to generate"),
    drift_size:    int  = typer.Option(200, "--drift",    "-d", help="Drifted events to inject"),
    output_dir:    str  = typer.Option("schemas",         "--output", "-o"),
    write_report:  bool = typer.Option(True,  "--report/--no-report", help="Write drift report to disk"),
    loop:          bool = typer.Option(False, "--loop/--no-loop",
                                       help="Loop continuously (for live dashboard demos). Ctrl+C to stop."),
):
    """
    Live drift detection demo — no Kafka needed.

    Generates realistic payment events in two phases:
      Phase 1: 300 clean baseline events → schema inferred, 3 clean watch ticks
      Phase 2: 200 drifted events → Tier 3 drift detected in real time

    No API key required. Run alongside `streamforge ui` to see the dashboard update live.

    Add --loop to run continuously during a presentation (Ctrl+C to stop).
    """
    import time
    from datetime import datetime

    from .connectors.generators import drifted_payment_events, payment_events
    from .drift_detector import detect_drift
    from .models import FieldSchema, FieldType, InferredSchema, PIICategory
    from .report_writer import write_drift_report
    from .sampler import reservoir_sample

    STREAM_NAME = "payments.demo"
    tier_colors = {1: "yellow", 2: "orange3", 3: "red"}

    console.rule("[bold]⚡ StreamForge Live Demo[/bold]")
    console.print(
        "\n[bold]Scenario:[/bold] A payments microservice just deployed at 2:17am.\n"
        "A developer renamed [cyan]amount[/cyan] to [cyan]amount_minor_units[/cyan] "
        "(dollars → integer cents), changed the timestamp format, and accidentally\n"
        "started logging [red]card_last_four[/red] — a PII field not in the baseline schema.\n"
        "\nStreamForge catches it before any consumer breaks.\n"
    )
    if loop:
        console.print("[dim]Running in loop mode (Ctrl+C to stop). Open 'streamforge ui' in another terminal.[/dim]\n")
    time.sleep(1)

    # ── Build baseline schema once — reused across loop iterations ────────────
    # Hand-coded schema matching what an LLM would produce for these events.
    # No API key required for the demo.
    demo_fields = [
        FieldSchema(name="event_id",    path="event_id",    field_type=FieldType.UUID,               required=True,  presence_rate=1.0,  confidence=0.99, notes="Payment event UUID"),
        FieldSchema(name="event_type",  path="event_type",  field_type=FieldType.STRING,             required=True,  presence_rate=1.0,  confidence=0.98, enum_values=["payment_initiated","payment_completed","payment_failed"], notes="Payment lifecycle event type"),
        FieldSchema(name="timestamp",   path="timestamp",   field_type=FieldType.TIMESTAMP_EPOCH_MS, required=True,  presence_rate=1.0,  confidence=0.99, notes="Event timestamp — Unix epoch milliseconds"),
        FieldSchema(name="amount",      path="amount",      field_type=FieldType.FLOAT,              required=True,  presence_rate=1.0,  confidence=0.99, notes="Payment amount in dollars"),
        FieldSchema(name="currency",    path="currency",    field_type=FieldType.STRING,             required=True,  presence_rate=1.0,  confidence=0.97, enum_values=["USD","EUR","GBP","CAD","AUD"], notes="ISO 4217 currency code"),
        FieldSchema(name="user_id",     path="user_id",     field_type=FieldType.UUID,               required=True,  presence_rate=1.0,  confidence=0.99, notes="Unique user identifier"),
        FieldSchema(name="user_email",  path="user_email",  field_type=FieldType.EMAIL,              required=True,  presence_rate=1.0,  confidence=0.99, pii_categories=[PIICategory.EMAIL], notes="User email — PII"),
        FieldSchema(name="merchant_id", path="merchant_id", field_type=FieldType.STRING,             required=True,  presence_rate=1.0,  confidence=0.96, notes="Merchant identifier"),
        FieldSchema(name="status",      path="status",      field_type=FieldType.STRING,             required=True,  presence_rate=1.0,  confidence=0.97, enum_values=["pending","completed","failed","processing"], notes="Payment status"),
        FieldSchema(name="metadata.source",  path="metadata.source",  field_type=FieldType.STRING,   required=False, presence_rate=0.72, confidence=0.94, enum_values=["web","mobile","api"], notes="Request source"),
        FieldSchema(name="metadata.version", path="metadata.version", field_type=FieldType.STRING,   required=False, presence_rate=0.65, confidence=0.88, enum_values=["v2","v3"], notes="API version"),
    ]

    baseline_schema = InferredSchema(
        stream_name=STREAM_NAME,
        version="1.0.0",
        inferred_at=datetime.now(UTC).isoformat(),
        event_count_sampled=baseline_size,
        fields=demo_fields,
        inference_model="statistical+demo",
        inference_confidence=0.97,
    )

    # Write baseline schema to disk so the dashboard discovers this stream.
    # Safe to call on every run — schema stays stable between loops.
    write_schema(baseline_schema, output_dir)

    baseline = payment_events(n=baseline_size, seed=42)
    drifted  = drifted_payment_events(n=drift_size, seed=99)

    def _run_one_cycle(iteration: int) -> None:
        """Run one full Phase1 → Phase2 demo cycle."""
        if iteration > 1:
            console.rule(f"[dim]Loop {iteration}[/dim]")

        # ── Phase 1 ────────────────────────────────────────────────────────────
        console.print("[bold]PHASE 1 — Baseline monitoring[/bold]  [dim](clean schema)[/dim]")
        if iteration == 1:
            console.print(f"  ✓ Schema inferred — [bold]{len(demo_fields)}[/bold] fields, confidence [green]97%[/green]")
            console.print("  ✓ PII detected: [yellow]user_email[/yellow] (email)")
            console.print()

        for _ in range(3):
            sample = reservoir_sample(baseline, 50)
            detect_drift(baseline_schema, sample, STREAM_NAME)  # always clean
            ts = datetime.now().strftime("%H:%M:%S")
            console.print(
                f"  [[dim]{ts}[/dim]] [green]✓[/green] {STREAM_NAME} — "
                f"[dim]50 events sampled — schema clean[/dim]"
            )
            time.sleep(0.9)

        console.print()

        # ── Phase 2 ────────────────────────────────────────────────────────────
        console.print("[bold red]PHASE 2 — Drift injected[/bold red]  [dim](deploy at 2:17am)[/dim]")
        console.print("  [dim]amount renamed · timestamp format changed · card_last_four PII appears[/dim]")
        time.sleep(1.2)

        sample       = reservoir_sample(drifted, min(200, len(drifted)))
        ts           = datetime.now().strftime("%H:%M:%S")
        drift_report = detect_drift(baseline_schema, sample, STREAM_NAME)

        if drift_report is None:
            console.print(f"  [[dim]{ts}[/dim]] [green]✓[/green] No drift detected (unexpected).")
            return

        highest = drift_report.highest_tier.value
        if highest == 3:
            console.print(
                f"\n  [[dim]{ts}[/dim]] [bold red]🔴 {STREAM_NAME} — TIER 3 DRIFT — human action required[/bold red]"
            )
        else:
            console.print(
                f"\n  [[dim]{ts}[/dim]] [bold yellow]⚠  {STREAM_NAME} — DRIFT DETECTED — Tier {highest}[/bold yellow]"
            )

        console.print()
        for d in drift_report.drifts:
            c   = tier_colors.get(d.tier.value, "white")
            lbl = f"[{c}][TIER {d.tier.value}][/{c}]"
            if d.drift_type == "type_changed":
                detail = (f"type changed: [cyan]{d.previous_type.value}[/cyan] → "
                          f"[red]{d.observed_type.value}[/red]  ({d.affected_event_rate:.0%} of events)")
            elif d.drift_type == "field_removed":
                detail = (f"field [bold red]REMOVED[/bold red] — was "
                          f"[cyan]{(d.previous_presence_rate or 0):.0%}[/cyan] present, now "
                          f"[red]{(d.observed_presence_rate or 0):.0%}[/red]")
            elif d.drift_type == "field_added":
                pres = d.observed_presence_rate or 0
                detail = f"new {'required' if pres >= 0.8 else 'optional'} field added ({pres:.0%} presence)"
            elif d.drift_type == "new_pii":
                detail = "[red bold]NEW PII FIELD[/red bold] — GDPR/CCPA review required"
            elif d.drift_type == "presence_drop":
                detail = (f"presence dropped: {(d.previous_presence_rate or 0):.0%} → "
                          f"{(d.observed_presence_rate or 0):.0%}")
            else:
                detail = d.drift_type
            console.print(f"    {lbl} [cyan]{d.field_path}[/cyan] — {detail}")

        console.print()

        if write_report:
            report_path = write_drift_report(drift_report, "drift_reports")
            console.print(f"  ✓ Report saved: [green]{report_path}[/green]")

        console.rule()
        console.print(
            "\n[bold]That would have been a 3am page.[/bold]\n"
            "Instead: a blocked PR and a Slack alert to [cyan]#payments-oncall[/cyan].\n"
        )

        if loop:
            console.print("[dim]Restarting in 5 seconds... (Ctrl+C to stop)[/dim]")
            time.sleep(5)

    # ── Run once or loop until KeyboardInterrupt ───────────────────────────────
    if loop:
        i = 1
        try:
            while True:
                _run_one_cycle(i)
                i += 1
        except KeyboardInterrupt:
            console.print("\n[dim]Demo stopped.[/dim]")
    else:
        _run_one_cycle(1)
        console.print(
            "Run [bold]streamforge ui[/bold] to see the drift in the Fleet dashboard.\n"
            "Run [bold]streamforge demo --loop[/bold] for a continuous presentation mode."
        )


# ---------------------------------------------------------------------------
# streamforge history — snapshot, diff, velocity, propose
# ---------------------------------------------------------------------------

history_app = typer.Typer(
    name="history",
    help="Schema history — snapshot, diff, velocity trends, and baseline proposals",
    add_completion=False,
)
app.add_typer(history_app, name="history")


def _resolve_snapshot_path(output_dir: str, stream_name: str, date_spec: str) -> Path:
    """
    Resolve a snapshot date specifier to an absolute snapshot directory path.

    Accepts:
      "latest"    — most recent snapshot
      "oldest"    — first snapshot
      "YYYY-MM-DD" — specific date
    """
    from .history import list_snapshots

    snaps = list_snapshots(output_dir, stream_name)
    if not snaps:
        raise typer.BadParameter(f"No snapshots found for {stream_name}. Run 'streamforge history snapshot' first.")

    if date_spec == "latest":
        return snaps[-1]
    if date_spec == "oldest":
        return snaps[0]

    # Try exact directory name match
    for s in snaps:
        if s.name == date_spec:
            return s
    raise typer.BadParameter(
        f"Snapshot '{date_spec}' not found. Available: {[s.name for s in snaps]}"
    )


@history_app.command("snapshot")
def history_snapshot(
    stream_path: str = typer.Argument(..., help="Stream path (same as used with init)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    triggered_by: str = typer.Option("manual", "--triggered-by", hidden=True),
    force: bool = typer.Option(False, "--force", help="Overwrite existing same-day snapshot"),
):
    """Archive today's profile.yaml as a dated history snapshot."""
    from .history import write_snapshot

    stream_name = _stream_name(stream_path)
    profile_dir = Path(output_dir) / stream_name
    profile_path = profile_dir / "profile.yaml"

    if not profile_path.exists():
        console.print(
            f"[red]No profile.yaml found at {profile_path}. "
            "Run 'streamforge init' first.[/red]"
        )
        raise typer.Exit(1)

    import yaml as _yaml
    raw = _yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    snap_path, meta_path = write_snapshot(raw, stream_name, output_dir, triggered_by, force=force)
    console.print(f"✓ Snapshot: [green]{snap_path}[/green]")
    console.print(f"✓ Meta:     [green]{meta_path}[/green]")


@history_app.command("diff")
def history_diff(
    stream_path: str = typer.Argument(...),
    left: str = typer.Option("oldest", "--left", "-l", help="Left date YYYY-MM-DD, 'oldest', or 'latest'"),
    right: str = typer.Option("latest", "--right", "-r", help="Right date YYYY-MM-DD or 'latest'"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    save: bool = typer.Option(True, "--save/--no-save", help="Write diff.md to left snapshot directory"),
):
    """Compare two profile.yaml snapshots and show what changed."""
    from .history import diff_profiles, list_snapshots, write_diff_report

    stream_name = _stream_name(stream_path)
    snaps = list_snapshots(output_dir, stream_name)
    if len(snaps) < 2:
        console.print(
            "[red]Need at least 2 snapshots to diff. "
            "Run 'streamforge history snapshot' after each init.[/red]"
        )
        raise typer.Exit(1)

    left_path = _resolve_snapshot_path(output_dir, stream_name, left)
    right_path = _resolve_snapshot_path(output_dir, stream_name, right)

    if left_path == right_path:
        console.print("[yellow]Left and right snapshots are the same — nothing to diff.[/yellow]")
        raise typer.Exit(0)

    diff = diff_profiles(left_path, right_path)

    console.print(
        f"\n[bold]Schema Diff[/bold] — [cyan]{stream_name}[/cyan] "
        f"({diff.left_date} → {diff.right_date}, {diff.days_between} days)\n"
    )
    console.print(diff.summary)

    _SIG_COLOR = {"breaking": "red", "non_breaking": "yellow", "informational": "blue"}
    _SIG_LABEL = {"breaking": "BREAKING", "non_breaking": "non-breaking", "informational": "info"}

    if diff.changes:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Field", style="cyan")
        table.add_column("Cluster")
        table.add_column("Change")
        table.add_column("Before")
        table.add_column("After")
        table.add_column("Severity")

        for c in sorted(diff.changes, key=lambda x: (x.significance != "breaking", x.field_path)):
            color = _SIG_COLOR.get(c.significance, "white")
            label = _SIG_LABEL.get(c.significance, c.significance)

            before_str = ""
            after_str = ""
            if c.change_type == "presence_changed":
                before_str = f"{(c.before or {}).get('presence_rate', 0):.0%}"
                after_str = f"{(c.after or {}).get('presence_rate', 0):.0%}"
            elif c.change_type == "type_changed":
                before_str = str((c.before or {}).get("type", ""))
                after_str = str((c.after or {}).get("type", ""))
            elif c.change_type == "enum_changed":
                before_str = ", ".join(c.enum_removed or []) or "—"
                after_str = "+[" + ", ".join(c.enum_added or []) + "]" if c.enum_added else "—"
            elif c.change_type == "added":
                after_str = str((c.after or {}).get("type", ""))
            elif c.change_type == "removed":
                before_str = str((c.before or {}).get("type", ""))

            table.add_row(
                c.field_path,
                c.cluster_id or "—",
                c.change_type,
                before_str,
                after_str,
                f"[{color}]{label}[/{color}]",
            )
        console.print(table)
    else:
        console.print("[green]No changes detected — schemas are identical.[/green]")

    console.print(
        f"\nSummary: [red]{diff.breaking_count} breaking[/red], "
        f"[yellow]{diff.non_breaking_count} non-breaking[/yellow], "
        f"[blue]{diff.informational_count} informational[/blue], "
        f"{diff.fields_stable_count} stable"
    )

    if save and diff.changes:
        report_path = write_diff_report(diff, left_path)
        console.print(f"\nDiff report: [green]{report_path}[/green]")


@history_app.command("velocity")
def history_velocity(
    stream_path: str = typer.Argument(...),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    alerts_only: bool = typer.Option(False, "--alerts-only", "-a", help="Show only fields with alerts"),
):
    """Compute field velocity trends across all snapshots and write velocity.yaml."""
    from .history import compute_velocity, list_snapshots, write_velocity_report

    stream_name = _stream_name(stream_path)
    snaps = list_snapshots(output_dir, stream_name)
    if not snaps:
        console.print(
            "[red]No snapshots found. Run 'streamforge history snapshot' first.[/red]"
        )
        raise typer.Exit(1)

    console.print(
        f"[bold]Computing velocity[/bold] — [cyan]{stream_name}[/cyan] "
        f"({len(snaps)} snapshots)"
    )

    report = compute_velocity(output_dir, stream_name)
    velocity_path = write_velocity_report(report, output_dir)

    # Alerts panel
    if report.alerts:
        console.print(Panel(
            "\n".join(f"  • {a}" for a in report.alerts),
            title=f"[red]⚠ {len(report.alerts)} Alert(s)[/red]",
            expand=False,
        ))

    # Velocity table
    _TREND_COLOR = {
        "stable": "green", "rising": "cyan", "declining": "red",
        "volatile": "yellow", "insufficient_data": "dim",
    }
    fields_to_show = [fv for fv in report.fields if fv.alert] if alerts_only else report.fields

    if fields_to_show:
        table = Table(
            title=f"Field Velocity — {stream_name} ({report.snapshot_count} snapshots)",
            show_header=True,
        )
        table.add_column("Field", style="cyan")
        table.add_column("Cluster")
        table.add_column("Trend")
        table.add_column("Current")
        table.add_column("Baseline")
        table.add_column("Slope/day")
        table.add_column("Weeks")
        table.add_column("Alert")

        for fv in sorted(fields_to_show, key=lambda x: (x.alert is None, x.field_path)):
            trend_color = _TREND_COLOR.get(fv.trend.value, "white")
            slope_str = f"{fv.trend_slope:+.4f}" if fv.trend_slope is not None else "—"
            table.add_row(
                fv.field_path,
                fv.cluster_id or "—",
                f"[{trend_color}]{fv.trend.value}[/{trend_color}]",
                f"{fv.current_presence_rate:.0%}",
                f"{fv.baseline_presence_rate:.0%}",
                slope_str,
                str(fv.weeks_of_data),
                "⚠" if fv.alert else "",
            )
        console.print(table)

    console.print(
        f"\nStability score: [bold]{report.schema_stability_score:.0%}[/bold]  "
        f"({len(report.alerts)} alert(s))"
    )
    console.print(f"Velocity report: [green]{velocity_path}[/green]")


@history_app.command("propose")
def history_propose(
    stream_path: str = typer.Argument(...),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    min_weeks: int = typer.Option(4, "--min-weeks", help="Minimum weeks of evidence required"),
    apply: bool = typer.Option(
        False, "--apply",
        help="Auto-apply high-confidence proposals (≥90%) to schema.yaml. Always creates a backup first.",
    ),
):
    """Generate adaptive baseline update proposals from schema history."""
    from .history import compute_velocity, propose_baseline_updates, write_proposal_report

    stream_name = _stream_name(stream_path)
    console.print(
        f"[bold]Generating proposals[/bold] — [cyan]{stream_name}[/cyan] "
        f"(min {min_weeks} weeks evidence)"
    )

    velocity = compute_velocity(output_dir, stream_name)
    report = propose_baseline_updates(output_dir, stream_name, velocity=velocity, min_weeks=min_weeks)
    proposals_path = write_proposal_report(report, output_dir)

    console.print(f"\n{report.summary}\n")

    _ACTION_EMOJI = {
        "promote_to_required": "⬆",
        "demote_to_optional": "⬇",
        "remove_field": "🗑",
        "flag_new_pii": "🔒",
        "widen_type": "↔",
    }

    if report.proposals:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Field", style="cyan")
        table.add_column("Action")
        table.add_column("Current")
        table.add_column("Proposed")
        table.add_column("Confidence")
        table.add_column("Weeks")
        table.add_column("Auto?")

        auto_set = {id(p) for p in report.auto_appliable}
        for p in sorted(report.proposals, key=lambda x: -x.confidence):
            emoji = _ACTION_EMOJI.get(p.action.value, "→")
            auto = "✓" if id(p) in auto_set else ""
            table.add_row(
                p.field_path,
                f"{emoji} {p.action.value.replace('_', ' ')}",
                p.current_schema_value or "—",
                p.proposed_value or "—",
                f"{p.confidence:.0%}",
                str(p.weeks_of_evidence),
                f"[green]{auto}[/green]",
            )
        console.print(table)

    if apply and report.auto_appliable:
        _apply_baseline_proposals(report.auto_appliable, output_dir, stream_name)
    elif apply:
        console.print("[yellow]No auto-appliable proposals (all require review).[/yellow]")

    console.print(f"\nProposal report: [green]{proposals_path}[/green]")
    if not apply and report.auto_appliable:
        console.print(
            f"[dim]Run with --apply to auto-apply {len(report.auto_appliable)} "
            f"high-confidence proposal(s).[/dim]"
        )


def _apply_baseline_proposals(
    proposals: list,
    output_dir: str,
    stream_name: str,
) -> None:
    """
    Apply auto-appliable proposals to schema.yaml.

    Uses write-then-rename for atomicity: writes to schema.yaml.tmp first,
    then renames — crash during write leaves the original intact.
    Creates schema.yaml.bak before any modification.
    """
    import shutil as _shutil

    from .models import ProposalAction

    schema_path = Path(output_dir) / stream_name / "schema.yaml"
    if not schema_path.exists():
        console.print("[yellow]No schema.yaml found — skipping apply.[/yellow]")
        return

    schema = load_schema(str(schema_path))
    # Backup before any modification
    bak_path = schema_path.with_suffix(".yaml.bak")
    _shutil.copy2(schema_path, bak_path)
    console.print(f"  Backup: [dim]{bak_path}[/dim]")

    field_map = {f.path: f for f in schema.fields}
    applied = 0

    for proposal in proposals:
        field = field_map.get(proposal.field_path)
        if field is None:
            logger.warning("Proposal target field not found in schema.yaml: %s", proposal.field_path)
            continue

        if proposal.action == ProposalAction.PROMOTE_TO_REQUIRED:
            field.required = True
            applied += 1
            console.print(f"  ⬆ {proposal.field_path}: marked required")

        elif proposal.action == ProposalAction.DEMOTE_TO_OPTIONAL:
            field.required = False
            applied += 1
            console.print(f"  ⬇ {proposal.field_path}: marked optional")

    if applied == 0:
        bak_path.unlink(missing_ok=True)
        console.print("[yellow]No changes applied (fields may have been manually edited).[/yellow]")
        return

    schema.fields = list(field_map.values())
    write_schema(schema, output_dir)
    console.print(f"\n[green]Applied {applied} proposal(s) to {schema_path}[/green]")
    console.print(f"[dim]Original backed up to {bak_path}[/dim]")


if __name__ == "__main__":
    app()
