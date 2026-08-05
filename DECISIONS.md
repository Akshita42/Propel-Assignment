# Architectural Decision Log (DECISIONS.md)

**KSPDB Electrical Fault Localization & Telemetry System (Subdivision SD 07)**

This document records technical design decisions, trade-off analyses, key assumptions, future extension roadmaps, and known limitations.

---

## Log of Key Architectural Decisions

### [ADR-007] 2026-08-05: Scheduled Outage Suppression Warning Flag over Silent Drop
- **Decision:** Flag outage candidates matching active scheduled outage windows as `SUPPRESSED` with an explicit warning note, rather than silently dropping them.
- **Rejected Alternative:** Silently dropping fault tickets for poles under scheduled outages.
- **Rationale:** In real-world power utilities, ~10% of planned maintenance outages are cancelled or rescheduled without updated feeds. Silently suppressing fault signals could leave genuine wire cuts unmonitored. Flagging tickets as `SUPPRESSED` keeps the control room informed without cluttering urgent queues.

---

### [ADR-006] 2026-08-04: Telemetry-Driven Auto-Verification over Manual Operator Closure
- **Decision:** Enforce strict telemetry verification rules before resolving tickets. Auto-verify tickets when $\ge 80\%$ of affected poles report `power_restored` or `boot` events. Block manual resolution if $\ge 20\%$ of poles remain dark.
- **Rejected Alternative:** Allowing operators or linemen to click "Close Ticket" freely.
- **Rationale:** Field technicians often attempt to close tickets prematurely before power is fully restored to meet SLA targets. Requiring telemetry confirmation ensures accountability and prevents prematurely closed tickets.

---

### [ADR-005] 2026-08-03: Deterministic Graph Traversal vs LLM-Based Localization
- **Decision:** Use deterministic BFS graph traversal for fault localization and restrict Google Gemini LLM strictly to generating human-readable dispatch summaries.
- **Rejected Alternative:** Feeding raw telemetry JSON into an LLM prompt to diagnose fault locations directly.
- **Rationale:** LLMs are non-deterministic, slow (~1-3s latency), expensive at scale, and prone to hallucinations (inventing non-existent pole IDs). Graph traversal is mathematical, instantaneous ($<20\text{ms}$), free, and 100% reproducible. Using LLMs solely for natural language synthesis leverages their true strength without compromising core system reliability.

---

### [ADR-004] 2026-08-02: Server-Sent Events (SSE) over WebSockets for Control Room Streaming
- **Decision:** Implement real-time dashboard updates via Server-Sent Events (`/api/sse` using `sse_starlette`).
- **Rejected Alternative:** Full-duplex WebSockets (`ws://`).
- **Rationale:** Control room dashboard updates are unidirectional (server pushes telemetry and incident events to client). SSE operates over standard HTTP/1.1 and HTTP/2, automatically handles reconnection, avoids WebSocket handshake failures behind cloud proxies (such as Render/Cloudflare), and consumes minimal memory.

---

### [ADR-003] 2026-08-01: 4-Layer Topology Confidence Stack (Approach B Pruned)
- **Decision:** Implement a 4-layer topology confidence stack (Gold: 1.00, Silver: 0.85, Bronze: 0.60, Fallback: 0.35) to handle incomplete GIS data.
- **Rejected Alternative:** Requiring 100% complete GIS data before attempting localization, or relying solely on spatial proximity clustering.
- **Rationale:** In Bangalore South (Subdivision SD 07), 60% of Distribution Transformers lack recorded pole hierarchy in GIS registries. The 4-layer confidence stack degrades gracefully: GIS trees where available, historical co-occurrence learning for unmapped poles with outage history, 1D PCA geometric line alignment for spatial coordinates, and area fallback as a last resort.

---

### [ADR-002] 2026-07-31: In-Memory Topology Graph Cache over External Graph DB (Neo4j)
- **Decision:** Store core entities in relational database (PostgreSQL/SQLite) and build an in-memory directed tree graph cache (`topology_engine`) on startup.
- **Rejected Alternative:** Deploying an external graph database cluster (e.g., Neo4j).
- **Rationale:** Low tension power distribution grids are strictly radial tree structures per Distribution Transformer. An in-memory Python dictionary graph (`parent_map`, `children_map`) processes 38,400 poles in $<5\text{ms}$ without the operational complexity, network overhead, or memory footprint of a dedicated graph DB service.

---

### [ADR-001] 2026-07-30: Per-DT Debouncing Window for Ingest Bursts
- **Decision:** Coalesce rapid telemetry messages from the same Distribution Transformer within a 2-second sliding window before triggering fault detection routines.
- **Rejected Alternative:** Running full grid fault detection synchronously inside every single incoming HTTP telemetry request.
- **Rationale:** When a main line snaps, up to 100 pole devices send `power_lost` messages within milliseconds. Running detection 100 times concurrently causes database lock contention. Debouncing ensures detection runs once per burst per DT while maintaining an ingest throughput $\ge 500\text{ msg/s}$.

---

## Key Assumptions Made Where Brief Was Ambiguous

1. **Radial Topology Assumption:** All low-tension distribution networks operate as strictly radial trees downstream of Distribution Transformers (no closed loop or mesh distribution at LT level).
2. **Monotonic Device Sequence Numbers:** Device sequence numbers (`seq`) reset on reboot but are strictly monotonic during active sessions, enabling out-of-order message rejection.
3. **Co-Occurrence Hop Limit ($K=3$):** Historical outage co-occurrence learning is bounded to ancestor-child pairs within 3 tree hops, preventing false co-occurrence associations across unrelated feeders.
4. **Heartbeat Timeout Window (18 minutes):** Devices on firmware $\ge 1.3$ send heartbeats every 15 minutes. A 18-minute threshold accounts for cellular retry delays before marking devices as `UNKNOWN`.
5. **Incident Deduplication & Reopening Window:** If an open incident already exists for a given span, incoming alerts update the existing incident rather than creating duplicate tickets. Once an incident is `CLOSED`, subsequent faults on the same span generate a new incident.
6. **Bronze Layer Maximum Pole Spacing (120m):** When chaining poles along the 1D PCA axis for unmapped DTs, adjacent poles separated by $>120\text{m}$ are treated as independent branch roots rather than connected segments.

---

## What We Would Do With Two More Weeks

1. **Distributed Redis Pub/Sub for SSE:** Replace in-memory SSE listener queues with Redis Pub/Sub to allow horizontal scaling across multiple FastAPI worker containers.
2. **Interactive Manual Topology Editor:** Build a visual drag-and-drop tree editor in the React Leaflet UI so control room engineers can manually correct inferred Bronze/Silver topology links.
3. **Real-time GIS GeoJSON Importer:** Add an ingestion pipeline for standard KSPDB GIS Shapefiles and GeoJSON exports.
4. **Historical Heatmap Analytics:** Add spatial heatmaps showing failure-prone wire spans and transformers with high maintenance frequency over time.

---

## Known Limitations and Fragilities

1. **Bronze Topology Inference on Multi-Branch DTs:** 1D Principal Component Analysis (PCA) projects 2D GPS points onto the primary line axis of maximum variance. For DTs with multiple 90-degree branch runs, poles on perpendicular branches may be chained in sub-optimal order, producing lower localization accuracy. The system handles this by assigning a base confidence of $0.60$ to Bronze tickets.
2. **Single-Worker SSE Queue:** The current SSE implementation uses an in-memory `asyncio.Queue`. When deploying with multiple uvicorn worker processes (`--workers > 1`), clients connect to a specific worker process, requiring Redis Pub/Sub for multi-worker event distribution.
3. **In-Memory Topology Invalidation:** If a pole's parent relationship is updated via direct SQL edits while the server is running, `topology_engine.rebuild()` must be called to update the in-memory graph cache.
4. **Poles API Load Scalability:** The `GET /api/network/poles` endpoint returns full pole data without pagination. At the demo scale (2,208 poles) response times are $<50\text{ms}$. At full scale (38,400 poles), server-side bounding-box spatial filtering or pagination should be added for optimal browser rendering performance.
