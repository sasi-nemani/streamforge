"""
StreamForge Dashboard — Schema Registry Page
"""

from __future__ import annotations

from collections import defaultdict

import streamlit as st

from ..components import _type_badge
from ..styling import (
    _BLUE,
    _BORDER,
    _BORDER2,
    _GREEN,
    _ORANGE,
    _RED,
    _SURF,
    _SURF2,
    _SURF3,
    _TEXT,
    _TEXT2,
    _TEXT3,
)


def render_registry():
    from .. import _get_shared_state
    stream_names, schemas, _drift_streams, _pii_streams = _get_shared_state()

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
