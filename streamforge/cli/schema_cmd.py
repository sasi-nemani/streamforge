"""Commands: plan, profile, validate, report, export."""

from datetime import UTC
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ._helpers import _auto_detect_schema, _stream_name, console


def plan(
    stream_path: str = typer.Argument(...),
    schema_path: str | None = typer.Option(None, "--schema"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    sample_size: int = typer.Option(200, "--sample-size", "-n"),
    api_key: str | None = typer.Option(None, "--api-key"),
    model: str = typer.Option("", "--model", "-m"),
    base_url: str = typer.Option("", "--base-url"),
    brokers: str | None = typer.Option(
        None, "--brokers",
        help="Kafka broker list for kafka:// URIs (e.g. localhost:9092).",
        envvar="KAFKA_BOOTSTRAP_SERVERS",
    ),
):
    """One-shot drift check. Like 'terraform plan' — shows drift without persisting."""
    from ..drift_detector import detect_drift
    from ..models import DriftReport, DriftTier
    from ..policy import load_policy
    from ..report_writer import write_drift_report
    from ..sampler import reservoir_sample, streaming_reservoir_sample_from_folder
    from ..schema_writer import load_profile, load_schema

    is_kafka = stream_path.startswith("kafka://")

    # For kafka:// URIs, auto-detect schema using the topic name directly
    if is_kafka:
        topic = stream_path[len("kafka://"):]
        stream_name = topic
        if not schema_path:
            candidate = Path(output_dir) / topic / "schema.yaml"
            if candidate.exists():
                resolved_schema: str | None = str(candidate)
            else:
                console.print(
                    "[red]No schema.yaml found. Run 'streamforge init' first or pass --schema.[/red]"
                )
                raise typer.Exit(1)
        else:
            resolved_schema = schema_path
    else:
        resolved_schema = schema_path or _auto_detect_schema(stream_path, output_dir)
        if not resolved_schema:
            console.print(
                "[red]No schema.yaml found. Run 'streamforge init' first or pass --schema.[/red]"
            )
            raise typer.Exit(1)
        stream_name = Path(stream_path).name

    baseline = load_schema(resolved_schema)
    policy = load_policy(output_dir, baseline.stream_name)

    console.print(f"[bold]StreamForge Plan[/bold] — checking [cyan]{stream_name}[/cyan] against schema v{baseline.version}")

    if is_kafka:
        import asyncio

        from ..config import KafkaConfig
        from ..connectors.kafka import KafkaConnector, KafkaConnectorError

        broker_list = (
            [b.strip() for b in brokers.split(",") if b.strip()]
            if brokers
            else ["localhost:9092"]
        )
        kafka_cfg = KafkaConfig(
            bootstrap_servers=broker_list,
            auto_offset_reset="earliest",
            consumer_group=f"streamforge-plan-{topic}",
        )
        console.print(f"Consuming up to {sample_size} events from [cyan]{topic}[/cyan] (Kafka)...")

        async def _consume_plan() -> list[dict]:
            async with KafkaConnector(topic, kafka_cfg) as conn:
                return await conn.read_batch(max_messages=sample_size, timeout_ms=15_000)

        try:
            events = asyncio.run(_consume_plan())
        except KafkaConnectorError as e:
            console.print(f"[red]Kafka error:[/red] {e}")
            raise typer.Exit(1)

        if not events:
            console.print(f"[red]No events received from topic '{topic}' within 15s.[/red]")
            raise typer.Exit(1)

        console.print(f"✓ Consumed [green]{len(events)}[/green] events from Kafka")
    else:
        effective_sample = sample_size if sample_size != 200 else policy.sample_size
        events, _total = streaming_reservoir_sample_from_folder(stream_path, effective_sample)
        if not events:
            console.print(f"[red]No events found in {stream_path}[/red]")
            raise typer.Exit(1)

    if is_kafka:
        effective_sample = sample_size if sample_size != 200 else policy.sample_size
        sample = reservoir_sample(events, effective_sample)
    else:
        sample = events  # already sampled by streaming function
    console.print(f"Sampled {len(sample)} events from {stream_path}")

    # P1-A: use multi-schema drift detection when profile.yaml is available
    from ..drift_detector import detect_drift_multi_schema
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


def profile(
    stream_path: str = typer.Argument(..., help="Path to folder containing NDJSON event files"),
    sample_size: int = typer.Option(500, "--sample-size", "-n"),
    top: int = typer.Option(30, "--top", "-t", help="Show top N fields by presence rate"),
    show_values: bool = typer.Option(True, "--values/--no-values", help="Show sample values"),
):
    """Profile a stream: show field stats, types, presence rates — no LLM call."""
    import re as _re

    from ..profiler import discover_clusters, get_detection_method
    from ..sampler import get_all_field_paths, streaming_resilient_sample_from_folder

    stream_name = _stream_name(stream_path)
    console.print(f"[bold]StreamForge Profile[/bold] — [cyan]{stream_name}[/cyan]\n")

    # Streaming resilient load + sample — O(sample_size) memory
    clean_sample, partial_sample, _total, parse_stats = streaming_resilient_sample_from_folder(
        stream_path, sample_size,
    )
    sample = clean_sample + partial_sample
    if not sample:
        console.print(f"[red]No events found in {stream_path}[/red]")
        raise typer.Exit(1)

    # Parse quality banner
    total_lines = parse_stats["total_lines"] or 1
    parse_rate = (parse_stats["parsed_clean"] + parse_stats["parsed_partial"]) / total_lines
    parse_color = "green" if parse_rate >= 0.95 else "yellow" if parse_rate >= 0.80 else "red"
    console.print(
        Panel(
            f"[bold]{len(sample)}[/bold] events from [bold]{parse_stats['total_lines']}[/bold] lines  •  "
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
                f"[green]{required_count} required[/green] (>=80%)  •  "
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

    from ..sampler import flatten_nested
    from ..schema_writer import load_schema

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


def report(
    stream_path: str = typer.Argument(...),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
):
    """Print current schema and drift history for a stream."""
    from datetime import datetime

    from ..schema_writer import load_schema

    stream_name = stream_path[len("kafka://"):] if stream_path.startswith("kafka://") else _stream_name(stream_path)
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

    # Schema version history
    history_dir = Path(output_dir) / stream_name / ".history"
    if history_dir.exists():
        history_files = sorted(history_dir.glob("schema_v*.yaml"))
        if history_files:
            console.print("\n[bold]Schema Version History[/bold]")
            for hf in history_files:
                mtime = hf.stat().st_mtime
                ts = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
                ver = hf.stem.replace("schema_", "")  # "schema_v1.0.0" -> "v1.0.0"
                console.print(f"  [dim]{ver}[/dim]  {ts}  [dim]{hf}[/dim]")
            console.print(f"  [bold]v{schema.version}[/bold]  (current)  [dim]{schema_path}[/dim]")

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

    from ..schema_writer import load_schema

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
        from ..exporters.json_schema import schema_to_json_schema
        doc = schema_to_json_schema(schema)
        result = json.dumps(doc, indent=2)
        suffix = ".schema.json"
    elif fmt == "avro":
        from ..exporters.avro import schema_to_avro
        doc = schema_to_avro(schema)
        result = json.dumps(doc, indent=2)
        suffix = ".avsc"
    elif fmt == "flink-ddl":
        from ..exporters.flink_ddl import schema_to_flink_ddl
        broker_list = [b.strip() for b in brokers.split(",") if b.strip()] if brokers else None
        result = schema_to_flink_ddl(schema, brokers=broker_list)
        suffix = ".sql"
    elif fmt == "ksqldb":
        from ..exporters.ksqldb import schema_to_ksqldb
        result = schema_to_ksqldb(schema)
        suffix = ".ksql"
    elif fmt == "proto":
        from ..exporters.protobuf import schema_to_proto
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
