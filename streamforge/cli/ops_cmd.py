"""Commands: generate, status, accept, suppress, consumers, demo, incident_report, roi."""

import logging
import time
from datetime import UTC
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ._helpers import _stream_name, console

logger = logging.getLogger(__name__)


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

    from ..generator import generate_events, generate_from_cluster
    from ..schema_writer import load_profile, load_schema

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


def status(
    stream_path: str | None = typer.Argument(None, help="Stream path (omit to show all streams)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    show_resolved: bool = typer.Option(False, "--all", "-a", help="Include resolved/accepted incidents"),
    output_format: str = typer.Option("table", "--format", help="Output format: table | json"),
):
    """Show open drift incidents for a stream (or all streams)."""
    import json as _json

    from ..models import DriftIncidentStatus
    from ..schema_writer import load_drift_state

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
    from ..models import DriftIncidentStatus
    from ..schema_writer import accept_drift, load_drift_state, load_schema
    from ..topic_config import load_topic_config

    stream_name = _stream_name(stream_path)
    schema_dir = Path(output_dir) / stream_name
    schema_path_resolved = schema_dir / "schema.yaml"

    if not schema_path_resolved.exists():
        console.print(f"[red]No schema found at {schema_path_resolved}. Run 'streamforge init' first.[/red]")
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

    current = load_schema(str(schema_path_resolved))
    updated = accept_drift(schema_dir, open_incidents, drifts_by_id={})
    console.print(
        f"\n[green]✓ Schema updated:[/green] v{current.version} → v{updated.version}"
    )
    console.print(f"  Written: [dim]{schema_path_resolved}[/dim]")
    console.print(
        "\n[dim]Restart 'streamforge watch' to monitor against the updated schema.[/dim]"
    )

    # VCS: create PR for accepted schema changes
    from ..vcs import SchemaCommitContext, get_vcs_backend
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
    from datetime import datetime, timedelta

    from ..models import DriftIncidentStatus
    from ..schema_writer import load_drift_state, save_drift_state

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


def consumers(
    stream_path: str = typer.Argument(..., help="Stream path or stream name (e.g. events/payments/stream_v1 or stream_v1)"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    auto: bool = typer.Option(False, "--auto", help="Auto-discover from Kafka consumer group metadata"),
    brokers: str = typer.Option("localhost:9092", "--brokers", help="Kafka broker list (used with --auto)"),
):
    """Show consumer registry and blast radius for a stream."""
    from ..consumer_registry import discover_consumers_from_kafka as _discover
    from ..consumer_registry import load_consumers as _load_consumers

    stream_name = _stream_name(stream_path)
    schema_dir  = Path(output_dir) / stream_name

    if not schema_dir.exists():
        console.print(f"[red]No schema directory found at {schema_dir}. Run 'streamforge init' first.[/red]")
        raise typer.Exit(1)

    consumer_list = _load_consumers(output_dir, stream_name)

    # --auto: supplement/replace consumer_list with Kafka-discovered groups
    if auto and not consumer_list:
        discovered = _discover(stream_name, brokers)
        if discovered:
            auto_table = Table(
                title=f"Auto-discovered Consumer Groups — {stream_name}",
                show_header=True,
                header_style="bold",
            )
            auto_table.add_column("Consumer Group", style="cyan", no_wrap=True)
            auto_table.add_column("Members",         justify="right")
            auto_table.add_column("Lag",             justify="right")
            auto_table.add_column("Team")
            for g in discovered:
                auto_table.add_row(
                    g["group_id"],
                    str(g["member_count"]),
                    str(g["lag"]) if g["lag"] is not None else "—",
                    g["team"] or "—",
                )
            console.print(auto_table)
        else:
            console.print(
                f"[yellow]No consumer groups found for {stream_name}.[/yellow]\n"
                f"  They may use a different broker or topic name.\n"
                f"  Brokers checked: {brokers}"
            )
        raise typer.Exit(0)

    if not consumer_list:
        console.print(
            f"[yellow]No consumers.yaml found for {stream_name}.[/yellow]\n"
            f"  Create one at: {schema_dir / 'consumers.yaml'}\n"
            f"  Format: list of consumers with name, team, contact, criticality, fields_used\n"
            f"  Or use --auto to discover from Kafka metadata."
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
      Phase 1: 300 clean baseline events -> schema inferred, 3 clean watch ticks
      Phase 2: 200 drifted events -> Tier 3 drift detected in real time

    No API key required. Run alongside `streamforge ui` to see the dashboard update live.

    Add --loop to run continuously during a presentation (Ctrl+C to stop).
    """
    from datetime import datetime

    from ..connectors.generators import drifted_payment_events, payment_events
    from ..drift_detector import detect_drift
    from ..models import FieldSchema, FieldType, InferredSchema, PIICategory
    from ..report_writer import write_drift_report
    from ..sampler import reservoir_sample
    from ..schema_writer import write_schema

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

    # -- Build baseline schema once -- reused across loop iterations
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
        """Run one full Phase1 -> Phase2 demo cycle."""
        if iteration > 1:
            console.rule(f"[dim]Loop {iteration}[/dim]")

        # -- Phase 1 --
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

        # -- Phase 2 --
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

    # -- Run once or loop until KeyboardInterrupt --
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
            "Run [bold]streamforge demo --loop[/bold] for a continuous presentation mode.\n\n"
            "[bold]Try it on your real Kafka:[/bold]\n"
            "  [cyan]streamforge init kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]\n"
            "  [cyan]streamforge watch kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]"
        )


def incident_report(
    stream_path: str = typer.Argument(..., help="Stream path (e.g. kafka://events.payments or folder)"),
    since: str = typer.Option("30d", "--since", help="Time window: 7d, 30d, 90d, or ISO date"),
    min_tier: int = typer.Option(2, "--min-tier", help="Minimum drift tier to include (1, 2, or 3)"),
    drift_reports_dir: str = typer.Option("drift_reports", "--drift-reports-dir", help="Directory containing drift reports"),
) -> None:
    """Generate a structured incident report from past drift detections.

    Shows breaking schema changes caught before production, suitable
    for sharing with engineering managers or design partner contacts.
    """
    import re
    from datetime import datetime, timedelta
    from pathlib import Path as _Path

    # Resolve stream name: strip kafka:// prefix if present
    if stream_path.startswith("kafka://"):
        stream_name = stream_path[len("kafka://"):]
    else:
        stream_name = _stream_name(stream_path)

    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", stream_name)

    reports_dir = _Path(drift_reports_dir) / slug

    # Parse --since into a cutoff datetime
    now = datetime.now(UTC)
    if since.endswith("d"):
        try:
            cutoff = now - timedelta(days=int(since[:-1]))
        except ValueError:
            cutoff = now - timedelta(days=30)
    elif since.endswith("h"):
        try:
            cutoff = now - timedelta(hours=int(since[:-1]))
        except ValueError:
            cutoff = now - timedelta(hours=24)
    else:
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            cutoff = now - timedelta(days=30)

    # Collect matching drift reports
    incidents: list[dict] = []
    if reports_dir.exists():
        for md_file in sorted(reports_dir.glob("*.md")):
            content = md_file.read_text()
            detected_match = re.search(r"\*\*Detected:\*\*\s+(.+)", content)
            if not detected_match:
                continue
            try:
                detected_at = datetime.fromisoformat(
                    detected_match.group(1).strip().replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if detected_at < cutoff:
                continue
            tier_match = re.search(r"Tier (\d)", content)
            tier = int(tier_match.group(1)) if tier_match else 1
            if tier < min_tier:
                continue
            incidents.append({
                "detected_at": detected_at,
                "tier": tier,
                "content": content,
                "file": md_file,
            })

    if not incidents:
        console.print(
            f"\n[green]✓[/green] [bold]{stream_name}[/bold] — "
            f"0 incidents in the last {since}"
        )
        console.print(
            f"  [dim]No drift above Tier {min_tier} detected. Schema is stable.[/dim]\n"
        )
        return

    # Header
    console.print(f"\n[bold]StreamForge Incident Report — {stream_name}[/bold]")
    console.print(
        f"[dim]Period: last {since} | Min tier: {min_tier} | "
        f"{len(incidents)} incident(s)[/dim]"
    )
    console.print()

    for i, incident in enumerate(incidents, 1):
        tier = incident["tier"]
        tier_color = "red" if tier == 3 else "yellow" if tier == 2 else "blue"
        console.print(
            f"[{tier_color}]Incident {i} — Tier {tier}[/{tier_color}]  "
            f"{incident['detected_at'].strftime('%Y-%m-%d %H:%M UTC')}"
        )

        field_matches = re.findall(r"### `([^`]+)`", incident["content"])
        drift_type_matches = re.findall(
            r"\*\*Drift type\*\*.*?`([^`]+)`", incident["content"]
        )

        for j, field_name in enumerate(field_matches):
            drift_type = drift_type_matches[j] if j < len(drift_type_matches) else "unknown"
            console.print(
                f"  [dim]→[/dim] [bold]{field_name}[/bold]: {drift_type.replace('_', ' ')}"
            )

        console.print(f"  [dim]Full report: {incident['file']}[/dim]")
        console.print()

    console.print("[dim]━━━[/dim]")
    console.print(
        f"[bold]{len(incidents)} schema incident(s) caught[/bold] before production "
        f"in the last {since}."
    )
    console.print(
        f"[dim]Generated by StreamForge — "
        f"streamforge incident-report kafka://{stream_name}[/dim]\n"
    )


def roi(
    stream_path: str = typer.Argument(..., help="Stream path or stream name"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    since: str = typer.Option("30d", "--since", help="Time window e.g. 30d, 7d, 90d"),
    tier3_cost_hours: float = typer.Option(
        4.0, "--tier3-cost-hours",
        help="Estimated engineer-hours per Tier 3 incident",
    ),
    slack_webhook: str | None = typer.Option(
        None, "--slack-webhook",
        envvar="SLACK_WEBHOOK_URL",
        help="Post ROI summary to Slack webhook URL",
    ),
):
    """ROI report: schema changes intercepted before production."""
    from ..roi import compute_roi_metrics, format_roi_panel
    from ..roi import parse_since as _parse_since
    from ..schema_writer import load_drift_state

    stream_name = (
        stream_path[len("kafka://"):] if stream_path.startswith("kafka://")
        else _stream_name(stream_path)
    )
    schema_dir = Path(output_dir) / stream_name

    if not schema_dir.exists():
        console.print(
            f"[red]No schema directory found at {schema_dir}. Run 'streamforge init' first.[/red]"
        )
        raise typer.Exit(1)

    since_days = _parse_since(since)
    state = load_drift_state(schema_dir)
    metrics = compute_roi_metrics(state, since_days=since_days, tier3_cost_hours=tier3_cost_hours)
    body = format_roi_panel(stream_name, metrics, since_days=since_days)

    console.print(
        Panel(
            body,
            title=f"[bold]StreamForge ROI — {stream_name} (last {since})[/bold]",
            expand=False,
        )
    )

    if slack_webhook:
        try:
            import httpx as _httpx
            payload = {"text": f"*StreamForge ROI — {stream_name}*\n```\n{body}\n```"}
            _httpx.post(slack_webhook, json=payload, timeout=10)
            console.print("[green]ROI summary posted to Slack.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Slack post failed: {exc}[/yellow]")
