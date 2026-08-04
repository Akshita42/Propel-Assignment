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
STATIC_DIR = "/app/static"
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=f"{STATIC_DIR}/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve React SPA for all non-API routes."""
        return FileResponse(f"{STATIC_DIR}/index.html")
