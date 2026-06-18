"""Commands: init, kafka-ping, discover."""

import time
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ._helpers import _resolve_api_key, _stream_name, console


def init(
    stream_path: str = typer.Argument(..., help="Folder path or kafka://topic URI"),
    sample_size: int = typer.Option(0, "--sample-size", "-n", help="Number of events to sample (0 = use config)"),
    output_dir: str = typer.Option("schemas", "--output", "-o", help="Output directory for schema files"),
    api_key: str | None = typer.Option(None, "--api-key", help="LLM API key (or set GROQ_API_KEY / OPENAI_API_KEY)"),
    offline: bool = typer.Option(
        False, "--offline",
        help="Deterministic statistical inference only — no LLM, no API key required.",
    ),
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
    quorum_votes: int = typer.Option(
        0, "--quorum-votes", "-q",
        help="Number of independent samples for quorum voting (0 = use STREAMFORGE_QUORUM_VOTES env, default 5). "
             "Higher values increase type confidence. Use 10-20 for critical onboarding.",
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
    from datetime import UTC, datetime

    # Import through __main__ so tests can patch streamforge.__main__.load_topic_config
    import streamforge.__main__ as _main_mod

    from ..inference import infer_sub_schema
    from ..models import InferredSchema, StreamProfile
    from ..policy import StreamPolicy, write_policy
    from ..profiler import discover_clusters, get_detection_method, get_routing_field
    from ..sampler import streaming_resilient_sample_from_folder
    from ..schema_writer import (
        write_inference_report,
        write_profile,
        write_profile_report,
        write_samples,
        write_schema,
    )
    load_topic_config = _main_mod.load_topic_config

    _MIN_CLEAN_EVENTS = 20  # floor below which inference quality is unreliable

    is_kafka = stream_path.startswith("kafka://")
    key = "" if offline else _resolve_api_key(api_key)
    if offline:
        console.print("[dim]Offline mode — deterministic statistical inference (no LLM)[/dim]")

    # Resolve topic name for config lookup
    _topic_for_cfg = stream_path[len("kafka://"):] if is_kafka else _stream_name(stream_path)
    tc = load_topic_config(_topic_for_cfg, env)

    # Scaffold a topic config file if one doesn't already exist
    from ..topic_config import scaffold_topic_config
    _scaffolded = scaffold_topic_config(_topic_for_cfg)
    if _scaffolded:
        console.print(f"[dim]Created topic config: {_scaffolded}[/dim]")

    # Apply config defaults for flags that weren't explicitly set
    effective_sample_size = sample_size if sample_size > 0 else tc.init_sample_size
    effective_model    = model    if model    else tc.inference_model
    effective_base_url = base_url if base_url else tc.inference_base_url

    # Early registry connectivity check — fail before inference if registry is unreachable
    _reg_backend_early = None
    if push_to or tc.registry_enabled:
        from ..registries import get_registry_backend, subject_for_topic
        from ..registries.confluent import ConfluentRegistryBackend
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

        from ..config import KafkaConfig
        from ..connectors.kafka import KafkaConnector, KafkaConnectorError

        # Brokers: CLI flag -> config (which already checked KAFKA_BOOTSTRAP_SERVERS)
        broker_list = (
            [b.strip() for b in brokers.split(",") if b.strip()]
            if brokers
            else tc.kafka_broker_list
        )
        if not broker_list:
            console.print("[red]--brokers required for kafka:// URIs (or set KAFKA_BOOTSTRAP_SERVERS)[/red]")
            raise typer.Exit(1)

        # Use a timestamp-based group ID so every init attempt reads from
        # 'earliest' without being blocked by a previous run's committed
        # offsets. Schema inference needs the full event distribution, not
        # just the tip of the stream.
        _init_group = f"streamforge-init-{topic}-{int(time.time())}"
        kafka_cfg = KafkaConfig(
            bootstrap_servers=broker_list,
            security_protocol=tc.kafka_security_protocol,
            auto_offset_reset="earliest",
            consumer_group=_init_group,
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
            console.print("[dim]Make sure the feed is running: python3 demo/feed_all.py[/dim]")
            raise typer.Exit(1)

        console.print(f"✓ Consumed [green]{len(all_events)}[/green] events from Kafka")
        clean_events = all_events
        inference_events = all_events
        ingest_stats = {"total": len(all_events), "clean": len(all_events), "partial": 0}
        parse_success_rate = 1.0

    else:
        stream_name = _stream_name(stream_path)
        console.print(f"[bold]StreamForge[/bold] — profiling [cyan]{stream_name}[/cyan]")

        # Streaming resilient load + sample — O(effective_sample_size) memory
        clean_events, partial_events, _total, parse_stats = streaming_resilient_sample_from_folder(
            stream_path, effective_sample_size,
        )
        n_clean = parse_stats["parsed_clean"]
        n_partial = parse_stats["parsed_partial"]
        n_total_parsed = n_clean + n_partial

        if n_total_parsed == 0:
            console.print(f"[red]No events found in {stream_path}[/red]")
            raise typer.Exit(1)

        total_lines = parse_stats["total_lines"] or 1
        parse_success_rate = n_total_parsed / total_lines
        skipped = parse_stats["skipped"]

        parse_color = "green" if parse_success_rate >= 0.95 else "yellow" if parse_success_rate >= 0.80 else "red"
        console.print(
            f"✓ Loaded [{parse_color}]{n_total_parsed} events[/{parse_color}]"
            f" from {parse_stats['total_lines']} lines"
            f" — parse rate [{parse_color}]{parse_success_rate:.1%}[/{parse_color}]"
            + (f"  ({n_partial} partial, {skipped} skipped)" if (n_partial or skipped) else "")
        )

        if n_clean < _MIN_CLEAN_EVENTS:
            if not allow_partial_inference:
                console.print(
                    f"[red]Error:[/red] Only {n_clean} clean (fully-parsed) events found — "
                    f"too few for reliable schema inference (minimum {_MIN_CLEAN_EVENTS}).\n"
                    f"  {n_partial} partial events were excluded because they were reconstructed "
                    f"via regex fallback and may not reflect the true event schema.\n"
                    f"  To include them anyway, rerun with [bold]--allow-partial-inference[/bold]."
                )
                raise typer.Exit(1)
            console.print(
                f"[yellow]⚠ --allow-partial-inference set: using all {n_total_parsed} events "
                f"({n_partial} partial) — schema quality may be degraded.[/yellow]"
            )
            inference_events = clean_events + partial_events
        else:
            if partial_events:
                console.print(
                    f"✓ Using [green]{len(clean_events)}[/green] clean events for inference "
                    f"[dim]({n_partial} partial excluded)[/dim]"
                )
            inference_events = clean_events

        ingest_stats = {
            "total": n_total_parsed,
            "clean": n_clean,
            "partial": n_partial,
        }

    # Sample is already bounded by streaming — use directly
    sample = inference_events
    console.print(f"✓ Sampled [bold]{len(sample)}[/bold] events")

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
    if offline:
        console.print("\n📊 Inferring sub-schemas — [bold]deterministic statistical[/bold] (no LLM)...")
    else:
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
            quorum_votes=quorum_votes if quorum_votes > 0 else None,
            offline=offline,
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

    # Human-readable success summary
    if sub_schemas:
        from ..output_formatter import format_init_success
        primary_confidence = sub_schemas[0].inference_confidence
        primary_field_count = len(sub_schemas[0].fields)
        console.print(format_init_success(stream_name, primary_field_count, primary_confidence))

    # VCS: commit new schema files if enabled
    from ..vcs import SchemaCommitContext, get_vcs_backend
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
        from ..registries import get_registry_backend, subject_for_topic
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

    from ..config import KafkaConfig
    from ..connectors.kafka import KafkaConnector, KafkaConnectorError

    if not brokers:
        from ..config import load as _load_config
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
        console.print("  Hint: Is Kafka running? Try: docker ps | grep kafka")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e} (timed out after {timeout}s)")
        raise typer.Exit(1)


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

    # Import through __main__ so tests can patch streamforge.__main__.load_topic_config
    import streamforge.__main__ as _main_mod

    from ..schema_writer import load_drift_state, load_schema
    load_topic_config = _main_mod.load_topic_config

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
                from ..models import DriftIncidentStatus
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
    without_schema = len(results) - with_schema
    console.print(
        f"\n[dim]{len(results)} topics | "
        f"[green]{with_schema} with schema[/green] | "
        f"[yellow]{without_schema} without schema[/yellow][/dim]"
    )

    # Summary panel
    from ..output_formatter import format_discover_panel
    monitored_topics = [r["topic"] for r in results if r["has_schema"]]
    unmonitored_topics = [r["topic"] for r in results if not r["has_schema"]]
    summary_text = format_discover_panel(effective_brokers[0], monitored_topics, unmonitored_topics)
    console.print(Panel(summary_text, expand=False))

    if without_schema > 0:
        console.print(
            "[dim]Run 'streamforge init kafka://<topic> --brokers ...' to initialise a topic.[/dim]"
        )
