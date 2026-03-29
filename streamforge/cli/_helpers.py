"""Shared helper functions used across CLI command modules."""

import os
from pathlib import Path

import typer
from rich.console import Console

console = Console()

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
            "[red]No LLM API key found.[/red]\n\n"
            "  Set GROQ_API_KEY in demo/.env  (recommended):\n"
            "    echo 'GROQ_API_KEY=gsk_...' >> demo/.env\n\n"
            "  Or export directly:\n"
            "    export GROQ_API_KEY=gsk_...\n\n"
            "  Get a free key at: https://console.groq.com\n"
            "  Or set OPENAI_API_KEY / LLM_API_KEY for other providers."
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
