"""FastAPI app for StreamForge Cockpit dashboard."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import health, sources, metrics, drift, pii, streams, search, connectors

app = FastAPI(
    title="StreamForge Cockpit",
    description="Dashboard API for schema drift detection",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(sources.router, prefix="/api", tags=["sources"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(drift.router, prefix="/api", tags=["drift"])
app.include_router(pii.router, prefix="/api", tags=["pii"])
app.include_router(streams.router)
app.include_router(search.router)
app.include_router(connectors.router)


@app.get("/")
async def root():
    return {"message": "StreamForge Cockpit API", "docs": "/api/docs"}
