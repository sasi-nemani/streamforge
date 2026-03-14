import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .drift_detector import detect_drift
from .inference import DEFAULT_BASE_URL, DEFAULT_MODEL, infer_schema, infer_sub_schema
from .models import DriftTier, StreamProfile
from .policy import StreamPolicy, load_policy, write_policy
from .profiler import discover_clusters, get_detection_method
from .report_writer import write_drift_report
from .sampler import get_all_field_paths, load_events_from_folder, load_events_resilient, reservoir_sample
from .schema_writer import (
    load_schema, write_inference_report, write_profile, write_profile_report,
    write_samples, write_schema,
)

app = typer.Typer(
    name="streamforge",
    help="StreamForge — AI-native schema inference and drift detection for event streams",
    add_completion=False,
)
console = Console()

logging.basicConfig(
    level=os.environ.get("STREAMFORGE_LOG_LEVEL", "WARNING"),
    format="%(levelname)s %(name)s: %(message)s",
)

# Env vars checked in order: LLM_API_KEY, GROQ_API_KEY, OPENAI_API_KEY
_KEY_ENV_VARS = ["LLM_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"]


def _resolve_api_key(api_key: Optional[str]) -> str:
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


def _auto_detect_schema(stream_path: str, output_dir: str) -> Optional[str]:
    """Try to find schema.yaml for the given stream path."""
    candidate = Path(output_dir) / _stream_name(stream_path) / "schema.yaml"
    if candidate.exists():
        return str(candidate)
    return None


@app.command()
def init(
    stream_path: str = typer.Argument(..., help="Path to folder containing NDJSON event files"),
    sample_size: int = typer.Option(500, "--sample-size", "-n", help="Number of events to sample"),
    output_dir: str = typer.Option("schemas", "--output", "-o", help="Output directory for schema files"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="LLM API key (or set GROQ_API_KEY / OPENAI_API_KEY)"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Model name"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url", help="OpenAI-compatible API base URL"),
):
    """Infer schema from event stream. Produces profile.yaml, profile_report.md, and schema.yaml."""
    from datetime import datetime, timezone

    key = _resolve_api_key(api_key)
    stream_name = _stream_name(stream_path)
    console.print(f"[bold]StreamForge[/bold] — profiling [cyan]{stream_name}[/cyan]")

    # Load with resilient parser — handles broken JSON, log-prefixed lines, partial extracts
    events, parse_stats = load_events_resilient(stream_path)
    if not events:
        console.print(f"[red]No events found in {stream_path}[/red]")
        raise typer.Exit(1)

    total_lines = parse_stats["total_lines"] or 1
    parse_success_rate = (parse_stats["parsed_clean"] + parse_stats["parsed_partial"]) / total_lines
    partial = parse_stats["parsed_partial"]
    skipped = parse_stats["skipped"]

    parse_color = "green" if parse_success_rate >= 0.95 else "yellow" if parse_success_rate >= 0.80 else "red"
    parse_note = f"  ({partial} partial, {skipped} skipped)" if (partial + skipped) > 0 else ""
    console.print(
        f"✓ Loaded [{parse_color}]{len(events)} events[/{parse_color}]"
        f" from {parse_stats['total_lines']} lines"
        f" — parse rate [{parse_color}]{parse_success_rate:.1%}[/{parse_color}]{parse_note}"
    )

    # Sample
    sample = reservoir_sample(events, sample_size)
    sampled_note = "(all)" if len(sample) == len(events) else f"reservoir sample"
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
    console.print(f"\n🤖 Inferring sub-schemas with [bold]{model}[/bold]...")
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
            model=model,
            base_url=base_url,
        )
        sub_schemas.append(sub)
        pii = [(f.path, f.pii_categories) for f in sub.fields if f.pii_categories]
        all_pii.extend([(cid, p, cats) for p, cats in pii])
        console.print(
            f"     ✓ {len(sub.fields)} fields, confidence {sub.inference_confidence:.0%}"
        )

    if all_pii:
        console.print(f"\n[yellow]⚠ PII detected:[/yellow]")
        for cid, path, cats in all_pii:
            cat_str = ", ".join(p.value for p in cats)
            console.print(f"   [yellow]{cid}[/yellow] → [cyan]{path}[/cyan] ({cat_str})")

    # Assemble StreamProfile
    profile = StreamProfile(
        stream_name=stream_name,
        profiled_at=datetime.now(timezone.utc).isoformat(),
        total_events_sampled=len(sample),
        parse_success_rate=round(parse_success_rate, 4),
        discovery_method=method,
        sub_schemas=sub_schemas,
        profile_model=model,
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
            inference_model=model,
            inference_confidence=primary.inference_confidence,
        )
        schema_path = write_schema(compat_schema, output_dir)
        write_inference_report(compat_schema, output_dir)
        console.print(f"\n✓ Written: [green]{profile_path}[/green]")
        console.print(f"✓ Written: [green]{profile_report_path}[/green]")
        console.print(f"✓ Written: [green]{schema_path}[/green] [dim](primary cluster — for watch/plan)[/dim]")

    # Write default policy
    policy = StreamPolicy(stream=stream_name, sample_size=sample_size)
    policy_path = write_policy(policy, output_dir)
    console.print(f"✓ Written: [green]{policy_path}[/green]")


@app.command()
def watch(
    stream_path: str = typer.Argument(...),
    schema_path: Optional[str] = typer.Option(None, "--schema", help="Path to schema.yaml (auto-detected if not set)"),
    interval: int = typer.Option(30, "--interval", "-i", help="Poll interval in seconds"),
    sample_size: int = typer.Option(200, "--sample-size", "-n"),
    webhook: Optional[str] = typer.Option(None, "--webhook", "-w", help="Webhook URL for drift notifications"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
):
    """Watch stream for schema drift. Runs continuously until Ctrl+C."""
    resolved_schema = schema_path or _auto_detect_schema(stream_path, "schemas")
    if not resolved_schema:
        console.print(
            f"[red]No schema.yaml found for {stream_path}. "
            "Run 'streamforge init' first or pass --schema.[/red]"
        )
        raise typer.Exit(1)

    stream_name = Path(stream_path).name
    policy = load_policy("schemas", stream_name)

    # CLI flags override policy
    effective_interval = interval if interval != 30 else policy.poll_interval_seconds
    effective_sample = sample_size if sample_size != 200 else policy.sample_size
    effective_webhook = webhook or policy.webhook_url

    from .drift_detector import watch_stream
    watch_stream(stream_path, resolved_schema, effective_interval, effective_sample, effective_webhook)


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
def plan(
    stream_path: str = typer.Argument(...),
    schema_path: Optional[str] = typer.Option(None, "--schema"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    sample_size: int = typer.Option(200, "--sample-size", "-n"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url"),
):
    """One-shot drift check. Like 'terraform plan' — shows drift without persisting."""
    resolved_schema = schema_path or _auto_detect_schema(stream_path, output_dir)
    if not resolved_schema:
        console.print(
            f"[red]No schema.yaml found. Run 'streamforge init' first or pass --schema.[/red]"
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

    drift_report = detect_drift(baseline, sample, stream_name)

    if drift_report is None:
        console.print(Panel("[green]✓ No drift detected — schema is clean.[/green]", expand=False))
        return

    # Print drift summary
    tier_colors = {DriftTier.TIER_1: "yellow", DriftTier.TIER_2: "orange3", DriftTier.TIER_3: "red"}
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

        if d.drift_type == "type_changed":
            detail = f"{d.previous_type.value} → {d.observed_type.value} ({d.affected_event_rate:.0%} of events)"
        elif d.drift_type == "field_removed":
            detail = f"field removed (was {d.previous_presence_rate:.0%} present, now {d.observed_presence_rate:.0%})"
        elif d.drift_type == "field_added":
            detail = f"new {'required' if (d.observed_presence_rate or 0) >= 0.8 else 'optional'} field (not in baseline schema)"
        elif d.drift_type == "new_pii":
            detail = f"new PII field detected"
        elif d.drift_type == "enum_changed":
            detail = f"new enum values detected ({d.affected_event_rate:.0%} of events)"
        elif d.drift_type == "presence_drop":
            detail = f"presence rate dropped {d.previous_presence_rate:.0%} → {d.observed_presence_rate:.0%}"
        else:
            detail = d.drift_type

        console.print(f"  {tier_label} [cyan]{d.field_path}[/cyan] — {detail}")

    # Save drift report
    report_path = write_drift_report(drift_report, "drift_reports")
    console.print(f"\nReport saved: [green]{report_path}[/green]")

    # Policy: block on Tier 3 if configured
    highest = drift_report.highest_tier.value
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
    from collections import Counter

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
        console.print(f"\n[dim]Single schema stream (no distinct event types detected)[/dim]")

    import re as _re

    def _quick_type(values: list) -> str:
        if not values:
            return "null"
        counts: dict[str, int] = {}
        for v in values[:50]:
            if isinstance(v, bool): t = "boolean"
            elif isinstance(v, int):
                t = "timestamp_epoch_ms" if 1_000_000_000_000 <= v <= 9_999_999_999_999 else "integer"
            elif isinstance(v, float): t = "float"
            elif isinstance(v, list): t = "array"
            elif isinstance(v, dict): t = "object"
            elif isinstance(v, str):
                if _re.match(r'^\d{4}-\d{2}-\d{2}T', v): t = "timestamp_iso8601"
                elif _re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', v, _re.I): t = "uuid"
                elif _re.match(r'^[^@]+@[^@]+\.[^@]+$', v): t = "email"
                else: t = "string"
            else: t = "null"
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
            distinct = len(set(str(v) for v in non_null[:200]))
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
    import subprocess, sys
    ui_script = Path(__file__).parent.parent / "streamforge_ui.py"
    if not ui_script.exists():
        console.print("[red]streamforge_ui.py not found.[/red]")
        raise typer.Exit(1)
    console.print(f"Opening dashboard at [cyan]http://localhost:{port}[/cyan]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ui_script), f"--server.port={port}", "--server.headless=false"])


if __name__ == "__main__":
    app()
