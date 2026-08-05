"""
Propel Fault Localization System — Main Application Entry Point

Karnataka State Power Distribution Board (KSPDB)
AI Product Engineer Assignment — Propel

Startup sequence:
1. Create database tables
2. Seed synthetic network data (if not already seeded)
3. Build topology engine (in-memory tree for fast traversal)
4. Start heartbeat timeout background job
5. Mount API routes

Architecture: FastAPI (async) + PostgreSQL (asyncpg) + SSE + React frontend
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.core.topology_engine import topology_engine
from app.seed.seed_db import run_seed

from app.api import ingest, incidents, simulator, sse, network

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


async def heartbeat_timeout_job():
    """
    Background job: detect poles that missed heartbeats.

    Poles with firmware ≥ 1.3 send heartbeats every 15 minutes.
    If we haven't heard from a pole in >18 minutes (HEARTBEAT_TIMEOUT_SECONDS),
    AND its last known state was LIVE, we mark it UNKNOWN/DARK.

    This catches:
    - Firmware 1.2.x devices that just go silent on power loss
    - Devices with dead modems
    - The 30% of power_lost messages that never arrive

    We mark as UNKNOWN (not DARK) because silence is ambiguous:
    could be a network fault or a dead device. The fault detection
    algorithm handles UNKNOWN poles by treating them as probable-DARK
    but with reduced confidence.
    """
    from sqlalchemy import select, and_
    from app.models import Pole, PoleState
    from app.api.ingest import _run_fault_detection

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            timeout_threshold = datetime.now(timezone.utc) - timedelta(
                seconds=settings.HEARTBEAT_TIMEOUT_SECONDS
            )

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Pole).where(
                        and_(
                            Pole.last_state == PoleState.LIVE,
                            Pole.last_event_ts < timeout_threshold,
                            Pole.device_id.isnot(None),
                        )
                    )
                )
                timed_out = result.scalars().all()

                if timed_out:
                    for pole in timed_out:
                        pole.last_state = PoleState.UNKNOWN
                        logger.info(
                            f"Heartbeat timeout: {pole.pole_id} "
                            f"(last seen: {pole.last_event_ts})"
                        )
                    await session.commit()
                    # Trigger fault detection for newly unknown poles
                    asyncio.create_task(_run_fault_detection())

        except Exception as e:
            logger.error(f"Heartbeat timeout job error: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info("🚀 Starting Propel Fault Localization System")

    # Step 1: Seed database
    await run_seed()

    # Step 2: Build topology engine
    logger.info("Building topology engine...")
    async with AsyncSessionLocal() as session:
        await topology_engine.build(session)

    # Step 3: Start heartbeat timeout background job
    hb_task = asyncio.create_task(heartbeat_timeout_job())
    logger.info("✅ System ready")

    yield  # Application runs here

    # Shutdown
    hb_task.cancel()
    logger.info("Shutting down...")


app = FastAPI(
    title="Propel Fault Localization System",
    description=(
        "Real-time electrical fault detection and localization for "
        "Karnataka State Power Distribution Board (KSPDB). "
        "Reduces fault identification time from 2 hours to under 2 minutes."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow React dev server and production frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routes ─────────────────────────────────────────────────────────────────
app.include_router(ingest.router)
app.include_router(incidents.router)
app.include_router(simulator.router)
app.include_router(sse.router)
app.include_router(network.router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "topology_built": topology_engine.is_built(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Serve React Frontend (production) ─────────────────────────────────────────
def get_static_dir():
    """
    Find the directory containing the built React frontend (index.html).

    Render deployment: build.sh copies frontend/dist/* → backend/static/
    The CWD when uvicorn starts is /opt/render/project/src/backend (after `cd backend`)
    So the static dir is at:  <CWD>/static  →  /opt/render/project/src/backend/static
    """
    possible_dirs = [
        # Render: CWD is backend/ after `cd backend` in startCommand
        os.path.join(os.getcwd(), "static"),
        # Relative to this file (backend/app/main.py → backend/static)
        os.path.join(os.path.dirname(__file__), "..", "static"),
        # Docker: mounted via docker-compose volume
        "/app/static",
        # Local dev: frontend dist relative to project root
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
        os.path.abspath("../frontend/dist"),
    ]
    for d in possible_dirs:
        norm = os.path.normpath(d)
        idx = os.path.join(norm, "index.html")
        if os.path.exists(idx):
            return norm
    return None


STATIC_DIR = get_static_dir()
if STATIC_DIR:
    logger.info(f"✅ Serving static frontend from: {STATIC_DIR}")
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
else:
    logger.warning(
        f"⚠️  No frontend static files found. CWD={os.getcwd()} "
        f"__file__={__file__}. "
        f"Run build.sh first to build the React frontend."
    )


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve React SPA for all non-API routes."""
    if full_path.startswith("api/"):
        return {"detail": "API endpoint not found"}

    static_dir = get_static_dir()
    if static_dir:
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)

    return {
        "status": "backend_running",
        "message": "Propel Fault Localizer backend is live, but frontend static assets (index.html) were not built or found.",
        "docs": "/docs",
        "health": "/api/health",
    }

