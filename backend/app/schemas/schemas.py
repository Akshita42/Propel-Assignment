"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

from app.models import (
    PoleState, FaultType, IncidentStatus, ConfidenceLevel, TopologySource
)


# ── Telemetry Ingest ───────────────────────────────────────────────────────────

class TelemetryPayload(BaseModel):
    device_id: str
    pole_id: str
    event: str = Field(..., pattern="^(heartbeat|power_lost|power_restored|boot)$")
    energized: bool
    ts: datetime
    seq: int
    battery_mv: Optional[int] = None
    rssi: Optional[int] = None
    fw: Optional[str] = None


class TelemetryBatchPayload(BaseModel):
    messages: List[TelemetryPayload]


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    unknown_poles: int


# ── Poles ──────────────────────────────────────────────────────────────────────

class PoleOut(BaseModel):
    pole_id: str
    lat: float
    lon: float
    feeder_id: str
    dt_id: str
    ward: Optional[str] = None
    pincode: Optional[str] = None
    has_device: bool
    last_state: PoleState
    last_event_ts: Optional[datetime] = None
    firmware_version: Optional[str] = None
    is_legacy_firmware: bool = False
    topology_confidence: float = 0.0

    class Config:
        from_attributes = True


# ── Incidents ──────────────────────────────────────────────────────────────────

class IncidentOut(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    status: IncidentStatus
    fault_type: FaultType

    dt_id: Optional[str] = None
    feeder_id: Optional[str] = None

    span_from_pole_id: Optional[str] = None
    span_to_pole_id: Optional[str] = None

    fault_lat: Optional[float] = None
    fault_lon: Optional[float] = None
    pincode: Optional[str] = None
    ward: Optional[str] = None

    affected_pole_count: int
    households_affected: Optional[int] = None

    confidence_score: float
    confidence_level: ConfidenceLevel
    topology_source: TopologySource
    consistency_ratio: Optional[float] = None

    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    resolution_source: Optional[str] = None

    ai_summary: Optional[str] = None

    class Config:
        from_attributes = True


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus
    note: Optional[str] = None


# ── Simulator ──────────────────────────────────────────────────────────────────

class SimulateSpanFault(BaseModel):
    dt_id: str
    span_from_pole_id: str   # Last live pole
    span_to_pole_id: str     # First dark pole (fault is on this span)


class SimulateDTFault(BaseModel):
    dt_id: str


class SimulateFeederFault(BaseModel):
    feeder_id: str


class SimulateDeviceFailure(BaseModel):
    pole_id: str             # Single device dies, power still on


class SimulateRepair(BaseModel):
    incident_id: UUID


class SimulateNoise(BaseModel):
    dt_id: str
    noise_type: str = Field(..., pattern="^(duplicate|out_of_order|stale)$")


class SimulateScheduledOutage(BaseModel):
    target_id: str
    scope: str = "dt"       # "dt" or "feeder"
    duration_hours: int = 2
    reason: str = "Planned maintenance - jumper replacement"


class SimulationResult(BaseModel):
    scenario: str
    messages_generated: int
    note: str


# ── Network Topology (for map) ─────────────────────────────────────────────────

class DTOut(BaseModel):
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: Optional[int] = None
    households_served: Optional[int] = None
    topology_source: TopologySource

    class Config:
        from_attributes = True


class TopologyEdgeOut(BaseModel):
    parent_id: str
    child_id: str
    confidence: float
    source: TopologySource


class TopologyOut(BaseModel):
    dt_id: str
    edges: List[TopologyEdgeOut]
    source: TopologySource
