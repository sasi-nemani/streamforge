"""
StreamForge Dashboard — Platform Overview and Setup Guide Pages
"""

from __future__ import annotations

import streamlit as st

from ..styling import (
    _BLUE,
    _BORDER,
    _BORDER2,
    _GREEN,
    _ORANGE,
    _PURPLE,
    _RED,
    _SURF,
    _SURF2,
    _TEXT,
    _TEXT2,
    _TEXT3,
)


def _node(label: str, sub: str = "", color: str = "", accent: str = "") -> str:
    """Render a diagram node as an HTML card string."""
    bg      = f"rgba({','.join(str(int(color.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.08)" if color else _SURF2
    border  = f"rgba({','.join(str(int(color.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.28)" if color else _BORDER2
    tc      = color if color else _TEXT2
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'padding:10px 13px;text-align:center">'
        f'<div style="font-size:12px;font-weight:600;color:{tc}">{label}</div>'
        + (f'<div style="font-size:10.5px;color:{_TEXT3};margin-top:2px">{sub}</div>' if sub else "")
        + '</div>'
    )

def _arrow_md(label: str = "", color: str = "") -> str:
    c = color or _TEXT3
    return (
        f'<div style="text-align:center;padding:6px 0">'
        f'<div style="font-size:18px;color:{c}">→</div>'
        + (f'<div style="font-size:9.5px;color:{c};margin-top:2px">{label}</div>' if label else "")
        + '</div>'
    )

def render_about():

    # ── Hero ──────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="padding:32px 0 24px 0;border-bottom:1px solid {_BORDER};margin-bottom:28px">'
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:10px">Platform Overview</div>'
        f'<div style="font-size:1.85rem;font-weight:700;color:{_TEXT};line-height:1.25;'
        f'letter-spacing:-0.03em;margin-bottom:12px">'
        f'Your data changes.<br>'
        f'Your consumers break.<br>'
        f'<span style="color:{_BLUE}">You find out last.</span></div>'
        f'<div style="font-size:13.5px;color:{_TEXT2};max-width:540px;line-height:1.65">'
        f'Every event stream has a schema. Engineers change fields at 2am. '
        f'Downstream services fail silently. StreamForge is the governance layer '
        f'that catches schema drift <em>before</em> it reaches production.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 3 Pain cards ──────────────────────────────────────────────────────────
    p1, p2, p3 = st.columns(3)
    for col, title, body in [
        (p1, "The 3am Incident",
         "An engineer renames a field. Twelve consumers fail silently. "
         "Six engineers spend six hours diagnosing. Root cause: one field rename."),
        (p2, "The Compliance Audit",
         '"Which streams contain passport numbers?" Three weeks of manual review '
         "across hundreds of Kafka topics. A GDPR audit that should take hours."),
        (p3, "The Unknown Unknown",
         '"We have 200 Kafka topics. Nobody knows what\'s in them." '
         "No schema. No ownership. No blast radius. Just hope nothing breaks."),
    ]:
        with col:
            st.markdown(
                f'<div style="background:{_SURF};border-radius:10px;padding:18px 16px;'
                f'border:1px solid {_BORDER};border-top:2px solid {_RED};height:100%">'
                f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:7px">{title}</div>'
                f'<div style="font-size:12px;color:{_TEXT3};line-height:1.65">{body}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── Architecture diagram — native columns, zero HTML rendering risk ────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Architecture</div>',
        unsafe_allow_html=True,
    )

    # ── WITHOUT row ───────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;'
        f'color:{_TEXT3};display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        f'<span style="width:20px;height:1px;background:{_BORDER2};display:inline-block"></span>'
        f'Without StreamForge'
        f'<span style="flex:1;height:1px;background:{_BORDER2};display:inline-block"></span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    w1, wa1, w2, wa2, w3, wa3, w4 = st.columns([2, 0.4, 2, 0.5, 2, 0.4, 2.2])
    with w1:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER2};border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">PRODUCERS</div>'
            f'<div style="font-size:12px;color:{_TEXT2};margin-bottom:3px">payment-service</div>'
            f'<div style="font-size:12px;color:{_TEXT2}">booking-api</div>'
            f'</div>', unsafe_allow_html=True)
    with wa1:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with w2:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid rgba(96,165,250,0.2);border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">KAFKA TOPICS</div>'
            f'<div style="font-size:12px;color:{_TEXT};margin-bottom:3px">payments.events</div>'
            f'<div style="font-size:12px;color:{_TEXT}">bookings.stream</div>'
            f'</div>', unsafe_allow_html=True)
    with wa2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px">'
            f'<div style="font-size:14px;color:{_TEXT3};margin-bottom:2px">→</div>'
            f'<div style="background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.25);'
            f'border-radius:4px;padding:3px 6px;font-size:9px;color:{_RED};line-height:1.4;'
            f'white-space:nowrap">field<br>renamed</div>'
            f'</div>', unsafe_allow_html=True)
    with w3:
        st.markdown(
            f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.18);'
            f'border-radius:8px;padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">CONSUMERS</div>'
            f'<div style="font-size:12px;color:{_RED};margin-bottom:3px">fraud-detection ✗</div>'
            f'<div style="font-size:12px;color:{_RED}">gdpr-audit ✗</div>'
            f'</div>', unsafe_allow_html=True)
    with wa3:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with w4:
        st.markdown(
            f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.18);'
            f'border-radius:8px;padding:10px 12px">'
            f'<div style="font-size:12px;font-weight:600;color:{_RED}">3am page</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:3px">6 engineers · 6 hours</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">root cause unknown</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)

    # ── WITH row ──────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;'
        f'color:{_BLUE};display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        f'<span style="width:20px;height:1px;background:rgba(96,165,250,0.3);display:inline-block"></span>'
        f'With StreamForge'
        f'<span style="flex:1;height:1px;background:rgba(96,165,250,0.3);display:inline-block"></span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    s1, sa1, s2, sa2, s3, sa3, s4, sa4, s5 = st.columns([2, 0.35, 2, 0.35, 2.4, 0.35, 2, 0.35, 1.8])
    with s1:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid {_BORDER2};border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">PRODUCERS</div>'
            f'<div style="font-size:12px;color:{_TEXT2};margin-bottom:3px">payment-service</div>'
            f'<div style="font-size:12px;color:{_TEXT2}">booking-api</div>'
            f'</div>', unsafe_allow_html=True)
    with sa1:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s2:
        st.markdown(
            f'<div style="background:{_SURF2};border:1px solid rgba(96,165,250,0.2);border-radius:8px;'
            f'padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">KAFKA TOPICS</div>'
            f'<div style="font-size:12px;color:{_TEXT};margin-bottom:3px">payments.events</div>'
            f'<div style="font-size:12px;color:{_TEXT}">bookings.stream</div>'
            f'</div>', unsafe_allow_html=True)
    with sa2:
        st.markdown(
            f'<div style="text-align:center;padding-top:4px">'
            f'<div style="font-size:10px;color:{_TEXT3};margin-bottom:4px;white-space:nowrap">monitors</div>'
            f'<div style="font-size:16px;color:{_TEXT3}">↓</div>'
            f'</div>', unsafe_allow_html=True)
    with s3:
        st.markdown(
            f'<div style="background:rgba(96,165,250,0.06);border:2px solid rgba(96,165,250,0.3);'
            f'border-radius:10px;padding:12px 14px;text-align:center">'
            f'<div style="font-size:13px;font-weight:700;color:{_BLUE};margin-bottom:8px">⚡ StreamForge</div>'
            f'<div style="font-size:11px;color:{_TEXT2};text-align:left;line-height:1.8">'
            f'<span style="color:{_GREEN}">●</span> Schema inferred<br>'
            f'<span style="color:{_ORANGE}">●</span> Drift detected · Tier 3<br>'
            f'<span style="color:{_RED}">●</span> CI/CD deploy blocked<br>'
            f'<span style="color:{_BLUE}">●</span> 3 consumers alerted'
            f'</div>'
            f'</div>', unsafe_allow_html=True)
    with sa3:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s4:
        st.markdown(
            f'<div style="background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.2);'
            f'border-radius:8px;padding:10px 12px;text-align:center">'
            f'<div style="font-size:10px;color:{_TEXT3};letter-spacing:0.05em;margin-bottom:5px">CONSUMERS</div>'
            f'<div style="font-size:12px;color:{_GREEN};margin-bottom:3px">fraud-detection ✓</div>'
            f'<div style="font-size:12px;color:{_GREEN}">gdpr-audit ✓</div>'
            f'</div>', unsafe_allow_html=True)
    with sa4:
        st.markdown(f'<div style="text-align:center;padding-top:16px;font-size:18px;color:{_TEXT3}">→</div>', unsafe_allow_html=True)
    with s5:
        st.markdown(
            f'<div style="background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.2);'
            f'border-radius:8px;padding:10px 12px">'
            f'<div style="font-size:12px;font-weight:600;color:{_GREEN}">Caught in 30s</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:3px">deploy blocked</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">no page · no outage</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── Setup guide — start to finish ─────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Setup — Start to Finish</div>',
        unsafe_allow_html=True,
    )

    steps = [
        ("1", "Install",       "pip install streamforge-cli",                          _BLUE,   "30 seconds"),
        ("2", "Point at data", "streamforge init events/payments/stream_v1",            _BLUE,   "Infers schema via LLM"),
        ("3", "Review schema", "cat schemas/payments.stream_v1/schema.yaml",            _BLUE,   "Git-commit the YAML"),
        ("4", "Start watching","streamforge watch events/payments/stream_v1 --interval 30", _BLUE, "Continuous monitoring"),
        ("5", "Drift fires",   "streamforge plan events/stream_v2 --schema schemas/...", _ORANGE, "One-shot drift check"),
        ("6", "Open dashboard","streamforge ui",                                         _GREEN,  "This dashboard"),
    ]

    setup_cols = st.columns(len(steps))
    for i, (num, label, cmd, color, note) in enumerate(steps):
        with setup_cols[i]:
            connector = (
                f'<div style="position:absolute;top:18px;left:50%;width:100%;height:1px;'
                f'background:{_BORDER2}"></div>'
            ) if i < len(steps) - 1 else ""
            st.markdown(
                f'<div style="position:relative;text-align:center;padding-bottom:4px">'
                f'{connector}'
                f'<div style="width:32px;height:32px;border-radius:50%;'
                f'background:{color};color:#111115;font-size:13px;font-weight:700;'
                f'display:flex;align-items:center;justify-content:center;margin:0 auto 8px auto;'
                f'position:relative;z-index:1">{num}</div>'
                f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:4px">{label}</div>'
                f'<div style="font-size:10px;color:{_TEXT3};margin-bottom:6px">{note}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.code(cmd, language="bash")

    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)

    # ── 3 Capability cards ────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{_TEXT3};margin-bottom:14px">Capabilities</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    for col, color, label, subtitle, bullets in [
        (c1, _BLUE, "Infer", "LLM-powered schema inference", [
            "Reads raw events — no producer changes needed",
            "Auto-discovers sub-schemas per event type",
            "Flags PII: email, passport, card numbers",
            "Outputs git-committable schema.yaml",
        ]),
        (c2, _ORANGE, "Watch", "Real-time drift detection", [
            "Tier 1 / 2 / 3 severity classification",
            "Presence rate, type change, enum drift",
            "Blast radius — which consumers break",
            "Who to page, automatically",
        ]),
        (c3, _GREEN, "Govern", "Schema as code", [
            "Block CI/CD pipelines on Tier 3 drift",
            "Webhook alerts to Slack, PagerDuty",
            "Consumer registry — every downstream mapped",
            "GDPR audit trail for every PII field",
        ]),
    ]:
        with col:
            bullet_html = "".join(
                f'<div style="display:flex;gap:7px;margin-bottom:5px">'
                f'<span style="color:{color};font-size:10px;flex-shrink:0;margin-top:2px">▸</span>'
                f'<span style="font-size:12px;color:{_TEXT2};line-height:1.5">{b}</span>'
                f'</div>'
                for b in bullets
            )
            st.markdown(
                f'<div style="background:{_SURF};border-radius:10px;padding:18px 16px;'
                f'border:1px solid {_BORDER};border-top:2px solid {color}">'
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.08em;color:{color};margin-bottom:4px">{label}</div>'
                f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:12px">{subtitle}</div>'
                f'{bullet_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

    # ── Technical details (engineers) ─────────────────────────────────────────
    with st.expander("For engineers — integration details and drift tier reference"):
        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:10px">Integration</div>', unsafe_allow_html=True)
            for lbl, val in [
                ("Event sources",  "NDJSON files, Kafka (via connector), any stream"),
                ("Schema storage", "Git-native YAML — diff, review, revert like code"),
                ("Drift output",   "Markdown reports + JSON webhook payload"),
                ("CI/CD gate",     "Tier 3 drift exits non-zero — blocks any pipeline"),
                ("Auth required",  "None — reads as a Kafka consumer group"),
            ]:
                st.markdown(
                    f'<div style="display:flex;gap:8px;padding:7px 0;border-bottom:1px solid {_BORDER}">'
                    f'<span style="font-size:11.5px;color:{_TEXT3};min-width:110px;flex-shrink:0">{lbl}</span>'
                    f'<span style="font-size:11.5px;color:{_TEXT2}">{val}</span>'
                    f'</div>', unsafe_allow_html=True)
        with tc2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:10px">Drift Tiers</div>', unsafe_allow_html=True)
            for tier, color, detail in [
                ("Tier 1 — Silent",   _GREEN,  "New optional field, presence rate increase"),
                ("Tier 2 — Breaking", _ORANGE, "Type widened, timestamp format changed, enum expanded"),
                ("Tier 3 — Critical", _RED,    "Required field removed, PII appears, type narrowed"),
            ]:
                st.markdown(
                    f'<div style="padding:8px 12px;border-radius:6px;margin-bottom:6px;'
                    f'background:rgba(255,255,255,0.02);border-left:3px solid {color}">'
                    f'<div style="font-size:11.5px;font-weight:600;color:{color}">{tier}</div>'
                    f'<div style="font-size:11px;color:{_TEXT3};margin-top:2px">{detail}</div>'
                    f'</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SETUP GUIDE — Rookie-friendly multi-source connection explainer
# ══════════════════════════════════════════════════════════════════════════════

def render_setup_guide():  # noqa: C901
    """Full-page setup guide for a new engineer onboarding StreamForge."""

    def _section_label(text: str):
        st.markdown(
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.1em;color:{_TEXT3};margin:32px 0 14px 0;'
            f'padding-bottom:8px;border-bottom:1px solid {_BORDER}">{text}</div>',
            unsafe_allow_html=True,
        )

    def _callout(icon: str, title: str, body: str, color: str = _BLUE):
        st.markdown(
            f'<div style="background:{color}11;border:1px solid {color}33;border-radius:12px;'
            f'padding:16px 18px;margin-bottom:12px">'
            f'<div style="font-size:14px;font-weight:700;color:{color};margin-bottom:4px">'
            f'{icon}  {title}</div>'
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.6">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Hero ──────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="padding:32px 0 24px 0;border-bottom:1px solid {_BORDER};margin-bottom:28px">'
        f'<div style="font-size:10.5px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.1em;color:{_TEXT3};margin-bottom:10px">Setup Guide</div>'
        f'<div style="font-size:1.85rem;font-weight:700;color:{_TEXT};line-height:1.25;'
        f'letter-spacing:-0.03em;margin-bottom:12px">'
        f'Connecting StreamForge to Your Data</div>'
        f'<div style="font-size:14px;color:{_TEXT2};max-width:640px;line-height:1.7">'
        f'A plain-English guide for engineers onboarding StreamForge. No prior knowledge assumed.'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── The one big idea ──────────────────────────────────────────────────────
    _section_label("The One Big Idea")

    _callout(
        "👁️", "StreamForge is a read-only observer — it never touches your production data",
        "Think of it like a <strong>security camera</strong> for your data streams. "
        "It watches events flowing through Kafka, SQS, IBM MQ, or files. "
        "It reads a sample, figures out the shape (the schema), and alerts you when that shape changes. "
        "<br><br>"
        "Your producers keep producing. Your consumers keep consuming. "
        "<strong>StreamForge sits beside the stream, not inside it.</strong> "
        "No data copy. No extra load on your pipeline. No code changes in your services.",
        _BLUE,
    )

    # ── How it works in 3 steps ───────────────────────────────────────────────
    _section_label("How It Works — 3 Steps")

    s1, s2, s3 = st.columns(3)
    for col, num, icon, title, body in [
        (s1, "1", "📥", "Tap",
         "A lightweight connector samples events from your source — Kafka, SQS, IBM MQ, a CSV file. "
         "It saves them as plain JSON files in the <code>events/</code> folder. "
         "StreamForge reads from there."),
        (s2, "2", "🧠", "Infer",
         "Run <code>streamforge init</code>. Claude reads the sampled events and infers a schema — "
         "field names, types, which fields are required, which have PII. "
         "Result: a human-readable <code>schema.yaml</code> you commit to git."),
        (s3, "3", "🔔", "Watch",
         "Run <code>streamforge watch</code>. Every 30 seconds it re-samples the source, "
         "compares against the committed schema, and fires an alert if anything drifted. "
         "Your CI/CD can query the drift tier and block deployments automatically."),
    ]:
        col.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
            f'padding:20px;height:100%">'
            f'<div style="font-size:10px;font-weight:700;color:{_BLUE};letter-spacing:0.1em;'
            f'text-transform:uppercase;margin-bottom:10px">Step {num}</div>'
            f'<div style="font-size:22px;margin-bottom:8px">{icon}</div>'
            f'<div style="font-size:14px;font-weight:600;color:{_TEXT};margin-bottom:8px">{title}</div>'
            f'<div style="font-size:12.5px;color:{_TEXT2};line-height:1.65">{body}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Your specific setup ───────────────────────────────────────────────────
    _section_label("Your Setup — 30 Streams Across 5 Source Types")

    st.markdown(
        f'<div style="font-size:13px;color:{_TEXT2};margin-bottom:18px">'
        f'Here\'s the full inventory: 2 Kafka clusters (10 topics), 2 IBM MQ queues, '
        f'4 SQS queues, 1 Google PubSub topic, and 3 file-based sources (CSV &amp; XML). '
        f'Each one follows the same 3-step pattern above.</div>',
        unsafe_allow_html=True,
    )

    sources = [
        ("Apache Kafka",       "2 clusters · 10 topics",  "⚡", _BLUE,   20, "kafka"),
        ("IBM MQ",             "2 queues",                 "🏦", _ORANGE,  2, "ibmmq"),
        ("Amazon SQS",         "4 queues",                 "☁️", _PURPLE,  4, "sqs"),
        ("Google Pub/Sub",     "1 topic",                  "🔵", _GREEN,   1, "pubsub"),
        ("Files (CSV / XML)",  "3 sources",                "📄", _TEXT2,   3, "files"),
    ]
    cols = st.columns(5)
    for col, (name, detail, icon, color, count, _) in zip(cols, sources, strict=False):
        col.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
            f'padding:16px;text-align:center">'
            f'<div style="font-size:24px;margin-bottom:8px">{icon}</div>'
            f'<div style="font-size:12px;font-weight:700;color:{_TEXT};margin-bottom:4px">{name}</div>'
            f'<div style="font-size:11px;color:{_TEXT3};margin-bottom:10px">{detail}</div>'
            f'<div style="font-size:28px;font-weight:700;color:{color}">{count}</div>'
            f'<div style="font-size:10px;color:{_TEXT3};margin-top:2px">stream(s)</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-source setup tabs ─────────────────────────────────────────────────
    _section_label("Connection Guide — Pick Your Source Type")

    tab_kafka, tab_ibmmq, tab_sqs, tab_pubsub, tab_files = st.tabs([
        "⚡ Kafka", "🏦 IBM MQ", "☁️ Amazon SQS", "🔵 Google Pub/Sub", "📄 Files (CSV/XML)"
    ])

    # ── KAFKA ─────────────────────────────────────────────────────────────────
    with tab_kafka:
        _callout(
            "✅", "Connector status: FileConnector built · KafkaConnector on roadmap (Phase 1)",
            "The current release reads events from local NDJSON files. For Kafka, you run a one-time "
            "<strong>tap script</strong> that connects to the topic, captures a sample, and writes it "
            "to the <code>events/</code> folder. StreamForge then runs entirely from those files — "
            "no permanent Kafka connection, no consumer group offset held.",
            _BLUE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>2 Kafka clusters and 10 topics</strong>. Each topic becomes one stream. '
            f'The tap subscribes briefly, saves a sample as NDJSON, then disconnects. '
            f'It does <em>not</em> hold a permanent consumer group position.</div>',
            unsafe_allow_html=True,
        )
        k1, k2 = st.columns([1, 1])
        with k1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">One-time setup per topic</div>', unsafe_allow_html=True)
            st.code("""\
# Step 1: tap the Kafka topic to capture a sample
#   (tap script connects, reads N messages, disconnects)
python tap_kafka.py \\
  --broker  cluster-1.company.com:9092 \\
  --topic   payments.transactions \\
  --sample  500 \\
  --output  events/payments.transactions/

# Step 2: infer schema from the sample
streamforge init events/payments.transactions/

# Step 3: schemas committed to git
git add schemas/payments.transactions/
git commit -m "chore: add payments.transactions schema" """, language="bash")
        with k2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">Ongoing drift monitoring</div>', unsafe_allow_html=True)
            st.code("""\
# Cron or systemd: re-tap every N minutes,
# then run watch to compare against baseline
*/30 * * * * python tap_kafka.py \\
  --topic payments.transactions \\
  --output events/payments.transactions/ && \\
  streamforge plan events/payments.transactions/

# Or run watch directly — it re-samples
# the events/ folder on each poll cycle
streamforge watch events/payments.transactions/ \\
  --interval 30""", language="bash")
        st.markdown(
            f'<div style="background:{_BLUE}11;border:1px solid {_BLUE}33;border-radius:8px;'
            f'padding:12px 16px;margin-top:8px;font-size:12.5px;color:{_TEXT2}">'
            f'<strong style="color:{_BLUE}">Cluster 2?</strong> Same tap script — change <code>--broker</code> '
            f'to the second cluster\'s bootstrap server. StreamForge sees only the NDJSON files; '
            f'it\'s completely broker-agnostic.</div>',
            unsafe_allow_html=True,
        )

    # ── IBM MQ ────────────────────────────────────────────────────────────────
    with tab_ibmmq:
        _callout(
            "🗓️", "Connector status: IBM MQ tap on roadmap (Phase 2)",
            "The architecture is designed for this. IBM MQ messages are browsed (not destructively consumed), "
            "converted to JSON, and written to <code>events/</code>. StreamForge then runs as normal. "
            "The connector interface is built — only the IBM MQ client binding needs implementing.",
            _ORANGE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>2 IBM MQ queues</strong>. IBM MQ messages are typically XML or binary. '
            f'The tap connects to the queue manager, <em>browses</em> (not destructively reads) '
            f'a sample of messages, converts them to JSON, and saves as NDJSON. '
            f'Browsing means messages stay on the queue — your real consumers are not affected.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Planned interface (Phase 2 connector):
python tap_ibmmq.py \\
  --host      mq.company.com \\
  --port      1414 \\
  --channel   SYSTEM.DEF.SVRCONN \\
  --queue-mgr QM1 \\
  --queue     ORDER.PROCESSING \\
  --sample    300 \\
  --output    events/order.processing/

# After capture, same StreamForge commands:
streamforge init events/order.processing/
streamforge watch events/order.processing/""", language="bash")

    # ── SQS ───────────────────────────────────────────────────────────────────
    with tab_sqs:
        _callout(
            "🗓️", "Connector status: SQS tap on roadmap (Phase 2)",
            "SQS messages are consumed-and-deleted, so the tap uses receive-then-reenqueue: "
            "reads a batch, saves the sample, sends messages back before the visibility timeout expires. "
            "Your actual consumers never know StreamForge was there.",
            _PURPLE,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>4 Amazon SQS queues</strong>. The connector needs: '
            f'<code>sqs:ReceiveMessage</code>, <code>sqs:SendMessage</code>, '
            f'<code>sqs:ChangeMessageVisibility</code> — read access only, no access to your data stores.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Planned interface (Phase 2 connector):
python tap_sqs.py \\
  --queue-url https://sqs.us-east-1.amazonaws.com/123/orders \\
  --sample 200 \\
  --output events/sqs.orders/

# After capture — same StreamForge commands for all 4 queues:
streamforge init events/sqs.orders/
streamforge init events/sqs.payments/
streamforge watch events/sqs.orders/ --interval 30""", language="bash")

    # ── GOOGLE PUBSUB ─────────────────────────────────────────────────────────
    with tab_pubsub:
        _callout(
            "🗓️", "Connector status: Google Pub/Sub tap on roadmap (Phase 2)",
            "The tap creates a temporary subscription, reads a sample, then deletes the subscription. "
            "Completely invisible to existing subscribers — they receive every message normally.",
            _GREEN,
        )
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>1 Google Pub/Sub topic</strong>. Service account needs: '
            f'<code>pubsub.subscriptions.create</code>, <code>pubsub.subscriptions.consume</code>, '
            f'<code>pubsub.subscriptions.delete</code>. No access to your topic producers or other subscribers.</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
# Authenticate with Google Cloud
gcloud auth application-default login

# Install the Pub/Sub tap
pip install streamforge-tap-pubsub

# Sample the topic (tap creates + deletes a temp subscription automatically)
streamforge tap pubsub \\
  --project   my-gcp-project \\
  --topic     analytics-events \\
  --sample    500 \\
  --output    events/pubsub.analytics/

# Infer schema
streamforge init events/pubsub.analytics/

# Watch
streamforge watch events/pubsub.analytics/""", language="bash")
        _callout(
            "🔑", "GCP permissions needed",
            "Service account needs: <code>pubsub.subscriptions.create</code>, "
            "<code>pubsub.subscriptions.consume</code>, <code>pubsub.subscriptions.delete</code>. "
            "StreamForge never needs access to your topic's producer or existing subscribers.",
            _GREEN,
        )

    # ── FILES ─────────────────────────────────────────────────────────────────
    with tab_files:
        st.markdown(
            f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
            f'You have <strong>3 file-based sources (CSV and XML)</strong>. '
            f'This is the simplest setup — no tap needed. StreamForge reads files directly. '
            f'For CSV: each row is an event. For XML: each top-level element is an event. '
            f'StreamForge converts both to JSON internally before inferring the schema.</div>',
            unsafe_allow_html=True,
        )
        f1, f2 = st.columns([1, 1])
        with f1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">CSV files</div>', unsafe_allow_html=True)
            st.code("""\
# Drop your CSV into an events/ folder
mkdir -p events/sales.daily/
cp /data/exports/sales_*.csv events/sales.daily/

# StreamForge auto-converts CSV → JSON
streamforge init events/sales.daily/

# Watch: re-reads the folder whenever
# new CSV files are added
streamforge watch events/sales.daily/""", language="bash")
        with f2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{_TEXT};margin-bottom:8px">XML files</div>', unsafe_allow_html=True)
            st.code("""\
# Same pattern for XML
mkdir -p events/orders.xml/
cp /data/feeds/orders_*.xml events/orders.xml/

# StreamForge flattens XML attributes
# and elements into a JSON schema
streamforge init events/orders.xml/

streamforge watch events/orders.xml/
# For a third file source (e.g. mixed):
mkdir -p events/transactions.files/
cp /data/*.csv /data/*.xml events/transactions.files/
streamforge init events/transactions.files/""", language="bash")

    # ── Where data lives ──────────────────────────────────────────────────────
    _section_label("Where Everything Lives on Disk")

    st.markdown(
        f'<div style="font-size:13px;color:{_TEXT2};line-height:1.7;margin-bottom:16px">'
        f'StreamForge writes two things to disk — both are plain text files you can commit to git.</div>',
        unsafe_allow_html=True,
    )

    w1, w2 = st.columns(2)
    with w1:
        st.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;padding:20px">'
            f'<div style="font-size:13px;font-weight:700;color:{_GREEN};margin-bottom:12px">'
            f'📁  schemas/  — the ground truth</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
schemas/
├── payments.transactions/
│   ├── schema.yaml          ← field names, types, PII flags
│   └── inference_report.md  ← confidence scores, anomalies
├── orders.created/
│   ├── schema.yaml
│   └── inference_report.md
├── sqs.payments/
│   └── schema.yaml
└── pubsub.analytics/
    └── schema.yaml

# Commit these to git.
# schema.yaml = the contract for this stream.
# If someone changes a field, drift fires.""", language="")
        st.markdown('</div>', unsafe_allow_html=True)

    with w2:
        st.markdown(
            f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;padding:20px">'
            f'<div style="font-size:13px;font-weight:700;color:{_ORANGE};margin-bottom:12px">'
            f'📁  drift_reports/  — the incident log</div>',
            unsafe_allow_html=True,
        )
        st.code("""\
drift_reports/
├── payments.transactions/
│   ├── 2026-03-14-1432.md   ← timestamp drift detected
│   └── 2026-03-11-0203.md   ← field removed at 2am
├── orders.created/
│   └── 2026-03-12-1801.md
└── sqs.payments/
    └── (empty — clean stream)

# Each .md file has:
#   - Which field changed
#   - Old type / new type
#   - % of events affected
#   - Tier (1=info, 2=breaking, 3=critical)
#   - Which consumers are impacted""", language="")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Full picture ──────────────────────────────────────────────────────────
    _section_label("The Full Picture — End to End")

    st.markdown(
        f'<div style="background:{_SURF};border:1px solid {_BORDER};border-radius:12px;'
        f'padding:24px;margin-bottom:24px">',
        unsafe_allow_html=True,
    )

    row_sources, row_arrow1, row_sf, row_arrow2, row_outputs = st.columns([5, 1, 3, 1, 5])
    with row_sources:
        st.markdown(f'<div style="font-size:11px;font-weight:700;color:{_TEXT3};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.08em">Your Data Sources</div>', unsafe_allow_html=True)
        for icon, label, _color in [
            ("⚡", "Kafka  (2 clusters, 10 topics)", _BLUE),
            ("🏦", "IBM MQ  (2 queues)",             _ORANGE),
            ("☁️", "Amazon SQS  (4 queues)",          _PURPLE),
            ("🔵", "Google Pub/Sub  (1 topic)",       _GREEN),
            ("📄", "CSV / XML files  (3 sources)",    _TEXT2),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;'
                f'background:{_SURF2};border-radius:7px;margin-bottom:5px">'
                f'<span>{icon}</span>'
                f'<span style="font-size:12px;color:{_TEXT}">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    with row_arrow1:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:center;height:100%;'
            f'font-size:22px;color:{_TEXT3}">→</div>',
            unsafe_allow_html=True,
        )
    with row_sf:
        st.markdown(
            f'<div style="background:{_BLUE}18;border:1.5px solid {_BLUE}55;border-radius:12px;'
            f'padding:16px;text-align:center;height:100%;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;gap:6px">'
            f'<div style="font-size:28px">⚡</div>'
            f'<div style="font-size:13px;font-weight:700;color:{_BLUE}">StreamForge</div>'
            f'<div style="font-size:10.5px;color:{_TEXT3};margin-top:4px">Read-only tap<br>'
            f'Sample → Infer → Watch</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with row_arrow2:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:center;height:100%;'
            f'font-size:22px;color:{_TEXT3}">→</div>',
            unsafe_allow_html=True,
        )
    with row_outputs:
        st.markdown(f'<div style="font-size:11px;font-weight:700;color:{_TEXT3};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.08em">StreamForge Outputs</div>', unsafe_allow_html=True)
        for icon, label, _color in [
            ("📋", "schema.yaml — per stream, in git",        _GREEN),
            ("📈", "drift_reports/ — timestamped alerts",     _ORANGE),
            ("🔒", "PII flags — GDPR / compliance layer",     _RED),
            ("👁️", "This dashboard — fleet health view",       _BLUE),
            ("🚦", "CI/CD gate — block on Tier 3 drift",      _PURPLE),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;'
                f'background:{_SURF2};border-radius:7px;margin-bottom:5px">'
                f'<span>{icon}</span>'
                f'<span style="font-size:12px;color:{_TEXT}">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Quick-start checklist ─────────────────────────────────────────────────
    _section_label("Quick-Start Checklist")

    steps = [
        (_GREEN,  "Install StreamForge",              "pip install streamforge-cli"),
        (_BLUE,   "Set your API key",                 "export ANTHROPIC_API_KEY=<your-key>"),
        (_BLUE,   "Install tap adapters for your sources",
                  "pip install streamforge-tap-kafka streamforge-tap-sqs streamforge-tap-ibmmq streamforge-tap-pubsub"),
        (_ORANGE, "Tap each source to capture a sample",
                  "streamforge tap kafka --broker ... --topic orders --output events/orders/"),
        (_ORANGE, "Infer schema for each stream",     "streamforge init events/orders/"),
        (_ORANGE, "Commit schemas to git",            "git add schemas/ && git commit -m 'chore: add StreamForge schemas'"),
        (_GREEN,  "Start watching all streams",
                  "streamforge watch events/orders/  # repeat for each stream"),
        (_PURPLE, "Open this dashboard",              "streamforge ui"),
    ]
    for i, (color, title, cmd) in enumerate(steps, 1):
        st.markdown(
            f'<div style="display:flex;gap:14px;align-items:flex-start;'
            f'padding:14px 0;border-bottom:1px solid {_BORDER}">'
            f'<div style="min-width:28px;height:28px;border-radius:50%;background:{color}22;'
            f'border:1px solid {color}66;display:flex;align-items:center;justify-content:center;'
            f'font-size:11px;font-weight:700;color:{color};flex-shrink:0">{i}</div>'
            f'<div style="flex:1">'
            f'<div style="font-size:13px;font-weight:600;color:{_TEXT};margin-bottom:4px">{title}</div>'
            f'<code style="font-size:11.5px;color:{_TEXT3};background:{_SURF2};padding:3px 8px;'
            f'border-radius:5px">{cmd}</code>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
