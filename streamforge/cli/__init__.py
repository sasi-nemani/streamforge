"""StreamForge CLI package — assembles all command modules into one Typer app."""

import os
from pathlib import Path

import typer

app = typer.Typer(
    name="streamforge",
    help="StreamForge — AI-native schema inference and drift detection for event streams",
    add_completion=True,
)

# ---------------------------------------------------------------------------
# Logging bootstrap (must run before any command)
# ---------------------------------------------------------------------------
from ..logging_config import configure as _configure_logging

_log_dir = os.environ.get("STREAMFORGE_LOG_DIR")
_log_file = str(Path(_log_dir) / "streamforge.log") if _log_dir else None
if _log_dir:
    Path(_log_dir).mkdir(parents=True, exist_ok=True)
_configure_logging(
    level=os.environ.get("STREAMFORGE_LOG_LEVEL", "WARNING"),
    fmt=os.environ.get("STREAMFORGE_LOG_FMT", "human"),
    log_file=_log_file,
)

# ---------------------------------------------------------------------------
# Register commands from init_cmd
# ---------------------------------------------------------------------------
from .init_cmd import discover, init, kafka_ping

app.command()(init)
app.command(name="kafka-ping")(kafka_ping)
app.command()(discover)

# ---------------------------------------------------------------------------
# Register commands from watch_cmd
# ---------------------------------------------------------------------------
from .watch_cmd import watch

app.command()(watch)

# ---------------------------------------------------------------------------
# Register commands from schema_cmd
# ---------------------------------------------------------------------------
from .schema_cmd import export, plan, profile, report, validate

app.command()(plan)
app.command()(profile)
app.command()(validate)
app.command()(report)
app.command()(export)

# ---------------------------------------------------------------------------
# Register commands from ops_cmd
# ---------------------------------------------------------------------------
from .ops_cmd import accept, consumers, demo, generate, incident_report, roi, status, suppress

app.command()(generate)
app.command()(status)
app.command()(accept)
app.command()(suppress)
app.command()(consumers)
app.command()(demo)
app.command(name="incident-report")(incident_report)
app.command()(roi)

# ---------------------------------------------------------------------------
# Register the history subcommand group
# ---------------------------------------------------------------------------
from .history_cmd import history_app

app.add_typer(history_app, name="history")

# ---------------------------------------------------------------------------
# Register the eval command (benchmark scorecard)
# ---------------------------------------------------------------------------
from .eval_cmd import evaluate

app.command(name="eval")(evaluate)

# ---------------------------------------------------------------------------
# ui command (kept inline — tiny)
# ---------------------------------------------------------------------------

@app.command()
def ui(
    port: int = typer.Option(8501, "--port", "-p"),
):
    """Launch the visual dashboard (Streamlit)."""
    import subprocess
    import sys

    from rich.console import Console

    console = Console()
    ui_script = Path(__file__).resolve().parent.parent / "ui.py"
    if not ui_script.exists():
        console.print("[red]streamforge/ui.py not found.[/red]")
        raise typer.Exit(1)
    console.print(f"Opening dashboard at [cyan]http://localhost:{port}[/cyan]")
    cmd = [sys.executable, "-m", "streamlit", "run", str(ui_script),
           f"--server.port={port}", "--server.headless=false"]
    subprocess.run(cmd)


# ---------------------------------------------------------------------------
# Cache subcommand group (Field Type RAG Registry)
# ---------------------------------------------------------------------------

cache_app = typer.Typer(help="Manage the field type registry cache.")


@cache_app.command(name="stats")
def cache_stats():
    """Show field type registry statistics."""
    from rich.console import Console
    from rich.table import Table

    from ..field_registry import FieldTypeRegistry

    console = Console()
    registry = FieldTypeRegistry.load()
    s = registry.stats()

    table = Table(title="Field Type Registry", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total entries", str(s["total_entries"]))
    table.add_row("Streams covered", str(s["streams_covered"]))
    console.print(table)


@cache_app.command(name="clear")
def cache_clear():
    """Clear the field type registry."""
    from rich.console import Console

    from ..field_registry import DEFAULT_REGISTRY_PATH

    console = Console()
    if DEFAULT_REGISTRY_PATH.exists():
        DEFAULT_REGISTRY_PATH.unlink()
        console.print("[green]Field type registry cleared.[/green]")
    else:
        console.print("No registry file found.")


app.add_typer(cache_app, name="cache")

__all__ = ["app"]
