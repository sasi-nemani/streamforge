"""
StreamForge Dashboard — Fleet Overview Page
"""

from __future__ import annotations

from datetime import datetime as _dt

import streamlit as st

from ..components import (
    _build_activity,
    _parse_drifted_fields,
    _time_ago,
    render_command_bar,
    render_incident_strip,
    render_story_hero,
)
from ..data import _is_live, load_drift_reports, load_poll_state
from ..styling import (
    _BORDER,
    _BORDER2,
    _GREEN,
    _ORANGE,
    _RED,
    _SURF,
    _SURF2,
    _TEXT,
    _TEXT2,
    _TEXT3,
    SCHEMAS_DIR,
)


def render_fleet_overview():
    from .. import _get_shared_state
    stream_names, schemas, _drift_streams, _pii_streams = _get_shared_state()

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
