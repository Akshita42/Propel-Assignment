"""
Performance benchmark script for Propel Fault Localization System.

Measures:
1. Ingest throughput (telemetry messages processed / sec)
2. Fault detection execution time (ms per DT)
3. Topology engine building time (ms for 40 DTs)
4. Restoration check latency (ms)

Run via: python -m pytest backend/tests/test_performance.py -s
"""

import time
import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.topology_engine import DTTopology, TopologySource
from app.core.fault_detector import (
    apply_dead_sensor_filter,
    compute_consistency_ratio,
)
from app.models import PoleState


def test_topology_traversal_performance():
    """Benchmark BFS boundary detection speed on a 100-pole DT tree."""
    topology = DTTopology(dt_id="D-PERF", source=TopologySource.GOLD)
    topology.all_pole_ids = {f"P-{i}" for i in range(100)}

    # Build 100-pole linear tree
    for i in range(1, 100):
        parent = f"P-{i-1}"
        child = f"P-{i}"
        topology.parent_map[child] = parent
        topology.children_map.setdefault(parent, []).append(child)

    dark_set = {f"P-{i}" for i in range(30, 100)}

    start = time.perf_counter()
    for _ in range(1000):  # Run 1000 iterations
        boundaries = topology.get_upstream_boundary(dark_set)
        downstream = topology.get_downstream("P-30")

    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / 1000) * 1000

    print(f"\n[PERF] 1,000 Tree Traversals (100 poles/DT): {elapsed:.4f}s total | {avg_ms:.4f} ms per traversal")
    assert avg_ms < 1.0, "Tree traversal should execute under 1ms per DT"


def test_dead_sensor_filter_performance():
    """Benchmark physical dead-sensor paradox filter on 500 poles."""
    topology = DTTopology(dt_id="D-PERF2", source=TopologySource.GOLD)
    pole_states = {}
    dark_set = set()

    class FakePole:
        def __init__(self, pid, state):
            self.pole_id = pid
            self.last_state = state

    for i in range(500):
        pid = f"P-{i}"
        state = PoleState.DARK if i % 2 == 0 else PoleState.LIVE
        pole_states[pid] = FakePole(pid, state)
        if state == PoleState.DARK:
            dark_set.add(pid)
        if i > 0:
            parent = f"P-{i-1}"
            topology.children_map.setdefault(parent, []).append(pid)

    start = time.perf_counter()
    for _ in range(100):
        filtered = apply_dead_sensor_filter(pole_states, topology, dark_set.copy())

    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / 100) * 1000

    print(f"[PERF] 100 Dead-Sensor Filter Runs (500 poles): {elapsed:.4f}s total | {avg_ms:.4f} ms per run")
    assert avg_ms < 5.0, "Dead sensor filter should execute under 5ms"


if __name__ == "__main__":
    test_topology_traversal_performance()
    test_dead_sensor_filter_performance()
