"""
StreamForge Dashboard — Apple Design System
============================================

A single-file Streamlit application. No backend, no database.
All data is read directly from the filesystem (schemas/, drift_reports/).

Layout:
  Sidebar  — Fleet Overview selector + stream list + aggregate stats
  Main     — Fleet Overview page -OR- Stream detail (5 tabs)

Design system: Apple HIG (Human Interface Guidelines) adapted for the web.
  - Font:      SF Pro / Inter (system-ui fallback)
  - Palette:   Apple's canonical colours (blue, green, orange, red, grays)
  - Depth:     Subtle shadows, no hard borders
  - Spacing:   Generous — never cramped
  - Motion:    CSS transitions where Streamlit allows

Run with:  streamforge ui
           streamlit run streamforge_ui.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st
import yaml

# ── Page config (must be the first Streamlit call) ────────────────────────────
st.set_page_config(
    page_title="StreamForge",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Directory conventions ──────────────────────────────────────────────────────
SCHEMAS_DIR      = Path("schemas")
DRIFT_DIR        = Path("drift_reports")
CONSUMERS_SUBDIR = "consumers.yaml"


# ══════════════════════════════════════════════════════════════════════════════
# APPLE DESIGN SYSTEM — CSS
# ══════════════════════════════════════════════════════════════════════════════

APPLE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --sf-bg:            #F5F5F7;
    --sf-card:          #FFFFFF;
    --sf-blue:          #0071E3;
    --sf-blue-dark:     #0077ED;
    --sf-green:         #34C759;
    --sf-orange:        #FF9F0A;
    --sf-red:           #FF3B30;
    --sf-text:          #1D1D1F;
    --sf-text-2:        #6E6E73;
    --sf-text-3:        #AEAEB2;
    --sf-border:        rgba(210,210,215,0.5);
    --sf-border-solid:  #D2D2D7;
    --sf-shadow-sm:     0 1px 4px rgba(0,0,0,0.06),0 2px 8px rgba(0,0,0,0.04);
    --sf-shadow-md:     0 2px 12px rgba(0,0,0,0.08),0 4px 24px rgba(0,0,0,0.04);
    --sf-radius-sm:     10px;
    --sf-radius-md:     14px;
    --sf-radius-lg:     20px;
    --sf-radius-pill:   980px;
    --sf-transition:    0.2s cubic-bezier(0.25,0.46,0.45,0.94);
}

html,body,.stApp {
    background-color: var(--sf-bg) !important;
    font-family: 'Inter',-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',sans-serif !important;
    color: var(--sf-text) !important;
    -webkit-font-smoothing: antialiased !important;
}

[data-testid="stSidebar"] {
    background: rgba(255,255,255,0.92) !important;
    backdrop-filter: blur(24px) saturate(180%) !important;
    border-right: 1px solid var(--sf-border) !important;
}
[data-testid="stSidebar"] .block-container { padding-top:1.5rem !important; }

.main .block-container {
    padding: 1.5rem 2rem 3rem 2rem !important;
    max-width: 1400px !important;
}

h1,h2,h3,h4,h5 {
    font-family: 'Inter',-apple-system,sans-serif !important;
    color: var(--sf-text) !important;
    letter-spacing: -0.02em !important;
}
h1 { font-size:2.25rem !important; font-weight:700 !important; }
h2 { font-size:1.5rem !important;  font-weight:600 !important; }
h3 { font-size:1.15rem !important; font-weight:600 !important; }

[data-testid="stMetric"] {
    background: var(--sf-card) !important;
    border-radius: var(--sf-radius-md) !important;
    padding: 20px 22px !important;
    box-shadow: var(--sf-shadow-sm) !important;
    border: 1px solid var(--sf-border) !important;
    transition: box-shadow var(--sf-transition) !important;
}
[data-testid="stMetric"]:hover { box-shadow: var(--sf-shadow-md) !important; }
[data-testid="stMetricLabel"] {
    font-size:12px !important; font-weight:500 !important;
    text-transform:uppercase !important; letter-spacing:0.06em !important;
    color:var(--sf-text-2) !important;
}
[data-testid="stMetricValue"] {
    font-size:2rem !important; font-weight:700 !important;
    color:var(--sf-text) !important; letter-spacing:-0.03em !important;
}

[data-testid="stTabs"] [role="tablist"] {
    border-bottom: 1px solid var(--sf-border-solid) !important;
    gap: 0 !important; padding-bottom: 0 !important;
}
[data-testid="stTabs"] button[role="tab"] {
    font-family: 'Inter',sans-serif !important; font-size:14px !important;
    font-weight:500 !important; color:var(--sf-text-2) !important;
    padding:10px 16px !important; border-radius:0 !important;
    border-bottom:2px solid transparent !important;
    transition: color var(--sf-transition),border-color var(--sf-transition) !important;
}
[data-testid="stTabs"] button[role="tab"]:hover { color:var(--sf-text) !important; background:transparent !important; }
[data-testid="stTabs"] button[aria-selected="true"] {
    color:var(--sf-blue) !important;
    border-bottom-color:var(--sf-blue) !important;
    background:transparent !important;
}

[data-testid="stExpander"] {
    background: var(--sf-card) !important;
    border: 1px solid var(--sf-border) !important;
    border-radius: var(--sf-radius-md) !important;
    overflow: hidden !important;
    box-shadow: var(--sf-shadow-sm) !important;
    margin-bottom: 8px !important;
}

.stButton > button {
    background: var(--sf-blue) !important;
    color: white !important; border: none !important;
    border-radius: var(--sf-radius-pill) !important;
    font-family: 'Inter',sans-serif !important;
    font-weight: 500 !important; font-size: 14px !important;
    padding: 8px 20px !important;
    transition: background var(--sf-transition),transform var(--sf-transition) !important;
}
.stButton > button:hover {
    background: var(--sf-blue-dark) !important;
    transform: translateY(-1px) !important;
}

[data-testid="stSelectbox"] > div > div {
    border-radius: var(--sf-radius-sm) !important;
    border-color: var(--sf-border-solid) !important;
    background: var(--sf-card) !important;
}

hr {
    border: none !important;
    border-top: 1px solid var(--sf-border-solid) !important;
    margin: 20px 0 !important; opacity: 0.6 !important;
}

code {
    background: rgba(0,0,0,0.04) !important;
    border-radius: 4px !important; font-size:12.5px !important;
    padding: 2px 6px !important; color: var(--sf-text) !important;
    font-family: 'SF Mono','Fira Code','Fira Mono',monospace !important;
}

::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:rgba(0,0,0,0.12); border-radius:3px; }

#MainMenu        { visibility:hidden !important; }
footer           { visibility:hidden !important; }
header           { visibility:hidden !important; }
[data-testid="stDeployButton"] { display:none !important; }
</style>
"""

st.markdown(APPLE_CSS, unsafe_allow_html=True)


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
def load_profile(stream_name: str) -> Optional[dict]:
    p = SCHEMAS_DIR / stream_name / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_consumers(stream_name: str) -> Optional[dict]:
    p = SCHEMAS_DIR / stream_name / CONSUMERS_SUBDIR
    return yaml.safe_load(p.read_text()) if p.exists() else None


@st.cache_data(ttl=30)
def load_drift_reports(stream_name: str) -> list[tuple[str, str]]:
    d = DRIFT_DIR / stream_name
    if not d.exists():
        return []
    return [(f.name, f.read_text()) for f in sorted(d.glob("*.md"), reverse=True)]


@st.cache_data(ttl=30)
def load_policy(stream_name: str) -> Optional[dict]:
    p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════

def _type_badge(ft: str) -> str:
    """Coloured pill for a FieldType value."""
    palettes = {
        "string":             ("#E3F2FD","#1565C0"), "integer":    ("#E8F5E9","#2E7D32"),
        "float":              ("#E8F5E9","#2E7D32"), "boolean":    ("#F3E5F5","#6A1B9A"),
        "timestamp_epoch_ms": ("#FFF8E1","#F57F17"), "timestamp_iso8601": ("#FFF8E1","#F57F17"),
        "timestamp_rfc2822":  ("#FFF8E1","#F57F17"), "date":       ("#FFF8E1","#F57F17"),
        "uuid":               ("#E0F7FA","#00695C"), "email":      ("#FCE4EC","#880E4F"),
        "phone":              ("#FCE4EC","#880E4F"), "array":      ("#F1F8E9","#33691E"),
        "object":             ("#EFEBE9","#4E342E"), "null":       ("#FAFAFA","#9E9E9E"),
        "mixed":              ("#FFF3E0","#E65100"),
    }
    bg, fg = palettes.get(ft, ("#F5F5F5","#424242"))
    return (f'<span style="background:{bg};color:{fg};padding:2px 9px;border-radius:980px;'
            f'font-size:11px;font-weight:600;letter-spacing:0.04em;white-space:nowrap">{ft}</span>')


def _pii_badge(cats: list) -> str:
    if not cats:
        return '<span style="color:#AEAEB2;font-size:12px">—</span>'
    label = ", ".join(str(c) for c in cats[:2])
    if len(cats) > 2: label += f" +{len(cats)-2}"
    return (f'<span style="background:#FFE5E5;color:#C0392B;padding:2px 9px;border-radius:980px;'
            f'font-size:11px;font-weight:600">{label}</span>')


def _status_dot(has_drift: bool, has_pii: bool) -> str:
    if has_drift:
        return '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FF3B30;box-shadow:0 0 6px #FF3B3088;flex-shrink:0"></span>'
    if has_pii:
        return '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FF9F0A;box-shadow:0 0 6px #FF9F0A88;flex-shrink:0"></span>'
    return '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#34C759;box-shadow:0 0 6px #34C75988;flex-shrink:0"></span>'


def render_field_table(fields: list[dict]) -> str:
    """
    Renders a list of field dicts as an Apple-styled HTML table.
    Reused across Schema tab and Sub-schemas tab.
    """
    if not fields:
        return "<p style='color:#6E6E73;font-style:italic;font-size:13px'>No fields.</p>"

    rows = []
    for f in sorted(fields, key=lambda x: -(x.get("presence_rate", 0))):
        path       = f.get("path", "—")
        ftype      = f.get("type", "string")
        required   = f.get("required", False)
        presence   = f.get("presence_rate", 0)
        confidence = f.get("confidence", 0)
        pii        = f.get("pii", [])
        notes      = (f.get("notes") or "")

        req_html = ('<span style="color:#34C759;font-weight:700;font-size:13px">●</span>'
                    if required else
                    '<span style="color:#AEAEB2;font-size:13px">○</span>')

        pct = int(presence * 100)
        bar_c = "#34C759" if pct >= 80 else "#FF9F0A" if pct >= 50 else "#FF3B30"
        pres_html = (
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="width:52px;height:5px;background:#F0F0F0;border-radius:3px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{bar_c};border-radius:3px"></div></div>'
            f'<span style="font-size:12px;color:#6E6E73;font-variant-numeric:tabular-nums">{pct}%</span>'
            f'</div>'
        )

        conf_pct = int(confidence * 100)
        conf_c = "#34C759" if conf_pct >= 80 else "#FF9F0A" if conf_pct >= 60 else "#FF3B30"
        conf_html = f'<span style="color:{conf_c};font-size:12px;font-weight:500">{conf_pct}%</span>'

        notes_html = (f'<span style="color:#6E6E73;font-size:12px">'
                      f'{notes[:70]}{"…" if len(notes)>70 else ""}</span>')

        rows.append(
            f"<tr>"
            f'<td style="padding:10px 12px;font-family:\'SF Mono\',\'Fira Code\',monospace;font-size:12.5px;white-space:nowrap;color:#1D1D1F">{path}</td>'
            f'<td style="padding:10px 12px">{_type_badge(ftype)}</td>'
            f'<td style="padding:10px 12px;text-align:center">{req_html}</td>'
            f'<td style="padding:10px 12px">{pres_html}</td>'
            f'<td style="padding:10px 12px;text-align:center">{conf_html}</td>'
            f'<td style="padding:10px 12px">{_pii_badge(pii)}</td>'
            f'<td style="padding:10px 12px">{notes_html}</td>'
            f"</tr>"
        )

    th = ('font-size:11px;font-weight:600;text-transform:uppercase;'
          'letter-spacing:0.06em;color:#6E6E73;border-bottom:1px solid #E5E5EA')
    header = (
        f'<tr style="background:#F5F5F7">'
        f'<th style="padding:10px 12px;{th}">Field Path</th>'
        f'<th style="padding:10px 12px;{th}">Type</th>'
        f'<th style="padding:10px 12px;{th};text-align:center">Req</th>'
        f'<th style="padding:10px 12px;{th}">Presence</th>'
        f'<th style="padding:10px 12px;{th};text-align:center">Conf.</th>'
        f'<th style="padding:10px 12px;{th}">PII</th>'
        f'<th style="padding:10px 12px;{th}">Notes</th>'
        f'</tr>'
    )

    return (
        '<div style="overflow-x:auto;border-radius:12px;border:1px solid rgba(210,210,215,0.5);'
        'box-shadow:0 1px 4px rgba(0,0,0,0.06)">'
        '<table style="width:100%;border-collapse:collapse;font-family:Inter,-apple-system,sans-serif;font-size:13px">'
        f'<thead>{header}</thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

if "selected_stream" not in st.session_state:
    st.session_state.selected_stream = None
if "view" not in st.session_state:
    st.session_state.view = "fleet"


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

schemas      = load_all_schemas()
stream_names = sorted(schemas.keys())

_drift_streams: set[str] = set()
_pii_streams: set[str] = set()
for _sn in stream_names:
    if load_drift_reports(_sn):
        _drift_streams.add(_sn)
    for _f in schemas.get(_sn, {}).get("fields", []):
        if _f.get("pii"):
            _pii_streams.add(_sn)
            break

with st.sidebar:
    st.markdown(
        '<div style="padding:4px 0 20px 0">'
        '<span style="font-size:22px;font-weight:700;letter-spacing:-0.02em;color:#1D1D1F">⚡ StreamForge</span><br>'
        '<span style="font-size:12px;color:#6E6E73;font-weight:400">Schema Intelligence Platform</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if st.button("🏠  Fleet Overview", use_container_width=True,
                 type="primary" if st.session_state.view == "fleet" else "secondary"):
        st.session_state.view = "fleet"
        st.session_state.selected_stream = None
        st.rerun()

    st.markdown(
        '<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
        'letter-spacing:0.08em;color:#AEAEB2;padding:20px 0 8px 4px">Streams</div>',
        unsafe_allow_html=True,
    )

    if not stream_names:
        st.caption("No streams. Run `streamforge init` first.")
    else:
        for _sn in stream_names:
            _active = st.session_state.selected_stream == _sn and st.session_state.view == "stream"
            _dot    = "🔴 " if _sn in _drift_streams else "🟡 " if _sn in _pii_streams else "✅ "
            if st.button(f"{_dot}{_sn}", key=f"sb_{_sn}", use_container_width=True,
                         type="primary" if _active else "secondary"):
                st.session_state.selected_stream = _sn
                st.session_state.view = "stream"
                st.rerun()

    n_total = len(stream_names)
    n_drift = len(_drift_streams)
    n_pii   = len(_pii_streams)

    if n_total:
        st.markdown("---")
        st.markdown(
            f'<div style="padding:4px 0">'
            f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
            f'letter-spacing:0.08em;color:#AEAEB2;margin-bottom:10px">Fleet Stats</div>'
            f'<div style="font-size:13px;color:#1D1D1F;margin-bottom:5px">📡 {n_total} streams</div>'
            f'<div style="font-size:13px;color:{"#FF3B30" if n_drift else "#34C759"};margin-bottom:5px">'
            f'{"🔴" if n_drift else "✅"} {n_drift} with drift</div>'
            f'<div style="font-size:13px;color:{"#FF9F0A" if n_pii else "#6E6E73"}">'
            f'🔒 {n_pii} with PII</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# FLEET OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def render_fleet_overview():
    st.markdown(
        '<div style="padding:32px 0 8px 0">'
        '<h1 style="font-size:2.6rem;font-weight:700;letter-spacing:-0.03em;color:#1D1D1F;margin:0">⚡ StreamForge</h1>'
        '<p style="font-size:1.15rem;color:#6E6E73;margin:8px 0 0 0;font-weight:400">'
        'AI-native schema intelligence for event streams at any scale.'
        '</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── Pain-point cards ──────────────────────────────────────────────────────
    st.markdown('<h2 style="font-size:1.2rem;font-weight:600;margin:0 0 16px 0">The Problem Every Data Platform Team Faces</h2>', unsafe_allow_html=True)

    CARD = ('background:#FFFFFF;border-radius:16px;padding:24px;'
            'box-shadow:0 2px 12px rgba(0,0,0,0.07);border:1px solid rgba(210,210,215,0.5);min-height:160px')

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div style="{CARD}"><div style="font-size:28px;margin-bottom:10px">🔥</div>'
            '<div style="font-size:15px;font-weight:600;color:#1D1D1F;margin-bottom:8px">The 3am Incident</div>'
            '<div style="font-size:13px;color:#6E6E73;line-height:1.6">Someone renamed <code>amount</code> '
            'at 2:17am. 4 engineers. 6 hours. $2M in delayed settlements.</div></div>',
            unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div style="{CARD}"><div style="font-size:28px;margin-bottom:10px">📋</div>'
            '<div style="font-size:15px;font-weight:600;color:#1D1D1F;margin-bottom:8px">The Compliance Audit</div>'
            '<div style="font-size:13px;color:#6E6E73;line-height:1.6">"Which Kafka topics have passport numbers?" '
            '3 weeks of manual review. Should take 30 seconds.</div></div>',
            unsafe_allow_html=True)
    with c3:
        st.markdown(
            f'<div style="{CARD}"><div style="font-size:28px;margin-bottom:10px">🤷</div>'
            '<div style="font-size:15px;font-weight:600;color:#1D1D1F;margin-bottom:8px">The Unknown Unknowns</div>'
            '<div style="font-size:13px;color:#6E6E73;line-height:1.6">"We have 847 Kafka topics. Nobody knows '
            'what\'s in them, who owns them, or what breaks if they change."</div></div>',
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── How it works ──────────────────────────────────────────────────────────
    st.markdown('<h2 style="font-size:1.2rem;font-weight:600;margin:8px 0 16px 0">How StreamForge Works</h2>', unsafe_allow_html=True)

    STEP = ('background:#FFFFFF;border-radius:16px;padding:24px 20px;text-align:center;'
            'box-shadow:0 2px 12px rgba(0,0,0,0.07);border:1px solid rgba(210,210,215,0.5)')

    s1, arr1, s2, arr2, s3 = st.columns([2, 0.25, 2, 0.25, 2])
    ARR = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:24px;color:#AEAEB2;padding-top:50px">→</div>'

    with s1:
        st.markdown(f'<div style="{STEP}"><div style="font-size:30px;margin-bottom:10px">📥</div>'
            '<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#0071E3;margin-bottom:6px">1 — Ingest</div>'
            '<div style="font-size:14px;font-weight:600;color:#1D1D1F;margin-bottom:6px">Any Format, Any Quality</div>'
            '<div style="font-size:12px;color:#6E6E73;line-height:1.5">Broken JSON, log-prefixed lines, '
            'mixed formats. Resilient parsing with confidence scoring.</div></div>', unsafe_allow_html=True)
    with arr1:
        st.markdown(ARR, unsafe_allow_html=True)
    with s2:
        st.markdown(f'<div style="{STEP}"><div style="font-size:30px;margin-bottom:10px">🔬</div>'
            '<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#0071E3;margin-bottom:6px">2 — Discover</div>'
            '<div style="font-size:14px;font-weight:600;color:#1D1D1F;margin-bottom:6px">Sub-Schema per Event Type</div>'
            '<div style="font-size:12px;color:#6E6E73;line-height:1.5">Structural fingerprinting clusters events. '
            'LLM builds a precise schema per cluster.</div></div>', unsafe_allow_html=True)
    with arr2:
        st.markdown(ARR, unsafe_allow_html=True)
    with s3:
        st.markdown(f'<div style="{STEP}"><div style="font-size:30px;margin-bottom:10px">🛡️</div>'
            '<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#0071E3;margin-bottom:6px">3 — Govern</div>'
            '<div style="font-size:14px;font-weight:600;color:#1D1D1F;margin-bottom:6px">Alert Before Consumers Break</div>'
            '<div style="font-size:12px;color:#6E6E73;line-height:1.5">PSI + chi-squared drift detection. '
            'Slack, CI/CD blocking, blast radius — before prod breaks.</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Fleet health grid ─────────────────────────────────────────────────────
    if not stream_names:
        st.markdown(
            '<div style="background:#F5F5F7;border-radius:16px;padding:48px;text-align:center;border:2px dashed #D2D2D7">'
            '<div style="font-size:40px;margin-bottom:16px">📂</div>'
            '<div style="font-size:18px;font-weight:600;color:#1D1D1F;margin-bottom:8px">No streams yet</div>'
            '<div style="font-size:14px;color:#6E6E73">Run <code>streamforge init events/&lt;stream&gt;</code> '
            'to infer your first schema.</div></div>',
            unsafe_allow_html=True)
    else:
        st.markdown(f'<h2 style="font-size:1.2rem;font-weight:600;margin:8px 0 16px 0">Fleet Health — {len(stream_names)} Streams</h2>', unsafe_allow_html=True)

        cols = st.columns(3)
        for idx, sn in enumerate(stream_names):
            sd          = schemas.get(sn, {})
            has_drift   = sn in _drift_streams
            has_pii     = sn in _pii_streams
            dr          = load_drift_reports(sn)
            all_fields  = sd.get("fields", [])
            pii_fields  = [f for f in all_fields if f.get("pii")]
            confidence  = sd.get("inference_confidence", 0)
            sampled     = sd.get("event_count_sampled", 0)

            if has_drift:
                border_c, status_icon, status_label = "#FF3B30", "🔴", f"{len(dr)} drift report(s)"
            elif has_pii:
                border_c, status_icon, status_label = "#FF9F0A", "🟡", f"{len(pii_fields)} PII field(s)"
            else:
                border_c, status_icon, status_label = "#34C759", "✅", "Schema Clean"

            with cols[idx % 3]:
                st.markdown(
                    f'<div style="background:#FFFFFF;border-radius:16px;padding:22px 20px;'
                    f'box-shadow:0 2px 12px rgba(0,0,0,0.07);border:1px solid rgba(210,210,215,0.5);'
                    f'border-top:3px solid {border_c};margin-bottom:16px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">'
                    f'<div style="font-size:14px;font-weight:600;color:#1D1D1F;word-break:break-word">{sn}</div>'
                    f'<span style="font-size:18px">{status_icon}</span></div>'
                    f'<div style="font-size:12px;font-weight:500;color:{border_c};margin-bottom:12px">{status_label}</div>'
                    f'<div style="font-size:12px;color:#6E6E73;display:flex;flex-direction:column;gap:4px">'
                    f'<span>📊 {len(all_fields)} fields</span>'
                    f'<span>🎯 {confidence:.0%} confidence</span>'
                    f'<span>📅 {sampled:,} events sampled</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button(f"View {sn}", key=f"fc_{sn}", use_container_width=True):
                    st.session_state.selected_stream = sn
                    st.session_state.view = "stream"
                    st.rerun()

    # ── Quick start ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<h2 style="font-size:1.2rem;font-weight:600;margin:8px 0 16px 0">Quick Start</h2>', unsafe_allow_html=True)
    qc1, qc2, qc3, qc4 = st.columns(4)
    for col, title, cmd in [
        (qc1, "Infer Schema",       "streamforge init \\\n  events/payments/stream_v1"),
        (qc2, "Detect Drift",       "streamforge plan \\\n  events/stream_v2 \\\n  --schema schemas/stream_v1/schema.yaml"),
        (qc3, "Watch Continuously", "streamforge watch \\\n  events/payments/stream_v1 \\\n  --interval 30"),
        (qc4, "Export JSON Schema", "streamforge export \\\n  schemas/stream_v1 \\\n  --format json-schema"),
    ]:
        with col:
            st.markdown(
                f'<div style="background:#FFFFFF;border-radius:12px;padding:16px;'
                f'box-shadow:0 1px 6px rgba(0,0,0,0.05);border:1px solid rgba(210,210,215,0.4)">'
                f'<div style="font-size:11px;font-weight:600;color:#0071E3;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.06em">{title}</div>'
                f'<code style="font-size:11px;color:#1D1D1F;white-space:pre-wrap;background:transparent;padding:0">{cmd}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# STREAM DETAIL
# ══════════════════════════════════════════════════════════════════════════════

def render_stream_detail(stream_name: str):
    sd            = schemas.get(stream_name, {})
    profile_data  = load_profile(stream_name)
    drift_reports = load_drift_reports(stream_name)
    policy_data   = load_policy(stream_name)
    consumers_data = load_consumers(stream_name)

    all_fields = sd.get("fields", [])
    pii_fields = [f for f in all_fields if f.get("pii")]

    # ── Header ─────────────────────────────────────────────────────────────────
    dot = _status_dot(bool(drift_reports), bool(pii_fields))
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;padding:20px 0 4px 0">'
        f'{dot}'
        f'<h1 style="font-size:1.8rem;font-weight:700;letter-spacing:-0.02em;color:#1D1D1F;margin:0">{stream_name}</h1>'
        f'</div>'
        f'<p style="color:#6E6E73;font-size:13px;margin:4px 0 20px 22px">'
        f'Inferred {sd.get("inferred_at","")[:10]}  ·  '
        f'Model: {sd.get("inference_model","—")}  ·  '
        f'{sd.get("event_count_sampled",0):,} events  ·  '
        f'v{sd.get("version","1.0.0")}'
        f'</p>',
        unsafe_allow_html=True,
    )

    # ── Metrics ────────────────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Fields",        len(all_fields))
    mc2.metric("Confidence",    f'{sd.get("inference_confidence",0):.0%}')
    mc3.metric("PII Fields",    len(pii_fields))
    mc4.metric("Drift Reports", len(drift_reports))
    mc5.metric("Sub-schemas",   len(profile_data.get("sub_schemas",[])) if profile_data else "—")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ───────────────────────────────────────────────────────────────────
    tab_schema, tab_sub, tab_pii, tab_drift, tab_policy = st.tabs([
        "📋  Schema", "🧩  Sub-schemas", "🔒  PII & Compliance", "📈  Drift History", "⚙️  Policy"
    ])

    # Schema tab
    with tab_schema:
        st.markdown(
            '<p style="color:#6E6E73;font-size:13px;margin-bottom:16px">'
            'Primary schema from the largest cluster. Edit <code>schema.yaml</code> to declare corrections — '
            'it\'s the source of truth for <code>streamforge watch</code> and CI/CD blocking.'
            '</p>',
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
                if p.exists(): st.code(p.read_text(), language="yaml")
        else:
            st.info("No schema found. Run `streamforge init` first.")

    # Sub-schemas tab
    with tab_sub:
        st.markdown(
            '<p style="color:#6E6E73;font-size:13px;margin-bottom:16px">'
            'StreamForge automatically discovers distinct event types in a single stream. '
            'Each cluster gets its own schema — presence rates are computed <em>within</em> the cluster, '
            'not diluted across the whole stream. This is the core differentiator.'
            '</p>',
            unsafe_allow_html=True,
        )
        if not profile_data:
            st.info("No `profile.yaml` found. Re-run `streamforge init` to generate sub-schema profiles.")
        else:
            sub_schemas = profile_data.get("sub_schemas", [])
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("Clusters",        len(sub_schemas))
            hc2.metric("Discovery",        profile_data.get("discovery_method","—").replace("_"," ").title())
            hc3.metric("Parse Rate",       f'{profile_data.get("parse_success_rate",1):.1%}')
            hc4.metric("Events Sampled",   f'{profile_data.get("total_events_sampled",0):,}')
            st.markdown("<br>", unsafe_allow_html=True)

            if sub_schemas:
                # Cluster summary table
                rows = []
                for sub in sub_schemas:
                    cid   = sub.get("cluster_id","—")
                    ev    = sub.get("event_count",0)
                    sr    = sub.get("sample_rate",0)
                    conf  = sub.get("inference_confidence",0)
                    sf    = sub.get("fields",[])
                    pf    = [f for f in sf if f.get("pii")]
                    ps    = ", ".join(f"`{f['path']}`" for f in pf[:2]) + (f" +{len(pf)-2}" if len(pf)>2 else "")
                    rows.append(
                        f"<tr><td style='padding:10px 12px;font-weight:600;font-size:13px'>{cid}</td>"
                        f"<td style='padding:10px 12px;font-size:13px'>{ev:,}</td>"
                        f"<td style='padding:10px 12px;font-size:13px'>{sr:.0%}</td>"
                        f"<td style='padding:10px 12px;font-size:13px'>{len(sf)}</td>"
                        f"<td style='padding:10px 12px;font-size:13px;color:{'#34C759' if conf>=0.8 else '#FF9F0A'}'>{conf:.0%}</td>"
                        f"<td style='padding:10px 12px;font-size:12px;color:#6E6E73'>{ps or '—'}</td></tr>"
                    )
                th_s = 'font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:#6E6E73;border-bottom:1px solid #E5E5EA'
                st.markdown(
                    '<div style="overflow-x:auto;border-radius:12px;border:1px solid rgba(210,210,215,0.5);margin-bottom:20px">'
                    '<table style="width:100%;border-collapse:collapse">'
                    f'<thead><tr style="background:#F5F5F7">'
                    f'<th style="padding:10px 12px;{th_s}">Cluster</th>'
                    f'<th style="padding:10px 12px;{th_s}">Events</th>'
                    f'<th style="padding:10px 12px;{th_s}">% Stream</th>'
                    f'<th style="padding:10px 12px;{th_s}">Fields</th>'
                    f'<th style="padding:10px 12px;{th_s}">Confidence</th>'
                    f'<th style="padding:10px 12px;{th_s}">PII</th>'
                    f'</tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table></div>',
                    unsafe_allow_html=True,
                )
                for sub in sub_schemas:
                    cid = sub.get("cluster_id","—")
                    sf  = sub.get("fields",[])
                    tk  = sub.get("top_keys",[])
                    with st.expander(f"🔍  {cid}  —  {sub.get('event_count',0):,} events  ·  {sub.get('inference_confidence',0):.0%} confidence"):
                        if tk:
                            st.markdown(
                                f'<div style="font-size:12px;color:#6E6E73;margin-bottom:12px">Top keys: '
                                + " · ".join(f"<code>{k}</code>" for k in tk[:10])
                                + '</div>', unsafe_allow_html=True)
                        st.markdown(render_field_table(sf), unsafe_allow_html=True)

    # PII tab
    with tab_pii:
        st.markdown(
            '<p style="color:#6E6E73;font-size:13px;margin-bottom:16px">'
            'PII detected via regex patterns and field-name heuristics — no LLM required. '
            'Runs on every <code>init</code>. Sub-schemas are checked independently.'
            '</p>', unsafe_allow_html=True)
        if not pii_fields:
            st.success("✅ No PII detected in primary schema.")
        else:
            st.warning(f"⚠️ {len(pii_fields)} PII field(s) — review for GDPR/CCPA compliance.")
            st.markdown(render_field_table(pii_fields), unsafe_allow_html=True)

        if profile_data:
            for sub in profile_data.get("sub_schemas",[]):
                spii = [f for f in sub.get("fields",[]) if f.get("pii")]
                if spii:
                    with st.expander(f"🔒 PII in {sub.get('cluster_id','—')}"):
                        st.markdown(render_field_table(spii), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<h3 style="font-size:15px;font-weight:600;margin-bottom:12px">Compliance Checklist</h3>', unsafe_allow_html=True)
        for title, desc in [
            ("Data Minimisation",  "Only collect PII necessary for the stated purpose. Review fields above."),
            ("Retention Policy",   "Kafka retention for PII topics: default 7 days may violate GDPR Art. 5(1)(e)."),
            ("Access Controls",    "Kafka ACLs must restrict read access to PII topics to authorised consumers only."),
            ("Encryption in Transit", "All PII topics must use TLS. Check broker security.protocol configuration."),
            ("Right to Erasure",   "GDPR Art. 17: you must be able to delete/anonymise a user's data across all consumers."),
            ("Consent Lineage",    "Every PII field should be traceable to a consent event. Register consumers in consumers.yaml."),
        ]:
            icon = "⚠️" if pii_fields else "✅"
            st.markdown(
                f'<div style="background:#FFFFFF;border-radius:10px;padding:14px 16px;margin-bottom:8px;'
                f'box-shadow:0 1px 4px rgba(0,0,0,0.05);border:1px solid rgba(210,210,215,0.4)">'
                f'<div style="font-size:13px;font-weight:600;color:#1D1D1F;margin-bottom:4px">{icon} {title}</div>'
                f'<div style="font-size:12px;color:#6E6E73">{desc}</div></div>',
                unsafe_allow_html=True)

    # Drift tab
    with tab_drift:
        st.markdown(
            '<p style="color:#6E6E73;font-size:13px;margin-bottom:16px">'
            'Reports generated by <code>streamforge watch</code> or <code>streamforge plan</code>. '
            'Tier 3 = critical (CI blocking) · Tier 2 = breaking · Tier 1 = informational.'
            '</p>', unsafe_allow_html=True)
        if not drift_reports:
            st.markdown(
                '<div style="background:#F0FFF4;border-radius:12px;padding:24px;text-align:center;border:1px solid #C6F6D5">'
                '<div style="font-size:24px;margin-bottom:8px">✅</div>'
                '<div style="font-size:15px;font-weight:600;color:#276749">Schema is clean</div>'
                '<div style="font-size:13px;color:#48BB78;margin-top:4px">'
                'Run <code>streamforge watch</code> to monitor continuously.</div></div>',
                unsafe_allow_html=True)
        else:
            for i, (fname, content) in enumerate(drift_reports):
                tc = "#FF3B30" if "tier 3" in content.lower() else "#FF9F0A" if "tier 2" in content.lower() else "#34C759"
                with st.expander(f"{'🆕' if i==0 else '📋'} {fname}", expanded=(i==0)):
                    st.markdown(f'<div style="border-left:3px solid {tc};padding-left:12px;margin-bottom:12px;'
                                f'font-size:12px;color:{tc};font-weight:600">'
                                f'{"🔴 Critical" if tc=="#FF3B30" else "⚠️ Breaking" if tc=="#FF9F0A" else "✅ Informational"}'
                                f'</div>', unsafe_allow_html=True)
                    st.markdown(content)

    # Policy tab
    with tab_policy:
        st.markdown(
            '<p style="color:#6E6E73;font-size:13px;margin-bottom:16px">'
            'Controls how StreamForge responds to drift. Edit <code>stream_policy.yaml</code> '
            'alongside <code>schema.yaml</code> — changes take effect on next poll cycle.'
            '</p>', unsafe_allow_html=True)

        if not policy_data:
            st.info("No policy found. Run `streamforge init` to generate a default policy.")
        else:
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Sample Size",   f'{policy_data.get("sample_size",200):,} events')
            pc2.metric("Poll Interval", f'{policy_data.get("poll_interval_seconds",30)}s')
            pc3.metric("Alert Tier",    f'Tier {policy_data.get("alert_tier",2)}+')
            st.markdown("<br>", unsafe_allow_html=True)

            actions = policy_data.get("actions", {})
            action_html = ""
            for tk, action in actions.items():
                bg = {"log":"#F0F0F0","alert":"#FFF8E1","block":"#FFEBEE"}.get(action,"#F5F5F5")
                fg = {"log":"#6E6E73","alert":"#F57F17","block":"#C62828"}.get(action,"#6E6E73")
                action_html += (
                    f'<div style="display:flex;align-items:center;padding:12px 16px;background:{bg};'
                    f'border-radius:8px;margin-bottom:8px">'
                    f'<div style="font-size:13px;font-weight:600;color:#1D1D1F">{tk.replace("_"," ").title()}</div>'
                    f'<div style="flex:1"></div>'
                    f'<span style="background:white;color:{fg};border:1px solid {fg};padding:3px 12px;'
                    f'border-radius:980px;font-size:11px;font-weight:700;letter-spacing:0.06em">{action.upper()}</span>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="background:#FFFFFF;border-radius:12px;padding:16px;'
                f'box-shadow:0 1px 6px rgba(0,0,0,0.05);border:1px solid rgba(210,210,215,0.4)">'
                f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;'
                f'color:#AEAEB2;margin-bottom:12px">Drift Response Actions</div>'
                f'{action_html}</div>',
                unsafe_allow_html=True)

            # Consumer registry
            st.markdown("---")
            st.markdown('<h3 style="font-size:15px;font-weight:600;margin-bottom:12px">Consumer Registry & Blast Radius</h3>', unsafe_allow_html=True)
            st.markdown(
                '<p style="color:#6E6E73;font-size:13px;margin-bottom:12px">'
                'Declare which services read this stream. When drift is detected, StreamForge computes '
                'the blast radius — exactly which consumers break and who to page.'
                '</p>', unsafe_allow_html=True)
            if consumers_data:
                for c in consumers_data.get("consumers", []):
                    crit = c.get("criticality","tier3")
                    cc   = {"tier1":"#FF3B30","tier2":"#FF9F0A","tier3":"#34C759"}.get(crit,"#6E6E73")
                    with st.expander(f"👤 {c.get('name','?')} — {c.get('team','?')} — {crit.upper()}"):
                        st.markdown(
                            f'**Contact:** {c.get("contact","—")}  \n'
                            f'**Schema version:** {c.get("schema_version","—")}  \n'
                            + (f'**Description:** {c.get("description","")}  \n' if c.get("description") else "")
                            + (f'**Runbook:** {c.get("runbook","")}' if c.get("runbook") else "")
                        )
                        fps = [f.get("path","?") for f in c.get("fields_used",[])]
                        if fps:
                            st.markdown("**Fields used:** " + " · ".join(f"`{p}`" for p in fps[:10]))
            else:
                st.info(
                    "No `consumers.yaml` yet.  \n"
                    f"A template was created at `schemas/{stream_name}/consumers.yaml` — "
                    "fill it in to enable blast radius analysis."
                )

            with st.expander("🗂  Raw stream_policy.yaml"):
                p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
                if p.exists(): st.code(p.read_text(), language="yaml")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.view == "fleet" or not st.session_state.selected_stream:
    render_fleet_overview()
else:
    render_stream_detail(st.session_state.selected_stream)
