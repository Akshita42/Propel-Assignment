"""Incidents API — CRUD + status lifecycle management."""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Incident, IncidentPole, Pole, IncidentStatus
from app.schemas.schemas import IncidentOut, IncidentStatusUpdate
from app.core.incident_manager import validate_manual_resolution, broadcast_sse_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=List[IncidentOut])
async def list_incidents(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_db),
):
    """
    List incidents, newest first.
    Filter by status if provided.
    """
    query = select(Incident).order_by(desc(Incident.created_at)).limit(limit).offset(offset)

    if status:
        try:
            status_enum = IncidentStatus(status.upper())
            query = query.where(Incident.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    result = await session.execute(query)
    incidents = result.scalars().all()
    return incidents


@router.get("/active", response_model=List[IncidentOut])
async def list_active_incidents(session: AsyncSession = Depends(get_db)):
    """List all currently active (non-closed) incidents."""
    result = await session.execute(
        select(Incident)
        .where(Incident.status.not_in([IncidentStatus.VERIFIED, IncidentStatus.CLOSED]))
        .order_by(desc(Incident.created_at))
    )
    return result.scalars().all()


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """Get a single incident by ID."""
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{incident_id}/poles")
async def get_incident_poles(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """Get all poles associated with an incident."""
    result = await session.execute(
        select(IncidentPole, Pole)
        .join(Pole, IncidentPole.pole_id == Pole.pole_id)
        .where(IncidentPole.incident_id == incident_id)
    )
    rows = result.all()
    return [
        {
            "pole_id": pole.pole_id,
            "lat": pole.lat,
            "lon": pole.lon,
            "role": ip.role,
            "last_state": pole.last_state.value,
            "ward": pole.ward,
            "pincode": pole.pincode,
        }
        for ip, pole in rows
    ]


@router.patch("/{incident_id}/status", response_model=IncidentOut)
async def update_incident_status(
    incident_id: uuid.UUID,
    update: IncidentStatusUpdate,
    session: AsyncSession = Depends(get_db),
):
    """
    Update incident status.

    Key business rule: if operator tries to mark RESOLVED while affected
    poles are still dark, the system rejects the request with a clear message.
    Restoration must be confirmed by telemetry.
    """
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Guard: block resolution if poles still dark
    if update.status in (IncidentStatus.RESOLVED, IncidentStatus.VERIFIED, IncidentStatus.CLOSED):
        allowed, reason = await validate_manual_resolution(session, incident_id)
        if not allowed:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "TELEMETRY_UNVERIFIED",
                    "message": reason,
                    "hint": "The system will auto-verify when telemetry confirms power is restored.",
                }
            )

    now = datetime.now(timezone.utc)
    old_status = incident.status
    incident.status = update.status
    incident.updated_at = now

    if update.status == IncidentStatus.RESOLVED:
        incident.resolved_at = now
        incident.resolution_source = "OPERATOR_MANUAL_UNVERIFIED"

    await session.flush()

    await broadcast_sse_event("incident_updated", {
        "incident_id": str(incident_id),
        "old_status": old_status.value,
        "new_status": update.status.value,
        "updated_at": now.isoformat(),
    })

    logger.info(f"Incident {incident_id}: {old_status.value} → {update.status.value}")
    return incident
