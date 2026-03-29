"""
StreamForge Dashboard — Stream Detail Page
"""

from __future__ import annotations

from datetime import datetime as _dt

import streamlit as st

from ..components import (
    _parse_drift_report_rows,
    _parse_drifted_fields,
    _render_impact_assessment,
    render_field_table,
)
from ..data import (
    _is_live,
    load_consumers,
    load_drift_reports,
    load_open_incidents,
    load_policy,
    load_poll_state,
    load_profile,
)
from ..styling import (
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
    SCHEMAS_DIR,
)


def render_stream_detail(stream_name: str):
    from .. import _get_shared_state
    stream_names, schemas, _drift_streams, _pii_streams = _get_shared_state()

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
