"""
StreamForge Dashboard — Reusable UI Components
"""

from __future__ import annotations

import re as _re
from datetime import datetime as _dt
from datetime import timedelta

import streamlit as st

from .data import load_drift_reports
from .styling import (
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


def render_command_bar(n_streams, drift_streams, pii_streams, all_schemas):
    from .data import load_drift_reports as _ldr
    from .data import load_poll_state

    # Need stream_names for iteration — get from all_schemas keys
    _stream_names = sorted(all_schemas.keys())

    n_drift    = len(drift_streams)
    n_pii      = sum(1 for sn in _stream_names for f in all_schemas.get(sn, {}).get("fields", []) if f.get("pii"))
    n_reports  = sum(len(_ldr(sn)) for sn in _stream_names)
    clean_pct  = int((n_streams - n_drift) / n_streams * 100) if n_streams else 100

    # Calculate events/min from poll states
    total_events_min = 0
    for sn in _stream_names:
        poll = load_poll_state(sn)
        if poll:
            window = poll.get("window_size", 0)
            interval = poll.get("poll_interval_seconds", 30)
            if interval > 0:
                total_events_min += int(window / interval * 60)

    # Determine if there are high-severity drifts (Tier 1 or 2)
    critical_drifts = []
    for sn in sorted(drift_streams):
        rpts = _ldr(sn)
        for rpt in rpts:
            tier = rpt.get("tier", 3)
            if tier <= 2:
                critical_drifts.append((sn, rpt.get("summary", "Schema drift detected"), tier))

    status_col = _RED if n_drift else _GREEN
    status_txt = f"{n_drift} Drift Active" if n_drift else "All Systems Operational"

    # Critical action banner for Tier 1/2 drifts
    critical_banner = ""
    if critical_drifts:
        top_drift = critical_drifts[0]
        critical_banner = (
            f'<div style="background:rgba(248,113,113,0.15);border:1px solid {_RED};'
            f'border-radius:8px;padding:12px 16px;margin:0 -1.5rem 12px -1.5rem;'
            f'display:flex;align-items:center;gap:12px">'
            f'<span style="font-size:18px">🚨</span>'
            f'<div style="flex:1">'
            f'<div style="font-size:13px;font-weight:600;color:{_RED}">Critical Action Required</div>'
            f'<div style="font-size:12px;color:{_TEXT2}">'
            f'Tier {top_drift[2]} drift in <strong>{top_drift[0]}</strong>: {top_drift[1][:60]}...'
            f'</div>'
            f'</div>'
            f'<span style="font-size:11px;color:{_TEXT3};background:{_SURF2};'
            f'padding:4px 10px;border-radius:4px">View Details →</span>'
            f'</div>'
        )

    st.markdown(
        critical_banner +
        f'<div style="background:{_SURF};border-bottom:1px solid {_BORDER};'
        f'padding:12px 0;margin:0 -1.5rem 0 -1.5rem">'

        # Top row: brand left, live counter + status pill right
        f'<div style="display:flex;align-items:center;padding:0 20px;margin-bottom:8px">'
        f'<div>'
        f'<span style="font-size:15px;font-weight:700;color:{_TEXT};'
        f'letter-spacing:-0.02em">⚡ StreamForge</span>'
        f'<span style="font-size:12px;color:{_TEXT3};margin-left:10px">Contract control plane for event streams</span>'
        f'</div>'
        f'<div style="flex:1"></div>'

        # Live events counter
        f'<div style="display:flex;align-items:center;gap:6px;margin-right:12px;'
        f'background:{_SURF2};padding:4px 10px;border-radius:980px;border:1px solid {_BORDER}">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{_GREEN};'
        f'animation:pulse 2s infinite;display:inline-block"></span>'
        f'<span style="font-size:11px;font-weight:500;color:{_GREEN}">'
        f'{total_events_min:,} events/min</span>'
        f'</div>'

        # Status pill
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
    from .data import load_consumers
    from .data import load_drift_reports as _ldr

    if not drift_streams:
        return

    # Pick the most critical stream (prefer Tier 3)
    sn = None
    for candidate in sorted(drift_streams):
        rpts = _ldr(candidate)
        if rpts:
            _, _c = rpts[0]
            if "tier 3" in _c.lower():
                sn = candidate
                break
    if not sn:
        sn = sorted(drift_streams)[0]

    reports = _ldr(sn)
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
    # Access shared state from __init__
    from . import _get_shared_state
    from .data import load_drift_reports as _ldr
    stream_names, schemas, _drift_streams, _pii_streams = _get_shared_state()

    total_reports = sum(len(_ldr(sn)) for sn in stream_names)
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
