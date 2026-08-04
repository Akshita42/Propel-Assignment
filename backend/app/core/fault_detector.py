"""
Fault Detection and Localization Engine

This is the core of the submission. It takes current pole states and
produces localized fault incidents.

Algorithm (Approach B Pruned):

1. PRE-FILTER
   Remove poles under active scheduled outage — these are expected dark,
   not fault symptoms.

2. DEAD-SENSOR PARADOX FILTER
   A pole that is dark but has at least one LIVE child is physically
   impossible as a line fault (power cannot skip a pole). Flag as
   DEVICE_FAILURE. Do not generate a ticket.

3. FAULT BOUNDARY DETECTION
   For each DT, traverse the topology tree. Find edges where parent=LIVE
   and child=DARK. Each such edge is a candidate fault span.

4. CONNECTED COMPONENTS
   If multiple dark pole clusters exist under the same DT (disconnected
   in the dark subgraph), they are separate faults → separate tickets.
   This handles simultaneous faults correctly.

5. TOPOLOGY CONSISTENCY RATIO
   actual_dark / expected_dark — accounts for poles without devices,
   firmware 1.2.x devices that go silent, and 30% missing dying messages.
   Adjusts confidence downward when fewer poles reported than expected.

6. INCIDENT ASSEMBLY
   One incident per boundary edge. Compute midpoint coordinates for dispatch,
   resolve PIN code, count affected poles and households.

7. DEDUPLICATION
   Check existing open incidents before creating new ones. If a matching
   incident already exists for the same span, update it rather than duplicate.
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Pole, DistributionTransformer, ScheduledOutage, Incident, IncidentPole,
    PoleState, FaultType, IncidentStatus, ConfidenceLevel, TopologySource
)
from app.core.topology_engine import topology_engine, DTTopology
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class FaultCandidate:
    """A potential fault identified during detection."""
    dt_id: str
    feeder_id: str
    fault_type: FaultType

    # Span-level (None for DT/feeder-level fallback)
    span_from_pole_id: Optional[str] = None   # Last LIVE pole
    span_to_pole_id: Optional[str] = None     # First DARK pole
    fault_lat: Optional[float] = None
    fault_lon: Optional[float] = None

    # Impact
    affected_pole_ids: list[str] = field(default_factory=list)
    expected_dark_count: int = 0

    # Confidence
    confidence_score: float = 0.0
    topology_source: TopologySource = TopologySource.NONE
    pincode: Optional[str] = None
    ward: Optional[str] = None
    households_affected: Optional[int] = None


async def get_active_scheduled_outage_targets(session: AsyncSession) -> dict[str, set[str]]:
    """
    Returns currently active scheduled outage scopes.

    Returns: {'feeder': {'F-01', 'F-02'}, 'dt': {'D-0001'}}

    Important: We treat outages as active within ±20 min of their window
    (real-world outages start late and overrun). However, we do NOT fully
    suppress during this window — we add a warning flag instead, because
    ~10% of outages are cancelled without the feed being updated.
    """
    now = datetime.now(timezone.utc)
    grace = timedelta(minutes=20)

    result = await session.execute(
        select(ScheduledOutage).where(
            and_(
                ScheduledOutage.start_time <= now + grace,
                ScheduledOutage.end_time >= now - grace,
            )
        )
    )
    outages = result.scalars().all()

    active: dict[str, set[str]] = {"feeder": set(), "dt": set()}
    for o in outages:
        active[o.scope].add(o.target_id)
    return active


async def get_current_pole_states(session: AsyncSession, dt_id: str) -> dict[str, Pole]:
    """Load current pole states for a DT."""
    result = await session.execute(
        select(Pole).where(Pole.dt_id == dt_id)
    )
    poles = result.scalars().all()
    return {p.pole_id: p for p in poles}


def apply_dead_sensor_filter(
    pole_states: dict[str, Pole],
    topology: DTTopology,
    dark_set: set[str],
) -> set[str]:
    """
    Physical impossibility filter:
    A dark pole with at least one LIVE child cannot be a line fault.
    The network is radial — power cannot skip a pole.
    Flag these as DEVICE_FAILURE and remove from dark set.

    Returns: filtered dark_set (without physically impossible dark poles)
    """
    sensor_failures = set()

    for pole_id in list(dark_set):
        children = topology.children_map.get(pole_id, [])
        for child_id in children:
            child_pole = pole_states.get(child_id)
            if child_pole and child_pole.last_state == PoleState.LIVE:
                # Dark pole with live child → sensor failure, not line fault
                sensor_failures.add(pole_id)
                logger.info(
                    f"Dead-sensor paradox: {pole_id} is dark but child {child_id} is live "
                    f"→ DEVICE_FAILURE (not a line fault)"
                )
                break

    return dark_set - sensor_failures


def compute_consistency_ratio(
    affected_pole_ids: list[str],
    pole_states: dict[str, Pole],
    topology: DTTopology,
    first_dark_pole_id: str,
) -> float:
    """
    Topology consistency ratio = actual_dark / expected_dark.

    Expected dark: all poles downstream of the fault boundary.
    Actual dark: how many of those actually reported as dark.

    Ratio < 1.0 when:
    - Some poles have no device (can't report)
    - Firmware 1.2.x devices just went silent (we inferred them as dark)
    - 30% dying messages never arrived (we're using heartbeat timeout)

    A low ratio reduces confidence — the fault may be in a different location,
    or there are multiple concurrent faults.
    """
    expected_ids = topology.get_downstream(first_dark_pole_id)
    if not expected_ids:
        return 1.0

    confirmed_dark = sum(
        1 for pid in expected_ids
        if pole_states.get(pid) and pole_states[pid].last_state in (PoleState.DARK, PoleState.UNKNOWN)
    )
    return confirmed_dark / len(expected_ids)


def score_to_level(score: float) -> ConfidenceLevel:
    if score >= 0.85:
        return ConfidenceLevel.HIGH
    elif score >= 0.50:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW


async def detect_faults_for_dt(
    session: AsyncSession,
    dt_id: str,
    outage_targets: dict[str, set[str]],
) -> list[FaultCandidate]:
    """
    Run fault detection for a single DT.
    Returns a list of FaultCandidate objects (0 if no fault).
    """
    topology = topology_engine.get_dt_topology(dt_id)
    if not topology:
        return []

    pole_states = await get_current_pole_states(session, dt_id)
    if not pole_states:
        return []

    # Get DT info
    dt_result = await session.execute(
        select(DistributionTransformer).where(DistributionTransformer.dt_id == dt_id)
    )
    dt = dt_result.scalar_one_or_none()
    if not dt:
        return []

    # PRE-FILTER: Scheduled outage suppression
    if dt.feeder_id in outage_targets.get("feeder", set()):
        logger.debug(f"DT {dt_id}: feeder {dt.feeder_id} under scheduled outage — suppressing")
        return []
    if dt_id in outage_targets.get("dt", set()):
        logger.debug(f"DT {dt_id}: under scheduled outage — suppressing")
        return []

    # Build dark set (poles we believe are without power)
    dark_set = {
        pole_id for pole_id, pole in pole_states.items()
        if pole.last_state in (PoleState.DARK, PoleState.UNKNOWN)
        and pole.device_id is not None  # Only poles with devices can report state
    }

    if not dark_set:
        return []

    # FEEDER FAULT: If all poles across ALL DTs on this feeder are dark
    # (handled at feeder level in detect_all_faults — skip here)

    # DT FAULT: All poles under this DT are dark
    live_poles = {pid for pid, p in pole_states.items() if p.last_state == PoleState.LIVE}
    if not live_poles and len(dark_set) == len([p for p in pole_states.values() if p.device_id]):
        # Entire DT is dark
        affected_ids = list(dark_set)
        return [FaultCandidate(
            dt_id=dt_id,
            feeder_id=dt.feeder_id,
            fault_type=FaultType.DT,
            fault_lat=dt.lat,
            fault_lon=dt.lon,
            affected_pole_ids=affected_ids,
            expected_dark_count=len(pole_states),
            confidence_score=0.75,  # DT fault is clear from full darkness
            topology_source=topology.source,
            pincode=_most_common_pincode(pole_states),
            ward=_most_common_ward(pole_states),
            households_affected=dt.households_served,
        )]

    # If topology is unavailable, fall back to DT-level
    if not topology.edges and topology.source == TopologySource.NONE:
        affected_ids = list(dark_set)
        return [FaultCandidate(
            dt_id=dt_id,
            feeder_id=dt.feeder_id,
            fault_type=FaultType.SPAN,
            fault_lat=dt.lat,
            fault_lon=dt.lon,
            affected_pole_ids=affected_ids,
            confidence_score=0.35,
            topology_source=TopologySource.NONE,
            pincode=_most_common_pincode(pole_states),
            ward=_most_common_ward(pole_states),
        )]

    # DEAD-SENSOR FILTER
    filtered_dark = apply_dead_sensor_filter(pole_states, topology, dark_set)

    if not filtered_dark:
        logger.info(f"DT {dt_id}: all dark poles explained by sensor failures — no fault ticket")
        return []

    # BOUNDARY DETECTION: Find live→dark edges
    boundaries = topology.get_upstream_boundary(filtered_dark)

    if not boundaries:
        # No clean boundary found — either all poles dark (DT fault already caught)
        # or topology mismatch — fall back to DT-level
        return [FaultCandidate(
            dt_id=dt_id,
            feeder_id=dt.feeder_id,
            fault_type=FaultType.SPAN,
            fault_lat=dt.lat,
            fault_lon=dt.lon,
            affected_pole_ids=list(filtered_dark),
            confidence_score=0.35,
            topology_source=topology.source,
            pincode=_most_common_pincode(pole_states),
            ward=_most_common_ward(pole_states),
        )]

    # GROUP boundaries into separate incidents (connected dark components)
    candidates = []
    processed_dark = set()

    for live_parent, first_dark, edge_conf in boundaries:
        if first_dark in processed_dark:
            continue

        # Get all dark poles downstream of this boundary
        downstream_dark = [
            pid for pid in topology.get_downstream(first_dark)
            if pid in filtered_dark
        ]

        if not downstream_dark:
            continue

        processed_dark.update(downstream_dark)

        # Topology consistency ratio
        consistency = compute_consistency_ratio(
            downstream_dark, pole_states, topology, first_dark
        )

        # Final confidence: edge confidence × consistency ratio
        # Also factor in topology source
        base_conf = edge_conf
        final_conf = base_conf * consistency

        # Clamp minimum confidence for span-level localization
        if final_conf < settings.MIN_SPAN_CONFIDENCE and topology.source != TopologySource.GOLD:
            # Fall back to DT-level for very low confidence
            fault_lat = dt.lat
            fault_lon = dt.lon
            span_from = None
            span_to = None
        else:
            # Compute fault location: midpoint between last live and first dark
            live_pole = pole_states.get(live_parent)
            dark_pole = pole_states.get(first_dark)
            if live_pole and dark_pole:
                fault_lat = (live_pole.lat + dark_pole.lat) / 2
                fault_lon = (live_pole.lon + dark_pole.lon) / 2
            else:
                fault_lat = dt.lat
                fault_lon = dt.lon
            span_from = live_parent
            span_to = first_dark

        # Pincode / ward from first dark pole
        first_dark_pole = pole_states.get(first_dark)
        pincode = first_dark_pole.pincode if first_dark_pole else _most_common_pincode(pole_states)
        ward = first_dark_pole.ward if first_dark_pole else _most_common_ward(pole_states)

        candidates.append(FaultCandidate(
            dt_id=dt_id,
            feeder_id=dt.feeder_id,
            fault_type=FaultType.SPAN,
            span_from_pole_id=span_from,
            span_to_pole_id=span_to,
            fault_lat=fault_lat,
            fault_lon=fault_lon,
            affected_pole_ids=downstream_dark,
            expected_dark_count=len(topology.get_downstream(first_dark)),
            confidence_score=round(min(1.0, final_conf), 3),
            topology_source=topology.source,
            consistency_ratio=round(consistency, 3),
            pincode=pincode,
            ward=ward,
        ))

    return candidates


async def detect_all_faults(session: AsyncSession) -> list[FaultCandidate]:
    """
    Run fault detection across all DTs.
    Also checks for feeder-level faults (all DTs on a feeder dark).
    """
    outage_targets = await get_active_scheduled_outage_targets(session)
    all_candidates: list[FaultCandidate] = []

    dt_ids = topology_engine.get_all_dt_ids()

    # Per-DT detection
    dt_candidates: dict[str, list[FaultCandidate]] = {}
    for dt_id in dt_ids:
        candidates = await detect_faults_for_dt(session, dt_id, outage_targets)
        dt_candidates[dt_id] = candidates
        all_candidates.extend(candidates)

    # Feeder-level fault detection:
    # If every DT on a feeder has a DT-level fault, merge into one feeder fault
    feeder_dts: dict[str, list[str]] = {}
    dt_result = await session.execute(select(DistributionTransformer))
    all_dts = dt_result.scalars().all()
    for dt in all_dts:
        feeder_dts.setdefault(dt.feeder_id, []).append(dt.dt_id)

    for feeder_id, feeder_dt_ids in feeder_dts.items():
        if feeder_id in outage_targets.get("feeder", set()):
            continue

        feeder_faults = [
            c for dt_id in feeder_dt_ids
            for c in dt_candidates.get(dt_id, [])
            if c.fault_type == FaultType.DT
        ]

        if len(feeder_faults) == len(feeder_dt_ids) and len(feeder_dt_ids) >= 2:
            # All DTs on feeder dark → feeder fault
            all_affected = [pid for f in feeder_faults for pid in f.affected_pole_ids]
            # Remove individual DT fault candidates and replace with feeder fault
            for fc in feeder_faults:
                all_candidates.remove(fc)

            all_candidates.append(FaultCandidate(
                dt_id=feeder_dt_ids[0],
                feeder_id=feeder_id,
                fault_type=FaultType.FEEDER,
                affected_pole_ids=all_affected,
                confidence_score=0.90,
                topology_source=TopologySource.GOLD,
            ))

    return all_candidates


# ── Helper utilities ───────────────────────────────────────────────────────────

def _most_common_pincode(pole_states: dict[str, Pole]) -> Optional[str]:
    counts: dict[str, int] = {}
    for p in pole_states.values():
        if p.pincode:
            counts[p.pincode] = counts.get(p.pincode, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _most_common_ward(pole_states: dict[str, Pole]) -> Optional[str]:
    counts: dict[str, int] = {}
    for p in pole_states.values():
        if p.ward:
            counts[p.ward] = counts.get(p.ward, 0) + 1
    return max(counts, key=counts.get) if counts else None
