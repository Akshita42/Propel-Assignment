"""
SQLAlchemy ORM models for the Propel Fault Localization System.

Design decisions:
- poles table separates STATIC asset data (GPS, DT, feeder) from RUNTIME state
  (last_state, last_event_ts). Static data comes from the pole registry CSV;
  runtime state is updated by the ingest pipeline.
- telemetry_events is an append-only log. We never update or delete rows here.
  Deduplication happens at write time via the (pole_id, seq) unique constraint.
- incidents captures one localized fault event. It deliberately does NOT store
  the affected pole list inline — that lives in incident_poles so we can query
  it independently.
- pole_cooccurrence stores the observational learning data: how many times two
  poles went dark in the same fault event. Used by the Silver topology layer.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime,
    ForeignKey, Text, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class PoleState(str, enum.Enum):
    LIVE = "LIVE"
    DARK = "DARK"
    UNKNOWN = "UNKNOWN"
    DEVICE_FAILURE = "DEVICE_FAILURE"   # dark pole with live children — sensor fault


class FaultType(str, enum.Enum):
    SPAN = "SPAN"           # Wire between two poles
    DT = "DT"               # Distribution transformer / its HT fuse
    FEEDER = "FEEDER"       # Entire 11kV feeder
    DEVICE_FAILURE = "DEVICE_FAILURE"   # Single pole sensor, not a real outage


class IncidentStatus(str, enum.Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CREW_ASSIGNED = "CREW_ASSIGNED"
    RESOLVED = "RESOLVED"           # Crew says fixed — pending telemetry verification
    VERIFIED = "VERIFIED"           # Telemetry confirms power restored
    CLOSED = "CLOSED"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "HIGH"       # > 0.85 — exact span, known topology
    MEDIUM = "MEDIUM"   # 0.50–0.85 — geometrically inferred span
    LOW = "LOW"         # < 0.50 — DT-level fallback


class TopologySource(str, enum.Enum):
    GOLD = "GOLD"       # Known parent_pole_id from registry
    SILVER = "SILVER"   # Validated by co-occurrence agreement
    BRONZE = "BRONZE"   # PCA geometric inference only
    NONE = "NONE"       # No topology available


# ── Distribution Transformer ───────────────────────────────────────────────────

class DistributionTransformer(Base):
    __tablename__ = "distribution_transformers"

    dt_id = Column(String, primary_key=True)
    feeder_id = Column(String, nullable=False, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    capacity_kva = Column(Integer)
    households_served = Column(Integer)
    topology_source = Column(SAEnum(TopologySource), default=TopologySource.NONE)

    poles = relationship("Pole", back_populates="dt")


# ── Pole (Asset Registry + Runtime State) ─────────────────────────────────────

class Pole(Base):
    __tablename__ = "poles"

    # --- Static asset data (from pole registry CSV) ---
    pole_id = Column(String, primary_key=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    feeder_id = Column(String, nullable=False)
    dt_id = Column(String, ForeignKey("distribution_transformers.dt_id"), nullable=False)
    seq_on_line = Column(Integer, nullable=True)          # NULL for 60% of DTs
    parent_pole_id = Column(String, ForeignKey("poles.pole_id"), nullable=True)
    pole_type = Column(String, nullable=True)
    ward = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    device_id = Column(String, nullable=True)             # NULL for ~9% without device

    # --- Runtime state (updated by ingest pipeline) ---
    last_state = Column(SAEnum(PoleState), default=PoleState.UNKNOWN, nullable=False)
    last_event_ts = Column(DateTime(timezone=True), nullable=True)
    last_seq = Column(Integer, nullable=True)
    last_event_type = Column(String, nullable=True)       # heartbeat/power_lost/power_restored/boot
    last_battery_mv = Column(Integer, nullable=True)
    last_rssi = Column(Integer, nullable=True)
    firmware_version = Column(String, nullable=True)
    is_legacy_firmware = Column(Boolean, default=False)   # True for fw 1.2.x (no power_lost)

    # --- Topology inference data ---
    inferred_parent_pole_id = Column(String, nullable=True)  # From PCA/MST inference
    topology_confidence = Column(Float, default=0.0)          # Edge confidence to parent

    dt = relationship("DistributionTransformer", back_populates="poles")
    children = relationship("Pole", foreign_keys=[parent_pole_id])

    __table_args__ = (
        Index("ix_poles_dt_id", "dt_id"),
        Index("ix_poles_feeder_id", "feeder_id"),
        Index("ix_poles_state", "last_state"),
    )


# ── Telemetry Events (Append-Only Log) ────────────────────────────────────────

class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime(timezone=True), nullable=False)   # Server time
    device_id = Column(String, nullable=False)
    pole_id = Column(String, ForeignKey("poles.pole_id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)    # heartbeat/power_lost/power_restored/boot
    energized = Column(Boolean, nullable=True)
    device_ts = Column(DateTime(timezone=True), nullable=True)      # Device clock (advisory)
    seq = Column(Integer, nullable=False)
    battery_mv = Column(Integer, nullable=True)
    rssi = Column(Integer, nullable=True)
    fw = Column(String, nullable=True)
    is_duplicate = Column(Boolean, default=False)  # Flagged but kept for audit

    __table_args__ = (
        # Deduplication: same pole + same seq = same message
        UniqueConstraint("pole_id", "seq", name="uq_telemetry_pole_seq"),
        Index("ix_telemetry_pole_received", "pole_id", "received_at"),
    )


# ── Scheduled Outages ──────────────────────────────────────────────────────────

class ScheduledOutage(Base):
    __tablename__ = "scheduled_outages"

    id = Column(String, primary_key=True)
    scope = Column(String, nullable=False)          # "feeder" or "dt"
    target_id = Column(String, nullable=False)      # feeder_id or dt_id
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    reason = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_scheduled_outages_target", "scope", "target_id"),
        Index("ix_scheduled_outages_time", "start_time", "end_time"),
    )


# ── Incidents ──────────────────────────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(SAEnum(IncidentStatus), default=IncidentStatus.DETECTED, nullable=False)

    # Fault classification
    fault_type = Column(SAEnum(FaultType), nullable=False)
    dt_id = Column(String, ForeignKey("distribution_transformers.dt_id"), nullable=True, index=True)
    feeder_id = Column(String, nullable=True, index=True)

    # Span-level localization (NULL if DT-level fallback)
    span_from_pole_id = Column(String, nullable=True)   # Last LIVE pole (upstream)
    span_to_pole_id = Column(String, nullable=True)     # First DARK pole (downstream)

    # Location for dispatch
    fault_lat = Column(Float, nullable=True)            # Midpoint of span
    fault_lon = Column(Float, nullable=True)
    pincode = Column(String, nullable=True)
    ward = Column(String, nullable=True)

    # Impact
    affected_pole_count = Column(Integer, default=0)
    households_affected = Column(Integer, nullable=True)

    # Confidence
    confidence_score = Column(Float, nullable=False)    # 0.0–1.0
    confidence_level = Column(SAEnum(ConfidenceLevel), nullable=False)
    topology_source = Column(SAEnum(TopologySource), nullable=False)
    consistency_ratio = Column(Float, nullable=True)    # actual_dark / expected_dark

    # Suppression (Scheduled Outage)
    is_suppressed = Column(Boolean, default=False)
    suppression_reason = Column(String, nullable=True)

    # Resolution
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    resolution_source = Column(String, nullable=True)   # TELEMETRY_AUTO | OPERATOR_MANUAL_UNVERIFIED

    # AI summary (Gemini-generated)
    ai_summary = Column(Text, nullable=True)

    poles = relationship("IncidentPole", back_populates="incident")
    dt = relationship("DistributionTransformer")

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_created", "created_at"),
    )


# ── Incident-Pole Association ──────────────────────────────────────────────────

class IncidentPole(Base):
    __tablename__ = "incident_poles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, index=True)
    pole_id = Column(String, ForeignKey("poles.pole_id"), nullable=False)
    role = Column(String, nullable=False)   # AFFECTED | LAST_LIVE | FIRST_DARK

    incident = relationship("Incident", back_populates="poles")
    pole = relationship("Pole")

    __table_args__ = (
        UniqueConstraint("incident_id", "pole_id", name="uq_incident_pole"),
    )


# ── Pole Co-occurrence (Observational Learning — Silver Layer) ─────────────────

class PoleCooccurrence(Base):
    """
    Tracks how often two poles go dark in the same fault event.
    Used by the Silver topology layer to validate geometric inference.

    If pole_a_id goes dark in 90% of events where pole_b_id goes dark,
    but pole_b_id is only dark in 50% of events where pole_a_id is dark,
    then pole_b_id is likely UPSTREAM of pole_a_id.
    """
    __tablename__ = "pole_cooccurrence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pole_a_id = Column(String, ForeignKey("poles.pole_id"), nullable=False)
    pole_b_id = Column(String, ForeignKey("poles.pole_id"), nullable=False)
    co_dark_count = Column(Integer, default=0)   # Times both dark in same event
    a_dark_total = Column(Integer, default=0)    # Times pole_a was dark (any event)
    b_dark_total = Column(Integer, default=0)    # Times pole_b was dark (any event)
    last_updated = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("pole_a_id", "pole_b_id", name="uq_cooccurrence_pair"),
        Index("ix_cooccurrence_a", "pole_a_id"),
        Index("ix_cooccurrence_b", "pole_b_id"),
    )
