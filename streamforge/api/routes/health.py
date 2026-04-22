"""
Health check endpoints for Kubernetes probes.

Endpoints:
- /health      → Overall system health (liveness probe)
- /ready       → Readiness to accept traffic (readiness probe)
- /startup     → Startup completion status (startup probe)
- /health/sidecar → Circuit breaker status
- /health/{component} → Component-specific health
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, Response

from ..store import get_store

router = APIRouter()

# Track startup time for startup probe
_startup_time = time.monotonic()
_startup_complete = False


def mark_startup_complete() -> None:
    """Call this when the application is fully initialized."""
    global _startup_complete
    _startup_complete = True


@router.get("/health")
async def health_check():
    """
    Overall system health (K8s liveness probe).

    Returns 200 if the service is alive and responding.
    Used by: livenessProbe
    """
    store = get_store()
    components = [
        store.check_health("redis"),
        store.check_health("schemas"),
    ]

    all_ok = all(c["status"] == "ok" for c in components)
    return {
        "status": "ok" if all_ok else "degraded",
        "components": components,
    }


@router.get("/ready")
async def readiness_check(response: Response):
    """
    Readiness to accept traffic (K8s readiness probe).

    Returns 200 if:
    - Schema directory exists and is readable
    - At least one schema file exists OR watcher is active

    Returns 503 if not ready.
    Used by: readinessProbe
    """
    store = get_store()
    checks = {}

    # Check 1: Schema directory exists
    schema_dir = Path(os.environ.get("STREAMFORGE_SCHEMA_DIR", "schemas"))
    checks["schema_dir_exists"] = schema_dir.exists()

    # Check 2: At least one schema file or watcher active
    schema_files = list(schema_dir.glob("*/schema.yaml")) if schema_dir.exists() else []
    checks["has_schemas"] = len(schema_files) > 0

    # Check 3: Store is accessible
    try:
        store_health = store.check_health("schemas")
        checks["store_accessible"] = store_health.get("status") == "ok"
    except Exception:
        checks["store_accessible"] = False

    ready = checks["schema_dir_exists"] and (checks["has_schemas"] or checks["store_accessible"])

    if not ready:
        response.status_code = 503

    return {
        "ready": ready,
        "checks": checks,
    }


@router.get("/startup")
async def startup_check(response: Response):
    """
    Startup completion status (K8s startup probe).

    Returns 200 once the application has fully initialized.
    Returns 503 during startup.

    Used by: startupProbe (with failureThreshold for slow starts)
    """
    elapsed = time.monotonic() - _startup_time

    if _startup_complete:
        return {
            "started": True,
            "phase": "ready",
            "startup_duration_s": round(elapsed, 2),
        }
    else:
        # Still starting up
        response.status_code = 503
        return {
            "started": False,
            "phase": "initializing",
            "elapsed_s": round(elapsed, 2),
        }


@router.get("/health/sidecar")
async def sidecar_health():
    """
    Circuit breaker status for all sidecars.

    Returns state of each circuit breaker:
    - closed: Normal operation
    - open: Rejecting requests (unhealthy)
    - half-open: Testing recovery
    """
    try:
        from streamforge.resilience import get_health_summary

        breakers = get_health_summary()

        # Determine overall status
        states = [b.get("state", "unknown") for b in breakers.values()]
        if "open" in states:
            overall = "degraded"
        elif "half-open" in states:
            overall = "recovering"
        else:
            overall = "healthy"

        return {
            "status": overall,
            "circuit_breakers": breakers,
        }
    except ImportError:
        return {
            "status": "unknown",
            "circuit_breakers": {},
            "note": "resilience module not loaded",
        }


@router.get("/health/{component}")
async def component_health(component: str):
    """Health check for a specific component."""
    store = get_store()
    return store.check_health(component)
