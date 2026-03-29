"""
StreamForge Dashboard — Design Tokens and CSS
"""

from __future__ import annotations

# ── Directory conventions ─────────────────────────────────────────────────────
from pathlib import Path

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
