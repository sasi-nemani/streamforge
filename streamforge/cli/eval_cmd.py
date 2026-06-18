"""`streamforge eval` — score schema inference and drift detection against
hand-labeled ground truth, with confidence calibration. Makes the system
measurable: this is the command you run on stage / in CI to PROVE it works.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

eval_app = typer.Typer(help="Evaluate inference & drift detection against labeled benchmarks.")


def _fmt_prf(prf) -> str:
    return f"{prf.precision:.2f} / {prf.recall:.2f} / [bold]{prf.f1:.2f}[/bold]"


def _scorecard_to_dict(sc) -> dict:
    return {
        "stream": sc.stream,
        "inference_path": sc.inference_path,
        "seed": sc.seed,
        "schema": {
            "type_precision": sc.schema.type_prf.precision,
            "type_recall": sc.schema.type_prf.recall,
            "type_f1": sc.schema.type_prf.f1,
            "type_accuracy": sc.schema.type_accuracy,
            "pii_precision": sc.schema.pii_prf.precision,
            "pii_recall": sc.schema.pii_prf.recall,
            "pii_f1": sc.schema.pii_prf.f1,
            "n_truth": sc.schema.n_truth,
            "n_inferred": sc.schema.n_inferred,
        },
        "drift": {
            "precision": sc.drift.prf.precision,
            "recall": sc.drift.prf.recall,
            "f1": sc.drift.prf.f1,
            "detection_latency_events": sc.drift.detection_latency_events,
            "fpr_null": sc.drift.fpr_null,
            "scenarios": [{"scenario": lbl, "f1": f1} for lbl, f1 in sc.scenarios],
        },
        "calibration": {"ece": sc.calibration.ece, "n_samples": sc.calibration.n_samples},
    }


def evaluate(
    stream: str = typer.Argument(
        None, help="Benchmark stream to score (default: all labeled benchmarks)."
    ),
    seed: int = typer.Option(42, "--seed", help="Injection seed (reproducible)."),
    json_out: str = typer.Option(
        None, "--json", help="Write the scored results to this JSON path."
    ),
    quiet_logs: bool = typer.Option(
        True, "--quiet-logs/--show-logs", help="Suppress audit/info logs during scoring."
    ),
) -> None:
    """Score inference + drift against ground truth and print a scorecard."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from streamforge.eval.benchmark import available_benchmarks
    from streamforge.eval.runner import run_benchmark

    console = Console()

    if quiet_logs:
        logging.disable(logging.CRITICAL)

    streams = [stream] if stream else available_benchmarks()
    if not streams:
        console.print("[red]No benchmarks found under eval/benchmarks/.[/red]")
        raise typer.Exit(1)

    results = []
    for name in streams:
        try:
            sc = run_benchmark(name, seed=seed)
        except (FileNotFoundError, KeyError) as exc:
            console.print(f"[red]Cannot score {name!r}: {exc}[/red]")
            raise typer.Exit(1) from exc
        results.append(sc)

        path_tag = (
            "[green]LLM[/green]" if sc.inference_path == "llm"
            else "[yellow]statistical (offline)[/yellow]"
        )
        table = Table(title=None, show_header=True, header_style="bold cyan", box=None)
        table.add_column("Metric")
        table.add_column("P / R / F1", justify="right")
        table.add_column("Detail", justify="right")
        table.add_row(
            "Schema — field detection", _fmt_prf(sc.schema.type_prf),
            f"type-acc {sc.schema.type_accuracy:.0%}  ({sc.schema.n_inferred} inferred / {sc.schema.n_truth} truth)",
        )
        table.add_row("Schema — PII detection", _fmt_prf(sc.schema.pii_prf), "")
        lat = sc.drift.detection_latency_events
        table.add_row(
            "Drift detection", _fmt_prf(sc.drift.prf),
            f"latency {lat}ev  ·  FPR-null {sc.drift.fpr_null:.1%}",
        )
        ece = sc.calibration.ece
        cal_tag = "well-calibrated" if ece <= 0.10 else ("fair" if ece <= 0.20 else "poor")
        table.add_row("Confidence calibration", f"ECE {ece:.3f}", f"{cal_tag}  (n={sc.calibration.n_samples})")

        console.print(Panel(table, title=f"[bold]{sc.stream}[/bold]  ·  inference path: {path_tag}  ·  seed {sc.seed}", border_style="cyan"))

        sc_table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2, 0, 0))
        sc_table.add_column("Injected drift scenario")
        sc_table.add_column("Detected?", justify="left")
        for label, f1 in sc.scenarios:
            mark = "[green]✓ caught[/green]" if f1 >= 0.99 else (
                f"[yellow]~ partial (F1 {f1})[/yellow]" if f1 > 0 else "[red]✗ missed[/red]"
            )
            sc_table.add_row(label, mark)
        console.print(sc_table)
        console.print()

    if json_out:
        payload = {"seed": seed, "streams": [_scorecard_to_dict(s) for s in results]}
        Path(json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[dim]Scored results written to {json_out}[/dim]")
