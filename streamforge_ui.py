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

# ── page config ──────────────────────────────────────────────────────────────
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
    """Return {stream_name: raw_yaml_dict} for all schemas found."""
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


def load_policy(stream_name: str) -> dict:
    p = SCHEMAS_DIR / stream_name / "stream_policy.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}


def load_drift_reports(stream_name: str) -> list[dict]:
    """Return list of drift report dicts, newest first."""
    d = DRIFT_DIR / stream_name
    reports = []
    if not d.exists():
        return reports
    for md_path in sorted(d.glob("*.md"), reverse=True):
        reports.append({"filename": md_path.name, "content": md_path.read_text()})
    return reports


def pii_badge(cats: list[str]) -> str:
    if not cats:
        return ""
    return " ".join(f'<span style="background:#7c3aed;color:white;padding:1px 6px;border-radius:4px;font-size:11px">{c}</span>' for c in cats)


def type_badge(t: str) -> str:
    color = TYPE_COLOR.get(t, "#374151")
    return f'<span style="background:{color};color:white;padding:1px 6px;border-radius:4px;font-size:11px">{t}</span>'


def tier_badge(tier: int) -> str:
    color = TIER_COLOR.get(tier, "#6b7280")
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">Tier {tier}</span>'


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ StreamForge")
    st.caption("AI-native schema inference & drift detection")
    st.divider()

    schemas = load_all_schemas()

    if not schemas:
        st.warning("No schemas found.\n\nRun `streamforge init <path>` first.")
        st.stop()

    stream_names = list(schemas.keys())
    selected = st.radio(
        "Streams",
        stream_names,
        format_func=lambda s: f"{'🔴 ' if load_drift_reports(s) else '✅ '}{s}",
    )
    st.divider()
    st.caption(f"{len(stream_names)} stream(s) monitored")
    st.caption("Refresh page to reload from disk")

# ── main content ──────────────────────────────────────────────────────────────

schema = schemas[selected]
fields = schema.get("fields", [])
policy = load_policy(selected)
drift_reports = load_drift_reports(selected)

# Header
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

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_schema, tab_pii, tab_drift, tab_policy = st.tabs(
    ["📋 Schema", "🔒 PII & Compliance", "📊 Drift History", "⚙️ Policy"]
)

# ── TAB: Schema ───────────────────────────────────────────────────────────────
with tab_schema:
    # Summary metrics
    required = [f for f in fields if f.get("required")]
    optional = [f for f in fields if not f.get("required")]
    pii_fields = [f for f in fields if f.get("pii")]
    low_conf = [f for f in fields if f.get("confidence", 1) < 0.8]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total fields", len(fields))
    m2.metric("Required", len(required))
    m3.metric("PII flagged", len(pii_fields))
    m4.metric("Low confidence", len(low_conf))

    st.markdown("#### Fields")

    # Build table rows
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

        # Presence bar
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

    st.markdown(f"""
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
    </table>
    """, unsafe_allow_html=True)

    if schema.get("event_types"):
        st.markdown("#### Event types")
        cols = st.columns(min(len(schema["event_types"]), 6))
        for i, et in enumerate(schema["event_types"]):
            cols[i % len(cols)].code(et)

# ── TAB: PII ──────────────────────────────────────────────────────────────────
with tab_pii:
    pii_fields = [f for f in fields if f.get("pii")]

    if not pii_fields:
        st.success("No PII detected in this stream.")
    else:
        st.warning(f"**{len(pii_fields)} field(s) contain PII.** Ensure compliance with GDPR / CCPA before sharing or storing.")
        st.markdown("")

        for f in pii_fields:
            name = f.get("path", f.get("name", "?"))
            cats = f.get("pii", [])
            ftype = f.get("type", f.get("field_type", ""))
            notes = f.get("notes") or ""

            with st.container():
                col_name, col_cats, col_type = st.columns([2, 2, 1])
                with col_name:
                    st.markdown(f"**`{name}`**")
                    if notes:
                        st.caption(notes[:100])
                with col_cats:
                    st.markdown(pii_badge(cats), unsafe_allow_html=True)
                with col_type:
                    st.markdown(type_badge(ftype), unsafe_allow_html=True)
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
        st.caption("StreamForge will write a report here whenever drift is found during `watch` or `plan`.")
    else:
        st.error(f"**{len(drift_reports)} drift report(s)** on record for this stream.")

        for i, r in enumerate(drift_reports):
            fname = r["filename"]
            # Parse date from filename YYYY-MM-DD-HHMM.md
            try:
                date_str = fname.replace(".md", "")
                dt = datetime.strptime(date_str, "%Y-%m-%d-%H%M")
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
            color = TIER_COLOR[tier_num]
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
