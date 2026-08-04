"""
Synthetic network generator for the Propel Fault Localization System.

Generates a realistic Karnataka-style LT distribution network:
  - 4 substations, 31 feeders, 412 DTs, ~38,400 poles (full scale)
  - For demo: 4 substations, 8 feeders, 40 DTs, ~3000 poles

Design principles:
  - 40% of DTs have known topology (parent_pole_id, seq_on_line) — Gold layer
  - 60% of DTs have missing topology — need Bronze/Silver inference
  - ~9% of poles have no device fitted
  - ~8% of devices on legacy firmware 1.2.x (no power_lost event)
  - Radial tree structure with 1–5 branches per DT
  - Realistic GPS coordinates in Bangalore South subdivision
  - Lines run along realistic street directions (not random scatter)
"""

import random
import math
import json
from dataclasses import dataclass, field
from typing import Optional

random.seed(42)  # Reproducible synthetic data

# ── Bangalore South subdivision bounding box ──────────────────────────────────
# Real coordinates for Jayanagar / Banashankari / JP Nagar area
LAT_CENTER = 12.9352
LON_CENTER = 77.5831
LAT_SPREAD = 0.08    # ~8.9 km N-S
LON_SPREAD = 0.10    # ~11 km E-W


@dataclass
class GeneratedPole:
    pole_id: str
    lat: float
    lon: float
    feeder_id: str
    dt_id: str
    seq_on_line: Optional[int]
    parent_pole_id: Optional[str]
    pole_type: str
    ward: str
    pincode: str
    device_id: Optional[str]
    firmware_version: Optional[str]
    is_legacy_firmware: bool


@dataclass
class GeneratedDT:
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int
    topology_known: bool
    poles: list = field(default_factory=list)


POLE_TYPES = ["LT-9m-PCC", "LT-9m-PCC", "LT-9m-PCC", "LT-8m-Steel", "LT-11m-PCC"]
WARDS = [f"W-{i:03d}" for i in range(60, 100)]
PINCODES = ["560011", "560041", "560061", "560070", "560078", "560085", "560095", "560098"]
CAPACITIES = [100, 160, 250, 315, 400, 500]


def random_lat(base_lat: float, spread: float = 0.002) -> float:
    return base_lat + random.uniform(-spread, spread)


def random_lon(base_lon: float, spread: float = 0.003) -> float:
    return base_lon + random.uniform(-spread, spread)


def bearing_to_delta(bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Convert bearing + distance to lat/lon delta."""
    # 1 degree lat ≈ 111,139 m; 1 degree lon ≈ 111,139 * cos(lat)
    lat_per_m = 1 / 111139
    lon_per_m = 1 / (111139 * math.cos(math.radians(LAT_CENTER)))
    rad = math.radians(bearing_deg)
    dlat = distance_m * math.cos(rad) * lat_per_m
    dlon = distance_m * math.sin(rad) * lon_per_m
    return dlat, dlon


def generate_lt_line(
    dt_lat: float,
    dt_lon: float,
    dt_id: str,
    feeder_id: str,
    num_poles: int,
    bearing_deg: float,
    ward: str,
    pincode: str,
    topology_known: bool,
    start_seq: int = 1,
    parent_pole_id: Optional[str] = None,
    pole_id_offset: int = 0,
) -> list[GeneratedPole]:
    """Generate a single LT line (main run or branch)."""
    poles = []
    current_lat = dt_lat
    current_lon = dt_lon
    current_parent = parent_pole_id

    for i in range(num_poles):
        # Space poles 30–60m apart along the line, with slight deviation
        spacing = random.uniform(35, 55)
        deviation = random.uniform(-15, 15)  # degrees off bearing
        actual_bearing = bearing_deg + deviation
        dlat, dlon = bearing_to_delta(actual_bearing, spacing)

        current_lat += dlat
        current_lon += dlon

        pole_num = pole_id_offset + i + 1
        pole_id = f"P-{dt_id}-{pole_num:03d}"

        # Device assignment (~9% no device)
        has_device = random.random() > 0.09
        if has_device:
            device_id = f"KSPDB-{feeder_id}-{pole_id}"
            # ~8% legacy firmware
            is_legacy = random.random() < 0.08
            fw = "1.2.3" if is_legacy else random.choice(["1.3.1", "1.3.2", "1.4.0", "1.4.2"])
        else:
            device_id = None
            is_legacy = False
            fw = None

        seq = (start_seq + i) if topology_known else None
        parent = current_parent if topology_known else None

        poles.append(GeneratedPole(
            pole_id=pole_id,
            lat=current_lat,
            lon=current_lon,
            feeder_id=feeder_id,
            dt_id=dt_id,
            seq_on_line=seq,
            parent_pole_id=parent,
            pole_type=random.choice(POLE_TYPES),
            ward=ward,
            pincode=pincode,
            device_id=device_id,
            firmware_version=fw,
            is_legacy_firmware=is_legacy,
        ))

        current_parent = pole_id

    return poles


def generate_dt_network(
    dt_id: str,
    feeder_id: str,
    dt_lat: float,
    dt_lon: float,
    topology_known: bool,
) -> tuple[GeneratedDT, list[GeneratedPole]]:
    """
    Generate a full distribution transformer with its LT lines.
    Each DT gets 1 main run + 1–3 branches.
    Total poles per DT: 9–240, median ~70.
    """
    capacity = random.choice(CAPACITIES)
    households = int(capacity * random.uniform(0.8, 1.5))
    ward = random.choice(WARDS)
    pincode = random.choice(PINCODES)

    dt = GeneratedDT(
        dt_id=dt_id,
        feeder_id=feeder_id,
        lat=dt_lat,
        lon=dt_lon,
        capacity_kva=capacity,
        households_served=households,
        topology_known=topology_known,
    )

    all_poles: list[GeneratedPole] = []
    bearing = random.uniform(0, 360)   # Primary direction of the main run

    # Main run: 15–50 poles
    main_count = random.randint(15, 50)
    main_poles = generate_lt_line(
        dt_lat, dt_lon, dt_id, feeder_id,
        main_count, bearing, ward, pincode, topology_known,
        start_seq=1, parent_pole_id=None, pole_id_offset=0,
    )
    all_poles.extend(main_poles)

    # Branches: 1–3 branches off random points on the main run
    num_branches = random.randint(1, 3)
    pole_offset = len(all_poles)

    for b in range(num_branches):
        branch_count = random.randint(5, 20)
        # Branch off a random pole in the first 2/3 of the main run
        branch_root_idx = random.randint(0, max(0, int(len(main_poles) * 0.66)))
        branch_root = main_poles[branch_root_idx]
        branch_bearing = bearing + random.choice([-90, -70, 70, 90]) + random.uniform(-15, 15)

        branch_poles = generate_lt_line(
            branch_root.lat, branch_root.lon, dt_id, feeder_id,
            branch_count, branch_bearing, ward, pincode, topology_known,
            start_seq=len(all_poles) + 1 if topology_known else None,
            parent_pole_id=branch_root.pole_id if topology_known else None,
            pole_id_offset=pole_offset,
        )
        all_poles.extend(branch_poles)
        pole_offset += len(branch_poles)

    dt.poles = all_poles
    return dt, all_poles


def generate_full_network(
    num_dts: int = 40,
    known_topology_fraction: float = 0.40,
) -> tuple[list[GeneratedDT], list[GeneratedPole]]:
    """
    Generate the full synthetic network.

    Args:
        num_dts: Number of distribution transformers
        known_topology_fraction: Fraction of DTs with known pole ordering

    Returns:
        (list of DTs, list of all poles)
    """
    num_feeders = max(4, num_dts // 8)
    feeder_ids = [f"F-{i+1:02d}" for i in range(num_feeders)]

    all_dts: list[GeneratedDT] = []
    all_poles: list[GeneratedPole] = []

    num_known = int(num_dts * known_topology_fraction)
    known_dt_indices = set(random.sample(range(num_dts), num_known))

    for i in range(num_dts):
        feeder_id = feeder_ids[i % num_feeders]
        dt_id = f"D-{i+1:04d}"

        # Spread DTs across the subdivision
        dt_lat = LAT_CENTER + random.uniform(-LAT_SPREAD, LAT_SPREAD)
        dt_lon = LON_CENTER + random.uniform(-LON_SPREAD, LON_SPREAD)

        topology_known = i in known_dt_indices

        dt, dt_poles = generate_dt_network(
            dt_id, feeder_id, dt_lat, dt_lon, topology_known
        )
        all_dts.append(dt)
        all_poles.extend(dt_poles)

    print(f"Generated {len(all_dts)} DTs, {len(all_poles)} poles")
    print(f"  Known topology: {num_known} DTs ({num_known/num_dts*100:.0f}%)")
    print(f"  Missing topology: {num_dts-num_known} DTs ({(num_dts-num_known)/num_dts*100:.0f}%)")
    print(f"  Poles with device: {sum(1 for p in all_poles if p.device_id)} ({sum(1 for p in all_poles if p.device_id)/len(all_poles)*100:.0f}%)")
    print(f"  Legacy firmware: {sum(1 for p in all_poles if p.is_legacy_firmware)}")

    return all_dts, all_poles


def generate_scheduled_outages(dts: list[GeneratedDT], feeder_ids: list[str]) -> list[dict]:
    """Generate realistic scheduled outage records."""
    from datetime import datetime, timezone, timedelta

    outages = []
    now = datetime.now(timezone.utc)

    # 2 feeder outages (future)
    for i, fid in enumerate(feeder_ids[:2]):
        start = now + timedelta(hours=random.randint(6, 24))
        outages.append({
            "id": f"SO-{now.strftime('%Y-%m-%d')}-{i+1:03d}",
            "scope": "feeder",
            "target_id": fid,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=2, minutes=30)).isoformat(),
            "reason": "Planned maintenance - jumper replacement",
        })

    # 3 DT outages (one in the past — simulates a completed scheduled outage)
    sample_dts = random.sample(dts, min(3, len(dts)))
    for i, dt in enumerate(sample_dts):
        if i == 0:
            # Past outage — already completed
            start = now - timedelta(hours=3)
            end = now - timedelta(hours=1)
        else:
            start = now + timedelta(hours=random.randint(1, 12))
            end = start + timedelta(hours=1)

        outages.append({
            "id": f"SO-{now.strftime('%Y-%m-%d')}-DT-{i+1:03d}",
            "scope": "dt",
            "target_id": dt.dt_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "reason": "Load shedding",
        })

    return outages


if __name__ == "__main__":
    dts, poles = generate_full_network(num_dts=40)
    print(f"\nSample pole: {poles[0].__dict__}")
    print(f"Sample DT: {dts[0].dt_id}, poles: {len(dts[0].poles)}")
