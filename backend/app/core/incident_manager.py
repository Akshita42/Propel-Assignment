"""
Incident Manager

Converts FaultCandidates into Incident database records.
Handles:
- Incident creation with deduplication
- Status lifecycle management
- Restoration auto-verification
- Gemini AI summary generation
- SSE event broadcasting
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Pole, DistributionTransformer, Incident, IncidentPole, PoleCooccurrence,
    PoleState, FaultType, IncidentStatus, ConfidenceLevel, TopologySource
)
from app.core.fault_detector import FaultCandidate, score_to_level
from app.core.topology_engine import topology_engine
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# SSE event queue (in-memory broadcast)
_sse_listeners: list = []


def add_sse_listener(queue):
    _sse_listeners.append(queue)


def remove_sse_listener(queue):
    if queue in _sse_listeners:
        _sse_listeners.remove(queue)


async def broadcast_sse_event(event_type: str, data: dict):
    """Broadcast an event to all connected SSE clients."""
    import json
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _sse_listeners:
        try:
            await q.put(message)
        except Exception:
            dead.append(q)
    for q in dead:
        remove_sse_listener(q)


async def generate_ai_summary(incident: Incident, session: AsyncSession) -> Optional[str]:
    """
    Generate a plain-English incident summary using Gemini.
    Falls back to a structured template if API is unavailable.

    This is the ONE place in the system where an LLM earns its keep:
    - Fault localization itself uses deterministic graph traversal (fast, free, explainable)
    - Dispatch note generation benefits from natural language synthesis
    - One call per incident (low cost: ~$0.001 per summary)
    - Graceful degradation: structured template if Gemini unavailable
    """
    if not settings.GEMINI_API_KEY:
        return _generate_template_summary(incident)

    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        fault_desc = {
            FaultType.SPAN: f"wire span between pole {incident.span_from_pole_id} and {incident.span_to_pole_id}",
            FaultType.DT: f"distribution transformer {incident.dt_id}",
            FaultType.FEEDER: f"11kV feeder {incident.feeder_id}",
        }.get(incident.fault_type, "unknown asset")

        prompt = f"""You are a control room assistant for an electricity distribution utility.
Write a concise 2-3 sentence dispatch note for a field crew. Use plain language, no jargon.

Fault details:
- Type: {incident.fault_type.value}
- Location: {fault_desc}
- GPS: {incident.fault_lat:.6f}°N, {incident.fault_lon:.6f}°E
- PIN code: {incident.pincode or 'Unknown'}
- Ward: {incident.ward or 'Unknown'}
- Poles affected: {incident.affected_pole_count}
- Households estimated: {incident.households_affected or 'Unknown'}
- Confidence: {incident.confidence_level.value} ({incident.confidence_score:.0%})
- Detection time: {incident.created_at.strftime('%H:%M IST')}

Write only the dispatch note. Do not include any preamble."""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logger.warning(f"Gemini summary failed: {e} — using template fallback")
        return _generate_template_summary(incident)


def _generate_template_summary(incident: Incident) -> str:
    """Structured template fallback when Gemini is unavailable."""
    fault_desc = {
        FaultType.SPAN: f"Span fault between poles {incident.span_from_pole_id} and {incident.span_to_pole_id}",
        FaultType.DT: f"Distribution transformer {incident.dt_id} fault",
        FaultType.FEEDER: f"Feeder {incident.feeder_id} fault",
    }.get(incident.fault_type, "Electrical fault")

    loc = ""
    if incident.fault_lat and incident.fault_lon:
        loc = f"Location: {incident.fault_lat:.6f}°N {incident.fault_lon:.6f}°E"
        if incident.pincode:
            loc += f" (PIN {incident.pincode})"

    return (
        f"{fault_desc}. {incident.affected_pole_count} poles affected, "
        f"approx. {incident.households_affected or 'unknown'} households. "
        f"{loc}. Confidence: {incident.confidence_level.value}."
    )


async def create_incident_from_candidate(
    session: AsyncSession,
    candidate: FaultCandidate,
) -> Optional[Incident]:
    """
    Create a new Incident from a FaultCandidate.
    Skips if a matching open incident already exists for this span.
    """
    # Deduplication: check for existing open incident on same span/DT
    existing = await _find_existing_incident(session, candidate)
    if existing:
        logger.debug(f"Incident already exists for {candidate.dt_id} span — skipping")
        return None

    now = datetime.now(timezone.utc)
    confidence_level = score_to_level(candidate.confidence_score)
    status = IncidentStatus.SUPPRESSED if candidate.is_suppressed else IncidentStatus.DETECTED

    incident = Incident(
        id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        status=status,
        fault_type=candidate.fault_type,
        dt_id=candidate.dt_id,
        feeder_id=candidate.feeder_id,
        span_from_pole_id=candidate.span_from_pole_id,
        span_to_pole_id=candidate.span_to_pole_id,
        fault_lat=candidate.fault_lat,
        fault_lon=candidate.fault_lon,
        pincode=candidate.pincode,
        ward=candidate.ward,
        affected_pole_count=len(candidate.affected_pole_ids),
        households_affected=candidate.households_affected,
        confidence_score=candidate.confidence_score,
        confidence_level=confidence_level,
        topology_source=candidate.topology_source,
        consistency_ratio=candidate.consistency_ratio,
        is_suppressed=candidate.is_suppressed,
        suppression_reason=candidate.suppression_reason,
    )
    session.add(incident)
    await session.flush()  # Get the ID

    # Attach affected poles
    for pole_id in candidate.affected_pole_ids:
        role = "FIRST_DARK" if pole_id == candidate.span_to_pole_id else "AFFECTED"
        session.add(IncidentPole(
            incident_id=incident.id,
            pole_id=pole_id,
            role=role,
        ))

    if candidate.span_from_pole_id:
        session.add(IncidentPole(
            incident_id=incident.id,
            pole_id=candidate.span_from_pole_id,
            role="LAST_LIVE",
        ))

    await session.flush()

    # Generate AI summary (async — don't block incident creation)
    try:
        summary = await generate_ai_summary(incident, session)
        incident.ai_summary = summary
    except Exception as e:
        logger.warning(f"AI summary generation failed: {e}")

    # Dynamic Silver Layer: update co-occurrence counts for local tree path pairs
    try:
        await update_cooccurrence_history(session, candidate.dt_id, candidate.affected_pole_ids)
    except Exception as e:
        logger.warning(f"Failed to update co-occurrence history: {e}")

    logger.info(
        f"🚨 Incident created: {incident.id} | {incident.fault_type.value} | "
        f"DT={incident.dt_id} | confidence={incident.confidence_score:.2f} | "
        f"poles={incident.affected_pole_count}"
    )

    return incident


async def update_cooccurrence_history(
    session: AsyncSession,
    dt_id: str,
    affected_pole_ids: list[str],
):
    """
    Dynamically populate and update PoleCooccurrence (Silver Layer).

    Option B: Only update ancestor-child pairs within K=3 hops along the
    LT line tree path. This keeps updates fast (O(N) instead of O(N^2)) and
    ensures co-occurrence tracking directly validates local tree edges.
    """
    if not dt_id or not affected_pole_ids:
        return

    topology = topology_engine.get_dt_topology(dt_id)
    if not topology:
        return

    dark_set = set(affected_pole_ids)
    now = datetime.now(timezone.utc)

    # Track ancestor-child pairs within 3 hops
    pairs_to_update = set()
    for child_id in affected_pole_ids:
        curr = child_id
        for _ in range(3):  # K=3 hops
            parent_id = topology.parent_map.get(curr)
            if not parent_id:
                break
            if parent_id in dark_set:
                pair = (min(parent_id, child_id), max(parent_id, child_id))
                pairs_to_update.add(pair)
            curr = parent_id

    for pole_a, pole_b in pairs_to_update:
        result = await session.execute(
            select(PoleCooccurrence).where(
                (PoleCooccurrence.pole_a_id == pole_a) &
                (PoleCooccurrence.pole_b_id == pole_b)
            )
        )
        row = result.scalar_one_or_none()

        if row:
            row.co_dark_count += 1
            row.a_dark_total += 1
            row.b_dark_total += 1
            row.last_updated = now
        else:
            session.add(PoleCooccurrence(
                pole_a_id=pole_a,
                pole_b_id=pole_b,
                co_dark_count=1,
                a_dark_total=1,
                b_dark_total=1,
                last_updated=now,
            ))


async def _find_existing_incident(
    session: AsyncSession,
    candidate: FaultCandidate,
) -> Optional[Incident]:
    """Find an existing open incident that matches this fault candidate."""
    open_statuses = [
        IncidentStatus.DETECTED,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.CREW_ASSIGNED,
        IncidentStatus.RESOLVED,
    ]

    query = select(Incident).where(
        and_(
            Incident.dt_id == candidate.dt_id,
            Incident.status.in_(open_statuses),
        )
    )

    if candidate.span_from_pole_id and candidate.span_to_pole_id:
        query = query.where(
            and_(
                Incident.span_from_pole_id == candidate.span_from_pole_id,
                Incident.span_to_pole_id == candidate.span_to_pole_id,
            )
        )

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def check_restoration(session: AsyncSession, incident_id: uuid.UUID) -> bool:
    """
    Auto-verify restoration when enough affected poles report power_restored.

    Rule: if ≥ RESTORATION_THRESHOLD% of affected poles are now LIVE → auto-verify.

    This is telemetry-driven, not button-click-driven.
    Linemen cannot fake this — the poles have to actually be live.
    """
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        return False

    if incident.status in (IncidentStatus.VERIFIED, IncidentStatus.CLOSED):
        return True

    # Get affected poles
    ip_result = await session.execute(
        select(IncidentPole).where(
            and_(
                IncidentPole.incident_id == incident_id,
                IncidentPole.role.in_(["AFFECTED", "FIRST_DARK"]),
            )
        )
    )
    incident_poles = ip_result.scalars().all()

    if not incident_poles:
        return False

    # Check current state of each affected pole
    pole_ids = [ip.pole_id for ip in incident_poles]
    pole_result = await session.execute(
        select(Pole).where(Pole.pole_id.in_(pole_ids))
    )
    poles = pole_result.scalars().all()

    live_count = sum(1 for p in poles if p.last_state == PoleState.LIVE)
    total = len(poles)

    if total == 0:
        return False

    ratio = live_count / total
    logger.debug(f"Restoration check: incident={incident_id} live={live_count}/{total} ({ratio:.0%})")

    if ratio >= settings.RESTORATION_THRESHOLD:
        now = datetime.now(timezone.utc)
        incident.status = IncidentStatus.VERIFIED
        incident.verified_at = now
        incident.updated_at = now
        incident.resolution_source = "TELEMETRY_AUTO"

        await broadcast_sse_event("incident_verified", {
            "incident_id": str(incident_id),
            "verified_at": now.isoformat(),
            "live_ratio": round(ratio, 3),
        })

        logger.info(f"✅ Incident {incident_id} auto-verified: {live_count}/{total} poles restored")
        return True

    return False


async def validate_manual_resolution(
    session: AsyncSession,
    incident_id: uuid.UUID,
) -> tuple[bool, str]:
    """
    Guard against manual resolution when poles are still dark.

    Returns: (allowed: bool, reason: str)
    """
    # Get affected poles
    ip_result = await session.execute(
        select(IncidentPole).where(
            and_(
                IncidentPole.incident_id == incident_id,
                IncidentPole.role.in_(["AFFECTED", "FIRST_DARK"]),
            )
        )
    )
    incident_poles = ip_result.scalars().all()
    pole_ids = [ip.pole_id for ip in incident_poles]

    if not pole_ids:
        return True, "No affected poles tracked"

    pole_result = await session.execute(
        select(Pole).where(Pole.pole_id.in_(pole_ids))
    )
    poles = pole_result.scalars().all()

    dark_count = sum(1 for p in poles if p.last_state == PoleState.DARK)

    if dark_count > 0:
        return False, (
            f"{dark_count} of {len(poles)} affected poles are still dark. "
            f"Resolution must be confirmed by telemetry, not manually. "
            f"System will auto-verify when power is restored."
        )

    return True, "Poles confirmed live by telemetry"
