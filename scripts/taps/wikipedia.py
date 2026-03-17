"""
Wikipedia Recent Changes tap — streams live edits as NDJSON.

Connects to the Wikimedia SSE stream (no auth required).
Writes events to an output folder that StreamForge can watch.

Usage:
    python taps/wikipedia.py                          # defaults
    python taps/wikipedia.py --max 200                # stop after 200 events
    python taps/wikipedia.py --wiki de.wikipedia.org  # German Wikipedia
    python taps/wikipedia.py --output events/wikipedia/live

Then in another terminal:
    streamforge init  events/wikipedia/live
    streamforge watch events/wikipedia/live --interval 10
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
EVENTS_PER_FILE = 500


def _output_path(output_dir: Path, file_index: int) -> Path:
    return output_dir / f"events_{file_index:04d}.ndjson"


def _flatten(event: dict) -> dict:
    """Flatten the Wikimedia event to a clean, consistent shape."""
    length = event.get("length") or {}
    revision = event.get("revision") or {}
    return {
        "event_type":     "wiki_edit",
        "wiki":           event.get("wiki", ""),
        "server_name":    event.get("server_name", ""),
        "title":          event.get("title", ""),
        "namespace":      event.get("namespace", 0),
        "change_type":    event.get("type", ""),          # edit | new | categorize | log
        "user":           event.get("user", ""),
        "bot":            event.get("bot", False),
        "minor":          event.get("minor", False),
        "comment":        (event.get("comment") or "")[:200],
        "length_old":     length.get("old"),
        "length_new":     length.get("new"),
        "revision_old":   revision.get("old"),
        "revision_new":   revision.get("new"),
        "timestamp":      event.get("timestamp"),          # unix epoch seconds
        "ingested_at":    datetime.now(timezone.utc).isoformat(),
    }


def run(output_dir: Path, wiki_filter: str, max_events: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    file_index = 0
    count = 0
    file_count_in_current = 0
    current_file = _output_path(output_dir, file_index)
    fh = open(current_file, "a", encoding="utf-8")

    print(f"Connecting to Wikimedia SSE stream...")
    print(f"Filter: {wiki_filter or 'all wikis'}  |  Output: {output_dir}  |  Max: {max_events or '∞'}")
    print("Press Ctrl+C to stop.\n")

    try:
        headers = {"User-Agent": "StreamForge/0.1 (https://github.com/nskq4b6gmv-rgb/streamforge-mvp; schema-demo-tap)"}
        with httpx.Client(timeout=None, headers=headers) as client:
            with client.stream("GET", STREAM_URL) as response:
                response.raise_for_status()
                data_buf = ""
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data_buf = line[5:].strip()
                        continue
                    if not (line == "" and data_buf):
                        continue

                    # We have a complete SSE event — parse it
                    try:
                        raw = json.loads(data_buf)
                    except json.JSONDecodeError:
                        data_buf = ""
                        continue
                    data_buf = ""

                    # Filter by wiki if requested
                    if wiki_filter and raw.get("server_name", "") != wiki_filter:
                        continue

                    # Only keep article namespace edits
                    if raw.get("namespace", -1) != 0:
                        continue

                    event = _flatten(raw)
                    fh.write(json.dumps(event) + "\n")
                    fh.flush()
                    count += 1
                    file_count_in_current += 1

                    title = event["title"][:40]
                    user = event["user"][:20]
                    print(f"  [{count:>5}] {title:<42} by {user}", end="\r")

                    if file_count_in_current >= EVENTS_PER_FILE:
                        fh.close()
                        print(f"\n  → Rotated: {current_file.name} ({file_count_in_current} events)")
                        file_index += 1
                        file_count_in_current = 0
                        current_file = _output_path(output_dir, file_index)
                        fh = open(current_file, "a", encoding="utf-8")

                    if max_events and count >= max_events:
                        break

    except KeyboardInterrupt:
        pass
    finally:
        fh.close()
        print(f"\n\nDone. {count} events written to {output_dir}/")
        print(f"Run: streamforge init {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream Wikipedia edits to NDJSON files")
    parser.add_argument("--wiki",   default="en.wikipedia.org", help="Wiki server name filter (default: en.wikipedia.org)")
    parser.add_argument("--output", default="events/wikipedia/live", help="Output directory")
    parser.add_argument("--max",    type=int, default=0, help="Stop after N events (0 = unlimited)")
    args = parser.parse_args()

    run(
        output_dir=Path(args.output),
        wiki_filter=args.wiki,
        max_events=args.max,
    )


if __name__ == "__main__":
    main()
