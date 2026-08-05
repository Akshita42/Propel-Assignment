# KSPDB Electrical Fault Localization & Telemetry System (Subdivision SD 07)

Karnataka State Power Distribution Board (KSPDB)
AI-Assisted LT Distribution Network Fault Localization Engine
Subdivision SD 07 Bangalore South (Full Specification: 4 Substations, 31 Feeders, 412 Transformers, ~38,400 Poles; Demo Seed Scale: 40 Transformers, 2,208 Poles).

---

## Quick Start (Single Command)

You can bring up PostgreSQL 16, the FastAPI backend, and the React Leaflet frontend using Docker Compose:

```bash
docker compose up --build
```

- Operator Dashboard: http://localhost:3000 (or http://localhost:5173 for local Vite development)
- Backend API and Swagger Documentation: http://localhost:8000/docs
- Health Check Endpoint: http://localhost:8000/api/health

---

## Submission Links

| Deliverable | Location | Notes |
| :--- | :--- | :--- |
| **GitHub Repository** | https://github.com/Akshita42/Propel-Assignment | Public repository with full incremental commit history |
| **Live Web Application** | https://propel-fault-localizer-6yq5.onrender.com | Live cloud deployment on Render |
| **5-Minute Video Demo** | https://drive.google.com/drive/folders/1ter7b4iIid_gEAQ-ZT7UdeoZSJCyxDlu?usp=sharing | Video walkthrough of fault detection and simulator |


> ⚠️ **Note on Live URL:** Hosted on Render Free Tier. The initial HTTP request after 15 minutes of inactivity may take 30–50 seconds for cold-start container spin up. Please allow time for first response.

---

## Why This System Was Built

When severe weather hits Bangalore South during the night, hundreds of low tension pole sensors send power lost alerts at the same time. 

In the traditional setup, utility crews had to walk lines pole by pole to find broken wires. This manual process took two hours or more, and control room operators were flooded with hundreds of repetitive alarms.

The main difficulty in Bangalore South is that **60 percent of Distribution Transformers (DTs) do not have any recorded pole hierarchy in the GIS registry**. 

To solve this, I implemented an approach called **Approach B Pruned**. It uses a 4-layer topology confidence stack (Gold, Silver, Bronze, and Fallback). The system combines exact GIS records, 1D PCA directional geometric inference, and historical co-occurrence learning. It pinpoints snapped wire spans in seconds while giving an honest confidence score for every ticket.

---

## Key Features

1. **4-Layer Topology Confidence Stack**
   - **Gold (1.00):** Exact GIS parent-child tree from the registry.
   - **Silver (0.85):** Learned from historical co-dark occurrences along LT line paths.
   - **Bronze (0.60):** Inferred using 1D PCA line alignment and nearest-neighbor chaining.
   - **Fallback (0.35):** Transformer area fallback used when topology data is missing.

2. **Physical Dead Sensor Paradox Filter**
   - Power cannot jump over a broken conductor. If Pole 5 is dark but Pole 6 downstream is reporting live, Pole 5 is just a faulty sensor, not a line cut. The system automatically filters out single-device sensor failures.

3. **Topology Consistency Ratio**
   - Calculates actual dark poles divided by expected dark poles. This reduces confidence when messages are dropped or when legacy 1.2.x firmware devices stop sending telemetry without an alert.

4. **Telemetry-Verified Restoration Guard**
   - Prevents manual closing of tickets if 20 percent or more of affected poles are still dark. It automatically verifies and closes tickets when 80 percent or more of poles report power restored or boot events.

5. **Control Room Operator Dashboard and Digital Twin Simulator**
   - Interactive Leaflet dark map with traffic-light badges, live Web Audio alert chime, real-time SLA age counter, and a built-in simulator drawer with 6 fault injection scenarios (Span Fault, DT Fault, Feeder Fault, Dead Sensor Anomaly, Duplicate Noise, and Scheduled Outage).

6. **Gemini AI Dispatch Notes**
   - Uses Google Gemini 1.5/2.0 API to write 2-sentence plain English dispatch notes for field repair crews. If offline or rate-limited, it falls back cleanly to structured template notes.

---

## Project Structure

```text
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes (ingest, incidents, network, simulator, sse)
│   │   ├── core/         # Business logic (topology_engine, fault_detector, incident_manager)
│   │   ├── models/       # SQLAlchemy ORM database models
│   │   ├── schemas/      # Pydantic validation schemas
│   │   └── seed/         # Synthetic network generator and seeder
│   ├── tests/            # Pytest suite (test_localization.py, test_performance.py)
│   └── Dockerfile
├── frontend/
│   ├── src/              # React frontend (App.jsx, NetworkMap.jsx, IncidentList.jsx, SimulatorPanel.jsx)
│   ├── index.html
│   ├── vite.config.js
│   └── Dockerfile
├── build.sh               # Render production build orchestrator
├── docker-compose.yml     # Complete local stack runner
├── render.yaml            # Render deployment configuration
├── ARCHITECTURE.md        # Deep technical architecture
├── DEPLOYMENT.md          # Setup and troubleshooting guide
├── DECISIONS.md           # Technical decision log
└── AI-WORKFLOW.md         # AI engineering report
```

---

## Verification and Automated Testing

You can run the full Pytest suite covering all 19 unit, edge-case, and performance benchmark tests:

```bash
python -m pytest backend/tests/ -v
```

All 19 tests pass cleanly in under 3 seconds.

---

## Documentation Guide

For complete architectural details and design justifications, explore the documentation files in the repository:
- **[ARCHITECTURE.md](file:///ARCHITECTURE.md):** System architecture, data flow diagrams, 4-layer topology engine math, database schema models, UI reasoning, and full API endpoint specifications.
- **[DEPLOYMENT.md](file:///DEPLOYMENT.md):** Step-by-step installation instructions, environment variables table, manual verification steps, and comprehensive troubleshooting guide.
- **[DECISIONS.md](file:///DECISIONS.md):** Log of architectural decisions (ADRs), rejected alternatives, trade-offs, explicit assumptions, known limitations, and 2-week extension roadmap.
- **[AI-WORKFLOW.md](file:///AI-WORKFLOW.md):** Breakdown of AI tool usage, delegation boundaries, concrete failure cases caught, code attribution estimates, and high-value prompt excerpts.
