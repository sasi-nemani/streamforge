# StreamForge Live Taps

Three scripts that pull live public data streams and write them as NDJSON files that StreamForge can infer schemas from and watch for drift.

No API keys required for any of these.

These are the fastest way to demo that StreamForge is source-agnostic without needing Kafka on day one.

---

## Wikipedia — live edits

Streams every edit made to Wikipedia in real time via the Wikimedia SSE feed.

```bash
# Collect 200 English Wikipedia article edits
python taps/wikipedia.py --max 200

# Then infer the schema
streamforge init events/wikipedia/live

# Watch for drift continuously
streamforge watch events/wikipedia/live --interval 15
```

**What you see:** Every time someone edits a Wikipedia article — the title, editor username, edit size, timestamp. Great for showing schema stability on a real production event stream.

**Options:**
```
--wiki    en.wikipedia.org     Wiki to filter (default: English)
--output  events/wikipedia/live Output folder
--max     200                   Stop after N events (0 = run forever)
```

---

## Coinbase — live crypto trades

Streams real-time price ticks for BTC, ETH, and SOL from the public Coinbase Exchange WebSocket.

```bash
# Collect 200 trade ticks
python taps/coinbase.py --max 200

# Profile the fields (price, volume, bid/ask spread)
streamforge profile events/coinbase/live

# Infer full schema
streamforge init events/coinbase/live
```

**What you see:** Live bid/ask prices, trade sizes, 24h volume. Good for showing how StreamForge handles numeric fields with high cardinality and detects format drift (e.g. if price format changes from string to float).

**Options:**
```
--products  BTC-USD,ETH-USD,SOL-USD  Products to subscribe to
--output    events/coinbase/live      Output folder
--max       200                        Stop after N events
```

---

## OpenSky — live flight positions

Polls the OpenSky Network API for real-time aircraft positions worldwide (or within a bounding box).

```bash
# Collect ~500 flight position records (3-4 polls)
python taps/opensky.py --max 500

# UK airspace only
python taps/opensky.py --bbox 49 -11 61 2 --max 300

# Infer schema from flight data
streamforge init events/opensky/live
```

**What you see:** Live aircraft positions — callsign, country, lat/lon, altitude, speed, heading. Great for showing StreamForge handles geospatial data and mixed-presence fields (not all aircraft report all fields).

**Options:**
```
--output  events/opensky/live            Output folder
--max     500                             Stop after N records
--bbox    LAT_MIN LON_MIN LAT_MAX LON_MAX  Filter to a region
```

Common bounding boxes:
- UK: `--bbox 49 -11 61 2`
- US: `--bbox 24 -125 50 -65`
- Europe: `--bbox 35 -10 70 40`

---

## Demo flow (all three)

Run this to collect data from all three streams simultaneously:

```bash
# Terminal 1 — collect 200 Wikipedia edits (~2 min)
python taps/wikipedia.py --max 200

# Terminal 2 — collect 200 Coinbase ticks (~1 min)
python taps/coinbase.py --max 200

# Terminal 3 — collect 300 flight positions (~1 min)
python taps/opensky.py --max 300
```

Then infer schemas and open the dashboard:

```bash
streamforge init events/wikipedia/live
streamforge init events/coinbase/live
streamforge init events/opensky/live

streamforge ui
```

All three streams appear in the dashboard sidebar and give you a visually varied fleet:

- `wikipedia/live` → text-heavy content events
- `coinbase/live` → numeric market data
- `opensky/live` → telemetry and geospatial data

## Recommended pitch demo

If you want one clean flow for a live meeting:

```bash
# 1. Collect data in separate terminals
python3 taps/wikipedia.py --max 200
python3 taps/coinbase.py --max 200
python3 taps/opensky.py --max 300

# 2. Infer contracts
streamforge init events/wikipedia/live
streamforge init events/coinbase/live
streamforge init events/opensky/live

# 3. Launch dashboard
streamforge ui
```

What to say while this runs:

1. StreamForge is not tied to a single broker or registry.
2. The same contract engine works across editorial events, market ticks, and flight telemetry.
3. The output is not just a dashboard; it is a Git-committable contract plus continuous enforcement.

---

## Notes

- **Rate limits:** OpenSky allows ~10 requests/minute without auth. The tap polls every 15s (4/min) — well within limits.
- **Live output folder:** Files written to `events/*/live/` are excluded from git (see `.gitignore`). Only the inferred schemas are committed.
- **Drift simulation:** To demo drift on a live stream, run `watch` on one stream while the tap is running. Wikipedia edits and Coinbase ticks naturally vary in field presence, which will surface as Tier 1 drift over time.
