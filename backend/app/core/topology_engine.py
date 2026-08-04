"""
Topology Engine — Approach B Pruned

Builds a per-DT directed tree where each edge has a confidence score
and a source layer (Gold/Silver/Bronze).

Layer Strategy:
  GOLD   (confidence=1.0): Known parent_pole_id from pole registry
  SILVER (confidence=0.85): Bronze edge confirmed by co-occurrence agreement
  BRONZE (confidence=0.60): PCA-based directional chain (geometric inference)
  NONE   (confidence=0.0):  No topology available → DT-level fallback

PCA-based geometric inference:
  For a DT with unknown topology, we project all its poles onto the first
  principal component (the axis of maximum variance from the DT location).
  This gives us a 1D "distance along the line" proxy, which we use to order
  poles and chain them parent→child along that axis.

  Why PCA instead of pure Euclidean distance from DT?
  - Euclidean distance from DT collapses all branches to the same ordering
  - PCA captures the primary direction of the line, so branches that deviate
    from the main axis are naturally separated
  - Still not perfect for multi-branch DTs, but far better than random order

Silver validation:
  After building Bronze chains, we check each inferred edge against the
  co-occurrence table. If pole B is dark in ≥85% of events where pole A is dark,
  the A→B edge is promoted from Bronze to Silver.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Pole, PoleCooccurrence, TopologySource

logger = logging.getLogger(__name__)


@dataclass
class TopologyEdge:
    """A directed edge in the LT network tree."""
    parent_id: str
    child_id: str
    confidence: float
    source: TopologySource


@dataclass
class DTTopology:
    """Complete topology for one distribution transformer."""
    dt_id: str
    source: TopologySource               # Worst-case source used
    edges: list[TopologyEdge] = field(default_factory=list)
    parent_map: dict[str, str] = field(default_factory=dict)    # child_id → parent_id
    children_map: dict[str, list[str]] = field(default_factory=dict)  # parent_id → [child_ids]
    root_pole_ids: list[str] = field(default_factory=list)      # First poles from DT
    all_pole_ids: set[str] = field(default_factory=set)
    pole_confidence: dict[str, float] = field(default_factory=dict)  # child → edge confidence

    def get_downstream(self, pole_id: str) -> list[str]:
        """BFS to get all poles downstream of a given pole (inclusive)."""
        result = []
        queue = [pole_id]
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            result.append(current)
            queue.extend(self.children_map.get(current, []))
        return result

    def get_upstream_boundary(self, dark_pole_ids: set[str]) -> list[tuple[str, str, float]]:
        """
        Find live→dark boundary edges.
        Returns list of (live_parent_id, dark_child_id, edge_confidence).
        """
        boundaries = []
        for edge in self.edges:
            parent_dark = edge.parent_id in dark_pole_ids
            child_dark = edge.child_id in dark_pole_ids
            if not parent_dark and child_dark:
                boundaries.append((edge.parent_id, edge.child_id, edge.confidence))
        return boundaries


class TopologyEngine:
    """
    Singleton topology engine — built once at startup, held in memory.
    Provides fast tree traversal for fault localization.
    """

    def __init__(self):
        self._dt_topologies: dict[str, DTTopology] = {}
        self._pole_to_dt: dict[str, str] = {}
        self._built = False

    async def build(self, session: AsyncSession):
        """Build topology for all DTs. Called once at startup."""
        logger.info("Building topology engine...")

        # Load all poles
        result = await session.execute(
            select(Pole).order_by(Pole.dt_id, Pole.seq_on_line.nullslast(), Pole.pole_id)
        )
        poles = result.scalars().all()

        # Load co-occurrence data
        cooc_result = await session.execute(select(PoleCooccurrence))
        cooc_rows = cooc_result.scalars().all()
        cooc_map: dict[tuple[str, str], PoleCooccurrence] = {}
        for row in cooc_rows:
            cooc_map[(row.pole_a_id, row.pole_b_id)] = row
            cooc_map[(row.pole_b_id, row.pole_a_id)] = row

        # Group poles by DT
        dt_poles: dict[str, list[Pole]] = {}
        for pole in poles:
            self._pole_to_dt[pole.pole_id] = pole.dt_id
            dt_poles.setdefault(pole.dt_id, []).append(pole)

        # Build topology per DT
        for dt_id, dt_pole_list in dt_poles.items():
            topology = self._build_dt_topology(dt_id, dt_pole_list, cooc_map)
            self._dt_topologies[dt_id] = topology

        self._built = True
        known = sum(1 for t in self._dt_topologies.values() if t.source == TopologySource.GOLD)
        bronze = sum(1 for t in self._dt_topologies.values() if t.source == TopologySource.BRONZE)
        silver = sum(1 for t in self._dt_topologies.values() if t.source == TopologySource.SILVER)
        logger.info(
            f"Topology built: {len(self._dt_topologies)} DTs | "
            f"Gold={known} Bronze={bronze} Silver={silver}"
        )

    def _build_dt_topology(
        self,
        dt_id: str,
        poles: list[Pole],
        cooc_map: dict[tuple[str, str], PoleCooccurrence],
    ) -> DTTopology:
        """Build topology for a single DT using the layered strategy."""

        topology = DTTopology(dt_id=dt_id)
        topology.all_pole_ids = {p.pole_id for p in poles}

        # Check if this DT has known topology (Gold layer)
        has_known = any(p.parent_pole_id is not None for p in poles)

        if has_known:
            return self._build_gold_topology(topology, poles, cooc_map)
        else:
            return self._build_bronze_topology(topology, poles, cooc_map)

    def _build_gold_topology(
        self,
        topology: DTTopology,
        poles: list[Pole],
        cooc_map: dict,
    ) -> DTTopology:
        """Build exact tree from known parent_pole_id data (Gold layer)."""
        for pole in poles:
            topology.pole_confidence[pole.pole_id] = 1.0
            if pole.parent_pole_id and pole.parent_pole_id in topology.all_pole_ids:
                edge = TopologyEdge(
                    parent_id=pole.parent_pole_id,
                    child_id=pole.pole_id,
                    confidence=1.0,
                    source=TopologySource.GOLD,
                )
                topology.edges.append(edge)
                topology.parent_map[pole.pole_id] = pole.parent_pole_id
                topology.children_map.setdefault(pole.parent_pole_id, []).append(pole.pole_id)
            else:
                # No parent → this is a root pole (directly fed by DT)
                topology.root_pole_ids.append(pole.pole_id)

        topology.source = TopologySource.GOLD
        return topology

    def _build_bronze_topology(
        self,
        topology: DTTopology,
        poles: list[Pole],
        cooc_map: dict,
    ) -> DTTopology:
        """
        Build inferred tree using PCA-based directional chaining (Bronze layer),
        then validate edges against co-occurrence (Silver promotion).
        """
        if len(poles) < 2:
            topology.source = TopologySource.NONE
            topology.root_pole_ids = [p.pole_id for p in poles]
            return topology

        # Step 1: PCA projection
        # Project all poles onto the first principal component from the DT
        coords = np.array([[p.lat, p.lon] for p in poles])

        # Center on mean (roughly the DT location)
        mean = coords.mean(axis=0)
        centered = coords - mean

        # PCA: find first principal component
        cov = np.cov(centered.T)
        if np.isscalar(cov) or cov.ndim < 2:
            # Degenerate case (all poles at same location)
            pca_scores = np.arange(len(poles), dtype=float)
        else:
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            # eigenvectors are sorted ascending; take last (largest eigenvalue)
            pc1 = eigenvectors[:, -1]
            pca_scores = centered @ pc1  # 1D projection

        # Step 2: Sort poles by PCA score (from DT outward along primary axis)
        order = np.argsort(pca_scores)
        sorted_poles = [poles[i] for i in order]

        # Step 3: Build nearest-neighbor chain along PCA axis
        # First pole becomes root (closest to DT on primary axis)
        # Each subsequent pole's parent is its nearest already-placed predecessor
        # that doesn't skip over poles (prevents long jumps across branches)
        placed: list[Pole] = []
        source_map: dict[str, TopologySource] = {}

        for i, pole in enumerate(sorted_poles):
            if i == 0:
                topology.root_pole_ids.append(pole.pole_id)
                topology.pole_confidence[pole.pole_id] = 0.6
                placed.append(pole)
                continue

            # Find nearest already-placed pole within a reasonable radius
            # Max distance = 120m (typical max pole spacing is ~70m, allow headroom)
            MAX_SPACING_M = 120.0
            best_parent = None
            best_dist = float("inf")

            for candidate in placed[-10:]:  # Only look at recent poles (efficiency)
                dist = self._haversine_m(pole.lat, pole.lon, candidate.lat, candidate.lon)
                if dist < best_dist and dist < MAX_SPACING_M:
                    best_dist = dist
                    best_parent = candidate

            if best_parent is None:
                # No nearby parent — start a new "branch root" from DT
                topology.root_pole_ids.append(pole.pole_id)
                topology.pole_confidence[pole.pole_id] = 0.6
            else:
                # Check Silver promotion: does co-occurrence confirm this edge?
                conf, src = self._get_edge_confidence(
                    best_parent.pole_id, pole.pole_id, cooc_map
                )
                edge = TopologyEdge(
                    parent_id=best_parent.pole_id,
                    child_id=pole.pole_id,
                    confidence=conf,
                    source=src,
                )
                topology.edges.append(edge)
                topology.parent_map[pole.pole_id] = best_parent.pole_id
                topology.children_map.setdefault(best_parent.pole_id, []).append(pole.pole_id)
                topology.pole_confidence[pole.pole_id] = conf

            placed.append(pole)

        # Determine overall source (worst case of all edges)
        if any(e.source == TopologySource.SILVER for e in topology.edges):
            topology.source = TopologySource.SILVER
        else:
            topology.source = TopologySource.BRONZE

        return topology

    def _get_edge_confidence(
        self,
        parent_id: str,
        child_id: str,
        cooc_map: dict,
    ) -> tuple[float, TopologySource]:
        """
        Determine edge confidence using co-occurrence data.

        If child is dark in ≥85% of events where parent is dark,
        the geometric inference is validated → Silver (0.85).
        Otherwise → Bronze (0.60).
        """
        pair = (min(parent_id, child_id), max(parent_id, child_id))
        cooc = cooc_map.get(pair) or cooc_map.get((parent_id, child_id))

        if cooc is None or cooc.a_dark_total < 3:
            # Insufficient co-occurrence data → Bronze
            return 0.60, TopologySource.BRONZE

        # Check directional ratio:
        # If child was dark in most events where parent was dark → likely downstream
        if cooc.pole_a_id == parent_id:
            parent_dark_total = cooc.a_dark_total
        else:
            parent_dark_total = cooc.b_dark_total

        if parent_dark_total == 0:
            return 0.60, TopologySource.BRONZE

        co_dark_ratio = cooc.co_dark_count / parent_dark_total

        if co_dark_ratio >= 0.85:
            return 0.85, TopologySource.SILVER
        else:
            return 0.60, TopologySource.BRONZE

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in metres."""
        R = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.asin(math.sqrt(a))

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_dt_topology(self, dt_id: str) -> Optional[DTTopology]:
        return self._dt_topologies.get(dt_id)

    def get_pole_dt(self, pole_id: str) -> Optional[str]:
        return self._pole_to_dt.get(pole_id)

    def get_all_dt_ids(self) -> list[str]:
        return list(self._dt_topologies.keys())

    def is_built(self) -> bool:
        return self._built


# Module-level singleton
topology_engine = TopologyEngine()
