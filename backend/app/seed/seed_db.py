"""
Database seeder — runs automatically on startup if tables are empty.

Seeding sequence:
1. Create all tables (via SQLAlchemy metadata)
2. Generate synthetic network
3. Insert DTs and poles
4. Seed co-occurrence table from known-topology DTs (Silver layer priming)
5. Insert scheduled outages
"""

import asyncio
import random
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, AsyncSessionLocal, Base
from app.models import (
    Pole, DistributionTransformer, ScheduledOutage, PoleCooccurrence,
    PoleState, TopologySource
)
from app.seed.generate_data import generate_full_network, generate_scheduled_outages

random.seed(42)


async def create_tables():
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created (or already exist)")


async def is_seeded(session: AsyncSession) -> bool:
    """Check if database already has data."""
    result = await session.execute(text("SELECT COUNT(*) FROM poles"))
    count = result.scalar()
    return count > 0


async def seed_network(session: AsyncSession, num_dts: int = 40):
    """Generate and insert the synthetic pole network."""
    print(f"Generating synthetic network ({num_dts} DTs)...")
    dts, poles = generate_full_network(num_dts=num_dts)
    feeder_ids = list({dt.feeder_id for dt in dts})

    # Insert DTs
    for dt in dts:
        topology_source = TopologySource.GOLD if dt.topology_known else TopologySource.NONE
        session.add(DistributionTransformer(
            dt_id=dt.dt_id,
            feeder_id=dt.feeder_id,
            lat=dt.lat,
            lon=dt.lon,
            capacity_kva=dt.capacity_kva,
            households_served=dt.households_served,
            topology_source=topology_source,
        ))

    await session.flush()
    print(f"✓ Inserted {len(dts)} distribution transformers")

    # Insert Poles
    pole_batch = []
    for p in poles:
        pole_batch.append(Pole(
            pole_id=p.pole_id,
            lat=p.lat,
            lon=p.lon,
            feeder_id=p.feeder_id,
            dt_id=p.dt_id,
            seq_on_line=p.seq_on_line,
            parent_pole_id=p.parent_pole_id,
            pole_type=p.pole_type,
            ward=p.ward,
            pincode=p.pincode,
            device_id=p.device_id,
            firmware_version=p.firmware_version,
            is_legacy_firmware=p.is_legacy_firmware,
            last_state=PoleState.LIVE,   # All poles start as LIVE
            last_event_ts=datetime.now(timezone.utc),
            topology_confidence=1.0 if p.parent_pole_id else 0.0,
        ))

    session.add_all(pole_batch)
    await session.flush()
    print(f"✓ Inserted {len(poles)} poles")

    # Insert Scheduled Outages
    outages_data = generate_scheduled_outages(dts, feeder_ids)
    for o in outages_data:
        from datetime import datetime
        session.add(ScheduledOutage(
            id=o["id"],
            scope=o["scope"],
            target_id=o["target_id"],
            start_time=datetime.fromisoformat(o["start_time"]),
            end_time=datetime.fromisoformat(o["end_time"]),
            reason=o["reason"],
        ))
    print(f"✓ Inserted {len(outages_data)} scheduled outages")

    return dts, poles


async def seed_cooccurrence(session: AsyncSession, dts, poles):
    """
    Seed the co-occurrence table (Silver layer) from known-topology DTs.

    For each known-topology DT, we simulate 10 synthetic historical fault events.
    In each event, we pick a random span to break and mark all downstream poles
    as co-dark. This gives the Silver layer realistic statistical priming so it
    validates (or overrides) geometric inference from day one.
    """
    print("Seeding co-occurrence table (Silver layer priming)...")

    # Build pole lookup
    pole_map = {p.pole_id: p for p in poles}

    # Build parent→children map for known-topology DTs
    children_map: dict[str, list] = {}
    for p in poles:
        if p.parent_pole_id:
            children_map.setdefault(p.parent_pole_id, []).append(p)

    def get_downstream(pole_id: str) -> list[str]:
        """Get all poles downstream of this pole (inclusive)."""
        result = [pole_id]
        for child in children_map.get(pole_id, []):
            result.extend(get_downstream(child.pole_id))
        return result

    cooccurrence: dict[tuple[str, str], int] = {}
    dark_counts: dict[str, int] = {}

    known_dts = [dt for dt in dts if dt.topology_known]

    for dt in known_dts:
        dt_poles = [p for p in dt.poles if p.parent_pole_id is not None]
        if not dt_poles:
            continue

        for event_num in range(10):  # 10 synthetic historical fault events per DT
            # Pick a random span to break
            fault_pole = random.choice(dt_poles)
            dark_poles = get_downstream(fault_pole.pole_id)

            # Record individual dark counts
            for p_id in dark_poles:
                dark_counts[p_id] = dark_counts.get(p_id, 0) + 1

            # Record co-occurrence pairs
            for i, a in enumerate(dark_poles):
                for b in dark_poles[i+1:]:
                    pair = (min(a, b), max(a, b))
                    cooccurrence[pair] = cooccurrence.get(pair, 0) + 1

    # Insert co-occurrence records
    batch = []
    for (a, b), count in cooccurrence.items():
        batch.append(PoleCooccurrence(
            pole_a_id=a,
            pole_b_id=b,
            co_dark_count=count,
            a_dark_total=dark_counts.get(a, 0),
            b_dark_total=dark_counts.get(b, 0),
            last_updated=datetime.now(timezone.utc),
        ))

    # Batch insert in chunks to avoid memory issues
    CHUNK = 500
    for i in range(0, len(batch), CHUNK):
        session.add_all(batch[i:i+CHUNK])
        await session.flush()

    print(f"✓ Seeded {len(batch)} co-occurrence pairs from {len(known_dts)} known-topology DTs")


async def run_seed():
    """Main seeding entry point called at app startup."""
    await create_tables()

    async with AsyncSessionLocal() as session:
        if await is_seeded(session):
            print("✓ Database already seeded — skipping")
            return

        print("🌱 Seeding database...")
        dts, poles = await seed_network(session, num_dts=40)
        await seed_cooccurrence(session, dts, poles)
        await session.commit()
        print("✅ Database seeded successfully")


if __name__ == "__main__":
    asyncio.run(run_seed())
