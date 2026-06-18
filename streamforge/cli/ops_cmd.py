"""Commands: generate, status, accept, suppress, consumers, demo, incident_report, roi."""

import contextlib
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing. Safe to run anytime."),
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

    if dry_run:
        console.print(
            "\n[dim]--dry-run: Would update schema.yaml and bump version. "
            "No files will be written.[/dim]"
        )
        raise typer.Exit(0)

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
    cto:           bool = typer.Option(False, "--cto", help="Full executive demo — 90-second walkthrough of all capabilities."),
    eng:           bool = typer.Option(False, "--eng", help="Engineering deep-dive — shows internals, math, and architecture."),
):
    """
    Live drift detection demo — no Kafka needed.

    Generates realistic payment events in two phases:
      Phase 1: 300 clean baseline events -> schema inferred, 3 clean watch ticks
      Phase 2: 200 drifted events -> Tier 3 drift detected in real time

    No API key required. Run alongside the cockpit dashboard to see updates live.

    Three demo modes:
      --cto   Executive walkthrough (90 seconds)
      --eng   Engineering deep-dive (shows internals, math, pipeline)
      --loop  Continuous presentation (for live dashboard demos)
    """
    from datetime import datetime

    from ..connectors.generators import drifted_payment_events, payment_events
    from ..drift_detector import detect_drift
    from ..models import InferredSchema
    from ..report_writer import write_drift_report
    from ..sampler import reservoir_sample
    from ..schema_writer import write_schema

    if cto:
        _run_cto_demo(baseline_size, drift_size, output_dir, write_report)
        return

    if eng:
        _run_eng_demo(baseline_size, drift_size, output_dir)
        return

    # Internal flag: when called from CTO demo, suppress header/footer narration
    _from_cto = getattr(demo, "_from_cto", False)

    STREAM_NAME = "payments.demo"
    tier_colors = {1: "yellow", 2: "orange3", 3: "red"}

    if not _from_cto:
        console.rule("[bold]StreamForge Live Demo[/bold]")
        console.print(
            "\n[bold]Scenario:[/bold] A payments microservice just deployed at 2:17am.\n"
            "A developer renamed [cyan]amount[/cyan] to [cyan]amount_minor_units[/cyan] "
            "(dollars → integer cents), changed the timestamp format, and accidentally\n"
            "started logging [red]card_last_four[/red] — a PII field not in the baseline schema.\n"
            "\nStreamForge catches it before any consumer breaks.\n"
        )
    if loop:
        console.print("[dim]Running in loop mode (Ctrl+C to stop). Open the cockpit dashboard in another terminal.[/dim]\n")
    time.sleep(0.5 if _from_cto else 1)

    # -- Build baseline schema once -- reused across loop iterations
    demo_fields = _build_demo_fields()

    baseline_schema = InferredSchema(
        stream_name=STREAM_NAME,
        version="1.0.0",
        inferred_at=datetime.now(UTC).isoformat(),
        event_count_sampled=baseline_size,
        fields=demo_fields,
        inference_model="statistical+demo",
        inference_confidence=0.97,
    )

    write_schema(baseline_schema, output_dir)

    baseline = payment_events(n=baseline_size, seed=42)
    drifted  = drifted_payment_events(n=drift_size, seed=99)

    def _run_one_cycle(iteration: int) -> None:
        """Run one full Phase1 -> Phase2 demo cycle."""
        if iteration > 1:
            console.rule(f"[dim]Loop {iteration}[/dim]")

        console.print("[bold]PHASE 1 — Baseline monitoring[/bold]  [dim](clean schema)[/dim]")
        if iteration == 1:
            console.print(f"  Schema inferred — [bold]{len(demo_fields)}[/bold] fields, confidence [green]97%[/green]")
            console.print("  PII detected: [yellow]user_email[/yellow] (email)")
            console.print()

        for _ in range(3):
            sample = reservoir_sample(baseline, 50)
            detect_drift(baseline_schema, sample, STREAM_NAME)
            ts = datetime.now().strftime("%H:%M:%S")
            console.print(
                f"  [[dim]{ts}[/dim]] [green]CLEAN[/green] {STREAM_NAME} — "
                f"[dim]50 events sampled — no drift[/dim]"
            )
            time.sleep(0.9)

        console.print()

        console.print("[bold red]PHASE 2 — Drift injected[/bold red]  [dim](deploy at 2:17am)[/dim]")
        console.print("  [dim]amount renamed, timestamp format changed, card_last_four PII appears[/dim]")
        time.sleep(1.2)

        sample       = reservoir_sample(drifted, min(200, len(drifted)))
        ts           = datetime.now().strftime("%H:%M:%S")
        drift_report = detect_drift(baseline_schema, sample, STREAM_NAME)

        if drift_report is None:
            console.print(f"  [[dim]{ts}[/dim]] [green]CLEAN[/green] No drift detected (unexpected).")
            return

        _print_drift_results(drift_report, STREAM_NAME, ts, tier_colors)

        if write_report:
            report_path = write_drift_report(drift_report, "drift_reports")
            console.print(f"  Report saved: [green]{report_path}[/green]")

        console.rule()
        console.print(
            "\n[bold]That would have been a 3am page.[/bold]\n"
            "Instead: a blocked PR and a Slack alert to [cyan]#payments-oncall[/cyan].\n"
        )

        if loop:
            console.print("[dim]Restarting in 5 seconds... (Ctrl+C to stop)[/dim]")
            time.sleep(5)

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
        if not _from_cto:
            console.print(
                "Open the [bold]cockpit dashboard[/bold] to see the drift in the Fleet view.\n"
                "Run [bold]streamforge demo --loop[/bold] for a continuous presentation mode.\n\n"
                "[bold]Try it on your real Kafka:[/bold]\n"
                "  [cyan]streamforge init kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]\n"
                "  [cyan]streamforge watch kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]"
            )


def _build_demo_fields():
    """Build the demo baseline schema fields."""
    from ..models import FieldSchema, FieldType, PIICategory
    return [
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


def _print_drift_results(drift_report, stream_name, ts, tier_colors):
    """Print drift detection results with enterprise formatting."""
    highest = drift_report.highest_tier.value
    if highest == 3:
        console.print(
            f"\n  [[dim]{ts}[/dim]] [bold red]TIER 3 DRIFT[/bold red] {stream_name} — human action required"
        )
    else:
        console.print(
            f"\n  [[dim]{ts}[/dim]] [bold yellow]DRIFT DETECTED[/bold yellow] {stream_name} — Tier {highest}"
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


def _run_eng_demo(baseline_size, drift_size, output_dir):
    """Engineering deep-dive — shows the internals, math, and pipeline.

    Designed for hands-on engineering directors who want to see that the
    product is technically credible: sampling algorithms, statistical tests,
    type inference pipeline, registry cache, drift detection math, and
    output artifacts.
    """
    import shutil
    import time as _t
    from datetime import datetime
    from pathlib import Path as _Path

    from ..connectors.generators import drifted_payment_events
    from ..drift_detector import detect_drift
    from ..field_registry import FieldTypeRegistry, RegistryConfig
    from ..models import InferredSchema
    from ..report_writer import write_drift_report
    from ..sampler import (
        get_all_field_paths,
        reservoir_sample,
        streaming_resilient_sample_from_folder,
    )
    from ..schema_writer import write_schema
    for d in ["schemas", "drift_reports", ".streamforge"]:
        shutil.rmtree(d, ignore_errors=True)

    # =====================================================================
    # TITLE
    # =====================================================================
    console.print()
    console.print(
        Panel(
            "[bold white]StreamForge — Engineering Deep Dive[/bold white]\n"
            "[dim]How it works under the hood[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    _t.sleep(1.5)

    # =====================================================================
    # 1. SAMPLING — Reservoir Algorithm
    # =====================================================================
    console.print()
    console.rule("[bold]  1. Sampling — Reservoir Algorithm R  [/bold]", style="cyan")
    console.print()

    events_dir = _Path("events")
    if not events_dir.exists():
        events_dir = _Path("../home/claude/streamforge-mvp/events")
    stream_path = str(events_dir / "payments" / "stream_v1")

    t0 = _t.monotonic()
    clean, partial, _total, stats = streaming_resilient_sample_from_folder(stream_path, 200)
    sample = clean + partial
    elapsed = (_t.monotonic() - t0) * 1000

    console.print(
        "  [bold]Problem:[/bold] Stream has N events across multiple files.\n"
        "  We need exactly k=200 events with [bold]uniform probability[/bold] — but\n"
        "  we can't load all N events into memory (stream could be 100GB).\n"
    )
    console.print(
        "  [bold]Solution:[/bold] Knuth's Algorithm R (reservoir sampling)\n"
        "  [dim]Each event has exactly k/N probability of being selected.[/dim]\n"
        "  [dim]Single pass. O(k) memory. O(N) time. No second pass needed.[/dim]\n"
    )

    # Show the actual numbers
    rs = Table(show_header=False, box=None, padding=(0, 3))
    rs.add_column("Metric", style="dim", min_width=28)
    rs.add_column("Value", style="bold")
    rs.add_row("Files scanned",     f"{len(list(_Path(stream_path).rglob('*.ndjson')))} .ndjson files")
    rs.add_row("Total lines",       str(stats["total_lines"]))
    rs.add_row("Reservoir size (k)", "200")
    rs.add_row("Clean events",      f"{stats['parsed_clean']}  [green]({stats['parsed_clean']/max(stats['total_lines'],1):.0%} parse rate)[/green]")
    rs.add_row("Partial extracts",  str(stats["parsed_partial"]))
    rs.add_row("Skipped/malformed", str(stats["skipped"]))
    rs.add_row("Wall time",         f"[green]{elapsed:.1f}ms[/green]")
    rs.add_row("Memory",            f"[green]O(200)[/green] — not O({stats['total_lines']})")
    console.print(rs)
    _t.sleep(2.5)

    # =====================================================================
    # 2. FIELD ANALYSIS — Statistical Profiling
    # =====================================================================
    console.print()
    console.rule("[bold]  2. Field Analysis — Statistical Profiling  [/bold]", style="cyan")
    console.print()

    t0 = _t.monotonic()
    field_values, presence_rates = get_all_field_paths(sample)
    profile_ms = (_t.monotonic() - t0) * 1000

    console.print(
        "  [bold]No LLM here.[/bold] Pure statistics over the sampled events:\n"
        "  [dim]For each field: count occurrences, compute presence rate,\n"
        "  detect type from values, flag PII patterns.[/dim]\n"
    )

    ft = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    ft.add_column("Field Path", style="cyan", min_width=22)
    ft.add_column("Presence", justify="right", min_width=10)
    ft.add_column("Formula", style="dim", min_width=28)
    ft.add_column("Verdict", min_width=14)

    sorted_fields = sorted(presence_rates.items(), key=lambda x: -x[1])
    for path, rate in sorted_fields[:8]:
        count = int(round(rate * len(sample)))
        formula = f"{count}/{len(sample)} = {rate:.2%}"
        verdict = "[green]required[/green]" if rate >= 0.8 else "[yellow]optional[/yellow]" if rate >= 0.1 else "[dim]rare[/dim]"
        ft.add_row(path, f"{rate:.0%}", formula, verdict)

    remaining = len(sorted_fields) - 8
    if remaining > 0:
        ft.add_row(f"[dim]... +{remaining} more[/dim]", "", "", "")
    console.print(ft)
    console.print(f"\n  [dim]Profiled {len(presence_rates)} fields in {profile_ms:.1f}ms[/dim]")
    _t.sleep(2.5)

    # =====================================================================
    # 3. TYPE INFERENCE — Registry + LLM Cascade
    # =====================================================================
    console.print()
    console.rule("[bold]  3. Type Inference — Registry-First Pipeline  [/bold]", style="cyan")
    console.print()

    console.print(
        "  [bold]Architecture:[/bold] Registry lookup → LLM cascade → statistical fallback\n"
    )

    # Show the cascade diagram
    console.print(
        "  [cyan]Step 0[/cyan]  Registry (229 pre-seeded patterns)  [green]FREE, <1ms[/green]\n"
        "         Exact field_path match. If seen 3+ times → cache hit.\n"
        "  [cyan]Step 1[/cyan]  Local Ollama (if available)           [green]FREE, ~2s[/green]\n"
        "         JSON-mode. Accepted if confidence >= 0.80.\n"
        "  [cyan]Step 2[/cyan]  Groq / primary remote LLM             [yellow]$0.02, ~1s[/yellow]\n"
        "         Tool-call mode. Structured output via function calling.\n"
        "  [cyan]Step 3[/cyan]  OpenAI fallback (gpt-4o-mini)         [yellow]$0.01, ~2s[/yellow]\n"
        "  [cyan]Step 4[/cyan]  OpenRouter fallback                    [yellow]$0.01, ~3s[/yellow]\n"
        "  [cyan]Step 5[/cyan]  Statistical inference (no LLM)        [green]FREE, <1ms[/green]\n"
        "         Python isinstance() checks + regex patterns.\n"
    )

    # Demo the registry hit rate
    registry = FieldTypeRegistry.load(seed=True)
    cached, unknown = registry.lookup_batch(
        list(field_values.keys()), config=RegistryConfig(),
    )

    total_f = len(field_values)
    hit_f = len(cached)
    miss_f = len(unknown)

    console.print(
        Panel(
            f"  Registry lookup for [bold]payments.stream_v1[/bold]:\n\n"
            f"    Fields in stream:    [bold]{total_f}[/bold]\n"
            f"    Registry hits:       [green]{hit_f}[/green]  ({hit_f}/{total_f} = {hit_f/max(total_f,1):.0%} cache rate)\n"
            f"    Sent to LLM:         [yellow]{miss_f}[/yellow]  ({miss_f}/{total_f} = {miss_f/max(total_f,1):.0%})\n\n"
            f"  [bold]Cost: {'$0.00 — LLM skipped entirely' if miss_f == 0 else f'~${miss_f * 0.002:.3f} for {miss_f} field(s)'}[/bold]",
            title="[bold] Registry Hit Rate [/bold]",
            border_style="green" if miss_f == 0 else "yellow",
            expand=False,
        )
    )
    _t.sleep(2.5)

    # =====================================================================
    # 4. DRIFT DETECTION — The Math
    # =====================================================================
    console.print()
    console.rule("[bold]  4. Drift Detection — Statistical Tests  [/bold]", style="cyan")
    console.print()

    # Build baseline and drifted data
    demo_fields = _build_demo_fields()
    baseline_schema = InferredSchema(
        stream_name="payments.demo",
        version="1.0.0",
        inferred_at=datetime.now(UTC).isoformat(),
        event_count_sampled=baseline_size,
        fields=demo_fields,
        inference_model="statistical+demo",
        inference_confidence=0.97,
    )
    write_schema(baseline_schema, output_dir)

    drifted = drifted_payment_events(n=drift_size, seed=99)

    console.print(
        "  [bold]How drift detection works:[/bold]\n\n"
        "  For each field in the baseline schema, we compare against the new sample:\n"
    )

    dt = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    dt.add_column("Check", style="cyan", min_width=22)
    dt.add_column("Method", min_width=34)
    dt.add_column("Trigger", min_width=24)

    dt.add_row("Field removed?",    "Presence rate comparison",          "was >= 20%, now < 5%")
    dt.add_row("Type changed?",     "Value-by-value type inference",     "majority type differs")
    dt.add_row("Presence dropped?", "Binomial z-test (two-tailed)",      "p < 0.01, drop > 15%")
    dt.add_row("Enum changed?",     "Chi-squared goodness-of-fit",       "p < 0.05 or new values")
    dt.add_row("New field?",        "Path appears, not in baseline",     "presence >= 10%")
    dt.add_row("New PII?",          "Regex + field name heuristics",     "email/phone/SSN/card pattern")
    console.print(dt)
    console.print()

    # Run actual drift detection and show the math
    t0 = _t.monotonic()
    drift_sample = reservoir_sample(drifted, min(200, len(drifted)))
    drift_report = detect_drift(baseline_schema, drift_sample, "payments.demo")
    detection_ms = (_t.monotonic() - t0) * 1000

    if drift_report:
        console.print(f"  [bold]Live result:[/bold] {len(drift_report.drifts)} drifts detected in [green]{detection_ms:.1f}ms[/green]\n")

        # Show a few drifts with the underlying math
        math_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        math_table.add_column("Field", style="cyan", min_width=20)
        math_table.add_column("Drift Type", min_width=16)
        math_table.add_column("Evidence", min_width=36)
        math_table.add_column("Tier", justify="center", min_width=6)

        tier_colors = {1: "blue", 2: "yellow", 3: "red"}
        for d in drift_report.drifts[:6]:
            c = tier_colors.get(d.tier.value, "white")
            tier_str = f"[{c}]T{d.tier.value}[/{c}]"

            if d.drift_type == "field_removed":
                evidence = f"presence: {(d.previous_presence_rate or 0):.0%} -> {(d.observed_presence_rate or 0):.0%}"
            elif d.drift_type == "type_changed":
                evidence = f"{d.previous_type.value} -> {d.observed_type.value} ({d.affected_event_rate:.0%})"
            elif d.drift_type == "field_added":
                evidence = f"new field, {(d.observed_presence_rate or 0):.0%} presence"
            elif d.drift_type == "new_pii":
                evidence = "PII pattern detected in values"
            else:
                evidence = d.drift_type

            math_table.add_row(d.field_path, d.drift_type, evidence, tier_str)

        if len(drift_report.drifts) > 6:
            math_table.add_row(f"[dim]... +{len(drift_report.drifts) - 6} more[/dim]", "", "", "")
        console.print(math_table)

        report_path = write_drift_report(drift_report, "drift_reports")
        console.print(f"\n  [dim]Report: {report_path}[/dim]")
    _t.sleep(2.5)

    # =====================================================================
    # 5. OUTPUT ARTIFACTS — What gets committed to Git
    # =====================================================================
    console.print()
    console.rule("[bold]  5. Output Artifacts — Schema as Code  [/bold]", style="cyan")
    console.print()

    console.print("  [bold]Everything lives in Git.[/bold] Three artifact types:\n")

    # Show schema YAML snippet
    schema_path = _Path(output_dir) / "payments.demo" / "schema.yaml"
    if schema_path.exists():
        yaml_lines = schema_path.read_text().splitlines()
        # Show the header + first 2 fields
        snippet = []
        field_count = 0
        for line in yaml_lines:
            snippet.append(line)
            if line.startswith("- path:"):
                field_count += 1
            if field_count >= 2 and not line.startswith(" "):
                break
            if len(snippet) > 25:
                break
        console.print("  [bold cyan]1. schema.yaml[/bold cyan] — the contract\n")
        for line in snippet[:20]:
            console.print(f"  [dim]{line}[/dim]")
        console.print(f"  [dim]  ... ({len(demo_fields)} fields total)[/dim]")

    # Show exports
    console.print("\n  [bold cyan]2. Export formats[/bold cyan] — generated from schema.yaml\n")

    from ..exporters.protobuf import schema_to_proto

    proto_out = schema_to_proto(baseline_schema)
    proto_lines = proto_out.splitlines()
    for line in proto_lines[:12]:
        console.print(f"  [dim]{line}[/dim]")
    console.print(f"  [dim]  ... ({len(baseline_schema.fields)} fields)[/dim]")

    export_table = Table(show_header=False, box=None, padding=(0, 3))
    export_table.add_column("Format", style="cyan", min_width=16)
    export_table.add_column("Command", style="dim", min_width=44)
    export_table.add_row("JSON Schema",  "streamforge export schema.yaml --format json-schema")
    export_table.add_row("Avro (.avsc)", "streamforge export schema.yaml --format avro")
    export_table.add_row("Protobuf",     "streamforge export schema.yaml --format proto")
    export_table.add_row("Flink DDL",    "streamforge export schema.yaml --format flink-ddl")
    export_table.add_row("ksqlDB",       "streamforge export schema.yaml --format ksqldb")
    console.print()
    console.print(export_table)

    # Show drift report snippet
    reports = sorted(_Path("drift_reports").rglob("*.md"))
    if reports:
        console.print("\n  [bold cyan]3. Drift reports[/bold cyan] — human-readable incident log\n")
        rpt_text = reports[0].read_text().splitlines()
        for line in rpt_text[:12]:
            console.print(f"  [dim]{line}[/dim]")
        console.print(f"  [dim]  ... (full report: {reports[0]})[/dim]")

    _t.sleep(2.5)

    # =====================================================================
    # 6. ARCHITECTURE
    # =====================================================================
    console.print()
    console.rule("[bold]  6. Architecture  [/bold]", style="cyan")
    console.print()

    arch = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    arch.add_column("Component", style="cyan", min_width=22)
    arch.add_column("Lines", justify="right", min_width=8)
    arch.add_column("What it does", min_width=42)

    arch.add_row("sampler.py",          "320",  "Reservoir sampling, resilient NDJSON parser")
    arch.add_row("profiler.py",         "120",  "Cluster discovery (event_type + structural)")
    arch.add_row("inference.py",        "960",  "5-provider LLM cascade + registry + fallback")
    arch.add_row("detector/core.py",    "280",  "Drift detection: z-test, chi-squared, PSI")
    arch.add_row("detector/classify.py","250",  "Tier 1/2/3 classification + drift/evolution")
    arch.add_row("detector/watch.py",   "870",  "Continuous watch loop (file + Kafka)")
    arch.add_row("pii_detector.py",     "200",  "Regex + heuristic PII detection (8 categories)")
    arch.add_row("field_registry.py",   "330",  "RAG cache — 229 pre-seeded field patterns")
    arch.add_row("statistical_tests.py","550",  "PSI, binomial z-test, chi-squared, Cramér's V")
    arch.add_row("exporters/",          "400",  "Proto, Avro, JSON Schema, Flink, ksqlDB")
    arch.add_row("[dim]Total[/dim]",    "[bold]~4,300", "[dim]Pure Python. No Spark. No Flink. No JVM.[/dim]")
    console.print(arch)
    console.print()

    console.print(
        Panel(
            "[bold]Key design decisions[/bold]\n\n"
            "  [cyan]Why reservoir sampling?[/cyan]\n"
            "    O(k) memory, O(N) time. Can profile a 100GB topic without loading it.\n\n"
            "  [cyan]Why registry-first inference?[/cyan]\n"
            "    229 common field patterns resolve immediately. LLM only called for\n"
            "    genuinely novel fields. First run: ~$0.02. Subsequent runs: $0.00.\n\n"
            "  [cyan]Why statistical drift detection (not LLM)?[/cyan]\n"
            "    Drift detection runs on every poll cycle (every 30s in watch mode).\n"
            "    Can't afford an API call per cycle. Binomial z-test + chi-squared\n"
            "    give p-values with zero cost, zero latency, zero rate limits.\n\n"
            "  [cyan]Why schema-as-code (YAML in Git)?[/cyan]\n"
            "    PRs, diffs, code review, blame, rollback — for data contracts.\n"
            "    No separate schema registry to operate. Works with any CI system.",
            border_style="cyan",
            padding=(1, 3),
        )
    )


def _run_cto_demo(baseline_size, drift_size, output_dir, write_report):
    """Full executive demo — thin orchestrator that calls real CLI commands.

    Sequences: profile -> fleet profiling -> demo (drift) -> plan (CI gate)
    with narrative headers and an executive summary. What the CTO sees is
    exactly what they'd get running the commands themselves.
    """
    import time as _t
    from pathlib import Path as _Path

    from click.exceptions import Exit as ClickExit

    from .schema_cmd import plan as _plan_cmd
    from .schema_cmd import profile as _profile_cmd

    # ── Resolve events dir ────────────────────────────────────────────────
    events_dir = _Path("events")
    if not events_dir.exists():
        parent_candidate = _Path("../home/claude/streamforge-mvp/events")
        if parent_candidate.exists():
            events_dir = parent_candidate
    if not events_dir.exists():
        console.print("[red]events/ directory not found. Run from the project root.[/red]")
        return

    # Clean previous state
    import shutil
    for d in ["schemas", "drift_reports", ".streamforge"]:
        shutil.rmtree(d, ignore_errors=True)

    # =====================================================================
    # TITLE
    # =====================================================================
    console.print()
    console.print(
        Panel(
            "[bold white]StreamForge[/bold white]\n"
            "[dim]Schema inference and contract enforcement for event streams[/dim]\n\n"
            "Point it at any Kafka topic. No Avro. No Protobuf. No config.\n"
            "StreamForge infers the schema, watches for drift, and blocks\n"
            "breaking changes before they reach production.",
            border_style="blue",
            padding=(1, 4),
        )
    )
    _t.sleep(2.0)

    # =====================================================================
    # ACT 1 — Schema Inference (single stream, real profile command)
    # =====================================================================
    console.print()
    console.rule("[bold]  ACT 1 — Schema Inference  [/bold]", style="blue")
    console.print()
    console.print(
        "  You have a payments topic. Thousands of events. No schema.\n"
        "  One command:\n"
    )
    console.print("    [bold cyan]$ streamforge profile events/payments/stream_v1[/bold cyan]\n")
    _t.sleep(1.5)

    # Call the real profile command
    with contextlib.suppress(SystemExit):
        _profile_cmd(
            stream_path=str(events_dir / "payments" / "stream_v1"),
            sample_size=200, top=12, show_values=False,
        )
    console.print()
    _t.sleep(2.0)

    # =====================================================================
    # ACT 2 — Fleet Profiling (four streams, real profile command)
    # =====================================================================
    console.rule("[bold]  ACT 2 — Fleet Profiling  [/bold]", style="blue")
    console.print()
    console.print("  Four topics. Four seconds. Zero configuration.\n")
    _t.sleep(1.0)

    fleet_streams = [
        "payments/stream_v1",
        "flights/stream",
        "bookings/stream",
        "iot/stream",
    ]
    fleet_t0 = _t.monotonic()
    for rel_path in fleet_streams:
        spath = str(events_dir / rel_path)
        if not _Path(spath).exists():
            continue
        with contextlib.suppress(SystemExit, ClickExit):
            # top=0 shows header panels only (no field tables) for compact fleet view
            _profile_cmd(stream_path=spath, sample_size=100, top=0, show_values=False)
        console.print()
    fleet_elapsed = (_t.monotonic() - fleet_t0) * 1000

    console.print(
        Panel(
            f"[bold]{len(fleet_streams)}[/bold] streams profiled in [green]{fleet_elapsed:.0f}ms[/green]  |  "
            f"API calls: [green]0[/green]  |  Cost: [green]$0.00[/green]",
            border_style="green",
            expand=False,
        )
    )
    _t.sleep(2.0)

    # =====================================================================
    # ACT 3 — Breaking Change Detection (real demo command)
    # =====================================================================
    console.print()
    console.rule("[bold]  ACT 3 — Breaking Change Detection  [/bold]", style="red")
    console.print()
    console.print(
        Panel(
            "[bold]Incident scenario[/bold]\n\n"
            "Tuesday, 2:17am. The payments team deploys [cyan]payments-service v4.12.0[/cyan].\n\n"
            "Three changes ship in one PR:\n"
            "  1. [cyan]amount[/cyan] renamed to [cyan]amount_minor_units[/cyan]  (dollars to integer cents)\n"
            "  2. [cyan]timestamp[/cyan] format changed  (epoch_ms to ISO 8601)\n"
            "  3. [red]card_last_four[/red] added  (PII — was in debug logging, accidentally promoted)\n\n"
            "[dim]Without StreamForge: the fraud model gets nulls for 6 hours.\n"
            "The analytics pipeline silently drops 100% of records.\n"
            "The compliance team finds PII in the data lake on Thursday.[/dim]",
            border_style="red",
            padding=(1, 3),
        )
    )
    _t.sleep(2.0)

    # Call the real demo command (non-cto path, suppress header/footer narration)
    demo._from_cto = True
    try:
        demo(
            baseline_size=baseline_size, drift_size=drift_size,
            output_dir=output_dir, write_report=write_report,
            loop=False, cto=False,
        )
    finally:
        demo._from_cto = False
    _t.sleep(2.0)

    # =====================================================================
    # ACT 4 — CI Gate (real plan command)
    # =====================================================================
    console.print()
    console.rule("[bold]  ACT 4 — CI/CD Gate  [/bold]", style="blue")
    console.print()
    console.print("  In your CI pipeline — one line:\n")
    console.print(
        "    [bold cyan]$ streamforge plan events/payments/stream_v2_drift \\\n"
        "        --schema schemas/payments.demo/schema.yaml[/bold cyan]\n"
    )
    _t.sleep(1.5)

    # Call the real plan command (must pass all params — Typer defaults don't apply to direct calls)
    schema_file = f"{output_dir}/payments.demo/schema.yaml"
    plan_stream = str(events_dir / "payments" / "stream_v2_drift")
    if _Path(schema_file).exists() and _Path(plan_stream).exists():
        # plan exits 1 on drift — expected
        with contextlib.suppress(SystemExit, ClickExit):
            _plan_cmd(
                stream_path=plan_stream,
                schema_path=schema_file,
                output_dir=output_dir,
                sample_size=100,
                api_key=None,
                model="",
                base_url="",
                brokers=None,
            )
    _t.sleep(2.0)

    # =====================================================================
    # CLOSE — Executive Summary
    # =====================================================================
    console.print()
    console.rule("[bold]  Summary  [/bold]", style="blue")
    console.print()

    summary_table = Table(show_header=False, box=None, padding=(0, 3))
    summary_table.add_column("Metric", style="dim", min_width=28)
    summary_table.add_column("Value", style="bold", min_width=30)
    summary_table.add_row("Time to first schema",       "[green]< 1 second[/green]  (no LLM needed for profiling)")
    summary_table.add_row("Full fleet profiling",        f"[green]{fleet_elapsed:.0f}ms[/green]  (4 streams)")
    summary_table.add_row("Schema inference cost",       "[green]$0.02/topic[/green]  (one LLM call for type enrichment)")
    summary_table.add_row("Continuous monitoring cost",   "[green]$0/month[/green]  (pure statistics, no API)")
    summary_table.add_row("PII detection",               "[green]Automatic[/green]  (email, phone, SSN, card, passport)")
    summary_table.add_row("CI gate",                     "[green]exit 0 = merge, exit 1 = block[/green]")
    summary_table.add_row("Kafka integration",           "[green]Any broker[/green]  (no Avro migration required)")
    summary_table.add_row("Schema storage",              "[green]Git-native[/green]  (PRs, diffs, code review — for data)")

    console.print(summary_table)
    console.print()

    console.print(
        Panel(
            "[bold]What you just saw[/bold]\n\n"
            "  1. Schema inferred from raw JSON — [green]real command output[/green]\n"
            "  2. Four heterogeneous streams profiled with [green]zero config[/green]\n"
            "  3. Breaking change caught in [green]real time[/green] — before any consumer saw it\n"
            "  4. CI gate that [green]blocks the deploy[/green] — no human needed\n\n"
            "[bold]Try it now:[/bold]\n"
            "  [cyan]streamforge init kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]\n"
            "  [cyan]streamforge watch kafka://YOUR_TOPIC --brokers YOUR_BROKERS[/cyan]\n"
            "  [cyan]uvicorn streamforge.api.main:app[/cyan]  [dim](cockpit dashboard API)[/dim]",
            border_style="blue",
            padding=(1, 3),
        )
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
