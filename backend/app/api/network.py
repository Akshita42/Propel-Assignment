"""Network/poles API — for map rendering."""

from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Pole, DistributionTransformer
from app.schemas.schemas import PoleOut, DTOut, TopologyOut, TopologyEdgeOut
from app.core.topology_engine import topology_engine, TopologySource

router = APIRouter(prefix="/api/network", tags=["network"])


@router.get("/poles", response_model=List[PoleOut])
async def get_all_poles(
    dt_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """Get all poles (optionally filtered by DT) with current state."""
    query = select(Pole)
    if dt_id:
        query = query.where(Pole.dt_id == dt_id)
    result = await session.execute(query)
    poles = result.scalars().all()
    return [
        PoleOut(
            pole_id=p.pole_id,
            lat=p.lat,
            lon=p.lon,
            feeder_id=p.feeder_id,
            dt_id=p.dt_id,
            ward=p.ward,
            pincode=p.pincode,
            has_device=p.device_id is not None,
            last_state=p.last_state,
            last_event_ts=p.last_event_ts,
            firmware_version=p.firmware_version,
            is_legacy_firmware=p.is_legacy_firmware,
            topology_confidence=p.topology_confidence,
        )
        for p in poles
    ]


@router.get("/dts", response_model=List[DTOut])
async def get_all_dts(session: AsyncSession = Depends(get_db)):
    """Get all distribution transformers."""
    result = await session.execute(select(DistributionTransformer))
    return result.scalars().all()


@router.get("/topology-all", response_model=List[TopologyEdgeOut])
async def get_all_topology_edges():
    """Get all topology tree edges across all DTs (for high-performance map rendering)."""
    all_topos = topology_engine.get_all_dt_topologies()
    edges = []
    for dt_id, topo in all_topos.items():
        for e in topo.edges:
            edges.append(
                TopologyEdgeOut(
                    parent_id=e.parent_id,
                    child_id=e.child_id,
                    confidence=e.confidence,
                    source=e.source,
                )
            )
    return edges


@router.get("/topology/{dt_id}", response_model=TopologyOut)
async def get_dt_topology(dt_id: str):
    """Get the topology tree edges for a specific DT (for map rendering)."""
    topology = topology_engine.get_dt_topology(dt_id)
    if not topology:
        return TopologyOut(dt_id=dt_id, edges=[], source=TopologySource.NONE)

    edges = [
        TopologyEdgeOut(
            parent_id=e.parent_id,
            child_id=e.child_id,
            confidence=e.confidence,
            source=e.source,
        )
        for e in topology.edges
    ]
    return TopologyOut(dt_id=dt_id, edges=edges, source=topology.source)


@router.get("/stats")
async def get_network_stats(session: AsyncSession = Depends(get_db)):
    """Network health summary for dashboard header."""
    from sqlalchemy import func
    from app.models import PoleState, Incident, IncidentStatus

    pole_result = await session.execute(
        select(Pole.last_state, func.count()).group_by(Pole.last_state)
    )
    state_counts = dict(pole_result.fetchall())

    incident_result = await session.execute(
        select(func.count()).where(
            Incident.status.not_in([IncidentStatus.VERIFIED, IncidentStatus.CLOSED])
        )
    )
    active_incidents = incident_result.scalar()

    return {
        "total_poles": sum(state_counts.values()),
        "live_poles": state_counts.get(PoleState.LIVE, 0),
        "dark_poles": state_counts.get(PoleState.DARK, 0),
        "unknown_poles": state_counts.get(PoleState.UNKNOWN, 0),
        "device_failures": state_counts.get(PoleState.DEVICE_FAILURE, 0),
        "active_incidents": active_incidents,
    }
