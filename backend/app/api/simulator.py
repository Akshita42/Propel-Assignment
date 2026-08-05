"""
Simulator API — inject faults and noise for demonstration and evaluation.

The simulator is a digital twin. It understands the physics:
- span fault → power_lost from all poles downstream (70% success rate)
- firmware 1.2.x devices → they just go silent (no power_lost event)
- DT fault → all poles under the DT
- feeder fault → all poles on the feeder
- device failure → single pole dark, children stay live (→ NOT a fault ticket)
- repair → power_restored + boot events for affected poles
- noise → duplicates, out-of-order messages, stale messages

All scenarios produce realistic telemetry payloads that are sent to
the ingest endpoint exactly as a real device would send them.
"""

import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Pole, DistributionTransformer, Incident, IncidentStatus, IncidentPole, PoleState, ScheduledOutage
from app.schemas.schemas import (
    SimulateSpanFault, SimulateDTFault, SimulateFeederFault,
    SimulateDeviceFailure, SimulateRepair, SimulateNoise, SimulateScheduledOutage, SimulationResult
)
from app.core.topology_engine import topology_engine
from app.api.ingest import process_single_message, _run_fault_detection, _run_restoration_check_all
from app.schemas.schemas import TelemetryPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulate", tags=["simulator"])

random.seed()  # Fresh random seed for simulator


def make_telemetry(
    pole: Pole,
    event: str,
    energized: bool,
    seq_offset: int = 0,
    ts_offset_seconds: float = 0.0,
) -> TelemetryPayload:
    """Build a realistic telemetry payload for a pole."""
    now = datetime.now(timezone.utc)
    # Add realistic timestamp skew (±90 seconds)
    skew = timedelta(seconds=random.uniform(-90, 90) + ts_offset_seconds)

    return TelemetryPayload(
        device_id=pole.device_id or f"UNKNOWN-{pole.pole_id}",
        pole_id=pole.pole_id,
        event=event,
        energized=energized,
        ts=now + skew,
        seq=(pole.last_seq or 1000) + seq_offset + random.randint(1, 5),
        battery_mv=random.randint(3100, 3800) if not energized else None,
        rssi=random.randint(-110, -60),
        fw=pole.firmware_version or "1.4.2",
    )


async def _get_dt_poles(session: AsyncSession, dt_id: str) -> list[Pole]:
    result = await session.execute(select(Pole).where(Pole.dt_id == dt_id))
    return result.scalars().all()


async def _get_downstream_poles(session: AsyncSession, dt_id: str, from_pole_id: str) -> list[Pole]:
    """Get all poles downstream of a given pole in the topology."""
    topology = topology_engine.get_dt_topology(dt_id)
    if not topology:
        return []

    downstream_ids = topology.get_downstream(from_pole_id)
    if not downstream_ids:
        return []

    result = await session.execute(
        select(Pole).where(Pole.pole_id.in_(downstream_ids))
    )
    return result.scalars().all()


async def _send_power_lost_batch(
    session: AsyncSession,
    poles: list[Pole],
    background_tasks: BackgroundTasks,
):
    """
    Simulate power_lost events from a list of poles.

    Physics:
    - fw >= 1.3: sends power_lost (succeeds 70% of the time)
    - fw 1.2.x: just stops heartbeating (no power_lost event)
    - 30% of messages never arrive (capacitor too low / radio busy)
    """
    payloads = []
    for i, pole in enumerate(poles):
        if not pole.device_id:
            continue  # No device — silent

        is_legacy = pole.is_legacy_firmware or (
            pole.firmware_version and pole.firmware_version.startswith("1.2.")
        )

        if is_legacy:
            # Firmware 1.2.x: just goes silent — mark as UNKNOWN via heartbeat timeout
            # We simulate this by NOT sending any message (they'll be detected via timeout)
            pole.last_state = PoleState.UNKNOWN  # Will become DARK after timeout
            continue

        # 70% chance of sending power_lost
        if random.random() < 0.70:
            payload = make_telemetry(pole, "power_lost", False, seq_offset=i)
            payloads.append(payload)
            status, _ = await process_single_message(session, payload)

    await session.flush()

    # Trigger fault detection
    background_tasks.add_task(_run_fault_detection)

    return len(payloads)


@router.post("/span-fault", response_model=SimulationResult)
async def simulate_span_fault(
    data: SimulateSpanFault,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """
    Inject a span fault between two poles.
    All poles downstream of span_to_pole_id go dark.
    """
    topology = topology_engine.get_dt_topology(data.dt_id)
    if not topology:
        raise HTTPException(status_code=404, detail=f"DT {data.dt_id} not found in topology")

    if data.span_to_pole_id not in topology.all_pole_ids:
        raise HTTPException(status_code=404, detail=f"Pole {data.span_to_pole_id} not in DT {data.dt_id}")

    downstream_poles = await _get_downstream_poles(session, data.dt_id, data.span_to_pole_id)
    if not downstream_poles:
        # Fallback: just the single pole
        result = await session.execute(select(Pole).where(Pole.pole_id == data.span_to_pole_id))
        pole = result.scalar_one_or_none()
        downstream_poles = [pole] if pole else []

    sent = await _send_power_lost_batch(session, downstream_poles, background_tasks)
    await session.commit()

    return SimulationResult(
        scenario="span_fault",
        messages_generated=sent,
        note=(
            f"Injected span fault between {data.span_from_pole_id} → {data.span_to_pole_id}. "
            f"{len(downstream_poles)} poles downstream. {sent} power_lost messages sent "
            f"({len(downstream_poles)-sent} firmware-1.2.x or suppressed by 30% drop rate)."
        ),
    )


@router.post("/dt-fault", response_model=SimulationResult)
async def simulate_dt_fault(
    data: SimulateDTFault,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Inject a DT-level fault — all poles under the DT go dark."""
    poles = await _get_dt_poles(session, data.dt_id)
    if not poles:
        raise HTTPException(status_code=404, detail=f"DT {data.dt_id} not found")

    sent = await _send_power_lost_batch(session, poles, background_tasks)
    await session.commit()

    return SimulationResult(
        scenario="dt_fault",
        messages_generated=sent,
        note=f"Injected DT fault on {data.dt_id}. {len(poles)} poles affected. {sent} messages sent.",
    )


@router.post("/feeder-fault", response_model=SimulationResult)
async def simulate_feeder_fault(
    data: SimulateFeederFault,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Inject a feeder-level fault — all poles on the feeder go dark."""
    result = await session.execute(select(Pole).where(Pole.feeder_id == data.feeder_id))
    poles = result.scalars().all()

    if not poles:
        raise HTTPException(status_code=404, detail=f"Feeder {data.feeder_id} not found")

    sent = await _send_power_lost_batch(session, poles, background_tasks)
    await session.commit()

    return SimulationResult(
        scenario="feeder_fault",
        messages_generated=sent,
        note=f"Injected feeder fault on {data.feeder_id}. {len(poles)} poles affected.",
    )


@router.post("/device-failure", response_model=SimulationResult)
async def simulate_device_failure(
    data: SimulateDeviceFailure,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """
    Simulate a single device dying while power is still on.
    Children of this pole remain LIVE.
    The system should detect the dead-sensor paradox and NOT create a fault ticket.
    """
    result = await session.execute(select(Pole).where(Pole.pole_id == data.pole_id))
    pole = result.scalar_one_or_none()

    if not pole:
        raise HTTPException(status_code=404, detail=f"Pole {data.pole_id} not found")

    # Send power_lost from just this one pole
    payload = make_telemetry(pole, "power_lost", False)
    await process_single_message(session, payload)
    await session.commit()

    background_tasks.add_task(_run_fault_detection)

    return SimulationResult(
        scenario="device_failure",
        messages_generated=1,
        note=(
            f"Pole {data.pole_id} device failure simulated. "
            f"Its children remain LIVE (if topology known). "
            f"The dead-sensor paradox filter should prevent a fault ticket. "
            f"Check the incident list — no new ticket should appear."
        ),
    )


@router.post("/repair", response_model=SimulationResult)
async def simulate_repair(
    data: SimulateRepair,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """
    Simulate a fault repair. Sends power_restored + boot events for all
    poles affected by the incident.

    The system should auto-verify the incident from telemetry.
    """
    result = await session.execute(
        select(Incident).where(Incident.id == data.incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Get affected poles
    ip_result = await session.execute(
        select(IncidentPole.pole_id).where(IncidentPole.incident_id == data.incident_id)
    )
    pole_ids = [row[0] for row in ip_result.fetchall()]

    if not pole_ids:
        raise HTTPException(status_code=400, detail="No poles associated with this incident")

    pole_result = await session.execute(select(Pole).where(Pole.pole_id.in_(pole_ids)))
    poles = pole_result.scalars().all()

    sent = 0
    for i, pole in enumerate(poles):
        if not pole.device_id:
            continue

        # Boot event first (device reboots when power returns)
        boot_payload = make_telemetry(pole, "boot", True, seq_offset=i * 2)
        await process_single_message(session, boot_payload)

        # Then power_restored (highly reliable — >95% success)
        restore_payload = make_telemetry(pole, "power_restored", True, seq_offset=i * 2 + 1)
        await process_single_message(session, restore_payload)
        sent += 1

    await session.commit()
    background_tasks.add_task(_run_restoration_check_all)

    return SimulationResult(
        scenario="repair",
        messages_generated=sent * 2,
        note=(
            f"Repair simulated for incident {data.incident_id}. "
            f"{sent} poles sent boot + power_restored. "
            f"Incident should auto-verify within a few seconds."
        ),
    )


@router.post("/noise", response_model=SimulationResult)
async def simulate_noise(
    data: SimulateNoise,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Inject noise: duplicate messages, out-of-order delivery, or stale retries."""
    poles = await _get_dt_poles(session, data.dt_id)
    if not poles:
        raise HTTPException(status_code=404, detail=f"DT {data.dt_id} not found")

    # Pick 3 random poles
    sample = random.sample(poles, min(3, len(poles)))
    sent = 0

    for pole in sample:
        if not pole.device_id:
            continue

        if data.noise_type == "duplicate":
            # Re-send the same seq number → should be deduplicated
            payload = make_telemetry(pole, "heartbeat", True, seq_offset=0)
            payload.seq = pole.last_seq or 100
            await process_single_message(session, payload)
            sent += 1

        elif data.noise_type == "out_of_order":
            # Send a message with a lower seq than current
            payload = make_telemetry(pole, "heartbeat", True, seq_offset=-50)
            await process_single_message(session, payload)
            sent += 1

        elif data.noise_type == "stale":
            # Send a power_lost from 5 hours ago (stale retry)
            payload = make_telemetry(pole, "power_lost", False, ts_offset_seconds=-18000)
            payload.seq = (pole.last_seq or 100) - 200  # Old seq → out-of-order
            await process_single_message(session, payload)
            sent += 1

    await session.commit()

    return SimulationResult(
        scenario=f"noise_{data.noise_type}",
        messages_generated=sent,
        note=f"Injected {data.noise_type} noise for DT {data.dt_id}. {sent} messages. No new incidents expected.",
    )


@router.post("/scheduled-outage", response_model=SimulationResult)
async def simulate_scheduled_outage(
    data: SimulateScheduledOutage,
    session: AsyncSession = Depends(get_db),
):
    """
    Inject a dynamic scheduled outage for load shedding / planned maintenance.
    Active scheduled outages suppress fault tickets during their time window.
    """
    now = datetime.now(timezone.utc)
    outage_id = f"SO-SIM-{now.strftime('%H%M%S')}"

    outage = ScheduledOutage(
        id=outage_id,
        scope=data.scope,
        target_id=data.target_id,
        start_time=now - timedelta(minutes=5),  # Active right now
        end_time=now + timedelta(hours=data.duration_hours),
        reason=data.reason,
    )
    session.add(outage)
    await session.commit()

    return SimulationResult(
        scenario="scheduled_outage",
        messages_generated=1,
        note=f"Injected active scheduled outage {outage_id} on {data.scope.upper()} {data.target_id}. Subsequent faults on this target will be suppressed.",
    )


@router.get("/dts")
async def list_simulatable_dts(session: AsyncSession = Depends(get_db)):
    """List all DTs with pole counts for the simulator UI."""
    result = await session.execute(select(DistributionTransformer))
    dts = result.scalars().all()

    response = []
    for dt in dts:
        topology = topology_engine.get_dt_topology(dt.dt_id)
        pole_count = len(topology.all_pole_ids) if topology else 0

        response.append({
            "dt_id": dt.dt_id,
            "feeder_id": dt.feeder_id,
            "lat": dt.lat,
            "lon": dt.lon,
            "pole_count": pole_count,
            "topology_source": topology.source.value if topology else "NONE",
        })

    return response


@router.get("/dts/{dt_id}/poles")
async def list_dt_poles_for_simulator(
    dt_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get poles for a specific DT, formatted for simulator span selection."""
    topology = topology_engine.get_dt_topology(dt_id)
    poles = await _get_dt_poles(session, dt_id)

    return [
        {
            "pole_id": p.pole_id,
            "lat": p.lat,
            "lon": p.lon,
            "has_device": p.device_id is not None,
            "is_legacy": p.is_legacy_firmware,
            "parent_pole_id": topology.parent_map.get(p.pole_id) if topology else None,
            "children_count": len(topology.children_map.get(p.pole_id, [])) if topology else 0,
        }
        for p in poles
    ]
