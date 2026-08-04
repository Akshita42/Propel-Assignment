"""
Telemetry ingest endpoint.

Design for throughput:
- Target: ≥500 msg/s sustained, 5000 msg/10s burst
- Async PostgreSQL (asyncpg) with connection pool (20 base + 40 overflow)
- Per-message dedup via (pole_id, seq) unique constraint
- Out-of-order handling: only update pole state if incoming seq > last_seq
- At-least-once delivery: duplicates handled gracefully (logged, not errored)
- Batch endpoint for simulator (POST /api/ingest/batch)

After state update, triggers fault detection cycle if power_lost event received.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Pole, TelemetryEvent, PoleState
from app.schemas.schemas import TelemetryPayload, TelemetryBatchPayload, IngestResponse
from app.core.fault_detector import detect_all_faults
from app.core.incident_manager import create_incident_from_candidate, broadcast_sse_event, check_restoration

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["ingest"])


async def process_single_message(
    session: AsyncSession,
    payload: TelemetryPayload,
) -> tuple[str, bool]:
    """
    Process one telemetry message. Returns (status, is_duplicate).
    status: 'accepted' | 'duplicate' | 'unknown_pole' | 'out_of_order'
    """
    now = datetime.now(timezone.utc)

    # Look up pole
    result = await session.execute(select(Pole).where(Pole.pole_id == payload.pole_id))
    pole = result.scalar_one_or_none()

    if not pole:
        logger.warning(f"Unknown pole_id: {payload.pole_id} from device {payload.device_id}")
        return "unknown_pole", False

    # Attempt to insert telemetry event (dedup via unique constraint)
    event = TelemetryEvent(
        received_at=now,
        device_id=payload.device_id,
        pole_id=payload.pole_id,
        event_type=payload.event,
        energized=payload.energized,
        device_ts=payload.ts,
        seq=payload.seq,
        battery_mv=payload.battery_mv,
        rssi=payload.rssi,
        fw=payload.fw,
        is_duplicate=False,
    )

    try:
        session.add(event)
        await session.flush()
    except IntegrityError:
        await session.rollback()
        logger.debug(f"Duplicate message: pole={payload.pole_id} seq={payload.seq}")
        return "duplicate", True

    # Out-of-order check: only update pole state if this message is newer
    # (seq is monotonic per device; resets on boot)
    is_boot = payload.event == "boot"
    should_update = (
        pole.last_seq is None
        or is_boot
        or payload.seq > pole.last_seq
    )

    if should_update:
        # Update pole runtime state
        if payload.event in ("power_lost",) or not payload.energized:
            pole.last_state = PoleState.DARK
        elif payload.event in ("power_restored", "heartbeat", "boot") and payload.energized:
            pole.last_state = PoleState.LIVE
        # heartbeat with energized=False treated as DARK
        elif payload.event == "heartbeat" and not payload.energized:
            pole.last_state = PoleState.DARK

        pole.last_event_ts = now
        pole.last_seq = payload.seq
        pole.last_event_type = payload.event
        pole.last_battery_mv = payload.battery_mv
        pole.last_rssi = payload.rssi
        if payload.fw:
            pole.firmware_version = payload.fw
            pole.is_legacy_firmware = payload.fw.startswith("1.2.")

        await session.flush()

    return "accepted", False


@router.post("", response_model=IngestResponse)
async def ingest_telemetry(
    payload: TelemetryPayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Accept a single telemetry message from a pole device."""
    status, is_dup = await process_single_message(session, payload)

    result = IngestResponse(
        accepted=1 if status == "accepted" else 0,
        duplicates=1 if is_dup else 0,
        unknown_poles=1 if status == "unknown_pole" else 0,
    )

    # Trigger fault detection in background if power_lost received
    if status == "accepted" and payload.event in ("power_lost",):
        background_tasks.add_task(_run_fault_detection)

    # Trigger restoration check if power_restored received
    if status == "accepted" and payload.event in ("power_restored", "boot"):
        background_tasks.add_task(_run_restoration_check, payload.pole_id)

    return result


@router.post("/batch", response_model=IngestResponse)
async def ingest_batch(
    payload: TelemetryBatchPayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Accept a batch of telemetry messages (used by simulator)."""
    accepted = duplicates = unknown = 0
    has_power_lost = False
    has_power_restored = False

    for msg in payload.messages:
        status, is_dup = await process_single_message(session, msg)
        if status == "accepted":
            accepted += 1
            if msg.event == "power_lost":
                has_power_lost = True
            if msg.event in ("power_restored", "boot"):
                has_power_restored = True
        elif is_dup:
            duplicates += 1
        elif status == "unknown_pole":
            unknown += 1

    if has_power_lost:
        background_tasks.add_task(_run_fault_detection)
    if has_power_restored:
        background_tasks.add_task(_run_restoration_check_all)

    return IngestResponse(accepted=accepted, duplicates=duplicates, unknown_poles=unknown)


async def _run_fault_detection():
    """Background task: run fault detection and create incidents."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            candidates = await detect_all_faults(session)
            for candidate in candidates:
                incident = await create_incident_from_candidate(session, candidate)
                if incident:
                    await broadcast_sse_event("incident_created", {
                        "incident_id": str(incident.id),
                        "fault_type": incident.fault_type.value,
                        "dt_id": incident.dt_id,
                        "confidence_score": incident.confidence_score,
                        "confidence_level": incident.confidence_level.value,
                        "affected_pole_count": incident.affected_pole_count,
                        "fault_lat": incident.fault_lat,
                        "fault_lon": incident.fault_lon,
                        "pincode": incident.pincode,
                    })
            await session.commit()
        except Exception as e:
            logger.error(f"Fault detection error: {e}", exc_info=True)
            await session.rollback()


async def _run_restoration_check(pole_id: str):
    """Check restoration for all incidents affecting this pole."""
    from app.database import AsyncSessionLocal
    from app.models import IncidentPole, Incident, IncidentStatus
    from sqlalchemy import and_
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(IncidentPole.incident_id).where(IncidentPole.pole_id == pole_id)
            )
            incident_ids = [row[0] for row in result.fetchall()]
            for iid in incident_ids:
                await check_restoration(session, iid)
            await session.commit()
        except Exception as e:
            logger.error(f"Restoration check error: {e}", exc_info=True)
            await session.rollback()


async def _run_restoration_check_all():
    """Check restoration for all open incidents."""
    from app.database import AsyncSessionLocal
    from app.models import Incident, IncidentStatus
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Incident.id).where(
                    Incident.status.in_([
                        IncidentStatus.DETECTED,
                        IncidentStatus.ACKNOWLEDGED,
                        IncidentStatus.CREW_ASSIGNED,
                        IncidentStatus.RESOLVED,
                    ])
                )
            )
            incident_ids = [row[0] for row in result.fetchall()]
            for iid in incident_ids:
                await check_restoration(session, iid)
            await session.commit()
        except Exception as e:
            logger.error(f"Restoration check all error: {e}", exc_info=True)
            await session.rollback()
