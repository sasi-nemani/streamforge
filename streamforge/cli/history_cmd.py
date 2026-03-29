"""History subcommand group: snapshot, diff, velocity, propose."""

import logging
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ._helpers import _stream_name, console

logger = logging.getLogger(__name__)

history_app = typer.Typer(
    name="history",
    help="Schema history — snapshot, diff, velocity trends, and baseline proposals",
    add_completion=False,
)


def _resolve_snapshot_path(output_dir: str, stream_name: str, date_spec: str) -> Path:
    """
    Resolve a snapshot date specifier to an absolute snapshot directory path.

    Accepts:
      "latest"    -- most recent snapshot
      "oldest"    -- first snapshot
      "YYYY-MM-DD" -- specific date
    """
    from ..history import list_snapshots

    snaps = list_snapshots(output_dir, stream_name)
    if not snaps:
        msg = f"No snapshots found for {stream_name}. Run 'streamforge history snapshot' first."
        raise typer.BadParameter(msg)

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
    from ..history import write_snapshot

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
    left: str = typer.Option("oldest", "--left", "-l",
                            help="Left date YYYY-MM-DD, 'oldest', or 'latest'"),
    right: str = typer.Option("latest", "--right", "-r",
                              help="Right date YYYY-MM-DD or 'latest'"),
    output_dir: str = typer.Option("schemas", "--output", "-o"),
    save: bool = typer.Option(True, "--save/--no-save",
                              help="Write diff.md to left snapshot directory"),
):
    """Compare two profile.yaml snapshots and show what changed."""
    from ..history import diff_profiles, list_snapshots, write_diff_report

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
    from ..history import compute_velocity, list_snapshots, write_velocity_report

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
        help="Auto-apply high-confidence proposals (>=90%) to schema.yaml. Always creates a backup first.",
    ),
):
    """Generate adaptive baseline update proposals from schema history."""
    from ..history import compute_velocity, propose_baseline_updates, write_proposal_report

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
    then renames -- crash during write leaves the original intact.
    Creates schema.yaml.bak before any modification.
    """
    import shutil as _shutil

    from ..models import ProposalAction
    from ..schema_writer import load_schema, write_schema

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
