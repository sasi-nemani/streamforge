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

# ruff: noqa: I001
# Re-export public API for backward compatibility (explicit re-exports)
from .components import (
    _build_activity as _build_activity,
    _parse_drift_report_rows as _parse_drift_report_rows,
    _parse_drifted_fields as _parse_drifted_fields,
    _pii_badge as _pii_badge,
    _render_impact_assessment as _render_impact_assessment,
    _status_dot as _status_dot,
    _time_ago as _time_ago,
    _type_badge as _type_badge,
    render_command_bar as render_command_bar,
    render_field_table as render_field_table,
    render_incident_strip as render_incident_strip,
    render_story_hero as render_story_hero,
)
from .data import (
    _is_live as _is_live,
    load_all_schemas as load_all_schemas,
    load_consumers as load_consumers,
    load_drift_reports as load_drift_reports,
    load_open_incidents as load_open_incidents,
    load_policy as load_policy,
    load_poll_state as load_poll_state,
    load_profile as load_profile,
)
from .pages.about import (
    _arrow_md as _arrow_md,
    _node as _node,
    render_about as render_about,
    render_setup_guide as render_setup_guide,
)
from .pages.fleet import render_fleet_overview as render_fleet_overview
from .pages.registry import render_registry as render_registry
from .pages.stream_detail import render_stream_detail as render_stream_detail
from .styling import (
    _BG as _BG,
    _BLUE as _BLUE,
    _BORDER as _BORDER,
    _BORDER2 as _BORDER2,
    _GREEN as _GREEN,
    _ORANGE as _ORANGE,
    _PURPLE as _PURPLE,
    _RED as _RED,
    _SURF as _SURF,
    _SURF2 as _SURF2,
    _SURF3 as _SURF3,
    _TEXT as _TEXT,
    _TEXT2 as _TEXT2,
    _TEXT3 as _TEXT3,
    CONSUMERS_SUBDIR as CONSUMERS_SUBDIR,
    DARK_CSS as DARK_CSS,
    DRIFT_DIR as DRIFT_DIR,
    SCHEMAS_DIR as SCHEMAS_DIR,
)

# Shared state — populated by run_dashboard(), accessed by page modules
_shared_stream_names: list[str] = []
_shared_schemas: dict[str, dict] = {}
_shared_drift_streams: set[str] = set()
_shared_pii_streams: set[str] = set()


def _get_shared_state() -> tuple[list[str], dict[str, dict], set[str], set[str]]:
    """Return (stream_names, schemas, drift_streams, pii_streams)."""
    return _shared_stream_names, _shared_schemas, _shared_drift_streams, _shared_pii_streams


def run_dashboard() -> None:
    """Execute the full Streamlit dashboard. Called when ui.py shim is run."""
    import time as _time_mod

    import streamlit as st

    global _shared_stream_names, _shared_schemas, _shared_drift_streams, _shared_pii_streams

    # ── Page config ───────────────────────────────────────────────────────────
    st.set_page_config(
        page_title="StreamForge",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(DARK_CSS, unsafe_allow_html=True)

    # ── Session state ─────────────────────────────────────────────────────────
    if "selected_stream" not in st.session_state:
        st.session_state.selected_stream = None
    if "view" not in st.session_state:
        st.session_state.view = "fleet"
    if "registry_search" not in st.session_state:
        st.session_state.registry_search = ""

    # ── Shared data — computed once, used in sidebar + main ───────────────────
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

    # Publish to module-level shared state for page modules
    _shared_stream_names = stream_names
    _shared_schemas = schemas
    _shared_drift_streams = _drift_streams
    _shared_pii_streams = _pii_streams

    # ── Sidebar — structured navigation ───────────────────────────────────────
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
            help="Dashboard refreshes every 10 seconds. Ideal for live demos.",
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

    # ── Router ────────────────────────────────────────────────────────────────
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

    # ── Auto-refresh — only on fleet view, only when toggle is on ─────────────
    if st.session_state.get("auto_refresh", False):
        _time_mod.sleep(10)
        st.rerun()
