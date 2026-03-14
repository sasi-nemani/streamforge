"""
StreamForge Dashboard — Streamlit UI

Reads schemas/ and drift_reports/ written by the CLI.
No backend, no database. Pure file reader.

Run:  streamlit run streamforge_ui.py
  or: streamforge ui
"""

import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import yaml

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StreamForge",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCHEMAS_DIR = Path("schemas")
DRIFT_DIR = Path("drift_reports")

TIER_COLOR = {1: "#f59e0b", 2: "#f97316", 3: "#ef4444"}
TIER_LABEL = {1: "Tier 1 — Non-breaking", 2: "Tier 2 — Breaking", 3: "Tier 3 — Critical"}
TYPE_COLOR = {
    "email": "#7c3aed", "uuid": "#2563eb", "timestamp_epoch_ms": "#0891b2",
    "timestamp_iso8601": "#0891b2", "timestamp_rfc2822": "#0891b2",
    "integer": "#16a34a", "float": "#16a34a", "boolean": "#ca8a04",
    "mixed": "#dc2626", "null": "#6b7280",
}

# ── helpers ───────────────────────────────────────────────────────────────────

def load_all_schemas() -> dict[str, dict]:
    schemas = {}
    if not SCHEMAS_DIR.exists():
        return schemas
    for p in sorted(SCHEMAS_DIR.glob("*/schema.yaml")):
        try:
            data = yaml.safe_load(p.read_text())
            if data:
                schemas[p.parent.name] = data
        except Exception:
            pass
    return schemas


def load_profile(stream_name: str) -> dict | None:
    p = SCHEMAS_DIR / stream_name / "profile.yaml"
    if p.exists():
        try:
            return yaml.safe_load(p.read_text())
        except Exception:
            return None
    return None


def load_policy(stream_name: str) -> dict:
    p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}


def load_drift_reports(stream_name: str) -> list[dict]:
    d = DRIFT_DIR / stream_name
    reports = []
    if not d.exists():
        return reports
    for md_path in sorted(d.glob("*.md"), reverse=True):
        reports.append({"filename": md_path.name, "content": md_path.read_text()})
    return reports


def has_pii(schema: dict) -> bool:
    return any(f.get("pii") for f in schema.get("fields", []))


def pii_badge(cats: list[str]) -> str:
    if not cats:
        return ""
    return " ".join(
        f'<span style="background:#7c3aed;color:white;padding:1px 6px;border-radius:4px;font-size:11px">{c}</span>'
        for c in cats
    )


def type_badge(t: str) -> str:
    color = TYPE_COLOR.get(t, "#374151")
    return f'<span style="background:{color};color:white;padding:1px 6px;border-radius:4px;font-size:11px">{t}</span>'


def tier_badge(tier: int) -> str:
    color = TIER_COLOR.get(tier, "#6b7280")
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">Tier {tier}</span>'


def render_field_table(fields: list[dict]) -> str:
    """Render a list of field dicts as an HTML table. Reused across Schema and Sub-schemas tabs."""
    rows_html = ""
    for f in fields:
        name = f.get("path", f.get("name", "?"))
        ftype = f.get("type", f.get("field_type", "string"))
        req = "✓" if f.get("required") else "○"
        presence = f.get("presence_rate", 1.0)
        conf = f.get("confidence", 1.0)
        pii = f.get("pii", [])
        notes = (f.get("notes") or "")[:80]
        enum_vals = f.get("enum_values") or []

        pct = int(presence * 100)
        bar_color = "#16a34a" if pct >= 80 else "#f59e0b" if pct >= 50 else "#6b7280"
        bar = (
            f'<div style="background:#e5e7eb;border-radius:4px;height:8px;width:80px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{bar_color};width:{pct}%;height:100%;border-radius:4px"></div></div>'
            f' <span style="font-size:11px;color:#6b7280">{pct}%</span>'
        )

        conf_color = "#16a34a" if conf >= 0.9 else "#f59e0b" if conf >= 0.7 else "#ef4444"
        conf_str = f'<span style="color:{conf_color};font-weight:600">{conf:.0%}</span>'

        enum_str = ""
        if enum_vals:
            shown = enum_vals[:4]
            more = f" +{len(enum_vals)-4}" if len(enum_vals) > 4 else ""
            enum_str = (
                "<br><span style='font-size:10px;color:#6b7280'>"
                + "  ".join(f"<code>{v}</code>" for v in shown) + more
                + "</span>"
            )

        rows_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:13px;padding:8px 12px;border-bottom:1px solid #f3f4f6">
            <strong>{name}</strong>{enum_str}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6">{type_badge(ftype)}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center">{req}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6">{bar}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center">{conf_str}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6">{pii_badge(pii)}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;color:#6b7280;font-size:12px">{notes}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#f9fafb;font-weight:600;color:#374151">
          <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Field</th>
          <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Type</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:2px solid #e5e7eb">Req</th>
          <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Presence</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:2px solid #e5e7eb">Confidence</th>
          <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">PII</th>
          <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Notes</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""


# ── session state ─────────────────────────────────────────────────────────────

if "selected_stream" not in st.session_state:
    st.session_state.selected_stream = "🏠 Fleet Overview"

# ── load data ─────────────────────────────────────────────────────────────────

schemas = load_all_schemas()
stream_names = list(schemas.keys())

# Pre-compute fleet stats
drift_map = {s: load_drift_reports(s) for s in stream_names}
pii_map = {s: has_pii(schemas[s]) for s in stream_names}
streams_with_drift = [s for s in stream_names if drift_map[s]]
streams_with_pii = [s for s in stream_names if pii_map[s]]

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ StreamForge")
    st.caption("AI-native schema inference & drift detection")
    st.divider()

    if not schemas:
        st.warning("No schemas found.\n\nRun `streamforge init <path>` first.")
        st.stop()

    # Navigation — Fleet Overview is always first
    nav_options = ["🏠 Fleet Overview"] + stream_names

    def _stream_label(s: str) -> str:
        if s == "🏠 Fleet Overview":
            return s
        icon = "🔴" if drift_map.get(s) else "✅"
        return f"{icon} {s}"

    # Find current index
    current = st.session_state.selected_stream
    if current not in nav_options:
        current = "🏠 Fleet Overview"
    current_idx = nav_options.index(current)

    selected = st.radio(
        "Navigation",
        nav_options,
        index=current_idx,
        format_func=_stream_label,
        label_visibility="collapsed",
    )
    st.session_state.selected_stream = selected

    st.divider()

    # Fleet stats
    st.markdown("**Fleet Stats**")
    col_a, col_b = st.columns(2)
    col_a.metric("📡 Streams", len(stream_names))
    col_b.metric("🔴 Drift", len(streams_with_drift))
    col_a2, col_b2 = st.columns(2)
    col_a2.metric("🔒 PII", len(streams_with_pii))
    col_b2.metric("✅ Clean", len(stream_names) - len(streams_with_drift))
    st.caption("Refresh page to reload from disk")


# ── FLEET OVERVIEW ────────────────────────────────────────────────────────────

if selected == "🏠 Fleet Overview":

    st.markdown(
        "<h1 style='font-size:2.2rem;margin-bottom:0'>⚡ StreamForge</h1>"
        "<p style='font-size:1.1rem;color:#6b7280;margin-top:4px'>"
        "AI-native schema intelligence for event-driven data platforms"
        "</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Problem statement ─────────────────────────────────────────────────────
    st.markdown("### The problem with data streams at scale")
    st.markdown("")

    card_style = (
        "border-radius:12px;padding:20px 24px;height:100%;min-height:160px;"
        "border:1px solid {border};background:{bg};"
    )

    p1, p2, p3 = st.columns(3)

    with p1:
        st.markdown(
            f'<div style="{card_style.format(bg="#fff7ed", border="#fed7aa")}">'
            "<div style='font-size:1.6rem'>🔥</div>"
            "<div style='font-weight:700;font-size:1rem;margin:8px 0 6px'>The 3am incident</div>"
            "<div style='color:#374151;font-size:0.9rem;line-height:1.5'>"
            "A field changed in the payments stream. Twelve downstream consumers broke. "
            "Four engineers. Six hours. Root cause: nobody knew the schema had drifted."
            "</div></div>",
            unsafe_allow_html=True,
        )

    with p2:
        st.markdown(
            f'<div style="{card_style.format(bg="#faf5ff", border="#d8b4fe")}">'
            "<div style='font-size:1.6rem'>📋</div>"
            "<div style='font-weight:700;font-size:1rem;margin:8px 0 6px'>The compliance audit</div>"
            "<div style='color:#374151;font-size:0.9rem;line-height:1.5'>"
            '"Which of our streams contain PII?" Three weeks of manual review across '
            "200 Kafka topics. GDPR deadline in four weeks. No automated answer existed."
            "</div></div>",
            unsafe_allow_html=True,
        )

    with p3:
        st.markdown(
            f'<div style="{card_style.format(bg="#f0fdf4", border="#86efac")}">'
            "<div style='font-size:1.6rem'>🤷</div>"
            "<div style='font-weight:700;font-size:1rem;margin:8px 0 6px'>The unknown unknowns</div>"
            "<div style='color:#374151;font-size:0.9rem;line-height:1.5'>"
            '"We have 847 Kafka topics. Nobody has current documentation. '
            "New engineers spend weeks just learning what data exists, let alone what shape it's in."
            "</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── How it works ──────────────────────────────────────────────────────────
    st.markdown("### How StreamForge works")
    st.markdown("")

    step_style = (
        "border-radius:10px;padding:18px 20px;text-align:center;"
        "background:{bg};border:1px solid {border};"
    )
    arrow_style = "display:flex;align-items:center;justify-content:center;font-size:1.8rem;color:#9ca3af;padding-top:20px"

    h1, arr1, h2, arr2, h3 = st.columns([3, 1, 3, 1, 3])

    with h1:
        st.markdown(
            f'<div style="{step_style.format(bg="#eff6ff", border="#bfdbfe")}">'
            "<div style='font-size:1.8rem'>📥</div>"
            "<div style='font-weight:700;margin:8px 0 4px;color:#1d4ed8'>1. Ingest</div>"
            "<div style='font-size:0.85rem;color:#374151;line-height:1.5'>"
            "Any format. Structured JSON, broken JSON, log-prefixed lines, mixed event types. "
            "The resilient parser extracts something from everything."
            "</div></div>",
            unsafe_allow_html=True,
        )
    with arr1:
        st.markdown(f'<div style="{arrow_style}">→</div>', unsafe_allow_html=True)
    with h2:
        st.markdown(
            f'<div style="{step_style.format(bg="#f0fdf4", border="#86efac")}">'
            "<div style='font-size:1.8rem'>🔍</div>"
            "<div style='font-weight:700;margin:8px 0 4px;color:#15803d'>2. Discover</div>"
            "<div style='font-size:0.85rem;color:#374151;line-height:1.5'>"
            "AI auto-clusters events by type. Builds a sub-schema per cluster. "
            "Presence rates, PII, types — all inferred. No documentation written."
            "</div></div>",
            unsafe_allow_html=True,
        )
    with arr2:
        st.markdown(f'<div style="{arrow_style}">→</div>', unsafe_allow_html=True)
    with h3:
        st.markdown(
            f'<div style="{step_style.format(bg="#faf5ff", border="#d8b4fe")}">'
            "<div style='font-size:1.8rem'>🛡️</div>"
            "<div style='font-weight:700;margin:8px 0 4px;color:#7c3aed'>3. Govern</div>"
            "<div style='font-size:0.85rem;color:#374151;line-height:1.5'>"
            "Continuous drift detection. PII flagged automatically. "
            "Policy-driven alerts: log, alert, or block deployment before consumers break."
            "</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── Fleet health grid ─────────────────────────────────────────────────────
    n_streams = len(stream_names)
    drift_count = len(streams_with_drift)
    pii_count = len(streams_with_pii)

    st.markdown(f"### Stream fleet — {n_streams} stream(s) monitored")
    if drift_count:
        st.error(f"**{drift_count} stream(s) have drift reports** — review recommended.")
    else:
        st.success("All streams clean — no drift detected.")
    st.markdown("")

    # 3 cards per row
    COLS = 3
    rows = [stream_names[i:i+COLS] for i in range(0, len(stream_names), COLS)]

    for row in rows:
        cols = st.columns(COLS)
        for col, stream in zip(cols, row):
            schema = schemas[stream]
            has_drift_flag = bool(drift_map[stream])
            pii_flag = pii_map[stream]
            fields = schema.get("fields", [])
            pii_fields = [f for f in fields if f.get("pii")]
            conf = schema.get("inference_confidence", 0)
            inferred_at = schema.get("inferred_at", "")
            drift_reports_list = drift_map[stream]

            status_icon = "🔴" if has_drift_flag else "✅"
            border_color = "#fca5a5" if has_drift_flag else "#86efac"
            bg_color = "#fff5f5" if has_drift_flag else "#f0fdf4"

            with col:
                # Stream card
                st.markdown(
                    f'<div style="border:2px solid {border_color};background:{bg_color};'
                    f'border-radius:12px;padding:16px 18px;margin-bottom:8px">'
                    f'<div style="font-size:1.2rem;font-weight:700">{status_icon} {stream}</div>'
                    f'<div style="color:#6b7280;font-size:0.8rem;margin:4px 0 10px">'
                    f'Confidence: <strong>{conf:.0%}</strong>'
                    + (f' &nbsp;·&nbsp; Inferred {inferred_at[:10]}' if inferred_at else '')
                    + '</div>'
                    f'<div style="display:flex;gap:12px;flex-wrap:wrap">'
                    f'<span style="background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:4px;font-size:12px">'
                    f'📋 {len(fields)} fields</span>'
                    + (f'<span style="background:#f3e8ff;color:#7c3aed;padding:2px 8px;border-radius:4px;font-size:12px">'
                       f'🔒 {len(pii_fields)} PII</span>' if pii_fields else '')
                    + (f'<span style="background:#fee2e2;color:#dc2626;padding:2px 8px;border-radius:4px;font-size:12px">'
                       f'⚠ {len(drift_reports_list)} drift</span>' if drift_reports_list else '')
                    + '</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button(f"Inspect →", key=f"inspect_{stream}"):
                    st.session_state.selected_stream = stream
                    st.rerun()

    # Pad empty cells in last row
    if stream_names and len(rows[-1]) < COLS:
        for _ in range(COLS - len(rows[-1])):
            with cols[len(rows[-1]) + _]:
                st.empty()

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── Quick-start reminder ──────────────────────────────────────────────────
    st.markdown("### Quick start")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Collect live data & infer schema:**")
        st.code(
            "python taps/wikipedia.py --max 200\n"
            "streamforge init events/wikipedia/live\n"
            "streamforge ui",
            language="bash",
        )
    with c2:
        st.markdown("**Watch for drift continuously:**")
        st.code(
            "streamforge watch events/wikipedia/live --interval 15\n"
            "# Then open a new terminal and edit a field\n"
            "# Drift report appears in the dashboard automatically",
            language="bash",
        )

    st.stop()


# ── STREAM DETAIL ─────────────────────────────────────────────────────────────

schema = schemas[selected]
fields = schema.get("fields", [])
policy = load_policy(selected)
drift_reports = load_drift_reports(selected)
profile = load_profile(selected)

has_drift = len(drift_reports) > 0
status_icon = "🔴" if has_drift else "✅"
status_text = f"{len(drift_reports)} drift report(s)" if has_drift else "Schema clean"

col_title, col_status = st.columns([3, 1])
with col_title:
    st.title(f"⚡ {selected}")
    st.caption(
        f"v{schema.get('version', '1.0.0')}  •  "
        f"{schema.get('event_count_sampled', '?')} events sampled  •  "
        f"Inferred by {schema.get('inference_model', 'unknown')}  •  "
        f"Confidence {schema.get('inference_confidence', 0):.0%}"
    )
with col_status:
    st.metric(label="Status", value=status_icon, delta=status_text,
              delta_color="inverse" if has_drift else "normal")

st.divider()

# ── tabs ───────────────────────────────────────────────────────────────────────
tab_schema, tab_sub, tab_pii, tab_drift, tab_policy = st.tabs(
    ["📋 Schema", "🧩 Sub-schemas", "🔒 PII & Compliance", "📊 Drift History", "⚙️ Policy"]
)

# ── TAB: Schema ───────────────────────────────────────────────────────────────
with tab_schema:
    required = [f for f in fields if f.get("required")]
    optional = [f for f in fields if not f.get("required")]
    pii_fields = [f for f in fields if f.get("pii")]
    low_conf = [f for f in fields if f.get("confidence", 1) < 0.8]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total fields", len(fields))
    m2.metric("Required", len(required))
    m3.metric("PII flagged", len(pii_fields))
    m4.metric("Low confidence", len(low_conf))

    if profile and len(profile.get("sub_schemas", [])) > 1:
        st.info(
            f"This stream has **{len(profile['sub_schemas'])} sub-schemas** "
            f"(discovery: `{profile.get('discovery_method', '?')}`). "
            "The fields below are from the **primary cluster** only. "
            "See the **Sub-schemas** tab for the full breakdown."
        )

    st.markdown("#### Fields")
    st.markdown(render_field_table(fields), unsafe_allow_html=True)

    if schema.get("event_types"):
        st.markdown("#### Event types in this stream")
        cols = st.columns(min(len(schema["event_types"]), 6))
        for i, et in enumerate(schema["event_types"]):
            cols[i % len(cols)].code(et)

# ── TAB: Sub-schemas ──────────────────────────────────────────────────────────
with tab_sub:
    if not profile:
        st.info(
            "No `profile.yaml` found for this stream yet.\n\n"
            "Re-run `streamforge init` to generate a full multi-cluster profile:\n"
            f"```\nstreamforge init events/{selected}\n```"
        )
    else:
        sub_schemas = profile.get("sub_schemas", [])
        discovery = profile.get("discovery_method", "unknown")
        parse_rate = profile.get("parse_success_rate", 1.0)
        total_sampled = profile.get("total_events_sampled", 0)

        # Metrics row
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Clusters found", len(sub_schemas))
        m2.metric("Discovery method", discovery.replace("_", " "))
        m3.metric("Parse success rate", f"{parse_rate:.1%}")
        m4.metric("Events sampled", total_sampled)

        if not sub_schemas:
            st.warning("Profile exists but contains no sub-schemas.")
            st.stop()

        st.markdown("#### Cluster summary")

        # Cluster summary table
        rows_html = ""
        for sub in sub_schemas:
            cid = sub.get("cluster_id", "?")
            event_count = sub.get("event_count", 0)
            sample_rate = sub.get("sample_rate", 0)
            sub_fields = sub.get("fields", [])
            conf = sub.get("inference_confidence", 0)
            top_keys = sub.get("top_keys", [])

            pii_in_sub = [f for f in sub_fields if f.get("pii")]
            pii_str = ", ".join(
                f'<code>{f["path"]}</code>' for f in pii_in_sub[:3]
            ) if pii_in_sub else "—"
            if len(pii_in_sub) > 3:
                pii_str += f" +{len(pii_in_sub)-3}"

            conf_color = "#16a34a" if conf >= 0.85 else "#f59e0b" if conf >= 0.7 else "#ef4444"
            pct = int(sample_rate * 100)
            bar = (
                f'<div style="background:#e5e7eb;border-radius:4px;height:6px;width:60px;'
                f'display:inline-block;vertical-align:middle">'
                f'<div style="background:#3b82f6;width:{pct}%;height:100%;border-radius:4px"></div></div>'
                f' <span style="font-size:11px;color:#6b7280">{pct}%</span>'
            )

            rows_html += f"""
            <tr>
              <td style="font-family:monospace;font-size:13px;padding:10px 12px;border-bottom:1px solid #f3f4f6;font-weight:600">{cid}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6;text-align:right">{event_count:,}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6">{bar}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6;text-align:center">{len(sub_fields)}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6;text-align:center">
                <span style="color:{conf_color};font-weight:600">{conf:.0%}</span>
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6;font-size:12px">{pii_str}</td>
            </tr>"""

        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:24px">
          <thead>
            <tr style="background:#f9fafb;font-weight:600;color:#374151">
              <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Cluster</th>
              <th style="padding:10px 12px;text-align:right;border-bottom:2px solid #e5e7eb">Events</th>
              <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">% Stream</th>
              <th style="padding:10px 12px;text-align:center;border-bottom:2px solid #e5e7eb">Fields</th>
              <th style="padding:10px 12px;text-align:center;border-bottom:2px solid #e5e7eb">Confidence</th>
              <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #e5e7eb">PII</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        """, unsafe_allow_html=True)

        st.markdown("#### Per-cluster field breakdown")

        for sub in sub_schemas:
            cid = sub.get("cluster_id", "?")
            sub_fields = sub.get("fields", [])
            event_count = sub.get("event_count", 0)
            sample_rate = sub.get("sample_rate", 0)
            conf = sub.get("inference_confidence", 0)
            top_keys = sub.get("top_keys", [])

            pii_in_sub = [f for f in sub_fields if f.get("pii")]
            pii_indicator = f" 🔒 {len(pii_in_sub)} PII" if pii_in_sub else ""

            with st.expander(
                f"**{cid}** — {event_count} events ({sample_rate:.0%}) · "
                f"{len(sub_fields)} fields · {conf:.0%} confidence{pii_indicator}",
                expanded=(len(sub_schemas) == 1),
            ):
                if top_keys:
                    st.caption(f"Top-level keys: `{'`, `'.join(top_keys[:10])}`")
                if sub_fields:
                    st.markdown(render_field_table(sub_fields), unsafe_allow_html=True)
                else:
                    st.info("No fields inferred for this cluster.")

# ── TAB: PII ──────────────────────────────────────────────────────────────────
with tab_pii:
    pii_fields = [f for f in fields if f.get("pii")]

    # Also pull PII from profile sub-schemas if available
    profile_pii: list[tuple[str, dict]] = []  # (cluster_id, field)
    if profile:
        for sub in profile.get("sub_schemas", []):
            for f in sub.get("fields", []):
                if f.get("pii"):
                    profile_pii.append((sub.get("cluster_id", "?"), f))

    all_pii = profile_pii if profile_pii else [(selected, f) for f in pii_fields]

    if not all_pii:
        st.success("No PII detected in this stream.")
    else:
        st.warning(
            f"**{len(all_pii)} PII field(s) detected.** "
            "Ensure compliance with GDPR / CCPA before sharing or storing."
        )
        st.markdown("")

        for cluster_id, f in all_pii:
            name = f.get("path", f.get("name", "?"))
            cats = f.get("pii", [])
            ftype = f.get("type", f.get("field_type", ""))
            notes = f.get("notes") or ""

            with st.container():
                col_name, col_cats, col_type, col_cluster = st.columns([2, 2, 1, 1])
                with col_name:
                    st.markdown(f"**`{name}`**")
                    if notes:
                        st.caption(notes[:100])
                with col_cats:
                    st.markdown(pii_badge(cats), unsafe_allow_html=True)
                with col_type:
                    st.markdown(type_badge(ftype), unsafe_allow_html=True)
                with col_cluster:
                    st.caption(f"in `{cluster_id}`")
                st.divider()

        st.markdown("#### Compliance checklist")
        checks = [
            ("Data minimisation", "Is each PII field strictly necessary?"),
            ("Retention policy", "Are PII fields subject to a deletion schedule?"),
            ("Access control", "Are PII fields masked or excluded from analytics exports?"),
            ("Consent", "Is there a lawful basis for collecting each PII field?"),
        ]
        for label, detail in checks:
            st.checkbox(f"**{label}** — {detail}", key=label)

# ── TAB: Drift ────────────────────────────────────────────────────────────────
with tab_drift:
    if not drift_reports:
        st.success("No drift detected. Schema is clean.")
        st.caption("StreamForge writes a report here when drift is found during `watch` or `plan`.")
    else:
        st.error(f"**{len(drift_reports)} drift report(s)** on record for this stream.")

        for i, r in enumerate(drift_reports):
            fname = r["filename"]
            try:
                dt = datetime.strptime(fname.replace(".md", ""), "%Y-%m-%d-%H%M")
                label = dt.strftime("%d %b %Y at %H:%M")
            except ValueError:
                label = fname

            with st.expander(f"{'🔴' if i == 0 else '📄'} {label}", expanded=(i == 0)):
                st.markdown(r["content"])

# ── TAB: Policy ───────────────────────────────────────────────────────────────
with tab_policy:
    if not policy:
        st.info("No stream_policy.yaml found. Run `streamforge init` to generate one.")
    else:
        st.markdown("#### Alert configuration")

        c1, c2, c3 = st.columns(3)
        c1.metric("Sample size", policy.get("sample_size", 200))
        c2.metric("Poll interval", f"{policy.get('poll_interval_seconds', 30)}s")
        c3.metric("Alert from tier", policy.get("alert_tier", 2))

        st.markdown("#### Actions per tier")
        actions = policy.get("actions", {})
        for tier_key, default in [("tier_1", "log"), ("tier_2", "alert"), ("tier_3", "block")]:
            action = actions.get(tier_key, default)
            tier_num = int(tier_key[-1])
            action_color = {"log": "#6b7280", "alert": "#f97316", "block": "#ef4444"}.get(action, "#6b7280")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:12px;margin:8px 0">'
                f'{tier_badge(tier_num)}'
                f'<span style="color:#374151">{TIER_LABEL[tier_num]}</span>'
                f'<span style="margin-left:auto;background:{action_color};color:white;'
                f'padding:2px 10px;border-radius:4px;font-size:13px;font-weight:600">{action.upper()}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        wh = policy.get("webhook_url")
        st.markdown("#### Webhook")
        if wh:
            st.code(wh)
        else:
            st.caption("No webhook configured. Edit `stream_policy.yaml` to add one.")

        st.markdown("#### Raw policy")
        with st.expander("stream_policy.yaml"):
            policy_path = SCHEMAS_DIR / selected / "stream_policy.yaml"
            if policy_path.exists():
                st.code(policy_path.read_text(), language="yaml")
