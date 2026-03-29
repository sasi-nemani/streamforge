"""
StreamForge Dashboard — Backward-compatibility shim.

This file exists so that `streamlit run streamforge/ui.py` continues to work.
All implementation lives in the `streamforge.ui` package (streamforge/ui/__init__.py).
"""

# Re-export everything from the package for any code that does
# `from streamforge.ui import <symbol>` via this file path.
from streamforge.ui import (  # noqa: F401
    _BG,
    _BLUE,
    _BORDER,
    _BORDER2,
    _GREEN,
    _ORANGE,
    _PURPLE,
    _RED,
    _SURF,
    _SURF2,
    _SURF3,
    _TEXT,
    _TEXT2,
    _TEXT3,
    CONSUMERS_SUBDIR,
    DARK_CSS,
    DRIFT_DIR,
    SCHEMAS_DIR,
    _arrow_md,
    _build_activity,
    _is_live,
    _node,
    _parse_drift_report_rows,
    _parse_drifted_fields,
    _pii_badge,
    _render_impact_assessment,
    _status_dot,
    _time_ago,
    _type_badge,
    load_all_schemas,
    load_consumers,
    load_drift_reports,
    load_open_incidents,
    load_policy,
    load_poll_state,
    load_profile,
    render_about,
    render_command_bar,
    render_field_table,
    render_fleet_overview,
    render_incident_strip,
    render_registry,
    render_setup_guide,
    render_story_hero,
    render_stream_detail,
    run_dashboard,  # noqa: F401
)

# When Streamlit runs this file directly, execute the dashboard.
run_dashboard()
