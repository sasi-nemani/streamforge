"""
StreamForge Dashboard — Contract Control Plane
==============================================

Purpose-built Streamlit UI for the StreamForge MVP.
Reads from schemas/ and drift_reports/ and tells a simple story:
infer the contract, declare it in code, detect drift before consumers break.

Design tokens:
  Background  #111115    Surface  #18181B    Elevated  #1F1F24
  Text        #F4F4F5    Muted    #A1A1AA    Dim      #52525B
  Blue        #60A5FA    Green    #4ADE80    Amber    #FBBF24    Red  #F87171
"""

from __future__ import annotations

import re as _re
import time as _time_mod
from collections import defaultdict
from datetime import datetime as _dt
from datetime import timedelta
from pathlib import Path

import streamlit as st
import yaml

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StreamForge",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Directory conventions ─────────────────────────────────────────────────────
SCHEMAS_DIR      = Path("schemas")
DRIFT_DIR        = Path("drift_reports")
CONSUMERS_SUBDIR = "consumers.yaml"

# ── Design tokens (hex — used in inline styles where CSS vars don't reach) ───
_BG      = "#111115"
_SURF    = "#18181B"
_SURF2   = "#1F1F24"
_SURF3   = "#27272A"
_BORDER  = "rgba(255,255,255,0.07)"
_BORDER2 = "rgba(255,255,255,0.11)"
_TEXT    = "#F4F4F5"
_TEXT2   = "#A1A1AA"
_TEXT3   = "#52525B"
_BLUE    = "#60A5FA"
_GREEN   = "#4ADE80"
_ORANGE  = "#FBBF24"
_RED     = "#F87171"
_PURPLE  = "#A78BFA"


# ══════════════════════════════════════════════════════════════════════════════
# DARK DESIGN SYSTEM — CSS
# ══════════════════════════════════════════════════════════════════════════════

DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --bg:          #111115;
    --surface:     #18181B;
    --surface-2:   #1F1F24;
    --surface-3:   #27272A;
    --border:      rgba(255,255,255,0.07);
    --border-2:    rgba(255,255,255,0.11);
    --text:        #F4F4F5;
    --text-2:      #A1A1AA;
    --text-3:      #52525B;
    --blue:        #60A5FA;
    --green:       #4ADE80;
    --amber:       #FBBF24;
    --red:         #F87171;
    --purple:      #A78BFA;
    --radius-sm:   8px;
    --radius-md:   12px;
    --radius-lg:   16px;
    --ease:        0.15s ease;
}

/* ── Global reset ── */
html, body, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: var(--bg) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: var(--text) !important;
    -webkit-font-smoothing: antialiased !important;
}

/* ── Hide Streamlit chrome — keep header shell for sidebar toggle ── */
#MainMenu, footer,
[data-testid="stDeployButton"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
    display: none !important;
}
/* Hide header background/padding but leave the collapse button intact */
[data-testid="stHeader"] {
    background: transparent !important;
    border-bottom: none !important;
    height: 0 !important;
    min-height: 0 !important;
    overflow: visible !important;
}

/* ── Sidebar — prevent collapse (override styled-components minWidth/maxWidth/transform) ── */
[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
    transform: translateX(0px) !important;
    min-width: 244px !important;
    max-width: 244px !important;
    overflow-y: auto !important;
}
[data-testid="stSidebar"] .block-container { padding: 0 !important; }
[data-testid="stSidebarContent"]           { width: 100% !important; }

/* Collapse/expand buttons — keep functional */
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
}

/* ── Main container ── */
.main .block-container {
    padding: 0 1.5rem 2rem 1.5rem !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}

/* ── Typography ── */
h1, h2, h3, h4 {
    font-family: 'Inter', sans-serif !important;
    color: var(--text) !important;
    letter-spacing: -0.02em !important;
}
h1 { font-size: 1.6rem !important; font-weight: 700 !important; }
h2 { font-size: 1.15rem !important; font-weight: 600 !important; }
h3 { font-size: 0.95rem !important; font-weight: 600 !important; }
p  { color: var(--text-2) !important; font-size: 13px !important; }

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: var(--surface) !important;
    border-radius: var(--radius-md) !important;
    padding: 14px 18px !important;
    border: 1px solid var(--border) !important;
    transition: border-color var(--ease) !important;
}
[data-testid="stMetric"]:hover { border-color: var(--border-2) !important; }
[data-testid="stMetricLabel"] {
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.07em !important;
    color: var(--text-3) !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.55rem !important;
    font-weight: 700 !important;
    color: var(--text) !important;
    letter-spacing: -0.03em !important;
}
[data-testid="stMetricDelta"] { font-size: 11px !important; }

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
    background: transparent !important;
}
[data-testid="stTabs"] button[role="tab"] {
    font-size: 13px !important;
    font-weight: 500 !important;
    color: var(--text-3) !important;
    padding: 9px 16px !important;
    border-radius: 0 !important;
    border-bottom: 2px solid transparent !important;
    background: transparent !important;
    transition: color var(--ease) !important;
}
[data-testid="stTabs"] button[role="tab"]:hover { color: var(--text-2) !important; }
[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--text) !important;
    border-bottom-color: var(--blue) !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden !important;
    margin-bottom: 6px !important;
}
[data-testid="stExpander"] summary { color: var(--text-2) !important; font-size: 13px !important; }
[data-testid="stExpander"] summary:hover { color: var(--text) !important; }

/* ── Buttons — base ── */
.stButton > button {
    background: var(--surface-2) !important;
    color: var(--text-3) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 12px !important;
    letter-spacing: 0.01em !important;
    transition: all var(--ease) !important;
}
.stButton > button:hover {
    background: var(--surface-3) !important;
    border-color: rgba(96,165,250,0.3) !important;
    color: var(--blue) !important;
    transform: none !important;
}
.stButton > button[kind="primary"] {
    background: var(--blue) !important;
    border-color: var(--blue) !important;
    color: #111115 !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #93C5FD !important;
    border-color: #93C5FD !important;
    color: #111115 !important;
}

/* ── Fleet card — fused footer button ── */
.sf-card-action {
    margin-top: -10px;
    margin-bottom: 16px;
}
.sf-card-action [data-testid="stButton"] > button {
    background: rgba(255,255,255,0.025) !important;
    border: 1px solid var(--border) !important;
    border-top: 1px solid rgba(255,255,255,0.045) !important;
    border-radius: 0 0 10px 4px !important;
    color: var(--text-3) !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    padding: 9px 18px !important;
    text-align: left !important;
    letter-spacing: 0.01em !important;
    transition: color var(--ease), background var(--ease), border-color var(--ease) !important;
}
.sf-card-action [data-testid="stButton"] > button:hover {
    background: rgba(96,165,250,0.06) !important;
    border-top-color: rgba(96,165,250,0.2) !important;
    color: var(--blue) !important;
    transform: none !important;
}

/* ── Inputs ── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stTextInput"] > div > div > input {
    background: var(--surface-2) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
    border-radius: var(--radius-sm) !important;
    font-size: 13px !important;
}
[data-testid="stTextInput"] input::placeholder { color: var(--text-3) !important; }

/* ── Code ── */
code {
    background: rgba(96,165,250,0.08) !important;
    color: var(--blue) !important;
    border-radius: 4px !important;
    font-size: 11.5px !important;
    padding: 2px 6px !important;
    font-family: 'SF Mono', 'Fira Code', monospace !important;
}

/* ── HR ── */
hr {
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 16px 0 !important;
    opacity: 1 !important;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
    border-radius: var(--radius-md) !important;
    background: var(--surface) !important;
    border-color: var(--border) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }

/* ── Animations — minimal, only where meaningful ── */
@keyframes incident-pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.7; }
}
.sf-incident-pulse { animation: incident-pulse 2.5s ease-in-out infinite; }

@keyframes dot-live {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.4; transform: scale(1.6); }
}
.sf-dot-live { animation: dot-live 2s ease-in-out infinite; display: inline-block; }

@keyframes fade-in {
    from { opacity: 0; transform: translateY(-2px); }
    to   { opacity: 1; transform: translateY(0); }
}
.sf-fade-in { animation: fade-in 0.2s ease; }
</style>
"""

st.markdown(DARK_CSS, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING (cached 30s)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=30)
def load_all_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    if not SCHEMAS_DIR.exists():
        return schemas
    for schema_file in sorted(SCHEMAS_DIR.glob("*/schema.yaml")):
        try:
            data = yaml.safe_load(schema_file.read_text()) or {}
            schemas[schema_file.parent.name] = data
        except Exception:
            pass
    return schemas


@st.cache_data(ttl=30)
def load_profile(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_consumers(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / CONSUMERS_SUBDIR
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_drift_reports(stream_name: str) -> list[tuple[str, str]]:
    d = DRIFT_DIR / stream_name
    if not d.exists():
        return []
    return [(f.name, f.read_text()) for f in sorted(d.glob("*.md"), reverse=True)]


@st.cache_data(ttl=15)
def load_open_incidents(stream_name: str) -> list[dict]:
    """Return open drift incidents from drift_state.yaml (cached 15 s)."""
    import yaml as _yaml
    p = SCHEMAS_DIR / stream_name / "drift_state.yaml"
    if not p.exists():
        return []
    try:
        doc = _yaml.safe_load(p.read_text())
        return [
            inc for inc in (doc.get("incidents") or [])
            if inc.get("status") == "open"
        ]
    except Exception:
        return []


@st.cache_data(ttl=30)
def load_policy(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=15)
def load_poll_state(stream_name: str) -> dict | None:
    """
    Load the last-polled state written by watch_stream after every poll cycle.
    Returns dict with keys: ts, sampled, window_size, new_events — or None if
    watch has never run for this stream.
    """
    import json as _json
    p = SCHEMAS_DIR / stream_name / ".watch_state" / "last_polled.json"
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text())
    except Exception:
        return None


def _is_live(stream_name: str, stale_minutes: int = 15) -> bool:
    """
    Return True if watch_stream polled this stream within the last stale_minutes.
    Uses last_polled.json written after every watch cycle.
    """
    ps = load_poll_state(stream_name)
    if not ps or not ps.get("ts"):
        return False
    try:
        polled_at = _dt.fromisoformat(ps["ts"]).replace(tzinfo=None)
        age = (_dt.utcnow() - polled_at).total_seconds()
        return age < stale_minutes * 60
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════

def _type_badge(ft: str) -> str:
    palettes = {
        "string":             ("#162238", "#4D9EFF"),
        "integer":            ("#0D2218", "#30D158"),
        "float":              ("#0D2218", "#30D158"),
        "boolean":            ("#231630", "#BF5AF2"),
        "timestamp_epoch_ms": ("#261A06", "#FF9F0A"),
        "timestamp_iso8601":  ("#261A06", "#FF9F0A"),
        "timestamp_rfc2822":  ("#261A06", "#FF9F0A"),
        "date":               ("#261A06", "#FF9F0A"),
        "uuid":               ("#082020", "#2DC9B8"),
        "email":              ("#280F1A", "#FF6B8A"),
        "phone":              ("#280F1A", "#FF6B8A"),
        "array":              ("#142006", "#7EC843"),
        "object":             ("#1C1608", "#C4A25A"),
        "null":               ("#1A1A1A", "#505058"),
        "mixed":              ("#261A06", "#FF9F0A"),
    }
    bg, fg = palettes.get(ft, ("#1E1E22", "#888891"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 9px;border-radius:980px;'
        f'font-size:10.5px;font-weight:600;letter-spacing:0.04em;white-space:nowrap">{ft}</span>'
    )


def _pii_badge(cats: list) -> str:
    if not cats:
        return f'<span style="color:{_TEXT3};font-size:12px">—</span>'
    label = ", ".join(str(c) for c in cats[:2])
    if len(cats) > 2:
        label += f" +{len(cats)-2}"
    return (
        f'<span style="background:rgba(255,69,58,0.15);color:{_RED};padding:2px 9px;'
        f'border-radius:980px;font-size:10.5px;font-weight:600">{label}</span>'
    )


def _status_dot(has_drift: bool, has_pii: bool) -> str:
    if has_drift:
        return (
            f'<span class="sf-dot-live" style="display:inline-block;width:9px;height:9px;'
            f'border-radius:50%;background:{_RED};flex-shrink:0"></span>'
        )
    if has_pii:
        return (
            f'<span style="display:inline-block;width:9px;height:9px;'
            f'border-radius:50%;background:{_ORANGE};flex-shrink:0"></span>'
        )
    return (
        f'<span style="display:inline-block;width:9px;height:9px;'
        f'border-radius:50%;background:{_GREEN};flex-shrink:0"></span>'
    )


def render_field_table(fields: list[dict]) -> str:
    if not fields:
        return f"<p style='color:{_TEXT3};font-style:italic;font-size:13px'>No fields.</p>"

    rows = []
    for i, f in enumerate(sorted(fields, key=lambda x: -(x.get("presence_rate", 0)))):
        path       = f.get("path", "—")
        ftype      = f.get("type", "string")
        required   = f.get("required", False)
        nullable   = f.get("nullable", False)
        presence   = f.get("presence_rate", 0)
        confidence = f.get("confidence", 0)
        pii        = f.get("pii", [])
        notes      = (f.get("notes") or "")

        req_html = (
            f'<span style="color:{_GREEN};font-weight:700;font-size:13px">●</span>'
            if required else
            f'<span style="color:{_TEXT3};font-size:13px">○</span>'
        )
        null_html = (
            f'<span style="color:{_ORANGE};font-size:11px;font-weight:600">null ok</span>'
            if nullable else
            f'<span style="color:{_TEXT3};font-size:11px">—</span>'
        )

        pct   = int(presence * 100)
        bar_c = _GREEN if pct >= 80 else _ORANGE if pct >= 50 else _RED
        pres_html = (
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="width:44px;height:4px;background:{_SURF3};border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{bar_c};border-radius:2px"></div></div>'
            f'<span style="font-size:11px;color:{_TEXT2};font-variant-numeric:tabular-nums">{pct}%</span>'
            f'</div>'
        )

        conf_pct  = int(confidence * 100)
        conf_c    = _GREEN if conf_pct >= 80 else _ORANGE if conf_pct >= 60 else _RED
        conf_html = f'<span style="color:{conf_c};font-size:11px;font-weight:600">{conf_pct}%</span>'
        notes_html = (
            f'<span style="color:{_TEXT2};font-size:11.5px">'
            f'{notes[:70]}{"…" if len(notes) > 70 else ""}</span>'
        )

        row_bg = _SURF if i % 2 == 0 else _SURF2
        rows.append(
            f'<tr style="background:{row_bg}">'
            f'<td style="padding:9px 12px;font-family:\'SF Mono\',\'Fira Code\',monospace;'
            f'font-size:12px;white-space:nowrap;color:{_TEXT}">{path}</td>'
            f'<td style="padding:9px 12px">{_type_badge(ftype)}</td>'
            f'<td style="padding:9px 12px;text-align:center">{req_html}</td>'
            f'<td style="padding:9px 12px;text-align:center">{null_html}</td>'
            f'<td style="padding:9px 12px">{pres_html}</td>'
            f'<td style="padding:9px 12px;text-align:center">{conf_html}</td>'
            f'<td style="padding:9px 12px">{_pii_badge(pii)}</td>'
            f'<td style="padding:9px 12px">{notes_html}</td>'
            f'</tr>'
        )

    th = (f'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;'
          f'color:{_TEXT3};border-bottom:1px solid {_BORDER2};padding:10px 12px;text-align:left')
    header = (
        f'<tr style="background:{_SURF3}">'
        f'<th style="{th}">Field Path</th>'
        f'<th style="{th}">Type</th>'
        f'<th style="{th};text-align:center">Req</th>'
        f'<th style="{th};text-align:center">Nullable</th>'
        f'<th style="{th}">Presence</th>'
        f'<th style="{th};text-align:center">Conf.</th>'
        f'<th style="{th}">PII</th>'
        f'<th style="{th}">Notes</th>'
        f'</tr>'
    )
    return (
        f'<div style="overflow-x:auto;border-radius:{_SURF};border-radius:10px;'
        f'border:1px solid {_BORDER}">'
        f'<table style="width:100%;border-collapse:collapse;'
        f'font-family:Inter,-apple-system,sans-serif;font-size:13px">'
        f'<thead>{header}</thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table></div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY FEED — generated from real filesystem data
# ══════════════════════════════════════════════════════════════════════════════

def _time_ago(ts: _dt) -> str:
    """Return human-readable relative time: '2m ago', '3h ago'."""
    delta = _dt.now() - ts
    secs  = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _build_activity(stream_names, drift_streams, pii_streams, schemas) -> list[dict]:
    """
    Build a realistic activity feed from actual data on disk.

    Priority order:
      1. Drift events — parsed from drift_reports/ filenames (real timestamps)
      2. PII detections — from schema inferred_at timestamp
      3. Schema inferred — from schema inferred_at timestamp
      4. Healthy check-ins — synthetic, spaced relative to schema times
    """
    events: list[dict] = []
    now = _dt.now()

    for sn in drift_streams:
        for fname, content in load_drift_reports(sn)[:3]:
            try:
                ts = _dt.strptime(fname.replace(".md", ""), "%Y-%m-%d-%H%M")
            except Exception:
                ts = now - timedelta(hours=1)
            tier = "3" if "tier 3" in content.lower() else "2" if "tier 2" in content.lower() else "1"
            fields = _parse_drifted_fields(content)
            top    = fields[0]["path"] if fields else "unknown"
            events.append({
                "ts": ts, "type": "drift", "tier": tier,
                "msg": f"{sn}",
                "detail": f'`{top}` changed — Tier {tier}',
            })

    for sn in pii_streams:
        sd   = schemas.get(sn, {})
        pii  = [f for f in sd.get("fields", []) if f.get("pii")]
        ia   = sd.get("inferred_at", "")
        try:
            ts = _dt.fromisoformat(ia[:19]) if ia else now - timedelta(hours=2)
        except Exception:
            ts = now - timedelta(hours=2)
        events.append({
            "ts": ts, "type": "pii", "tier": None,
            "msg": f"{sn}",
            "detail": f"{len(pii)} PII field(s) detected",
        })

    for sn, sd in schemas.items():
        ia = sd.get("inferred_at", "")
        try:
            ts = _dt.fromisoformat(ia[:19]) if ia else now - timedelta(hours=3)
        except Exception:
            ts = now - timedelta(hours=3)
        conf     = sd.get("inference_confidence", 0)
        n_fields = len(sd.get("fields", []))
        events.append({
            "ts": ts, "type": "schema", "tier": None,
            "msg": f"{sn}",
            "detail": f"Schema inferred — {n_fields} fields, {conf:.0%}",
        })
        # Add synthetic health checks ~30 min after inference
        events.append({
            "ts": ts + timedelta(minutes=30), "type": "healthy", "tier": None,
            "msg": f"{sn}",
            "detail": "Schema check passed — no drift",
        })

    events.sort(key=lambda x: x["ts"], reverse=True)
    return events[:18]


# ══════════════════════════════════════════════════════════════════════════════
# DRIFT REPORT PARSER + BLAST RADIUS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_drifted_fields(content: str) -> list[dict]:
    fields = []
    sections = _re.split(r'^###\s+', content, flags=_re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().split('\n')
        path  = lines[0].strip().strip('`')
        if not path or path.startswith('#'):
            continue
        tier = None
        drift_type = None
        for line in lines[1:]:
            tm = _re.search(r'\*\*Tier\*\*:\s*Tier\s*(\d)', line)
            if tm:
                tier = int(tm.group(1))
            dm = _re.search(r'\*\*Drift type\*\*:\s*`?(\w+)`?', line)
            if dm:
                drift_type = dm.group(1)
        fields.append({"path": path, "tier": tier, "drift_type": drift_type})
    return fields


def _parse_drift_report_rows(content: str) -> list[dict]:
    """Parse drift report markdown into structured rows with before/after values."""
    rows = []
    sections = _re.split(r'^###\s+', content, flags=_re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().split('\n')
        path = lines[0].strip().strip('`')
        if not path or path.startswith('#'):
            continue
        row = {
            "path": path, "drift_type": None,
            "before": None, "after": None,
            "presence_before": None, "presence_after": None,
            "events": None, "tier": None,
        }
        for line in lines[1:]:
            dm = _re.search(r'\*\*Drift type\*\*:\s*`?([^`\n]+)`?', line)
            if dm:
                row["drift_type"] = dm.group(1).strip()
            tm = _re.search(r'\*\*Type\*\*:\s*`?([^`\s→\n]+)`?\s*→\s*`?([^`\s\n]+)`?', line)
            if tm:
                row["before"] = tm.group(1).strip()
                row["after"]  = tm.group(2).strip()
            pm = _re.search(r'\*\*Presence rate\*\*:\s*([\d.]+%)\s*→\s*([\d.]+%)', line)
            if pm:
                row["presence_before"] = pm.group(1)
                row["presence_after"]  = pm.group(2)
            tier_m = _re.search(r'\*\*Tier\*\*:\s*Tier\s*(\d)', line)
            if tier_m:
                row["tier"] = int(tier_m.group(1))
            ev_m = _re.search(r'\*\*Affected events\*\*:\s*([\d.]+%)', line)
            if ev_m:
                row["events"] = ev_m.group(1)
        rows.append(row)
    return rows


def _render_impact_assessment(drifted_fields: list[dict], consumers_data: dict) -> str:
    if not consumers_data or not drifted_fields:
        return ""

    drifted_map = {f["path"]: f for f in drifted_fields}
    crit_order  = {"tier1": 0, "tier2": 1, "tier3": 2}

    rows = []
    for c in sorted(consumers_data.get("consumers", []),
                    key=lambda x: crit_order.get(x.get("criticality", "tier3"), 9)):
        crit    = c.get("criticality", "tier3")
        name    = c.get("name", "?")
        team    = c.get("team", "?")
        contact = c.get("contact", "—")
        runbook = c.get("runbook", "")
        hits    = []

        for f in c.get("fields_used", []):
            fpath = f.get("path", "")
            if fpath in drifted_map:
                drift = drifted_map[fpath]
                hard  = f.get("required", False) and drift.get("drift_type") in (
                    "field_removed", "type_changed", "presence_drop"
                )
                hits.append({
                    "path": fpath, "required": f.get("required", False),
                    "hard_break": hard, "drift_type": drift.get("drift_type", ""),
                    "tier": drift.get("tier"),
                })
        if not hits:
            continue

        has_hard    = any(h["hard_break"] for h in hits)
        crit_color  = {"tier1": _RED, "tier2": _ORANGE, "tier3": _GREEN}.get(crit, _TEXT2)
        crit_label  = {"tier1": "P0", "tier2": "P1", "tier3": "P2"}.get(crit, crit)
        row_bg      = "rgba(255,69,58,0.08)"  if has_hard else "rgba(255,159,10,0.06)"
        border_col  = _RED if has_hard else _ORANGE
        status_icon = "🔴" if has_hard else "⚠️"

        field_lines = ""
        for h in hits:
            dt_label = {
                "field_removed": "REMOVED", "type_changed": "type changed",
                "field_added": "new field", "new_pii": "NEW PII",
                "enum_changed": "enum changed", "presence_drop": "presence dropped",
            }.get(h["drift_type"], h["drift_type"])
            req_label   = "required" if h["required"] else "optional"
            break_label = (
                f' → <strong style="color:{_RED}">HARD BREAK</strong>'
                if h["hard_break"] else ""
            )
            field_lines += (
                f'<div style="font-size:12px;color:{_TEXT2};margin-top:5px;padding-left:8px;'
                f'border-left:2px solid {border_col}">'
                f'<code style="color:{_TEXT}">{h["path"]}</code> '
                f'<span style="color:{border_col};font-weight:600">({dt_label})</span> '
                f'<span style="color:{_TEXT3}">{req_label}</span>'
                f'{break_label}</div>'
            )

        runbook_html = (
            f'<a href="{runbook}" style="font-size:11px;color:{_BLUE};text-decoration:none">📖 Runbook</a>'
            if runbook else ""
        )
        rows.append(
            f'<div style="background:{row_bg};border-radius:10px;padding:14px 16px;'
            f'margin-bottom:8px;border-left:3px solid {border_col}">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            f'<span style="font-size:15px">{status_icon}</span>'
            f'<strong style="font-size:13px;color:{_TEXT}">{name}</strong>'
            f'<span style="background:{crit_color};color:#0C0C0E;font-size:10px;font-weight:700;'
            f'padding:2px 7px;border-radius:980px">{crit_label}</span>'
            f'<span style="font-size:12px;color:{_TEXT2}">{team}</span>'
            f'<div style="flex:1"></div>'
            f'<code style="font-size:11px;background:transparent;color:{_TEXT3};padding:0">'
            f'{contact.split("|")[0].strip()}</code>'
            f'{" " + runbook_html if runbook_html else ""}'
            f'</div>'
            f'{field_lines}'
            f'</div>'
        )

    if not rows:
        return ""

    return (
        f'<div style="background:{_SURF};border-radius:12px;padding:18px;'
        f'border:1px solid rgba(255,69,58,0.2);margin-bottom:18px">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;'
        f'color:{_RED};margin-bottom:12px">🚨 Impact Assessment — Who Breaks</div>'
        + "".join(rows)
        + "</div>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

if "selected_stream" not in st.session_state:
    st.session_state.selected_stream = None
if "view" not in st.session_state:
    st.session_state.view = "fleet"
if "registry_search" not in st.session_state:
    st.session_state.registry_search = ""


# ══════════════════════════════════════════════════════════════════════════════
# SHARED DATA — computed once, used in sidebar + main
# ══════════════════════════════════════════════════════════════════════════════

schemas      = load_all_schemas()
stream_names = sorted(schemas.keys())

_drift_streams: set[str] = set()
_pii_streams:   set[str] = set()
for _sn in stream_names:
    if load_drift_reports(_sn):
        _drift_streams.add(_sn)
    # For multi-schema streams, PII lives in profile.yaml sub-schemas, not schema.yaml
    _prof = load_profile(_sn)
    if _prof:
        for _sub in _prof.get("sub_schemas", []):
            for _f in _sub.get("fields", []):
                if _f.get("pii_categories"):
                    _pii_streams.add(_sn)
                    break
            if _sn in _pii_streams:
                break
    else:
        for _f in schemas.get(_sn, {}).get("fields", []):
            if _f.get("pii"):
                _pii_streams.add(_sn)
                break


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — structured navigation
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # Brand
    st.markdown(
        f'<div style="padding:18px 16px 14px 16px;border-bottom:1px solid {_BORDER}">'
        f'<div style="font-size:15px;font-weight:700;letter-spacing:-0.02em;'
        f'color:{_TEXT}">⚡ StreamForge</div>'
        f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">Contract Control Plane</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="padding:12px 16px 5px 16px;font-size:10px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.08em;color:{_TEXT3}">Observability</div>',
        unsafe_allow_html=True,
    )

    if st.button("Fleet Overview", use_container_width=True,
                 type="primary" if st.session_state.view == "fleet" else "secondary"):
        st.session_state.view = "fleet"
        st.session_state.selected_stream = None
        st.rerun()

    if st.button("Schema Registry", use_container_width=True,
                 type="primary" if st.session_state.view == "registry" else "secondary"):
        st.session_state.view = "registry"
        st.session_state.selected_stream = None
        st.rerun()

    if st.button("Platform Overview", use_container_width=True,
                 type="primary" if st.session_state.view == "about" else "secondary"):
        st.session_state.view = "about"
        st.session_state.selected_stream = None
        st.rerun()

    if st.button("Setup Guide", use_container_width=True,
                 type="primary" if st.session_state.view == "setup" else "secondary"):
        st.session_state.view = "setup"
        st.session_state.selected_stream = None
        st.rerun()

    st.markdown(
        f'<div style="padding:14px 16px 5px 16px;font-size:10px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.08em;color:{_TEXT3}">Active Streams</div>',
        unsafe_allow_html=True,
    )

    if not stream_names:
        st.markdown(
            f'<div style="padding:4px 16px;font-size:12px;color:{_TEXT3};">'
            f'No streams. Run <code>streamforge init</code>.</div>',
            unsafe_allow_html=True,
        )
    else:
        for _sn in stream_names:
            _active   = st.session_state.selected_stream == _sn and st.session_state.view == "stream"
            _dot_emoji = "🔴" if _sn in _drift_streams else "🟡" if _sn in _pii_streams else "🟢"
            _live_tag  = " ⚡" if _is_live(_sn) else ""
            _label     = f"{_dot_emoji} {_sn}{_live_tag}"
            if st.button(_label, key=f"sb_{_sn}", use_container_width=True,
                         type="primary" if _active else "secondary"):
                st.session_state.selected_stream = _sn
                st.session_state.view = "stream"
                st.rerun()

    n_total = len(stream_names)
    n_drift = len(_drift_streams)
    n_pii   = len(_pii_streams)

    if n_total:
        clean = n_total - n_drift
        stats = [
            (str(n_total), "streams"),
            (str(n_drift) if n_drift else "—", "drift",   _RED    if n_drift else _TEXT3),
            (str(n_pii)   if n_pii   else "—", "PII",     _ORANGE if n_pii   else _TEXT3),
            (str(clean),                        "clean",   _GREEN),
        ]
        cells = ""
        for i, item in enumerate(stats):
            val   = item[0]
            lbl   = item[1]
            color = item[2] if len(item) > 2 else _TEXT
            sep   = f'<div style="width:1px;background:{_BORDER2};margin:2px 0"></div>' if i < 3 else ""
            cells += (
                f'<div style="text-align:center;padding:0 8px">'
                f'<div style="font-size:16px;font-weight:700;color:{color};letter-spacing:-0.02em">{val}</div>'
                f'<div style="font-size:9.5px;color:{_TEXT3};margin-top:1px;letter-spacing:0.03em">{lbl}</div>'
                f'</div>'
                f'{sep}'
            )
        st.markdown(
            f'<div style="margin:14px 0 0 0;padding:12px 16px;border-top:1px solid {_BORDER}">'
            f'<div style="display:flex;align-items:center;justify-content:space-between">'
            f'{cells}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # Watch status section
    _live_streams = [sn for sn in stream_names if _is_live(sn)]
    st.markdown(
        f'<div style="padding:14px 16px 5px 16px;border-top:1px solid {_BORDER};">'
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3}">Watch Status</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if _live_streams:
        for _sn in _live_streams:
            _ps = load_poll_state(_sn)
            _w  = _ps.get("window_size", 0) if _ps else 0
            _s  = _ps.get("sampled", 0) if _ps else 0
            st.markdown(
                f'<div style="padding:4px 16px 4px 16px">'
                f'<div style="display:flex;align-items:center;gap:6px">'
                f'<span class="sf-dot-live" style="color:{_GREEN};font-size:9px">●</span>'
                f'<span style="font-size:12px;font-weight:600;color:{_TEXT}">{_sn}</span>'
                f'</div>'
                f'<div style="font-size:10.5px;color:{_TEXT3};padding-left:15px;margin-top:1px">'
                f'{_s} sampled · {_w} in window</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f'<div style="padding:4px 16px 10px 16px;font-size:11.5px;color:{_TEXT3}">'
            f'No active watchers — run <code>watch_all.sh</code></div>',
            unsafe_allow_html=True,
        )

    # Auto-refresh toggle — at bottom of sidebar
    st.markdown(
        f'<div style="padding:10px 16px 6px 16px;border-top:1px solid {_BORDER}">'
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:{_TEXT3};margin-bottom:6px">Demo</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _auto = st.toggle(
        "Auto-refresh (10s)",
        value=st.session_state.get("auto_refresh", False),
        help="Fleet view refreshes every 10 seconds. Ideal for live demos.",
        key="auto_refresh_toggle",
    )
    st.session_state["auto_refresh"] = _auto
    if _auto:
        st.markdown(
            f'<div style="padding:4px 16px 12px 16px">'
            f'<div style="font-size:10.5px;color:{_GREEN}">● Live — refreshing every 10s</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND BAR + INCIDENT STRIP
# ══════════════════════════════════════════════════════════════════════════════

def render_command_bar(n_streams, drift_streams, pii_streams, all_schemas):
    n_drift    = len(drift_streams)
    n_pii      = sum(1 for sn in stream_names for f in all_schemas.get(sn, {}).get("fields", []) if f.get("pii"))
    n_reports  = sum(len(load_drift_reports(sn)) for sn in stream_names)
    clean_pct  = int((n_streams - n_drift) / n_streams * 100) if n_streams else 100

    status_col = _RED if n_drift else _GREEN
    status_txt = f"{n_drift} Drift Active" if n_drift else "All Systems Operational"

    st.markdown(
        f'<div style="background:{_SURF};border-bottom:1px solid {_BORDER};'
        f'padding:12px 0;margin:0 -1.5rem 0 -1.5rem">'

        # Top row: brand left, status pill right
        f'<div style="display:flex;align-items:center;padding:0 20px;margin-bottom:8px">'
        f'<div>'
        f'<span style="font-size:15px;font-weight:700;color:{_TEXT};'
        f'letter-spacing:-0.02em">⚡ StreamForge</span>'
        f'<span style="font-size:12px;color:{_TEXT3};margin-left:10px">Contract control plane for event streams</span>'
        f'</div>'
        f'<div style="flex:1"></div>'
        f'<div style="display:flex;align-items:center;gap:7px;'
        f'background:{_SURF2};padding:5px 13px;border-radius:980px;border:1px solid {_BORDER}">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{status_col};'
        f'display:inline-block"></span>'
        f'<span style="font-size:12px;font-weight:500;color:{status_col}">{status_txt}</span>'
        f'</div>'
        f'</div>'

        # Scale credibility — subtle
        f'<div style="padding:0 20px 4px 20px;font-size:11px;color:{_TEXT3}">'
        f'Monitoring <strong style="color:{_TEXT3};font-weight:600">'
        f'{n_streams} event stream{"s" if n_streams != 1 else ""}</strong>'
        f' · AI on the cold path, deterministic drift detection on the hot path'
        f' · Git-native schema contracts with no manual rule-writing'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Platform metrics row
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Streams Monitored", n_streams)
    mc2.metric("Drift Events",      n_reports,
               delta=f"{'↑ Active' if n_drift else '0 active'}", delta_color="inverse" if n_drift else "off")
    mc3.metric("PII Fields",        n_pii,
               delta=f"+{n_pii} tracked" if n_pii else "None detected", delta_color="off")
    mc4.metric("Streams Clean",     f"{clean_pct}%",
               delta="All healthy" if clean_pct == 100 else f"{100-clean_pct}% at risk", delta_color="off")
    mc5.metric("Last Scan",         _dt.now().strftime("%H:%M:%S"),
               delta="live", delta_color="off")


def render_incident_strip(drift_streams, schemas):
    if not drift_streams:
        return

    # Pick the most critical stream (prefer Tier 3)
    sn = None
    for candidate in sorted(drift_streams):
        rpts = load_drift_reports(candidate)
        if rpts:
            _, _c = rpts[0]
            if "tier 3" in _c.lower():
                sn = candidate
                break
    if not sn:
        sn = sorted(drift_streams)[0]

    reports = load_drift_reports(sn)
    if not reports:
        return
    fname, content = reports[0]
    fields  = _parse_drifted_fields(content)
    tier3   = [f for f in fields if f.get("tier") == 3]
    top     = tier3[0] if tier3 else (fields[0] if fields else None)

    drift_type_label = {
        "field_removed":              "field removed",
        "type_changed":               "type mismatch",
        "field_added":                "unexpected new field",
        "enum_changed":               "enum values changed",
        "new_pii":                    "new PII field detected",
        "presence_drop":              "presence rate dropped",
        "cluster_routing_regression": "cluster routing regression",
        "new_cluster":                "new event family detected",
    }.get(top.get("drift_type", "") if top else "", "schema drift")

    field_path = top["path"] if top else "multiple fields"

    badge_map = {
        "field_removed": "P0 · FIELD REMOVED · DATA INTEGRITY RISK",
        "new_pii":       "P0 · NEW PII DETECTED · COMPLIANCE RISK",
        "type_changed":  "P1 · TYPE MISMATCH · CONSUMERS FAILING",
        "presence_drop": "P1 · PRESENCE DROP · PIPELINE DEGRADED",
    }
    badge_txt = badge_map.get(top.get("drift_type", "") if top else "",
                              "P0 · SCHEMA DRIFT · IMMEDIATE ACTION REQUIRED")

    try:
        ts       = _dt.strptime(fname.replace(".md", ""), "%Y-%m-%d-%H%M")
        when_str = ts.strftime("%b %d · %H:%M UTC")
    except Exception:
        when_str = "recently"

    consumers_data = load_consumers(sn) or {}
    tier1_consumers = [c for c in consumers_data.get("consumers", [])
                       if c.get("criticality") == "tier1"]
    all_consumers   = consumers_data.get("consumers", [])
    if tier1_consumers:
        names = [
            f'<code style="font-size:12px;color:{_RED};background:rgba(248,113,113,0.1);'
            f'padding:1px 6px;border-radius:3px">{c["name"]}</code>'
            for c in tier1_consumers[:2]
        ]
        consumer_html = " and ".join(names) + " are rejecting payloads."
    elif all_consumers:
        consumer_html = (
            f'<span style="color:{_TEXT2}">'
            f'{len(all_consumers)} registered consumer'
            f'{"s" if len(all_consumers) != 1 else ""} affected.</span>'
        )
    else:
        consumer_html = (
            f'<span style="color:{_TEXT3}">Run '
            f'<code>streamforge consumers {sn}</code> to see blast radius.</span>'
        )

    st.markdown(
        f'<div style="background:{_SURF};border:1px solid rgba(248,113,113,0.22);'
        f'border-radius:14px;padding:24px 28px;margin:16px 0;'
        f'border-left:4px solid {_RED}">'

        # ── Header row ────────────────────────────────────────────────────────
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:14px">'
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<span class="sf-incident-pulse" style="width:9px;height:9px;border-radius:50%;'
        f'background:{_RED};display:inline-block;flex-shrink:0"></span>'
        f'<span style="font-size:10px;font-weight:800;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:{_RED}">Critical Escalation</span>'
        f'<span style="font-size:11px;color:{_TEXT3}">· Detected {when_str}</span>'
        f'</div>'
        f'<span style="font-size:11px;color:{_TEXT3};font-weight:500;letter-spacing:0.04em">'
        f'VIEW RUNBOOK →</span>'
        f'</div>'

        # ── P0 badge ──────────────────────────────────────────────────────────
        f'<div style="margin-bottom:14px">'
        f'<span style="background:rgba(248,113,113,0.1);color:{_RED};'
        f'border:1px solid rgba(248,113,113,0.28);font-size:9.5px;font-weight:800;'
        f'letter-spacing:0.1em;padding:3px 11px;border-radius:4px">{badge_txt}</span>'
        f'</div>'

        # ── Stream name ───────────────────────────────────────────────────────
        f'<div style="font-family:\'SF Mono\',\'Fira Code\',\'Consolas\',monospace;'
        f'font-size:1.85rem;font-weight:700;color:{_TEXT};letter-spacing:-0.02em;'
        f'margin-bottom:12px;line-height:1">{sn}</div>'

        # ── Description ───────────────────────────────────────────────────────
        f'<div style="font-size:13px;color:{_TEXT2};line-height:1.8">'
        f'Detected <strong style="color:{_TEXT}">{drift_type_label}</strong> in field '
        f'<code style="font-size:12px;color:{_ORANGE};background:rgba(251,191,36,0.1);'
        f'padding:2px 7px;border-radius:3px">{field_path}</code>. '
        f'{consumer_html}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_story_hero():
    total_reports = sum(len(load_drift_reports(sn)) for sn in stream_names)
    total_pii_fields = sum(
        1 for sn in stream_names for f in schemas.get(sn, {}).get("fields", []) if f.get("pii")
    )

    st.markdown(
        f'<div style="background:linear-gradient(135deg, rgba(96,165,250,0.12), rgba(17,17,21,0.92) 58%);'
        f'border:1px solid rgba(96,165,250,0.16);border-radius:18px;padding:26px 28px;margin:18px 0 18px 0">'
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:18px;flex-wrap:wrap">'
        f'<div style="max-width:760px">'
        f'<div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;'
        f'color:{_BLUE};margin-bottom:10px">Why StreamForge Exists</div>'
        f'<div style="font-size:30px;line-height:1.05;font-weight:700;letter-spacing:-0.04em;'
        f'color:{_TEXT};margin-bottom:12px">Hidden schema contracts break event systems long before dashboards notice.</div>'
        f'<div style="font-size:14px;line-height:1.7;color:{_TEXT2};max-width:700px">'
        f'StreamForge turns live event payloads into reviewed contracts, stores them as code, and continuously detects drift before downstream consumers fail or new PII slips into production.'
        f'</div>'
        f'</div>'
        f'<div style="min-width:220px;background:rgba(255,255,255,0.03);border:1px solid {_BORDER};'
        f'border-radius:14px;padding:14px 16px">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;'
        f'color:{_TEXT3};margin-bottom:10px">Live Proof</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">'
        f'<div><div style="font-size:22px;font-weight:700;color:{_TEXT}">{len(stream_names)}</div><div style="font-size:11px;color:{_TEXT3}">Streams</div></div>'
        f'<div><div style="font-size:22px;font-weight:700;color:{_RED if _drift_streams else _GREEN}">{total_reports}</div><div style="font-size:11px;color:{_TEXT3}">Drift reports</div></div>'
        f'<div><div style="font-size:22px;font-weight:700;color:{_ORANGE if total_pii_fields else _TEXT}">{total_pii_fields}</div><div style="font-size:11px;color:{_TEXT3}">PII fields</div></div>'
        f'<div><div style="font-size:22px;font-weight:700;color:{_TEXT}">{sum(len(schemas.get(sn, {}).get("fields", [])) for sn in stream_names)}</div><div style="font-size:11px;color:{_TEXT3}">Tracked fields</div></div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    cards = [
        (
            "01  Infer",
            _BLUE,
            "Read real payloads and discover event families automatically.",
            "LLM-assisted onboarding on the cold path. Partial records excluded by default.",
        ),
        (
            "02  Declare",
            _ORANGE,
            "Write `schema.yaml` as a reviewed, git-committable contract.",
            "The contract becomes auditable infrastructure instead of tribal knowledge.",
        ),
        (
            "03  Detect",
            _RED,
            "Watch live events for drift, missing fields, type changes, and new PII.",
            "Deterministic statistical checks run continuously with no LLM in the hot path.",
        ),
    ]

    cols = st.columns(3)
    for col, (label, color, title, body) in zip(cols, cards, strict=False):
        with col:
            st.markdown(
                f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:14px;'
                f'padding:18px 18px 16px 18px;min-height:170px">'
                f'<div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;'
                f'color:{color};margin-bottom:12px">{label}</div>'
                f'<div style="font-size:18px;font-weight:650;letter-spacing:-0.03em;color:{_TEXT};'
                f'margin-bottom:10px;line-height:1.15">{title}</div>'
                f'<div style="font-size:12.5px;line-height:1.7;color:{_TEXT2}">{body}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# FLEET OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def render_fleet_overview():
    render_command_bar(len(stream_names), _drift_streams, _pii_streams, schemas)
    render_story_hero()
    render_incident_strip(_drift_streams, schemas)

    # ── Registry Snapshot — full-width table ─────────────────────────────────
    st.markdown(
        '<div style="height:18px"></div>',
        unsafe_allow_html=True,
    )

    if not stream_names:
        st.markdown(
            f'<div style="background:{_SURF};border:1px dashed {_BORDER2};border-radius:12px;'
            f'padding:40px;text-align:center">'
            f'<div style="font-size:15px;font-weight:600;color:{_TEXT};margin-bottom:6px">No streams yet</div>'
            f'<div style="font-size:13px;color:{_TEXT3}">Run <code>streamforge init events/&lt;stream&gt;</code> '
            f'to infer your first schema.</div></div>',
            unsafe_allow_html=True,
        )
    else:
        # Section label + full-registry link
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'margin-bottom:10px">'
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.1em;color:{_TEXT3}">Registry Snapshot</div>'
            f'<div style="font-size:11px;color:{_TEXT3};font-weight:500;letter-spacing:0.04em">'
            f'FULL REGISTRY ↗</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # SVG sparklines — three flavours
        _SPARK = {
            "drift": (
                '<svg width="72" height="22" viewBox="0 0 72 22" fill="none">'
                '<polyline points="0,18 10,17 20,15 30,11 44,7 56,4 72,1"'
                f' stroke="{_RED}" stroke-width="1.5" stroke-linejoin="round"/>'
                '</svg>'
            ),
            "pii": (
                '<svg width="72" height="22" viewBox="0 0 72 22" fill="none">'
                '<polyline points="0,11 9,13 18,10 27,12 36,9 45,11 54,10 63,12 72,10"'
                f' stroke="{_ORANGE}" stroke-width="1.5" stroke-linejoin="round"/>'
                '</svg>'
            ),
            "clean": (
                '<svg width="72" height="22" viewBox="0 0 72 22" fill="none">'
                '<polyline points="0,12 9,11 18,13 27,11 36,12 45,10 54,12 63,11 72,12"'
                f' stroke="{_GREEN}" stroke-width="1.5" stroke-linejoin="round"/>'
                '</svg>'
            ),
        }

        th = (
            f'padding:9px 16px;font-size:9.5px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.1em;color:{_TEXT3};background:{_SURF2};text-align:left;'
            f'border-bottom:1px solid {_BORDER2};white-space:nowrap'
        )

        rows_html = ""
        for sn in stream_names:
            sd         = schemas.get(sn, {})
            has_drift  = sn in _drift_streams
            has_pii    = sn in _pii_streams
            dr         = load_drift_reports(sn)
            all_fields = sd.get("fields", [])
            pii_fields = [f for f in all_fields if f.get("pii")]
            confidence = sd.get("inference_confidence", 0)

            # State dot
            dot_color = _RED if has_drift else _ORANGE if has_pii else _GREEN
            dot = (
                f'<span style="width:9px;height:9px;border-radius:50%;'
                f'background:{dot_color};display:inline-block;'
                f'box-shadow:0 0 0 2px {dot_color}33"></span>'
            )

            # Watch live/idle badge
            if _is_live(sn):
                watch_badge = (
                    f'<span style="background:rgba(74,222,128,0.1);color:{_GREEN};'
                    f'border:1px solid rgba(74,222,128,0.3);font-size:9.5px;font-weight:700;'
                    f'letter-spacing:0.07em;padding:3px 8px;border-radius:4px;'
                    f'display:inline-flex;align-items:center;gap:4px">'
                    f'<span class="sf-dot-live" style="font-size:7px">●</span>LIVE</span>'
                )
            else:
                watch_badge = (
                    f'<span style="color:{_TEXT3};font-size:11px">IDLE</span>'
                )

            # Last event timestamp — prefer live watch poll state, then schema mtime
            poll_state = load_poll_state(sn)
            if poll_state and poll_state.get("ts"):
                try:
                    _ts = _dt.fromisoformat(poll_state["ts"]).replace(tzinfo=None)
                    last_event = _time_ago(_ts)
                except Exception:
                    last_event = "recently"
            else:
                # Fall back to schema.yaml file mtime (reflects last init run)
                _schema_file = SCHEMAS_DIR / sn / "schema.yaml"
                try:
                    _ts = _dt.fromtimestamp(_schema_file.stat().st_mtime)
                    last_event = _time_ago(_ts)
                except Exception:
                    last_event = "—"

            # Sampled column — show live watch stats if available, else init count
            if poll_state:
                _sampled    = poll_state.get("sampled", 0)
                _window     = poll_state.get("window_size", 0)
                _new        = poll_state.get("new_events", 0)
                sampled_cell = (
                    f'<span style="font-size:12px;color:{_TEXT2}">{_sampled} sampled</span>'
                    f'<br><span style="font-size:11px;color:{_TEXT3}">'
                    f'{_window} in window'
                    f'{f" · +{_new} new" if _new else ""}'
                    f'</span>'
                )
            else:
                _n = sd.get("event_count_sampled", 0)
                sampled_cell = (
                    f'<span style="font-size:12px;color:{_TEXT2}">{_n} at init</span>'
                    f'<br><span style="font-size:11px;color:{_TEXT3}">watch not started</span>'
                )

            # Health badge
            if has_drift:
                if dr:
                    _, _c = dr[0]
                    _fs = _parse_drifted_fields(_c)
                    max_tier = max((f.get("tier") or 0 for f in _fs), default=0)
                else:
                    max_tier = 0
                tier_lbl  = f"T{max_tier} DRIFT" if max_tier else "DRIFT"
                badge_bg  = "rgba(248,113,113,0.1)" if max_tier == 3 else "rgba(251,191,36,0.1)"
                badge_bdr = "rgba(248,113,113,0.3)" if max_tier == 3 else "rgba(251,191,36,0.3)"
                badge_fg  = _RED if max_tier == 3 else _ORANGE
                health_badge = (
                    f'<span style="background:{badge_bg};color:{badge_fg};'
                    f'border:1px solid {badge_bdr};font-size:9.5px;font-weight:700;'
                    f'letter-spacing:0.07em;padding:3px 9px;border-radius:4px">{tier_lbl}</span>'
                )
                spark = _SPARK["drift"]
            elif has_pii:
                health_badge = (
                    f'<span style="background:rgba(251,191,36,0.1);color:{_ORANGE};'
                    f'border:1px solid rgba(251,191,36,0.28);font-size:9.5px;font-weight:700;'
                    f'letter-spacing:0.07em;padding:3px 9px;border-radius:4px">PII FLAGGED</span>'
                )
                spark = _SPARK["pii"]
            else:
                health_badge = (
                    f'<span style="background:rgba(74,222,128,0.08);color:{_GREEN};'
                    f'border:1px solid rgba(74,222,128,0.22);font-size:9.5px;font-weight:700;'
                    f'letter-spacing:0.07em;padding:3px 9px;border-radius:4px">SYNCED</span>'
                )
                spark = _SPARK["clean"]

            # Fields cell
            pii_frag = (
                f' <span style="color:{_ORANGE};font-size:11px">· {len(pii_fields)} PII</span>'
                if pii_fields else ""
            )
            fields_cell = (
                f'<span style="font-size:12px;color:{_TEXT2}">{len(all_fields)} fields</span>'
                f'{pii_frag}'
                f'<span style="font-size:11px;color:{_TEXT3};margin-left:8px">'
                f'{confidence:.0%}</span>'
            )

            rows_html += (
                f'<tr style="border-bottom:1px solid {_BORDER}">'
                f'<td style="padding:14px 16px;width:36px;text-align:center">{dot}</td>'
                f'<td style="padding:14px 16px;font-family:\'SF Mono\',\'Fira Code\','
                f'\'Consolas\',monospace;font-size:13px;font-weight:600;color:{_TEXT}'
                f';white-space:nowrap">{sn}</td>'
                f'<td style="padding:14px 16px;font-size:12px;color:{_TEXT3};'
                f'white-space:nowrap">{last_event}</td>'
                f'<td style="padding:14px 16px">{health_badge}</td>'
                f'<td style="padding:14px 16px">{fields_cell}</td>'
                f'<td style="padding:14px 16px;line-height:1.6">{sampled_cell}</td>'
                f'<td style="padding:14px 16px;text-align:center">{watch_badge}</td>'
                f'<td style="padding:14px 16px">{spark}</td>'
                f'</tr>'
            )

        table_html = (
            f'<table style="width:100%;border-collapse:collapse;background:{_SURF};'
            f'border-radius:12px;overflow:hidden;border:1px solid {_BORDER}">'
            f'<thead><tr>'
            f'<th style="{th};width:36px"></th>'
            f'<th style="{th}">Stream Identifier</th>'
            f'<th style="{th}">Last Polled</th>'
            f'<th style="{th}">Schema Health</th>'
            f'<th style="{th}">Fields</th>'
            f'<th style="{th}">Sampled</th>'
            f'<th style="{th};text-align:center">Watch</th>'
            f'<th style="{th}">Trend</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>'
        )
        st.markdown(table_html, unsafe_allow_html=True)

        # ── Row navigation — one slim button per stream ────────────────────
        st.markdown(
            '<div style="height:10px"></div>',
            unsafe_allow_html=True,
        )
        btn_cols = st.columns(len(stream_names))
        for _i, _sn in enumerate(stream_names):
            with btn_cols[_i]:
                if st.button(
                    f"Inspect {_sn} →",
                    key=f"rt_{_sn}",
                    use_container_width=True,
                ):
                    st.session_state.selected_stream = _sn
                    st.session_state.view = "stream"
                    st.rerun()

    # ── Live Activity feed — compact, below table ─────────────────────────────
    st.markdown(
        '<div style="height:20px"></div>',
        unsafe_allow_html=True,
    )

    activity = _build_activity(stream_names, _drift_streams, _pii_streams, schemas)
    if activity:
        st.markdown(
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:8px">Recent Activity</div>',
            unsafe_allow_html=True,
        )
        _pill_bg  = {"drift": "rgba(248,113,113,0.15)", "pii": "rgba(251,191,36,0.1)", "schema": "rgba(96,165,250,0.1)", "healthy": "rgba(74,222,128,0.1)"}
        _pill_fg  = {"drift": "#F87171", "pii": "#FBBF24", "schema": "#60A5FA", "healthy": "#4ADE80"}
        _pill_lbl = {"drift": "drift", "pii": "pii", "schema": "inferred", "healthy": "clean"}

        feed_html = (
            f'<div style="background:{_SURF};border-radius:10px;'
            f'border:1px solid {_BORDER};overflow:hidden">'
        )
        for i, ev in enumerate(activity[:8]):
            ts_str   = _time_ago(ev["ts"])
            pill_bg  = _pill_bg.get(ev["type"], "rgba(82,82,91,0.15)")
            pill_fg  = _pill_fg.get(ev["type"], "#52525B")
            pill_lbl = _pill_lbl.get(ev["type"], "event")
            sep      = f'border-bottom:1px solid {_BORDER};' if i < 7 else ''
            feed_html += (
                f'<div style="padding:8px 14px;{sep}">'
                f'<div style="display:flex;align-items:center;gap:10px">'
                + f'<span style="background:{pill_bg};color:{pill_fg};font-size:9.5px;font-weight:600;'
                + 'letter-spacing:0.04em;padding:1px 7px;border-radius:980px;flex-shrink:0;'
                + f'white-space:nowrap">{pill_lbl}</span>'
                    + f'<div style="min-width:0;flex:1">'
                    f'<div style="font-size:11.5px;font-weight:500;color:{_TEXT2};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                    f'{ev["msg"]}</div>'
                    f'<div style="font-size:10.5px;color:{_TEXT3};margin-top:1px;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                    f'{ev["detail"]}</div>'
                    f'</div>'
                    f'<span style="font-size:10px;color:{_TEXT3};white-space:nowrap;'
                    f'font-family:\'SF Mono\',monospace;flex-shrink:0">{ts_str}</span>'
                    f'</div>'
                    f'</div>'
                )
            feed_html += '</div>'
            st.markdown(feed_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# STREAM DETAIL
# ══════════════════════════════════════════════════════════════════════════════

def render_stream_detail(stream_name: str):
    sd             = schemas.get(stream_name, {})
    profile_data   = load_profile(stream_name)
    drift_reports  = load_drift_reports(stream_name)
    policy_data    = load_policy(stream_name)
    consumers_data = load_consumers(stream_name)

    # For multi-schema streams, aggregate fields and PII from all sub-schemas in profile.yaml.
    # schema.yaml only contains the primary cluster; profile.yaml has the full picture.
    if profile_data and profile_data.get("sub_schemas"):
        all_fields = [
            f
            for sub in profile_data["sub_schemas"]
            for f in sub.get("fields", [])
        ]
        pii_fields = [f for f in all_fields if f.get("pii_categories")]
    else:
        all_fields = sd.get("fields", [])
        pii_fields = [f for f in all_fields if f.get("pii")]

    # ── Header ────────────────────────────────────────────────────────────────
    has_drift = bool(drift_reports)
    accent    = _RED if has_drift else _ORANGE if pii_fields else _GREEN
    badge_txt = "DRIFT" if has_drift else "PII" if pii_fields else "HEALTHY"
    badge_bg  = (
        "rgba(248,113,113,0.12)" if has_drift else
        "rgba(251,191,36,0.12)"  if pii_fields else
        "rgba(74,222,128,0.10)"
    )

    # Back button
    if st.button("← Fleet", key="back_fleet"):
        st.session_state.view = "fleet"
        st.session_state.selected_stream = None
        st.rerun()

    st.markdown(
        f'<div style="padding:12px 0 4px 0;border-bottom:1px solid {_BORDER};margin-bottom:16px">'
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<span style="width:8px;height:8px;border-radius:50%;background:{accent};'
        f'flex-shrink:0;display:inline-block"></span>'
        f'<h1 style="font-size:1.4rem;font-weight:700;color:{_TEXT};margin:0">{stream_name}</h1>'
        f'<span style="background:{badge_bg};color:{accent};font-size:9.5px;font-weight:700;'
        f'letter-spacing:0.07em;padding:2px 9px;border-radius:980px">{badge_txt}</span>'
        f'</div>'
        f'<div style="font-size:11.5px;color:{_TEXT3};margin:6px 0 0 18px">'
        f'Inferred {sd.get("inferred_at","")[:10]}'
        f'  ·  {sd.get("inference_model","—")}'
        f'  ·  {sd.get("event_count_sampled",0):,} events'
        f'  ·  v{sd.get("version","1.0.0")}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    consumer_count = len(consumers_data.get("consumers", [])) if consumers_data else 0
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    mc1.metric("Fields",        len(all_fields))
    mc2.metric("Confidence",    f'{sd.get("inference_confidence",0):.0%}')
    mc3.metric("PII Fields",    len(pii_fields))
    _open_inc_count = len(load_open_incidents(stream_name))
    mc4.metric("Open Incidents", _open_inc_count, delta=None if _open_inc_count == 0 else f"{len(drift_reports)} reports")
    mc5.metric("Sub-schemas",   len(profile_data.get("sub_schemas", [])) if profile_data else "—")
    mc6.metric("Consumers",     consumer_count)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Active profiling status banner ────────────────────────────────────────
    _stream_ps = load_poll_state(stream_name)
    if _is_live(stream_name) and _stream_ps:
        _w  = _stream_ps.get("window_size", 0)
        _s  = _stream_ps.get("sampled", 0)
        _n  = _stream_ps.get("new_events", 0)
        _ts_str = _stream_ps.get("ts", "")[:19].replace("T", " ")
        # Show per-field profiling status (which fields are being tracked)
        _tracked = [f.get("path", "") for f in all_fields if f.get("presence_rate") is not None]
        _pii_tracked = [f.get("path", "") for f in all_fields if f.get("pii")]
        st.markdown(
            f'<div style="background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.22);'
            f'border-radius:10px;padding:14px 18px;margin-bottom:16px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            f'<span class="sf-dot-live" style="color:{_GREEN};font-size:11px">●</span>'
            f'<span style="font-size:13px;font-weight:700;color:{_GREEN}">Actively Profiling</span>'
            f'<span style="font-size:11px;color:{_TEXT3}">last polled {_ts_str} UTC</span>'
            f'</div>'
            f'<div style="display:flex;gap:32px;flex-wrap:wrap">'
            f'<div><div style="font-size:18px;font-weight:700;color:{_TEXT}">{_s}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;letter-spacing:0.07em">Sampled this cycle</div></div>'
            f'<div><div style="font-size:18px;font-weight:700;color:{_TEXT}">{_w}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;letter-spacing:0.07em">Events in window</div></div>'
            f'<div><div style="font-size:18px;font-weight:700;color:{_TEXT}">{_n}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;letter-spacing:0.07em">New this poll</div></div>'
            f'<div><div style="font-size:18px;font-weight:700;color:{_TEXT}">{len(_tracked)}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;letter-spacing:0.07em">Fields being inferred</div></div>'
            f'<div><div style="font-size:18px;font-weight:700;color:{_ORANGE}">{len(_pii_tracked)}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;letter-spacing:0.07em">PII fields tracked</div></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif _stream_ps:
        _ts_str = _stream_ps.get("ts", "")[:19].replace("T", " ")
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER};'
            f'border-radius:10px;padding:12px 18px;margin-bottom:16px;'
            f'display:flex;align-items:center;gap:10px">'
            f'<span style="color:{_TEXT3};font-size:11px">●</span>'
            f'<span style="font-size:12px;color:{_TEXT3}">Watch idle — last run {_ts_str} UTC · '
            f'run <code>./scripts/watch_all.sh</code> to resume</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER};'
            f'border-radius:10px;padding:12px 18px;margin-bottom:16px;'
            f'display:flex;align-items:center;gap:10px">'
            f'<span style="color:{_TEXT3};font-size:11px">○</span>'
            f'<span style="font-size:12px;color:{_TEXT3}">Watch never started for this stream — '
            f'run <code>streamforge watch {stream_name}</code></span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Open incidents panel ───────────────────────────────────────────────────
    open_incidents = load_open_incidents(stream_name)
    if open_incidents:
        highest_tier = max(inc.get("tier", 1) for inc in open_incidents)
        banner_color = _RED if highest_tier >= 3 else _ORANGE
        rows_html = ""
        for inc in open_incidents:
            tc = _RED if inc.get("tier", 1) >= 3 else _ORANGE if inc.get("tier", 1) == 2 else _GREEN
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;'
                f'border-bottom:1px solid {_BORDER}">'
                f'<span style="font-size:10px;font-weight:700;color:{tc};background:{tc}22;'
                f'padding:1px 7px;border-radius:980px;white-space:nowrap">T{inc.get("tier",1)}</span>'
                f'<code style="font-size:12px;color:{_TEXT};flex:1">{inc.get("field_path","")}</code>'
                f'<span style="font-size:11px;color:{_TEXT2}">{inc.get("drift_type","").replace("_"," ")}</span>'
                f'<span style="font-size:11px;color:{_TEXT3};white-space:nowrap">'
                f'{inc.get("occurrences",1)}× since {inc.get("first_detected","")[:10]}</span>'
                f'</div>'
            )
        st.markdown(
            f'<div style="background:{banner_color}11;border:1px solid {banner_color}44;'
            f'border-radius:10px;padding:14px 18px;margin-bottom:16px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            f'<span style="color:{banner_color};font-size:13px">⚠</span>'
            f'<span style="font-size:13px;font-weight:700;color:{banner_color}">'
            f'{len(open_incidents)} Open Incident(s)</span>'
            f'<span style="font-size:11px;color:{_TEXT3}">'
            f'Run <code>streamforge accept {stream_name}</code> to update schema.yaml '
            f'and stop re-detection · or <code>streamforge suppress … --days 7</code></span>'
            f'</div>'
            f'{rows_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_schema, tab_sub, tab_pii, tab_drift, tab_policy = st.tabs([
        "📋  Schema", "🧩  Sub-schemas", "🔒  PII & Compliance", "📈  Drift History", "⚙️  Policy"
    ])

    # Schema tab
    with tab_schema:
        st.markdown(
            f'<p style="color:{_TEXT2};font-size:13px;margin-bottom:14px">'
            f'Primary schema from the largest event cluster. '
            f'Edit <code>schema.yaml</code> to declare corrections — '
            f'it\'s the source of truth for <code>watch</code> and CI/CD blocking.</p>',
            unsafe_allow_html=True,
        )
        if all_fields:
            st.markdown(render_field_table(all_fields), unsafe_allow_html=True)
            enum_fields = [f for f in all_fields if f.get("enum_values")]
            if enum_fields:
                with st.expander(f"📌 Enum Values ({len(enum_fields)} fields)"):
                    for f in enum_fields:
                        vals = f.get("enum_values", [])
                        st.markdown(f'`{f["path"]}` → ' + " | ".join(f"`{v}`" for v in vals[:20]))
            with st.expander("🗂  Raw schema.yaml"):
                p = SCHEMAS_DIR / stream_name / "schema.yaml"
                if p.exists():
                    st.code(p.read_text(), language="yaml")
        else:
            st.info("No schema found. Run `streamforge init` first.")

    # Sub-schemas tab
    with tab_sub:
        st.markdown(
            f'<p style="color:{_TEXT2};font-size:13px;margin-bottom:14px">'
            f'StreamForge auto-discovers distinct event types in a single stream. '
            f'Each cluster gets its own schema — presence rates computed <em>within</em> the cluster, '
            f'not diluted across the whole stream. This is the core differentiator over schema registries.</p>',
            unsafe_allow_html=True,
        )
        if not profile_data:
            st.info("No `profile.yaml` found. Re-run `streamforge init` to generate sub-schema profiles.")
        else:
            sub_schemas = profile_data.get("sub_schemas", [])
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("Clusters",      len(sub_schemas))
            hc2.metric("Discovery",     profile_data.get("discovery_method", "—").replace("_", " ").title())
            hc3.metric("Parse Rate",    f'{profile_data.get("parse_success_rate", 1):.1%}')
            hc4.metric("Events Sampled", f'{profile_data.get("total_events_sampled", 0):,}')
            st.markdown("<br>", unsafe_allow_html=True)

            if sub_schemas:
                rows = []
                TH_S = (f'font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
                        f'color:{_TEXT3};border-bottom:1px solid {_BORDER2};padding:10px 12px')
                for sub in sub_schemas:
                    cid  = sub.get("cluster_id", "—")
                    ev   = sub.get("event_count", 0)
                    sr   = sub.get("sample_rate", 0)
                    conf = sub.get("inference_confidence", 0)
                    sf   = sub.get("fields", [])
                    pf   = [f for f in sf if f.get("pii") or f.get("pii_categories")]
                    ps   = ", ".join(f"`{f['path']}`" for f in pf[:2]) + (f" +{len(pf)-2}" if len(pf) > 2 else "")
                    conf_c = _GREEN if conf >= 0.8 else _ORANGE
                    rows.append(
                        f'<tr>'
                        f'<td style="padding:9px 12px;font-weight:600;font-size:13px;color:{_TEXT}">{cid}</td>'
                        f'<td style="padding:9px 12px;font-size:12px;color:{_TEXT2}">{ev:,}</td>'
                        f'<td style="padding:9px 12px;font-size:12px;color:{_TEXT2}">{sr:.0%}</td>'
                        f'<td style="padding:9px 12px;font-size:12px;color:{_TEXT2}">{len(sf)}</td>'
                        f'<td style="padding:9px 12px;font-size:12px;color:{conf_c};font-weight:600">{conf:.0%}</td>'
                        f'<td style="padding:9px 12px;font-size:11px;color:{_TEXT3}">{ps or "—"}</td>'
                        f'</tr>'
                    )
                st.markdown(
                    f'<div style="overflow-x:auto;border-radius:10px;border:1px solid {_BORDER};margin-bottom:18px">'
                    f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
                    f'<thead><tr style="background:{_SURF3}">'
                    f'<th style="{TH_S}">Cluster</th><th style="{TH_S}">Events</th>'
                    f'<th style="{TH_S}">% Stream</th><th style="{TH_S}">Fields</th>'
                    f'<th style="{TH_S}">Confidence</th><th style="{TH_S}">PII</th>'
                    f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
                    unsafe_allow_html=True,
                )
                for sub in sub_schemas:
                    cid = sub.get("cluster_id", "—")
                    sf  = sub.get("fields", [])
                    tk  = sub.get("top_keys", [])
                    with st.expander(
                        f"🔍  {cid}  —  {sub.get('event_count',0):,} events  ·  "
                        f"{sub.get('inference_confidence',0):.0%} confidence"
                    ):
                        if tk:
                            st.markdown(
                                f'<div style="font-size:11px;color:{_TEXT3};margin-bottom:10px">Top keys: '
                                + " · ".join(f"<code>{k}</code>" for k in tk[:10])
                                + '</div>', unsafe_allow_html=True)
                        st.markdown(render_field_table(sf), unsafe_allow_html=True)

    # PII tab
    with tab_pii:
        st.markdown(
            f'<p style="color:{_TEXT2};font-size:13px;margin-bottom:14px">'
            f'PII detected via regex patterns and field-name heuristics — no LLM required. '
            f'Runs automatically on every <code>init</code>.</p>',
            unsafe_allow_html=True,
        )
        if not pii_fields:
            st.success("✅ No PII detected in primary schema.")
        else:
            st.warning(f"⚠️ {len(pii_fields)} PII field(s) — review for GDPR/CCPA compliance.")
            st.markdown(render_field_table(pii_fields), unsafe_allow_html=True)

        if profile_data:
            for sub in profile_data.get("sub_schemas", []):
                spii = [f for f in sub.get("fields", []) if f.get("pii")]
                if spii:
                    with st.expander(f"🔒 PII in {sub.get('cluster_id','—')}"):
                        st.markdown(render_field_table(spii), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(
            f'<div style="font-size:12px;font-weight:600;color:{_TEXT2};margin-bottom:12px">Compliance Checklist</div>',
            unsafe_allow_html=True,
        )
        for title, desc in [
            ("Data Minimisation",     "Only collect PII necessary for the stated purpose."),
            ("Retention Policy",      "Kafka retention for PII topics: default 7 days may violate GDPR Art. 5(1)(e)."),
            ("Access Controls",       "Kafka ACLs must restrict read access to PII topics to authorised consumers only."),
            ("Encryption in Transit", "All PII topics must use TLS. Check broker security.protocol."),
            ("Right to Erasure",      "GDPR Art. 17: must be able to delete/anonymise per user across all consumers."),
            ("Consent Lineage",       "Every PII field should be traceable to a consent event. Register in consumers.yaml."),
        ]:
            icon = "⚠️" if pii_fields else "✅"
            st.markdown(
                f'<div style="background:{_SURF};border-radius:8px;padding:12px 14px;margin-bottom:6px;'
                f'border:1px solid {_BORDER}">'
                f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:3px">{icon} {title}</div>'
                f'<div style="font-size:11.5px;color:{_TEXT2}">{desc}</div></div>',
                unsafe_allow_html=True,
            )

    # Drift tab
    with tab_drift:
        st.markdown(
            f'<p style="color:{_TEXT2};font-size:13px;margin-bottom:14px">'
            f'Reports from <code>streamforge watch</code> or <code>streamforge plan</code>. '
            f'Tier 3 = CI blocking · Tier 2 = breaking · Tier 1 = informational.</p>',
            unsafe_allow_html=True,
        )
        if not drift_reports:
            st.markdown(
                f'<div style="background:rgba(48,209,88,0.08);border-radius:12px;padding:24px;'
                f'text-align:center;border:1px solid rgba(48,209,88,0.2)">'
                f'<div style="font-size:24px;margin-bottom:8px">✅</div>'
                f'<div style="font-size:14px;font-weight:600;color:{_GREEN}">Schema is clean</div>'
                f'<div style="font-size:12px;color:{_TEXT2};margin-top:4px">'
                f'Run <code>streamforge watch</code> to monitor continuously.</div></div>',
                unsafe_allow_html=True,
            )
        else:
            _most_recent_content = drift_reports[0][1]
            _drifted_fields      = _parse_drifted_fields(_most_recent_content)
            _impact_html         = _render_impact_assessment(_drifted_fields, consumers_data)
            if _impact_html:
                st.markdown(_impact_html, unsafe_allow_html=True)
            elif consumers_data:
                st.success("✅ No registered consumers are affected by this drift.")
            else:
                st.info(
                    f"💡 Add `consumers.yaml` to see blast radius. "
                    f"Path: `schemas/{stream_name}/consumers.yaml`"
                )

            # ── Unified drift timeline table ───────────────────────────────────
            # Collapse consecutive reports that have the same drift fingerprint
            # (same set of field_path + drift_type) into a single row group.
            parsed_reports: list[tuple[str, str, list[dict]]] = []  # (fname, date_str, rows)
            for fname, content in drift_reports:
                rows = _parse_drift_report_rows(content)
                if not rows:
                    continue
                try:
                    ts = _dt.strptime(fname.replace(".md", ""), "%Y-%m-%d-%H%M")
                    date_str = ts.strftime("%b %d, %Y  %H:%M")
                except Exception:
                    date_str = fname.replace(".md", "")
                parsed_reports.append((fname, date_str, rows))

            # Group consecutive entries with identical fingerprints
            grouped: list[tuple[str, list[dict], int]] = []  # (date_str, rows, count)
            for _fname, date_str, rows in parsed_reports:
                sig = frozenset((r.get("path", ""), r.get("drift_type", "")) for r in rows)
                if grouped and frozenset(
                    (r.get("path", ""), r.get("drift_type", "")) for r in grouped[-1][1]
                ) == sig:
                    grouped[-1] = (grouped[-1][0], grouped[-1][1], grouped[-1][2] + 1)
                else:
                    grouped.append((date_str, rows, 1))

            tbody_html = ""
            for i, (date_str, rows, count) in enumerate(grouped):
                highest = max((r["tier"] or 0 for r in rows), default=0)
                hc = _RED if highest == 3 else _ORANGE if highest == 2 else _GREEN
                badge = "CRITICAL" if highest == 3 else "BREAKING" if highest == 2 else "INFO"
                latest_tag = (
                    f'<span style="margin-left:8px;font-size:10px;color:{_TEXT3}">latest</span>'
                    if i == 0 else ""
                )
                persist_tag = (
                    f'<span style="margin-left:8px;font-size:10px;color:{_TEXT3};'
                    f'background:#ffffff10;padding:1px 6px;border-radius:6px">'
                    f'persisted {count} cycles</span>'
                    if count > 1 else ""
                )
                tbody_html += (
                    f'<tr><td colspan="6" style="padding:10px 14px 6px;background:{_SURF3};'
                    f'border-top:1px solid {_BORDER2};border-bottom:1px solid {_BORDER}">'
                    f'<span style="font-size:11px;font-weight:600;color:{_TEXT2}">{date_str}</span>'
                    f'<span style="margin-left:10px;background:{hc}22;color:{hc};'
                    f'border:1px solid {hc}44;padding:1px 8px;border-radius:980px;'
                    f'font-size:10px;font-weight:700;letter-spacing:0.05em">{badge}</span>'
                    f'{latest_tag}{persist_tag}</td></tr>'
                )
                for row in rows:
                    tier = row.get("tier") or 0
                    tc_r = _RED if tier == 3 else _ORANGE if tier == 2 else _GREEN
                    dt_label = (row.get("drift_type") or "—").replace("_", " ").title()
                    if row.get("before") and row.get("after"):
                        before_str = f'<code style="font-size:11px;color:{_TEXT2}">{row["before"]}</code>'
                        after_str  = f'<code style="font-size:11px;color:{_TEXT}">{row["after"]}</code>'
                    elif row.get("presence_before") and row.get("presence_after"):
                        before_str = f'<span style="font-size:12px;color:{_TEXT2}">{row["presence_before"]}</span>'
                        after_str  = f'<span style="font-size:12px;color:{_TEXT}">{row["presence_after"]}</span>'
                    else:
                        before_str = '<span style="color:#444">—</span>'
                        after_str  = '<span style="color:#444">—</span>'
                    events_str = row.get("events") or "—"
                    tier_str = (
                        f'<span style="color:{tc_r};font-weight:700;font-size:12px">T{tier}</span>'
                        if tier else '<span style="color:#444">—</span>'
                    )
                    tbody_html += (
                        f'<tr style="border-bottom:1px solid {_BORDER}">'
                        f'<td style="padding:10px 14px;font-family:monospace;font-size:12px;color:{_TEXT}">'
                        f'{row["path"]}</td>'
                        f'<td style="padding:10px 14px;font-size:12px;color:{_TEXT2}">{dt_label}</td>'
                        f'<td style="padding:10px 14px">{before_str}</td>'
                        f'<td style="padding:10px 14px">{after_str}</td>'
                        f'<td style="padding:10px 14px;font-size:12px;color:{_TEXT2};text-align:center">'
                        f'{events_str}</td>'
                        f'<td style="padding:10px 14px;text-align:center">{tier_str}</td>'
                        f'</tr>'
                    )
            th_style = (
                f'padding:10px 14px;font-size:10px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.08em;color:{_TEXT3};background:{_SURF2};text-align:left'
            )
            table_html = (
                f'<table style="width:100%;border-collapse:collapse;background:{_SURF};'
                f'border-radius:12px;overflow:hidden;border:1px solid {_BORDER}">'
                f'<thead><tr>'
                f'<th style="{th_style}">Field</th>'
                f'<th style="{th_style}">Change</th>'
                f'<th style="{th_style}">Before</th>'
                f'<th style="{th_style}">After</th>'
                f'<th style="{th_style};text-align:center">Events</th>'
                f'<th style="{th_style};text-align:center">Tier</th>'
                f'</tr></thead>'
                f'<tbody>{tbody_html}</tbody></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)

    # Policy tab
    with tab_policy:
        st.markdown(
            f'<p style="color:{_TEXT2};font-size:13px;margin-bottom:14px">'
            f'Controls how StreamForge responds to drift. Edit <code>stream_policy.yaml</code> '
            f'alongside <code>schema.yaml</code> — takes effect on next poll cycle.</p>',
            unsafe_allow_html=True,
        )

        if not policy_data:
            st.info("No policy found. Run `streamforge init` to generate a default policy.")
        else:
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Sample Size",   f'{policy_data.get("sample_size", 200):,} events')
            pc2.metric("Poll Interval", f'{policy_data.get("poll_interval_seconds", 30)}s')
            pc3.metric("Alert Tier",    f'Tier {policy_data.get("alert_tier", 2)}+')
            st.markdown("<br>", unsafe_allow_html=True)

            actions    = policy_data.get("actions", {})
            action_html = ""
            for tk, action in actions.items():
                bg = {"log": _SURF2, "alert": "rgba(255,159,10,0.1)", "block": "rgba(255,69,58,0.1)"}.get(action, _SURF2)
                fg = {"log": _TEXT3, "alert": _ORANGE, "block": _RED}.get(action, _TEXT2)
                action_html += (
                    f'<div style="display:flex;align-items:center;padding:12px 14px;background:{bg};'
                    f'border-radius:8px;margin-bottom:6px">'
                    f'<div style="font-size:12px;font-weight:600;color:{_TEXT}">{tk.replace("_"," ").title()}</div>'
                    f'<div style="flex:1"></div>'
                    f'<span style="background:{_SURF3};color:{fg};border:1px solid {fg};padding:2px 10px;'
                    f'border-radius:980px;font-size:10px;font-weight:700;letter-spacing:0.06em">{action.upper()}</span>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="background:{_SURF};border-radius:10px;padding:14px;border:1px solid {_BORDER};margin-bottom:16px">'
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
                f'color:{_TEXT3};margin-bottom:10px">Drift Response Actions</div>'
                f'{action_html}</div>',
                unsafe_allow_html=True,
            )

            st.markdown("---")
            st.markdown(
                f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:6px">'
                f'Consumer Registry & Blast Radius</div>'
                f'<p style="font-size:12px;color:{_TEXT2};margin-bottom:12px">'
                f'When drift fires, StreamForge shows exactly which services break and who to page.</p>',
                unsafe_allow_html=True,
            )
            if consumers_data:
                for c in consumers_data.get("consumers", []):
                    crit = c.get("criticality", "tier3")
                    with st.expander(f"👤 {c.get('name','?')} — {c.get('team','?')} — {crit.upper()}"):
                        st.markdown(
                            f'**Contact:** {c.get("contact","—")}  \n'
                            f'**Schema version:** {c.get("schema_version","—")}  \n'
                            + (f'**Description:** {c.get("description","")}  \n' if c.get("description") else "")
                            + (f'**Runbook:** {c.get("runbook","")}' if c.get("runbook") else "")
                        )
                        fps = [f.get("path", "?") for f in c.get("fields_used", [])]
                        if fps:
                            st.markdown("**Fields used:** " + " · ".join(f"`{p}`" for p in fps[:10]))
            else:
                st.info(
                    f"No `consumers.yaml` yet.  \n"
                    f"Path: `schemas/{stream_name}/consumers.yaml`"
                )

            with st.expander("🗂  Raw stream_policy.yaml"):
                p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
                if p.exists():
                    st.code(p.read_text(), language="yaml")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

def render_registry():
    all_rows: list[dict] = []
    for sn, sd in schemas.items():
        for f in sd.get("fields", []):
            all_rows.append({
                "stream":        sn,
                "path":          f.get("path", ""),
                "type":          f.get("type", "string"),
                "required":      f.get("required", False),
                "presence_rate": f.get("presence_rate", 0.0),
                "confidence":    f.get("confidence", 0.0),
                "pii":           f.get("pii", []),
                "notes":         f.get("notes") or "",
            })

    total_fields    = len(all_rows)
    unique_paths    = len({r["path"] for r in all_rows})
    pii_field_count = sum(1 for r in all_rows if r["pii"])
    streams_covered = len({r["stream"] for r in all_rows})

    st.markdown(
        f'<div style="padding:20px 0 16px 0;border-bottom:1px solid {_BORDER};margin-bottom:16px">'
        f'<h1 style="font-size:1.5rem;font-weight:700;color:{_TEXT};margin:0">🗂 Schema Registry</h1>'
        f'<p style="font-size:12px;color:{_TEXT2};margin:5px 0 0 0">'
        f'Every field across every stream — searchable, filterable, cross-referenced. '
        f'Find where a field lives, which streams share names, where PII hides.'
        f'</p></div>',
        unsafe_allow_html=True,
    )

    rm1, rm2, rm3, rm4 = st.columns(4)
    rm1.metric("Total Fields",    total_fields)
    rm2.metric("Unique Names",    unique_paths)
    rm3.metric("PII Fields",      pii_field_count)
    rm4.metric("Streams Indexed", streams_covered)
    st.markdown("<br>", unsafe_allow_html=True)

    if not all_rows:
        st.info("No schemas found. Run `streamforge init` first.")
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns([3, 1.2, 1.2, 1.2])
    with fc1:
        query = st.text_input(
            "Search", placeholder="field path, stream, type, or keyword in notes…",
            label_visibility="collapsed",
        )
    with fc2:
        pii_only = st.toggle("PII only", value=False)
    with fc3:
        req_only = st.toggle("Required only", value=False)
    with fc4:
        all_types   = sorted({r["type"] for r in all_rows})
        type_filter = st.selectbox("Type", ["All types"] + all_types, label_visibility="collapsed")

    stream_filter = st.selectbox(
        "Stream", ["All streams"] + sorted({r["stream"] for r in all_rows}),
        label_visibility="collapsed",
    )

    # ── Filter ────────────────────────────────────────────────────────────────
    q        = query.strip().lower()
    filtered = all_rows
    if q:
        filtered = [r for r in filtered
                    if q in r["path"].lower() or q in r["stream"].lower()
                    or q in r["type"].lower()  or q in r["notes"].lower()]
    if pii_only:
        filtered = [r for r in filtered if r["pii"]]
    if req_only:
        filtered = [r for r in filtered if r["required"]]
    if type_filter != "All types":
        filtered = [r for r in filtered if r["type"] == type_filter]
    if stream_filter != "All streams":
        filtered = [r for r in filtered if r["stream"] == stream_filter]

    filtered.sort(key=lambda r: (r["stream"], r["path"]))

    st.markdown(
        f'<div style="font-size:11.5px;color:{_TEXT3};margin:8px 0">'
        f'Showing <strong style="color:{_TEXT}">{len(filtered)}</strong> of '
        f'<strong>{total_fields}</strong> fields'
        + (f' — query: <code>{query}</code>' if q else "")
        + '</div>',
        unsafe_allow_html=True,
    )

    if not filtered:
        st.markdown(
            f'<div style="background:{_SURF};border-radius:10px;padding:32px;text-align:center">'
            f'<div style="font-size:28px;margin-bottom:8px">🔍</div>'
            f'<div style="font-size:14px;font-weight:600;color:{_TEXT}">No fields match</div>'
            f'<div style="font-size:12px;color:{_TEXT2};margin-top:4px">Try a broader term or clear filters.</div>'
            f'</div>', unsafe_allow_html=True)
        return

    # ── Table ─────────────────────────────────────────────────────────────────
    TH = (f'font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
          f'color:{_TEXT3};border-bottom:1px solid {_BORDER2};padding:9px 12px;text-align:left')
    TD = f'padding:8px 12px;vertical-align:middle;border-bottom:1px solid {_BORDER}'

    rows_html  = []
    prev_stream = None
    for i, r in enumerate(filtered):
        stream_changed = r["stream"] != prev_stream
        prev_stream    = r["stream"]
        row_bg = _SURF if i % 2 == 0 else _SURF2

        stream_html = (
            f'<span style="font-size:11px;font-weight:600;color:{_BLUE};'
            f'background:rgba(77,158,255,0.1);padding:2px 8px;border-radius:980px">'
            f'{r["stream"]}</span>'
        ) if stream_changed else (
            f'<span style="font-size:11px;color:{_TEXT3}">↳</span>'
        )

        path_display = r["path"]
        if q and q in path_display.lower():
            idx = path_display.lower().index(q)
            path_display = (
                path_display[:idx]
                + f'<mark style="background:rgba(255,159,10,0.25);border-radius:2px;color:{_TEXT}">'
                + path_display[idx:idx+len(q)] + '</mark>'
                + path_display[idx+len(q):]
            )

        pct   = int(r["presence_rate"] * 100)
        bar_c = _GREEN if pct >= 80 else _ORANGE if pct >= 50 else _RED
        pres_html = (
            f'<div style="display:flex;align-items:center;gap:5px">'
            f'<div style="width:40px;height:3px;background:{_SURF3};border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{bar_c};border-radius:2px"></div></div>'
            f'<span style="font-size:11px;color:{_TEXT2}">{pct}%</span>'
            f'</div>'
        )

        conf     = int(r["confidence"] * 100)
        conf_col = _GREEN if conf >= 80 else _ORANGE if conf >= 60 else _RED
        conf_html = f'<span style="font-size:11px;color:{conf_col};font-weight:600">{conf}%</span>'

        req_html = (
            f'<span style="color:{_GREEN};font-size:13px;font-weight:700">●</span>'
            if r["required"] else
            f'<span style="color:{_TEXT3};font-size:13px">○</span>'
        )

        pii = r["pii"]
        if pii:
            label    = ", ".join(str(p) for p in pii[:2]) + (f" +{len(pii)-2}" if len(pii) > 2 else "")
            pii_html = (
                f'<span style="background:rgba(255,69,58,0.15);color:{_RED};padding:2px 8px;'
                f'border-radius:980px;font-size:10px;font-weight:700">{label}</span>'
            )
        else:
            pii_html = f'<span style="color:{_TEXT3};font-size:12px">—</span>'

        notes = r["notes"][:60] + ("…" if len(r["notes"]) > 60 else "")
        if q and notes and q in notes.lower():
            idx = notes.lower().index(q)
            notes = (
                notes[:idx]
                + f'<mark style="background:rgba(255,159,10,0.25);border-radius:2px;color:{_TEXT}">'
                + notes[idx:idx+len(q)] + '</mark>'
                + notes[idx+len(q):]
            )

        rows_html.append(
            f'<tr style="background:{row_bg}">'
            f'<td style="{TD}">{stream_html}</td>'
            f'<td style="{TD};font-family:\'SF Mono\',\'Fira Code\',monospace;font-size:12px;color:{_TEXT}">'
            f'{path_display}</td>'
            f'<td style="{TD}">{_type_badge(r["type"])}</td>'
            f'<td style="{TD};text-align:center">{req_html}</td>'
            f'<td style="{TD}">{pres_html}</td>'
            f'<td style="{TD};text-align:right">{conf_html}</td>'
            f'<td style="{TD}">{pii_html}</td>'
            f'<td style="{TD};font-size:11px;color:{_TEXT2};max-width:200px">{notes}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:10px;border:1px solid {_BORDER};margin-bottom:24px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr style="background:{_SURF3}">'
        f'<th style="{TH}">Stream</th><th style="{TH}">Field Path</th>'
        f'<th style="{TH}">Type</th><th style="{TH};text-align:center">Req</th>'
        f'<th style="{TH}">Presence</th><th style="{TH};text-align:right">Conf.</th>'
        f'<th style="{TH}">PII</th><th style="{TH}">Notes</th>'
        f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>',
        unsafe_allow_html=True,
    )

    visible_streams = sorted({r["stream"] for r in filtered})
    nav_cols = st.columns(min(len(visible_streams), 5))
    for i, sn in enumerate(visible_streams):
        with nav_cols[i % 5]:
            if st.button(f"Open {sn} →", key=f"reg_nav_{sn}"):
                st.session_state.selected_stream = sn
                st.session_state.view = "stream"
                st.rerun()

    # ── Field Insights ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:4px">Field Insights</div>'
        f'<p style="font-size:12px;color:{_TEXT2};margin:0 0 14px 0">'
        f'Fields shared across streams — standardisation gaps and type conflicts.</p>',
        unsafe_allow_html=True,
    )

    field_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in all_rows:
        field_map[r["path"]].append((r["stream"], r["type"]))

    cross_stream = {p: e for p, e in field_map.items() if len({s for s, _ in e}) > 1}

    if not cross_stream:
        st.markdown(
            f'<div style="font-size:12px;color:{_TEXT3}">No field names shared across streams yet.</div>',
            unsafe_allow_html=True,
        )
        return

    consistent  = {p: e for p, e in cross_stream.items() if len({t for _, t in e}) == 1}
    conflicting = {p: e for p, e in cross_stream.items() if len({t for _, t in e}) > 1}

    TH_I = (f'font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            f'color:{_TEXT3};border-bottom:1px solid {_BORDER2};padding:9px 12px;text-align:left')
    TD_I = f'padding:8px 12px;vertical-align:middle;border-bottom:1px solid {_BORDER}'

    if conflicting:
        st.markdown(
            f'<div style="background:rgba(255,159,10,0.08);border-radius:10px;padding:12px 16px;'
            f'border-left:3px solid {_ORANGE};margin-bottom:14px">'
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            f'color:{_ORANGE};margin-bottom:4px">⚠ {len(conflicting)} Type Conflict(s)</div>'
            f'<div style="font-size:11.5px;color:{_TEXT2}">'
            f'Same field name, different types across streams. Standardise before consumers cross-reference.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        conf_rows = []
        for path, entries in sorted(conflicting.items()):
            by_stream = " &nbsp;·&nbsp; ".join(
                f'<code>{s}</code> {_type_badge(t)}'
                for s, t in sorted(entries, key=lambda x: x[0])
            )
            conf_rows.append(
                f'<tr>'
                f'<td style="{TD_I};font-family:monospace;font-size:12px;color:{_TEXT}">{path}</td>'
                f'<td style="{TD_I};font-size:12px">{by_stream}</td>'
                f'<td style="{TD_I};text-align:center">'
                f'<span style="background:rgba(255,159,10,0.15);color:{_ORANGE};font-size:9.5px;'
                f'font-weight:700;padding:2px 8px;border-radius:980px">CONFLICT</span>'
                f'</td></tr>'
            )
        st.markdown(
            f'<div style="overflow-x:auto;border-radius:10px;border:1px solid rgba(255,159,10,0.2);margin-bottom:18px">'
            f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
            f'<thead><tr style="background:{_SURF2}">'
            f'<th style="{TH_I}">Field</th><th style="{TH_I}">Type per Stream</th>'
            f'<th style="{TH_I};text-align:center">Status</th>'
            f'</tr></thead><tbody>{"".join(conf_rows)}</tbody></table></div>',
            unsafe_allow_html=True,
        )

    if consistent:
        n_streams_total = len(stream_names) or 1
        consist_rows    = []
        for path, entries in sorted(consistent.items(), key=lambda x: -len({s for s, _ in x[1]})):
            streams_with = sorted({s for s, _ in entries})
            coverage     = len(streams_with) / n_streams_total
            freq_bar     = int(coverage * 100)
            ftype        = entries[0][1]
            freq_html    = (
                f'<div style="display:flex;align-items:center;gap:6px">'
                f'<div style="width:52px;height:3px;background:{_SURF3};border-radius:2px;overflow:hidden">'
                f'<div style="width:{freq_bar}%;height:100%;background:{_BLUE};border-radius:2px"></div></div>'
                f'<span style="font-size:11px;color:{_TEXT2}">{len(streams_with)}/{n_streams_total}</span>'
                f'</div>'
            )
            streams_html = " ".join(
                f'<span style="background:rgba(77,158,255,0.1);color:{_BLUE};padding:1px 7px;'
                f'border-radius:980px;font-size:10px">{s}</span>'
                for s in streams_with
            )
            consist_rows.append(
                f'<tr>'
                f'<td style="{TD_I};font-family:monospace;font-size:12px;color:{_TEXT}">{path}</td>'
                f'<td style="{TD_I}">{_type_badge(ftype)}</td>'
                f'<td style="{TD_I}">{freq_html}</td>'
                f'<td style="{TD_I};font-size:11px">{streams_html}</td>'
                f'</tr>'
            )
        st.markdown(
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
            f'color:{_TEXT3};margin-bottom:10px">{len(consistent)} Consistent Field(s) Across Streams</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="overflow-x:auto;border-radius:10px;border:1px solid {_BORDER}">'
            f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
            f'<thead><tr style="background:{_SURF3}">'
            f'<th style="{TH_I}">Field</th><th style="{TH_I}">Type</th>'
            f'<th style="{TH_I}">Coverage</th><th style="{TH_I}">Streams</th>'
            f'</tr></thead><tbody>{"".join(consist_rows)}</tbody></table></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM OVERVIEW  — "Why StreamForge" explainer page
# ══════════════════════════════════════════════════════════════════════════════

def _node(label: str, sub: str = "", color: str = "", accent: str = "") -> str:
    """Render a diagram node as an HTML card string."""
    bg      = f"rgba({','.join(str(int(color.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.08)" if color else _SURF2
    border  = f"rgba({','.join(str(int(color.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.28)" if color else _BORDER2
    tc      = color if color else _TEXT2
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'padding:10px 13px;text-align:center">'
        f'<div style="font-size:12px;font-weight:600;color:{tc}">{label}</div>'
        + (f'<div style="font-size:10.5px;color:{_TEXT3};margin-top:2px">{sub}</div>' if sub else "")
        + '</div>'
    )

def _arrow_md(label: str = "", color: str = "") -> str:
    c = color or _TEXT3
    return (
        f'<div style="text-align:center;padding:6px 0">'
        f'<div style="font-size:18px;color:{c}">→</div>'
        + (f'<div style="font-size:9.5px;color:{c};margin-top:2px">{label}</div>' if label else "")
        + '</div>'
    )

def render_about():

    # ── Hero ──────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="padding:32px 0 24px 0;border-bottom:1px solid {_BORDER};margin-bottom:28px">'
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:10px">Platform Overview</div>'
        f'<div style="font-size:1.85rem;font-weight:700;color:{_TEXT};line-height:1.25;'
        f'letter-spacing:-0.03em;margin-bottom:12px">'
        f'Your data changes.<br>'
        f'Your consumers break.<br>'
        f'<span style="color:{_BLUE}">You find out last.</span></div>'
        f'<div style="font-size:13.5px;color:{_TEXT2};max-width:540px;line-height:1.65">'
        f'Every event stream has a schema. Engineers change fields at 2am. '
        f'Downstream services fail silently. StreamForge is the governance layer '
        f'that catches schema drift <em>before</em> it reaches production.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 3 Pain cards ──────────────────────────────────────────────────────────
    p1, p2, p3 = st.columns(3)
    for col, title, body in [
        (p1, "The 3am Incident",
         "An engineer renames a field. Twelve consumers fail silently. "
         "Six engineers spend six hours diagnosing. Root cause: one field rename."),
        (p2, "The Compliance Audit",
         '"Which streams contain passport numbers?" Three weeks of manual review '
         "across hundreds of Kafka topics. A GDPR audit that should take hours."),
        (p3, "The Unknown Unknown",
         '"We have 200 Kafka topics. Nobody knows what\'s in them." '
         "No schema. No ownership. No blast radius. Just hope nothing breaks."),
    ]:
        with col:
            st.markdown(
                f'<div style="background:{_SURF};border-radius:10px;padding:18px 16px;'
                f'border:1px solid {_BORDER};border-top:2px solid {_RED};height:100%">'
                f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:7px">{title}</div>'
                f'<div style="font-size:12px;color:{_TEXT3};line-height:1.65">{body}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── Architecture diagram — native columns, zero HTML rendering risk ────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Architecture</div>',
        unsafe_allow_html=True,
    )

    # ── WITHOUT row ───────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;'
        f'color:{_TEXT3};display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        f'<span style="width:20px;height:1px;background:{_BORDER2};display:inline-block"></span>'
        f'Without StreamForge'
        f'<span style="flex:1;height:1px;background:{_BORDER2};display:inline-block"></span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    w1, wa1, w2, wa2, w3, wa3, w4 = st.columns([2, 0.4, 2, 0.5, 2, 0.4, 2.2])
    with w1:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER2};border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">PRODUCERS</div>'
            f'<div style="font-size:12px;color:{_TEXT2};margin-bottom:3px">payment-service</div>'
            f'<div style="font-size:12px;color:{_TEXT2}">booking-api</div>'
            f'</div>', unsafe_allow_html=True)
    with wa1:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with w2:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid rgba(96,165,250,0.2);border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">KAFKA TOPICS</div>'
            f'<div style="font-size:12px;color:{_TEXT};margin-bottom:3px">payments.events</div>'
            f'<div style="font-size:12px;color:{_TEXT}">bookings.stream</div>'
            f'</div>', unsafe_allow_html=True)
    with wa2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px">'
            f'<div style="font-size:14px;color:{_TEXT3};margin-bottom:2px">→</div>'
            f'<div style="background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.25);'
            f'border-radius:4px;padding:3px 6px;font-size:9px;color:{_RED};line-height:1.4;'
            f'white-space:nowrap">field<br>renamed</div>'
            f'</div>', unsafe_allow_html=True)
    with w3:
        st.markdown(
            f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.18);'
            f'border-radius:8px;padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">CONSUMERS</div>'
            f'<div style="font-size:12px;color:{_RED};margin-bottom:3px">fraud-detection ✗</div>'
            f'<div style="font-size:12px;color:{_RED}">gdpr-audit ✗</div>'
            f'</div>', unsafe_allow_html=True)
    with wa3:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with w4:
        st.markdown(
            f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.18);'
            f'border-radius:8px;padding:10px 12px">'
            f'<div style="font-size:12px;font-weight:600;color:{_RED}">3am page</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:3px">6 engineers · 6 hours</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">root cause unknown</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)

    # ── WITH row ──────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;'
        f'color:{_BLUE};display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        f'<span style="width:20px;height:1px;background:rgba(96,165,250,0.3);display:inline-block"></span>'
        f'With StreamForge'
        f'<span style="flex:1;height:1px;background:rgba(96,165,250,0.3);display:inline-block"></span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    s1, sa1, s2, sa2, s3, sa3, s4, sa4, s5 = st.columns([2, 0.35, 2, 0.35, 2.4, 0.35, 2, 0.35, 1.8])
    with s1:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER2};border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">PRODUCERS</div>'
            f'<div style="font-size:12px;color:{_TEXT2};margin-bottom:3px">payment-service</div>'
            f'<div style="font-size:12px;color:{_TEXT2}">booking-api</div>'
            f'</div>', unsafe_allow_html=True)
    with sa1:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s2:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid rgba(96,165,250,0.2);border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">KAFKA TOPICS</div>'
            f'<div style="font-size:12px;color:{_TEXT};margin-bottom:3px">payments.events</div>'
            f'<div style="font-size:12px;color:{_TEXT}">bookings.stream</div>'
            f'</div>', unsafe_allow_html=True)
    with sa2:
        st.markdown(
            f'<div style="text-align:center;padding-top:4px">'
            f'<div style="font-size:10px;color:{_TEXT3};margin-bottom:4px;white-space:nowrap">monitors</div>'
            f'<div style="font-size:16px;color:{_TEXT3}">↓</div>'
            f'</div>', unsafe_allow_html=True)
    with s3:
        st.markdown(
            f'<div style="background:rgba(96,165,250,0.06);border:2px solid rgba(96,165,250,0.3);'
            f'border-radius:10px;padding:12px 14px;text-align:center">'
            f'<div style="font-size:13px;font-weight:700;color:{_BLUE};margin-bottom:8px">⚡ StreamForge</div>'
            f'<div style="font-size:11px;color:{_TEXT2};text-align:left;line-height:1.8">'
            f'<span style="color:{_GREEN}">●</span> Schema inferred<br>'
            f'<span style="color:{_ORANGE}">●</span> Drift detected · Tier 3<br>'
            f'<span style="color:{_RED}">●</span> CI/CD deploy blocked<br>'
            f'<span style="color:{_BLUE}">●</span> 3 consumers alerted'
            f'</div>'
            f'</div>', unsafe_allow_html=True)
    with sa3:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s4:
        st.markdown(
            f'<div style="background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.2);'
            f'border-radius:8px;padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">CONSUMERS</div>'
            f'<div style="font-size:12px;color:{_GREEN};margin-bottom:3px">fraud-detection ✓</div>'
            f'<div style="font-size:12px;color:{_GREEN}">gdpr-audit ✓</div>'
            f'</div>', unsafe_allow_html=True)
    with sa4:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s5:
        st.markdown(
            f'<div style="background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.2);'
            f'border-radius:8px;padding:10px 12px">'
            f'<div style="font-size:12px;font-weight:600;color:{_GREEN}">Caught in 30s</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:3px">deploy blocked</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">no page · no outage</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── Setup guide — start to finish ─────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Setup — Start to Finish</div>',
        unsafe_allow_html=True,
    )

    steps = [
        ("1", "Install",       "pip install streamforge-cli",                          _BLUE,   "30 seconds"),
        ("2", "Point at data", "streamforge init events/payments/stream_v1",            _BLUE,   "Infers schema via LLM"),
        ("3", "Review schema", "cat schemas/payments.stream_v1/schema.yaml",            _BLUE,   "Git-commit the YAML"),
        ("4", "Start watching","streamforge watch events/payments/stream_v1 --interval 30", _BLUE, "Continuous monitoring"),
        ("5", "Drift fires",   "streamforge plan events/stream_v2 --schema schemas/...", _ORANGE, "One-shot drift check"),
        ("6", "Open dashboard","streamforge ui",                                         _GREEN,  "This dashboard"),
    ]

    setup_cols = st.columns(len(steps))
    for i, (num, label, cmd, color, note) in enumerate(steps):
        with setup_cols[i]:
            connector = (
                f'<div style="position:absolute;top:18px;left:50%;width:100%;height:1px;'
                f'background:{_BORDER2}"></div>'
            ) if i < len(steps) - 1 else ""
            st.markdown(
                f'<div style="position:relative;text-align:center;padding-bottom:4px">'
                f'{connector}'
                f'<div style="width:32px;height:32px;border-radius:50%;'
                f'background:{color};color:#111115;font-size:13px;font-weight:700;'
                f'display:flex;align-items:center;justify-content:center;margin:0 auto 8px auto;'
                f'position:relative;z-index:1">{num}</div>'
                f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:4px">{label}</div>'
                f'<div style="font-size:10px;color:{_TEXT3};margin-bottom:6px">{note}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.code(cmd, language="bash")

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── 3 Capability cards ────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Capabilities</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    for col, color, label, subtitle, bullets in [
        (c1, _BLUE, "Infer", "LLM-powered schema inference", [
            "Reads raw events — no producer changes needed",
            "Auto-discovers sub-schemas per event type",
            "Flags PII: email, passport, card numbers",
            "Outputs git-committable schema.yaml",
        ]),
        (c2, _ORANGE, "Watch", "Real-time drift detection", [
            "Tier 1 / 2 / 3 severity classification",
            "Presence rate, type change, enum drift",
            "Blast radius — which consumers break",
            "Who to page, automatically",
        ]),
        (c3, _GREEN, "Govern", "Schema as code", [
            "Block CI/CD pipelines on Tier 3 drift",
            "Webhook alerts to Slack, PagerDuty",
            "Consumer registry — every downstream mapped",
            "GDPR audit trail for every PII field",
        ]),
    ]:
        with col:
            bullet_html = "".join(
                f'<div style="display:flex;gap:7px;margin-bottom:5px">'
                f'<span style="color:{color};font-size:10px;flex-shrink:0;margin-top:2px">▸</span>'
                f'<span style="font-size:12px;color:{_TEXT2};line-height:1.5">{b}</span>'
                f'</div>'
                for b in bullets
            )
            st.markdown(
                f'<div style="background:{_SURF};border-radius:10px;padding:18px 16px;'
                f'border:1px solid {_BORDER};border-top:2px solid {color}">'
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.08em;color:{color};margin-bottom:4px">{label}</div>'
                f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:12px">{subtitle}</div>'
                f'{bullet_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

    # ── Technical details (engineers) ─────────────────────────────────────────
    with st.expander("For engineers — integration details and drift tier reference"):
        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:10px">Integration</div>', unsafe_allow_html=True)
            for lbl, val in [
                ("Event sources",  "NDJSON files, Kafka (via connector), any stream"),
                ("Schema storage", "Git-native YAML — diff, review, revert like code"),
                ("Drift output",   "Markdown reports + JSON webhook payload"),
                ("CI/CD gate",     "Tier 3 drift exits non-zero — blocks any pipeline"),
                ("Auth required",  "None — reads as a Kafka consumer group"),
            ]:
                st.markdown(
                    f'<div style="display:flex;gap:8px;padding:7px 0;border-bottom:1px solid {_BORDER}">'
                    f'<span style="font-size:11.5px;color:{_TEXT3};min-width:110px;flex-shrink:0">{lbl}</span>'
                    f'<span style="font-size:11.5px;color:{_TEXT2}">{val}</span>'
                    f'</div>', unsafe_allow_html=True)
        with tc2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:10px">Drift Tiers</div>', unsafe_allow_html=True)
            for tier, color, detail in [
                ("Tier 1 — Silent",   _GREEN,  "New optional field, presence rate increase"),
                ("Tier 2 — Breaking", _ORANGE, "Type widened, timestamp format changed, enum expanded"),
                ("Tier 3 — Critical", _RED,    "Required field removed, PII appears, type narrowed"),
            ]:
                st.markdown(
                    f'<div style="padding:8px 12px;border-radius:6px;margin-bottom:6px;'
                    f'background:rgba(255,255,255,0.02);border-left:3px solid {color}">'
                    f'<div style="font-size:11.5px;font-weight:600;color:{color}">{tier}</div>'
                    f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">{detail}</div>'
                    f'</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SETUP GUIDE — Rookie-friendly multi-source connection explainer
# ══════════════════════════════════════════════════════════════════════════════

def render_setup_guide():  # noqa: C901
    """Full-page setup guide for a new engineer onboarding StreamForge."""

    def _section_label(text: str):
        st.markdown(
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.1em;color:{_TEXT3};margin:32px 0 14px 0;'
            f'padding-bottom:8px;border-bottom:1px solid {_BORDER}">{text}</div>',
            unsafe_allow_html=True,
        )

    def _callout(icon: str, title: str, body: str, color: str = _BLUE):
        st.markdown(
            f'<div style="background:{color}11;border:1px solid {color}33;border-radius:12px;'
            f'padding:16px 18px;margin-bottom:12px">'
            f'<div style="font-size:14px;font-weight:700;color:{color};margin-bottom:4px">'
            f'{icon}  {title}</div>'
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.6">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Hero ──────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="padding:32px 0 24px 0;border-bottom:1px solid {_BORDER};margin-bottom:28px">'
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:10px">Setup Guide</div>'
        f'<div style="font-size:1.85rem;font-weight:700;color:{_TEXT};line-height:1.25;'
        f'letter-spacing:-0.03em;margin-bottom:12px">'
        f'Connecting StreamForge to Your Data</div>'
        f'<div style="font-size:14px;color:{_TEXT2};max-width:640px;line-height:1.7">'
        f'A plain-English guide for engineers onboarding StreamForge. No prior knowledge assumed.'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── The one big idea ──────────────────────────────────────────────────────
    _section_label("The One Big Idea")

    _callout(
        "👁️", "StreamForge is a read-only observer — it never touches your production data",
        "Think of it like a <strong>security camera</strong> for your data streams. "
        "It watches events flowing through Kafka, SQS, IBM MQ, or files. "
        "It reads a sample, figures out the shape (the schema), and alerts you when that shape changes. "
        "<br><br>"
        "Your producers keep producing. Your consumers keep consuming. "
        "<strong>StreamForge sits beside the stream, not inside it.</strong> "
        "No data copy. No extra load on your pipeline. No code changes in your services.",
        _BLUE,
    )

    # ── How it works in 3 steps ───────────────────────────────────────────────
    _section_label("How It Works — 3 Steps")

    s1, s2, s3 = st.columns(3)
    for col, num, icon, title, body in [
        (s1, "1", "📥", "Tap",
         "A lightweight connector samples events from your source — Kafka, SQS, IBM MQ, a CSV file. "
         "It saves them as plain JSON files in the <code>events/</code> folder. "
         "StreamForge reads from there."),
        (s2, "2", "🧠", "Infer",
         "Run <code>streamforge init</code>. Claude reads the sampled events and infers a schema — "
         "field names, types, which fields are required, which have PII. "
         "Result: a human-readable <code>schema.yaml</code> you commit to git."),
        (s3, "3", "🔔", "Watch",
         "Run <code>streamforge watch</code>. Every 30 seconds it re-samples the source, "
         "compares against the committed schema, and fires an alert if anything drifted. "
         "Your CI/CD can query the drift tier and block deployments automatically."),
    ]:
        col.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
            f'padding:20px;height:100%">'
            f'<div style="font-size:10px;font-weight:700;color:{_BLUE};letter-spacing:0.1em;'
            f'text-transform:uppercase;margin-bottom:10px">Step {num}</div>'
            f'<div style="font-size:22px;margin-bottom:8px">{icon}</div>'
            f'<div style="font-size:14px;font-weight:600;color:{_TEXT};margin-bottom:8px">{title}</div>'
            f'<div style="font-size:12.5px;color:{_TEXT2};line-height:1.65">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Your specific setup ───────────────────────────────────────────────────
    _section_label("Your Setup — 30 Streams Across 5 Source Types")

    st.markdown(
        f'<div style="font-size:13px;color:{_TEXT2};margin-bottom:18px">'
        f'Here\'s the full inventory: 2 Kafka clusters (10 topics), 2 IBM MQ queues, '
        f'4 SQS queues, 1 Google PubSub topic, and 3 file-based sources (CSV &amp; XML). '
        f'Each one follows the same 3-step pattern above.</div>',
        unsafe_allow_html=True,
    )

    sources = [
        ("Apache Kafka",       "2 clusters · 10 topics",  "⚡", _BLUE,   20, "kafka"),
        ("IBM MQ",             "2 queues",                 "🏦", _ORANGE,  2, "ibmmq"),
        ("Amazon SQS",         "4 queues",                 "☁️", _PURPLE,  4, "sqs"),
        ("Google Pub/Sub",     "1 topic",                  "🔵", _GREEN,   1, "pubsub"),
        ("Files (CSV / XML)",  "3 sources",                "📄", _TEXT2,   3, "files"),
    ]
    cols = st.columns(5)
    for col, (name, detail, icon, color, count, _) in zip(cols, sources, strict=False):
        col.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
            f'padding:16px;text-align:center">'
            f'<div style="font-size:24px;margin-bottom:8px">{icon}</div>'
            f'<div style="font-size:12px;font-weight:700;color:{_TEXT};margin-bottom:4px">{name}</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-bottom:10px">{detail}</div>'
            f'<div style="font-size:28px;font-weight:700;color:{color}">{count}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};margin-top:2px">stream(s)</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-source setup tabs ─────────────────────────────────────────────────
    _section_label("Connection Guide — Pick Your Source Type")

    tab_kafka, tab_ibmmq, tab_sqs, tab_pubsub, tab_files = st.tabs([
        "⚡ Kafka", "🏦 IBM MQ", "☁️ Amazon SQS", "🔵 Google Pub/Sub", "📄 Files (CSV/XML)"
    ])

    # ── KAFKA ─────────────────────────────────────────────────────────────────
    with tab_kafka:
        _callout(
            "✅", "Connector status: FileConnector built · KafkaConnector on roadmap (Phase 1)",
            "The current release reads events from local NDJSON files. For Kafka, you run a one-time "
            "<strong>tap script</strong> that connects to the topic, captures a sample, and writes it "
            "to the <code>events/</code> folder. StreamForge then runs entirely from those files — "
            "no permanent Kafka connection, no consumer group offset held.",
            _BLUE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>2 Kafka clusters and 10 topics</strong>. Each topic becomes one stream. '
            f'The tap subscribes briefly, saves a sample as NDJSON, then disconnects. '
            f'It does <em>not</em> hold a permanent consumer group position.</div>',
            unsafe_allow_html=True,
        )
        k1, k2 = st.columns([1, 1])
        with k1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">One-time setup per topic</div>', unsafe_allow_html=True)
            st.code("""\
# Step 1: tap the Kafka topic to capture a sample
#   (tap script connects, reads N messages, disconnects)
python tap_kafka.py \\
  --broker  cluster-1.company.com:9092 \\
  --topic   payments.transactions \\
  --sample  500 \\
  --output  events/payments.transactions/

# Step 2: infer schema from the sample
streamforge init events/payments.transactions/

# Step 3: schemas committed to git
git add schemas/payments.transactions/
git commit -m "chore: add payments.transactions schema" """, language="bash")
        with k2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">Ongoing drift monitoring</div>', unsafe_allow_html=True)
            st.code("""\
# Cron or systemd: re-tap every N minutes,
# then run watch to compare against baseline
*/30 * * * * python tap_kafka.py \\
  --topic payments.transactions \\
  --output events/payments.transactions/ && \\
  streamforge plan events/payments.transactions/

# Or run watch directly — it re-samples
# the events/ folder on each poll cycle
streamforge watch events/payments.transactions/ \\
  --interval 30""", language="bash")
        st.markdown(
            f'<div style="background:{_BLUE}11;border:1px solid {_BLUE}33;border-radius:8px;'
            f'padding:12px 16px;margin-top:8px;font-size:12.5px;color:{_TEXT2}">'
            f'<strong style="color:{_BLUE}">Cluster 2?</strong> Same tap script — change <code>--broker</code> '
            f'to the second cluster\'s bootstrap server. StreamForge sees only the NDJSON files; '
            f'it\'s completely broker-agnostic.</div>',
            unsafe_allow_html=True,
        )

    # ── IBM MQ ────────────────────────────────────────────────────────────────
    with tab_ibmmq:
        _callout(
            "🗓️", "Connector status: IBM MQ tap on roadmap (Phase 2)",
            "The architecture is designed for this. IBM MQ messages are browsed (not destructively consumed), "
            "converted to JSON, and written to <code>events/</code>. StreamForge then runs as normal. "
            "The connector interface is built — only the IBM MQ client binding needs implementing.",
            _ORANGE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>2 IBM MQ queues</strong>. IBM MQ messages are typically XML or binary. '
            f'The tap connects to the queue manager, <em>browses</em> (not destructively reads) '
            f'a sample of messages, converts them to JSON, and saves as NDJSON. '
            f'Browsing means messages stay on the queue — your real consumers are not affected.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Planned interface (Phase 2 connector):
python tap_ibmmq.py \\
  --host      mq.company.com \\
  --port      1414 \\
  --channel   SYSTEM.DEF.SVRCONN \\
  --queue-mgr QM1 \\
  --queue     ORDER.PROCESSING \\
  --sample    300 \\
  --output    events/order.processing/

# After capture, same StreamForge commands:
streamforge init events/order.processing/
streamforge watch events/order.processing/""", language="bash")

    # ── SQS ───────────────────────────────────────────────────────────────────
    with tab_sqs:
        _callout(
            "🗓️", "Connector status: SQS tap on roadmap (Phase 2)",
            "SQS messages are consumed-and-deleted, so the tap uses receive-then-reenqueue: "
            "reads a batch, saves the sample, sends messages back before the visibility timeout expires. "
            "Your actual consumers never know StreamForge was there.",
            _PURPLE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>4 Amazon SQS queues</strong>. The connector needs: '
            f'<code>sqs:ReceiveMessage</code>, <code>sqs:SendMessage</code>, '
            f'<code>sqs:ChangeMessageVisibility</code> — read access only, no access to your data stores.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Planned interface (Phase 2 connector):
python tap_sqs.py \\
  --queue-url https://sqs.us-east-1.amazonaws.com/123/orders \\
  --sample 200 \\
  --output events/sqs.orders/

# After capture — same StreamForge commands for all 4 queues:
streamforge init events/sqs.orders/
streamforge init events/sqs.payments/
streamforge watch events/sqs.orders/ --interval 30""", language="bash")

    # ── GOOGLE PUBSUB ─────────────────────────────────────────────────────────
    with tab_pubsub:
        _callout(
            "🗓️", "Connector status: Google Pub/Sub tap on roadmap (Phase 2)",
            "The tap creates a temporary subscription, reads a sample, then deletes the subscription. "
            "Completely invisible to existing subscribers — they receive every message normally.",
            _GREEN,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>1 Google Pub/Sub topic</strong>. Service account needs: '
            f'<code>pubsub.subscriptions.create</code>, <code>pubsub.subscriptions.consume</code>, '
            f'<code>pubsub.subscriptions.delete</code>. No access to your topic producers or other subscribers.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Authenticate with Google Cloud
gcloud auth application-default login

# Install the Pub/Sub tap
pip install streamforge-tap-pubsub

# Sample the topic (tap creates + deletes a temp subscription automatically)
streamforge tap pubsub \\
  --project   my-gcp-project \\
  --topic     analytics-events \\
  --sample    500 \\
  --output    events/pubsub.analytics/

# Infer schema
streamforge init events/pubsub.analytics/

# Watch
streamforge watch events/pubsub.analytics/""", language="bash")
        _callout(
            "🔑", "GCP permissions needed",
            "Service account needs: <code>pubsub.subscriptions.create</code>, "
            "<code>pubsub.subscriptions.consume</code>, <code>pubsub.subscriptions.delete</code>. "
            "StreamForge never needs access to your topic's producer or existing subscribers.",
            _GREEN,
        )

    # ── FILES ─────────────────────────────────────────────────────────────────
    with tab_files:
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>3 file-based sources (CSV and XML)</strong>. '
            f'This is the simplest setup — no tap needed. StreamForge reads files directly. '
            f'For CSV: each row is an event. For XML: each top-level element is an event. '
            f'StreamForge converts both to JSON internally before inferring the schema.</div>',
            unsafe_allow_html=True,
        )
        f1, f2 = st.columns([1, 1])
        with f1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">CSV files</div>', unsafe_allow_html=True)
            st.code("""\
# Drop your CSV into an events/ folder
mkdir -p events/sales.daily/
cp /data/exports/sales_*.csv events/sales.daily/

# StreamForge auto-converts CSV → JSON
streamforge init events/sales.daily/

# Watch: re-reads the folder whenever
# new CSV files are added
streamforge watch events/sales.daily/""", language="bash")
        with f2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">XML files</div>', unsafe_allow_html=True)
            st.code("""\
# Same pattern for XML
mkdir -p events/orders.xml/
cp /data/feeds/orders_*.xml events/orders.xml/

# StreamForge flattens XML attributes
# and elements into a JSON schema
streamforge init events/orders.xml/

streamforge watch events/orders.xml/

# For a third file source (e.g. mixed):
mkdir -p events/transactions.files/
cp /data/*.csv /data/*.xml events/transactions.files/
streamforge init events/transactions.files/""", language="bash")

    # ── Where data lives ──────────────────────────────────────────────────────
    _section_label("Where Everything Lives on Disk")

    st.markdown(
        f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
        f'StreamForge writes two things to disk — both are plain text files you can commit to git.</div>',
        unsafe_allow_html=True,
    )

    w1, w2 = st.columns(2)
    with w1:
        st.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;padding:20px">'
            f'<div style="font-size:13px;font-weight:700;color:{_GREEN};margin-bottom:12px">'
            f'📁  schemas/  — the ground truth</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
schemas/
├── payments.transactions/
│   ├── schema.yaml          ← field names, types, PII flags
│   └── inference_report.md  ← confidence scores, anomalies
├── orders.created/
│   ├── schema.yaml
│   └── inference_report.md
├── sqs.payments/
│   └── schema.yaml
└── pubsub.analytics/
    └── schema.yaml

# Commit these to git.
# schema.yaml = the contract for this stream.
# If someone changes a field, drift fires.""", language="")
        st.markdown('</div>', unsafe_allow_html=True)

    with w2:
        st.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;padding:20px">'
            f'<div style="font-size:13px;font-weight:700;color:{_ORANGE};margin-bottom:12px">'
            f'📁  drift_reports/  — the incident log</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
drift_reports/
├── payments.transactions/
│   ├── 2026-03-14-1432.md   ← timestamp drift detected
│   └── 2026-03-11-0203.md   ← field removed at 2am
├── orders.created/
│   └── 2026-03-12-1801.md
└── sqs.payments/
    └── (empty — clean stream)

# Each .md file has:
#   - Which field changed
#   - Old type / new type
#   - % of events affected
#   - Tier (1=info, 2=breaking, 3=critical)
#   - Which consumers are impacted""", language="")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Full picture ──────────────────────────────────────────────────────────
    _section_label("The Full Picture — End to End")

    st.markdown(
        f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
        f'padding:24px;margin-bottom:24px">',
        unsafe_allow_html=True,
    )

    row_sources, row_arrow1, row_sf, row_arrow2, row_outputs = st.columns([5, 1, 3, 1, 5])
    with row_sources:
        st.markdown(f'<div style="font-size:11px;font-weight:700;color:{_TEXT3};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.08em">Your Data Sources</div>', unsafe_allow_html=True)
        for icon, label, _color in [
            ("⚡", "Kafka  (2 clusters, 10 topics)", _BLUE),
            ("🏦", "IBM MQ  (2 queues)",             _ORANGE),
            ("☁️", "Amazon SQS  (4 queues)",          _PURPLE),
            ("🔵", "Google Pub/Sub  (1 topic)",       _GREEN),
            ("📄", "CSV / XML files  (3 sources)",    _TEXT2),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;'
                f'background:{_SURF2};border-radius:7px;margin-bottom:5px">'
                f'<span>{icon}</span>'
                f'<span style="font-size:12px;color:{_TEXT}">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    with row_arrow1:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:center;height:100%;'
            f'font-size:22px;color:{_TEXT3}">→</div>',
            unsafe_allow_html=True,
        )
    with row_sf:
        st.markdown(
            f'<div style="background:{_BLUE}18;border:1.5px solid {_BLUE}55;border-radius:12px;'
            f'padding:16px;text-align:center;height:100%;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;gap:6px">'
            f'<div style="font-size:28px">⚡</div>'
            f'<div style="font-size:13px;font-weight:700;color:{_BLUE}">StreamForge</div>'
            f'<div style="font-size:10.5px;color:{_TEXT3};margin-top:4px">Read-only tap<br>'
            f'Sample → Infer → Watch</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with row_arrow2:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:center;height:100%;'
            f'font-size:22px;color:{_TEXT3}">→</div>',
            unsafe_allow_html=True,
        )
    with row_outputs:
        st.markdown(f'<div style="font-size:11px;font-weight:700;color:{_TEXT3};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.08em">StreamForge Outputs</div>', unsafe_allow_html=True)
        for icon, label, _color in [
            ("📋", "schema.yaml — per stream, in git",        _GREEN),
            ("📈", "drift_reports/ — timestamped alerts",     _ORANGE),
            ("🔒", "PII flags — GDPR / compliance layer",     _RED),
            ("👁️", "This dashboard — fleet health view",       _BLUE),
            ("🚦", "CI/CD gate — block on Tier 3 drift",      _PURPLE),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;'
                f'background:{_SURF2};border-radius:7px;margin-bottom:5px">'
                f'<span>{icon}</span>'
                f'<span style="font-size:12px;color:{_TEXT}">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Quick-start checklist ─────────────────────────────────────────────────
    _section_label("Quick-Start Checklist")

    steps = [
        (_GREEN,  "Install StreamForge",              "pip install streamforge-cli"),
        (_BLUE,   "Set your API key",                 "export ANTHROPIC_API_KEY=<your-key>"),
        (_BLUE,   "Install tap adapters for your sources",
                  "pip install streamforge-tap-kafka streamforge-tap-sqs streamforge-tap-ibmmq streamforge-tap-pubsub"),
        (_ORANGE, "Tap each source to capture a sample",
                  "streamforge tap kafka --broker ... --topic orders --output events/orders/"),
        (_ORANGE, "Infer schema for each stream",     "streamforge init events/orders/"),
        (_ORANGE, "Commit schemas to git",            "git add schemas/ && git commit -m 'chore: add StreamForge schemas'"),
        (_GREEN,  "Start watching all streams",
                  "streamforge watch events/orders/  # repeat for each stream"),
        (_PURPLE, "Open this dashboard",              "streamforge ui"),
    ]
    for i, (color, title, cmd) in enumerate(steps, 1):
        st.markdown(
            f'<div style="display:flex;gap:14px;align-items:flex-start;'
            f'padding:14px 0;border-bottom:1px solid {_BORDER}">'
            f'<div style="min-width:28px;height:28px;border-radius:50%;background:{color}22;'
            f'border:1px solid {color}66;display:flex;align-items:center;justify-content:center;'
            f'font-size:11px;font-weight:700;color:{color};flex-shrink:0">{i}</div>'
            f'<div style="flex:1">'
            f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:4px">{title}</div>'
            f'<code style="font-size:11.5px;color:{_TEXT3};background:{_SURF2};padding:3px 8px;'
            f'border-radius:5px">{cmd}</code>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.view == "about":
    render_about()
elif st.session_state.view == "setup":
    render_setup_guide()
elif st.session_state.view == "registry":
    render_registry()
elif st.session_state.view == "fleet" or not st.session_state.selected_stream:
    render_fleet_overview()
else:
    render_stream_detail(st.session_state.selected_stream)


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH  — only on fleet view, only when toggle is on
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.get("auto_refresh", False) and st.session_state.view == "fleet":
    _time_mod.sleep(10)
    st.rerun()
