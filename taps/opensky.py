"""
OpenSky Network tap — polls live flight state vectors as NDJSON.

Uses the public OpenSky REST API (no auth, 10 requests/minute limit).
Polls every 15 seconds and writes each response as individual flight events.

Usage:
    python taps/opensky.py                            # all flights worldwide
    python taps/opensky.py --max 500                  # stop after 500 flight records
    python taps/opensky.py --output events/opensky/live
    python taps/opensky.py --bbox 49 -11 61 2         # UK bounding box

Then in another terminal:
    streamforge init    events/opensky/live
    streamforge watch   events/opensky/live --interval 30

Bounding box format: --bbox lat_min lon_min lat_max lon_max
Common bboxes:
    UK:        49 -11 61 2
    US:        24 -125 50 -65
    Europe:    35 -10 70 40
    Australia: -45 110 -10 155
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

API_URL = "https://opensky-network.org/api/states/all"
POLL_INTERVAL_SECONDS = 15
EVENTS_PER_FILE = 500

# OpenSky state vector field order (from API docs)
STATE_FIELDS = [
    "icao24", "callsign", "origin_country", "time_position",
    "last_contact", "longitude", "latitude", "baro_altitude",
    "on_ground", "velocity", "true_track", "vertical_rate",
    "sensors", "geo_altitude", "squawk", "spi", "position_source",
]


def _output_path(output_dir: Path, file_index: int) -> Path:
    return output_dir / f"events_{file_index:04d}.ndjson"


def _flatten_state(state: list, poll_time: int) -> dict:
    """Convert a state vector array to a named dict."""
    d = dict(zip(STATE_FIELDS, state))
    return {
        "event_type":       "flight_position",
        "icao24":           d.get("icao24", ""),
        "callsign":         (d.get("callsign") or "").strip(),
        "origin_country":   d.get("origin_country", ""),
        "longitude":        d.get("longitude"),
        "latitude":         d.get("latitude"),
        "baro_altitude_m":  d.get("baro_altitude"),      # metres
        "geo_altitude_m":   d.get("geo_altitude"),
        "velocity_ms":      d.get("velocity"),            # m/s
        "true_track_deg":   d.get("true_track"),          # degrees (0=N, 90=E)
        "vertical_rate_ms": d.get("vertical_rate"),       # m/s, negative = descending
        "on_ground":        d.get("on_ground", False),
        "squawk":           d.get("squawk"),
        "time_position":    d.get("time_position"),       # unix timestamp
        "poll_time":        poll_time,                    # when we fetched this
        "ingested_at":      datetime.now(timezone.utc).isoformat(),
    }


def run(output_dir: Path, bbox: list[float] | None, max_events: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    file_index = 0
    total_count = 0
    file_count_in_current = 0
    current_file = _output_path(output_dir, file_index)

    params = {}
    if bbox:
        params = {
            "lamin": bbox[0], "lomin": bbox[1],
            "lamax": bbox[2], "lomax": bbox[3],
        }
        area = f"bbox({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})"
    else:
        area = "worldwide"

    print(f"Polling OpenSky Network every {POLL_INTERVAL_SECONDS}s...")
    print(f"Coverage: {area}  |  Output: {output_dir}  |  Max: {max_events or '∞'}")
    print("Press Ctrl+C to stop.\n")

    try:
        with open(current_file, "a", encoding="utf-8") as fh:
            while True:
                try:
                    resp = httpx.get(API_URL, params=params, timeout=20)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, Exception) as e:
                    print(f"\n  [warn] API error: {e}. Retrying in {POLL_INTERVAL_SECONDS}s...")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                states = data.get("states") or []
                poll_time = data.get("time", int(time.time()))
                batch_count = 0

                for state in states:
                    if not state or state[5] is None or state[6] is None:
                        continue  # skip states with no position

                    event = _flatten_state(state, poll_time)
                    fh.write(json.dumps(event) + "\n")
                    fh.flush()
                    total_count += 1
                    file_count_in_current += 1
                    batch_count += 1

                    if file_count_in_current >= EVENTS_PER_FILE:
                        print(f"\n  → Rotated: {current_file.name} ({file_count_in_current} events)")
                        fh.close()
                        file_index += 1
                        file_count_in_current = 0
                        current_file = _output_path(output_dir, file_index)
                        fh = open(current_file, "a", encoding="utf-8")

                    if max_events and total_count >= max_events:
                        break

                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] {batch_count:>5} aircraft tracked  |  {total_count:>6} total events written", end="\r")

                if max_events and total_count >= max_events:
                    break

                time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        pass

    print(f"\n\nDone. {total_count} events written to {output_dir}/")
    print(f"Run: streamforge init {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll OpenSky flight positions to NDJSON files")
    parser.add_argument("--output", default="events/opensky/live", help="Output directory")
    parser.add_argument("--max",    type=int, default=0, help="Stop after N flight records (0 = unlimited)")
    parser.add_argument("--bbox",   type=float, nargs=4,
                        metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                        help="Bounding box filter. Example: --bbox 49 -11 61 2 (UK)")
    args = parser.parse_args()

    run(
        output_dir=Path(args.output),
        bbox=args.bbox,
        max_events=args.max,
    )


if __name__ == "__main__":
    main()
