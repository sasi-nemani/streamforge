"""
Coinbase trades tap — streams live ticker data as NDJSON.

Connects to the public Coinbase Exchange WebSocket feed (no auth required).
Writes ticker events to an output folder that StreamForge can watch.

Usage:
    python taps/coinbase.py                             # BTC-USD, ETH-USD, SOL-USD
    python taps/coinbase.py --products BTC-USD,ETH-USD
    python taps/coinbase.py --max 200
    python taps/coinbase.py --output events/coinbase/live

Then in another terminal:
    streamforge init    events/coinbase/live
    streamforge profile events/coinbase/live
    streamforge watch   events/coinbase/live --interval 10
"""

import argparse
import asyncio
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

import certifi
import websockets

WS_URL = "wss://ws-feed.exchange.coinbase.com"
EVENTS_PER_FILE = 500
DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]


def _output_path(output_dir: Path, file_index: int) -> Path:
    return output_dir / f"events_{file_index:04d}.ndjson"


def _flatten_ticker(msg: dict) -> dict:
    """Normalise a Coinbase ticker message to a consistent shape."""
    return {
        "event_type":   "trade_tick",
        "product_id":   msg.get("product_id", ""),
        "price":        _float(msg.get("price")),
        "open_24h":     _float(msg.get("open_24h")),
        "high_24h":     _float(msg.get("high_24h")),
        "low_24h":      _float(msg.get("low_24h")),
        "volume_24h":   _float(msg.get("volume_24h")),
        "volume_30d":   _float(msg.get("volume_30d")),
        "best_bid":     _float(msg.get("best_bid")),
        "best_ask":     _float(msg.get("best_ask")),
        "side":         msg.get("side", ""),       # buy | sell
        "last_size":    _float(msg.get("last_size")),
        "trade_id":     msg.get("trade_id"),
        "time":         msg.get("time", ""),       # ISO8601
        "ingested_at":  datetime.now(timezone.utc).isoformat(),
    }


def _float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


async def run(output_dir: Path, products: list[str], max_events: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    file_index = 0
    count = 0
    file_count_in_current = 0
    current_file = _output_path(output_dir, file_index)

    subscribe_msg = json.dumps({
        "type": "subscribe",
        "product_ids": products,
        "channels": ["ticker"],
    })

    print(f"Connecting to Coinbase WebSocket...")
    print(f"Products: {', '.join(products)}  |  Output: {output_dir}  |  Max: {max_events or '∞'}")
    print("Press Ctrl+C to stop.\n")

    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        async with websockets.connect(WS_URL, ssl=ssl_ctx) as ws:
            await ws.send(subscribe_msg)

            # Confirm subscription
            resp = json.loads(await ws.recv())
            if resp.get("type") == "error":
                print(f"Error: {resp.get('message')}", file=sys.stderr)
                return

            with open(current_file, "a", encoding="utf-8") as fh:
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)

                    if msg.get("type") != "ticker":
                        continue

                    event = _flatten_ticker(msg)

                    fh.write(json.dumps(event) + "\n")
                    fh.flush()
                    count += 1
                    file_count_in_current += 1

                    product = event["product_id"]
                    price = event["price"] or 0
                    print(f"  [{count:>5}] {product}  ${price:>12,.2f}", end="\r")

                    # Rotate file
                    if file_count_in_current >= EVENTS_PER_FILE:
                        print(f"\n  → Rotated: {current_file.name} ({file_count_in_current} events)")
                        file_index += 1
                        file_count_in_current = 0
                        current_file = _output_path(output_dir, file_index)
                        fh.close()
                        fh = open(current_file, "a", encoding="utf-8")

                    if max_events and count >= max_events:
                        break

    except KeyboardInterrupt:
        pass

    print(f"\n\nDone. {count} events written to {output_dir}/")
    print(f"Run: streamforge init {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream Coinbase ticker data to NDJSON files")
    parser.add_argument("--products", default=",".join(DEFAULT_PRODUCTS),
                        help="Comma-separated product IDs (default: BTC-USD,ETH-USD,SOL-USD)")
    parser.add_argument("--output",   default="events/coinbase/live", help="Output directory")
    parser.add_argument("--max",      type=int, default=0, help="Stop after N events (0 = unlimited)")
    args = parser.parse_args()

    asyncio.run(run(
        output_dir=Path(args.output),
        products=[p.strip() for p in args.products.split(",")],
        max_events=args.max,
    ))


if __name__ == "__main__":
    main()
