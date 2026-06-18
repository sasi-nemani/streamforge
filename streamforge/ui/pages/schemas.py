"""
StreamForge Dashboard — Schemas Overview Page

Shows all auto-inferred schemas in an easy-to-understand format:
- Stream name and type
- Field count and structure
- Schema details with expandable view
"""

from __future__ import annotations

from datetime import datetime as _dt

import streamlit as st

from ..components import _type_badge
from ..data import load_profile
from ..styling import (
    _BLUE,
    _BORDER,
    _BORDER2,
    _GREEN,
    _ORANGE,
    _RED,
    _SURF2,
    _TEXT,
    _TEXT2,
    _TEXT3,
)


def _detect_stream_type(stream_name: str) -> tuple[str, str]:
    """Detect stream type from name or config. Returns (type, icon)."""
    sn_lower = stream_name.lower()
    if "kafka" in sn_lower or "events." in sn_lower:
        return "Kafka", "📨"
    elif "sqs" in sn_lower or "queue" in sn_lower:
        return "SQS", "📬"
    elif "mq" in sn_lower or "ibm" in sn_lower:
        return "IBM MQ", "🔗"
    elif "kinesis" in sn_lower:
        return "Kinesis", "🌊"
    elif "pubsub" in sn_lower:
        return "Pub/Sub", "☁️"
    else:
        return "File", "📁"


def _get_inferred_at(stream_name: str, schema: dict) -> str:
    """Get human-readable inference time."""
    inferred_at = schema.get("inferred_at", "")
    if inferred_at:
        try:
            dt = _dt.fromisoformat(inferred_at.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %Y %H:%M")
        except Exception:
            return inferred_at[:16] if len(inferred_at) > 16 else inferred_at
    return "Unknown"


def render_schemas_overview():
    """Render the schemas overview page."""
    from .. import _get_shared_state

    stream_names, schemas, _drift_streams, _pii_streams = _get_shared_state()

    # Header
    st.markdown(
        f'<div style="padding:20px 0 16px 0;border-bottom:1px solid {_BORDER};margin-bottom:20px">'
        f'<h1 style="font-size:1.6rem;font-weight:700;color:{_TEXT};margin:0">📋 Auto-Inferred Schemas</h1>'
        f'<p style="font-size:13px;color:{_TEXT2};margin:6px 0 0 0">'
        f'All schemas discovered by StreamForge. Click any stream to see field details.'
        f'</p></div>',
        unsafe_allow_html=True,
    )

    # Summary metrics
    total_streams = len(stream_names)
    total_fields = sum(len(schemas.get(sn, {}).get("fields", [])) for sn in stream_names)
    total_pii = sum(
        1 for sn in stream_names
        for f in schemas.get(sn, {}).get("fields", [])
        if f.get("pii")
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Streams", total_streams)
    m2.metric("Total Fields", total_fields)
    m3.metric("PII Fields", total_pii)
    m4.metric("Avg Fields/Stream", f"{total_fields // total_streams if total_streams else 0}")

    st.markdown("<br>", unsafe_allow_html=True)

    if not stream_names:
        st.info("No schemas found. Run `streamforge init` to infer your first schema.")
        return

    # Stream cards
    for sn in stream_names:
        sd = schemas.get(sn, {})
        fields = sd.get("fields", [])
        stream_type, stream_icon = _detect_stream_type(sn)
        inferred_at = _get_inferred_at(sn, sd)

        # Check for drift and PII
        has_drift = sn in _drift_streams
        has_pii = sn in _pii_streams

        # Status indicator
        if has_drift:
            status_color = _RED
            status_text = "Drift Detected"
        elif has_pii:
            status_color = _ORANGE
            status_text = "Contains PII"
        else:
            status_color = _GREEN
            status_text = "Healthy"

        # Load profile for multi-schema info
        profile = load_profile(sn)
        sub_schemas = profile.get("sub_schemas", []) if profile else []
        discovery_method = profile.get("discovery_method", "single") if profile else "single"
        routing_field = profile.get("routing_field", None) if profile else None

        with st.expander(
            f"{stream_icon} **{sn}** — {len(fields)} fields · {stream_type}",
            expanded=False
        ):
            # Stream info row
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                st.markdown(
                    f'<div style="background:{_SURF2};border-radius:8px;padding:12px 16px">'
                    f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:6px">Stream Info</div>'
                    f'<div style="font-size:13px;color:{_TEXT}">'
                    f'<strong>Type:</strong> {stream_type}<br>'
                    f'<strong>Inferred:</strong> {inferred_at}<br>'
                    f'<strong>Fields:</strong> {len(fields)}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            with col2:
                if sub_schemas and len(sub_schemas) > 1:
                    st.markdown(
                        f'<div style="background:{_SURF2};border-radius:8px;padding:12px 16px">'
                        f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                        f'letter-spacing:0.1em;margin-bottom:6px">Multi-Schema</div>'
                        f'<div style="font-size:13px;color:{_TEXT}">'
                        f'<strong>Event Types:</strong> {len(sub_schemas)}<br>'
                        f'<strong>Routing Field:</strong> {routing_field or "structural"}<br>'
                        f'<strong>Discovery:</strong> {discovery_method}'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="background:{_SURF2};border-radius:8px;padding:12px 16px">'
                        f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                        f'letter-spacing:0.1em;margin-bottom:6px">Schema Type</div>'
                        f'<div style="font-size:13px;color:{_TEXT}">'
                        f'<strong>Type:</strong> Single schema<br>'
                        f'<strong>Confidence:</strong> {sd.get("inference_confidence", 0.95):.0%}<br>'
                        f'<strong>Model:</strong> {sd.get("inference_model", "statistical")[:20]}'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

            with col3:
                st.markdown(
                    f'<div style="background:{_SURF2};border-radius:8px;padding:12px 16px;text-align:center">'
                    f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:6px">Status</div>'
                    f'<div style="font-size:20px;margin-bottom:4px">'
                    f'{"🔴" if has_drift else "🟡" if has_pii else "🟢"}</div>'
                    f'<div style="font-size:11px;color:{status_color};font-weight:600">'
                    f'{status_text}</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)

            # Fields table
            if fields:
                st.markdown(
                    f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:8px">Field Schema</div>',
                    unsafe_allow_html=True,
                )

                # Table header
                th_style = (
                    f'padding:8px 12px;font-size:10px;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.08em;color:{_TEXT3};background:{_SURF2};text-align:left;'
                    f'border-bottom:1px solid {_BORDER2}'
                )
                td_style = (
                    f'padding:10px 12px;font-size:12px;color:{_TEXT};border-bottom:1px solid {_BORDER};'
                    f'vertical-align:middle'
                )

                rows_html = ""
                for f in fields[:20]:  # Limit to first 20 fields
                    field_path = f.get("path", f.get("name", ""))
                    field_type = f.get("type", f.get("field_type", "string"))
                    required = "✓" if f.get("required", False) else "—"
                    presence = f"{f.get('presence_rate', 1.0):.0%}"
                    pii_tags = f.get("pii", f.get("pii_categories", []))

                    pii_html = ""
                    if pii_tags:
                        pii_html = f'<span style="background:{_ORANGE};color:#000;font-size:9px;' \
                                   f'padding:2px 6px;border-radius:3px;margin-left:6px">' \
                                   f'{", ".join(pii_tags[:2])}</span>'

                    rows_html += (
                        f'<tr>'
                        f'<td style="{td_style}"><code style="font-size:11px;color:{_BLUE}">{field_path}</code>{pii_html}</td>'
                        f'<td style="{td_style}">{_type_badge(field_type)}</td>'
                        f'<td style="{td_style};text-align:center">{required}</td>'
                        f'<td style="{td_style};text-align:center">{presence}</td>'
                        f'</tr>'
                    )

                if len(fields) > 20:
                    rows_html += (
                        f'<tr><td colspan="4" style="{td_style};text-align:center;color:{_TEXT3}">'
                        f'... and {len(fields) - 20} more fields</td></tr>'
                    )

                st.markdown(
                    f'<table style="width:100%;border-collapse:collapse;border:1px solid {_BORDER};'
                    f'border-radius:8px;overflow:hidden">'
                    f'<thead><tr>'
                    f'<th style="{th_style}">Field Path</th>'
                    f'<th style="{th_style}">Type</th>'
                    f'<th style="{th_style};text-align:center">Required</th>'
                    f'<th style="{th_style};text-align:center">Presence</th>'
                    f'</tr></thead>'
                    f'<tbody>{rows_html}</tbody></table>',
                    unsafe_allow_html=True,
                )

            # Multi-schema event types
            if sub_schemas and len(sub_schemas) > 1:
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown(
                    f'<div style="font-size:10px;color:{_TEXT3};text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:8px">Event Types Detected</div>',
                    unsafe_allow_html=True,
                )

                for sub in sub_schemas[:5]:
                    cluster_id = sub.get("cluster_id", "unknown")
                    sample_rate = sub.get("sample_rate", 0)
                    sub_fields = len(sub.get("fields", []))

                    st.markdown(
                        f'<div style="background:{_SURF2};border:1px solid {_BORDER};'
                        f'border-radius:6px;padding:10px 14px;margin-bottom:8px;'
                        f'display:flex;align-items:center;justify-content:space-between">'
                        f'<div>'
                        f'<code style="font-size:12px;color:{_BLUE}">{cluster_id}</code>'
                        f'<span style="font-size:11px;color:{_TEXT3};margin-left:10px">'
                        f'{sub_fields} fields</span>'
                        f'</div>'
                        f'<div style="font-size:11px;color:{_TEXT3}">'
                        f'{sample_rate:.0%} of events'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

                if len(sub_schemas) > 5:
                    st.markdown(
                        f'<div style="font-size:11px;color:{_TEXT3};text-align:center;padding:8px">'
                        f'... and {len(sub_schemas) - 5} more event types</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("<br>", unsafe_allow_html=True)
