# AI Collaboration & Engineering Report (AI-WORKFLOW.md)

**KSPDB Electrical Fault Localization & Telemetry System (Subdivision SD 07)**

This document details how AI assistance was integrated into the software development process, what responsibilities were delegated vs. hand-architected, key AI failures caught during testing, and prompts that produced high-value output.

---

## 1. AI Tools and Usage Breakdown

| Tool / Model | Primary Usage | Purpose |
| :--- | :--- | :--- |
| **Antigravity IDE (Gemini 3.6 Flash / High)** | Core coding pair programmer | Boilerplate generation, Pydantic schemas, React components, CSS styling, Pytest suite expansion |
| **Claude 3.5 Sonnet** | Architectural review & mathematical validation | Validating 1D PCA formula, consistency ratio math, and review of dead-sensor paradox filter |
| **Google Gemini 1.5/2.0 API** | Runtime application feature | Translating raw incident payloads into 2-sentence plain English dispatch notes for control room crews |

---

## 2. Delegation Boundaries: What Was Delegated vs. Hand-Architected

### Delegated to AI (Wholesale Generation):
- **FastAPI Endpoint Boilerplate:** CRUD handlers for incident status updates, pole lists, network stats, and seed runner scripts.
- **Pydantic Validation Schemas:** Ingest payload models (`TelemetryPayload`, `TelemetryBatchPayload`, `IngestResponse`).
- **React UI Component Scaffolding:** CSS layout rules, Leaflet map component setup, navigation bar status indicators, and modal popups.
- **Test Boilerplate:** Pytest fixture setup and mock telemetry generator functions.

### Hand-Architected & Strictly Controlled (Human Ownership):
- **4-Layer Topology Confidence Stack (Approach B Pruned):** Designing the exact fallback progression (Gold → Silver → Bronze → Fallback) and defining confidence scoring logic ($1.00, 0.85, 0.60, 0.35$).
- **Physical Dead-Sensor Paradox Filter:** Deriving the mathematical condition:
  $$\text{Filter Out if } \text{State}(P) = \text{DARK} \quad \text{and} \quad \exists C \in \text{Children}(P) \text{ such that } \text{State}(C) = \text{LIVE}$$
- **1D PCA Geometric Line Inference:** Writing the linear algebra projection formula to convert 2D GPS coordinates into an ordered 1D physical line vector.
- **Topology Consistency Ratio Formula:** Defining expected dark vs. actual dark ratio math to gracefully handle missing telemetry and legacy 1.2.x firmware silent drops.

### Why We Drew the Line There:
We delegated boilerplate infrastructure (FastAPI routes, Pydantic models, React styling) because LLMs excel at syntax generation for well-established patterns. However, we strictly hand-architected the core fault localization algorithms (`fault_detector.py`, `topology_engine.py`) because AI code generation consistently failed to reason about radial tree constraints, introduced $O(N^2)$ distance loops, and hallucinated false span connections when data was incomplete. The business domain math required human derivation and explicit automated unit test verification.

---

## 3. Concrete Cases Where AI Was Misleading / Wrong & How We Caught It

### Case 1: $O(N^2)$ Pairwise Distance Matrix in Co-Occurrence Learning
- **What AI Suggested:** The AI proposed calculating all-pairs pairwise co-dark matrices across all 38,400 poles during telemetry ingest.
- **Why It Failed:** During initial burst load testing with 5,000 messages, database write locks occurred because an $O(N^2)$ update generated over $100,000$ database writes per burst.
- **How We Caught It:** Identified during `test_telemetry_burst_ingest_throughput` execution in Pytest when ingest latency spiked to $>4\text{ seconds}$.
- **Resolution:** Replaced pairwise updates with an $O(N)$ tree path traversal (`update_cooccurrence_history`) restricted to ancestor-child pairs within $K=3$ hops along the LT line tree.

### Case 2: WebSockets Disconnects on Cloud Proxies
- **What AI Suggested:** The AI initially generated a full-duplex WebSockets implementation (`/ws/telemetry`).
- **Why It Failed:** When deployed to Render's free tier, Cloudflare/Render HTTP proxies dropped idle WebSocket connections after 60 seconds, resulting in repeated client reconnect loops.
- **How We Caught It:** Browser console logs showed constant `WebSocket connection to 'wss://...' failed` errors during staging verification.
- **Resolution:** Replaced WebSockets with Server-Sent Events (SSE) using `sse_starlette` (`/api/sse`) and a 15-second heartbeat ping (`event: heartbeat`).

### Case 3: AI Proposing LLM for Direct Fault Localization
- **What AI Suggested:** The AI suggested passing raw telemetry event JSON arrays directly into a GPT-4 / Gemini prompt to diagnose broken wire spans.
- **Why It Failed:** Prompt tests revealed that the LLM hallucinated non-existent pole IDs 15% of the time, was non-deterministic, and took 2.5 seconds per query.
- **How We Caught It:** Automated Pytest assertion checks (`TestBoundaryDetection`) failed when comparing LLM output against known synthetic graph ground truth.
- **Resolution:** Restricted LLM usage strictly to generating plain English dispatch summaries *after* deterministic BFS graph traversal pinpointed the exact span.

---

## 4. Code Base Attribution Estimate

- **AI-Generated / AI-Assisted:** ~65% (FastAPI boilerplate, Pydantic models, React Leaflet layout, CSS glassmorphism, Pytest fixtures).
- **Hand-Architected / Refactored / Verified:** ~35% (Core graph traversal algorithms, dead-sensor paradox filter, PCA geometric inference, consistency ratio formulas, SSE streaming, and performance optimizations).

---

## 5. High-Value Prompt Excerpts

### Excerpt 1: Defining the 4-Layer Topology Confidence Stack

> *"We are building a fault localization system for KSPDB Subdivision SD 07 where 60% of Distribution Transformers lack pole hierarchy in the GIS registry. I need a 4-layer confidence fallback algorithm (Gold=1.0, Silver=0.85, Bronze=0.6, Fallback=0.35).*
> 
> *Write a Python class `TopologyEngine` that:*
> 1. *Uses explicit `parent_pole_id` trees where GIS data exists (Gold).*
> 2. *Uses historical co-occurrence counts along LT line paths up to 3 hops for missing GIS data (Silver).*
> 3. *Uses 1D PCA (Principal Component Analysis) on pole lat/lon coordinates to project 2D GPS points onto a 1D primary line vector and chain adjacent poles (Bronze).*
> 4. *Falls back to DT-level area attribution when coordinates are missing (Fallback).*
> 
> *Ensure all graph traversals are $O(N)$ and return confidence scores for each edge."*

### Excerpt 2: Formulating the Dead-Sensor Paradox Filter

> *"In an electrical power distribution grid, electric current cannot jump across a physical wire break. If Pole A reports DARK but its downstream child Pole B reports LIVE, Pole A must be a single sensor failure (e.g. dead modem or blown internal fuse), NOT a broken conductor line.*
> 
> *Write a python function `filter_dead_sensor_paradox(dark_poles: set[str], topology: DTTopology) -> set[str]` that iterates through dark_poles and removes any pole that has at least one child pole reporting LIVE. Return the cleaned set of genuine dark poles."*
