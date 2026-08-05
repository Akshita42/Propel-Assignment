# Deployment & Operator Setup Guide

**KSPDB Electrical Fault Localization & Telemetry System (Subdivision SD 07)**

This document provides step-by-step instructions for running, testing, verifying, and troubleshooting the system locally or deploying to production environments.

---

## 1. System Requirements & Prerequisites

| Requirement | Minimum Version | Recommended | Notes |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 24.0.0+ | 27.0.0+ | Required for single-command start |
| **Docker Compose** | 2.20.0+ | 2.29.0+ | Included with Docker Desktop / Docker Engine |
| **Node.js** *(Local Dev only)* | 18.0.0+ | 20.18.0+ | Required if running React Vite frontend directly |
| **Python** *(Local Dev only)* | 3.11.0+ | 3.12.0+ | Required if running FastAPI backend directly |

---

## 2. One-Command Quick Start (Docker Compose)

To start the full stack (FastAPI Backend, React Leaflet Frontend, Database, and Topology Seeder):

```bash
# 1. Clone the repository
git clone https://github.com/Akshita42/Propel-Assignment.git
cd Propel-Assignment

# 2. Build and launch all services
docker compose up --build
```

### What Happens On Startup:
1. Database tables are created (`SQLite` / `PostgreSQL`).
2. Topology Seeder populates Subdivision SD 07 (40 Transformers, 2,208 Poles demo scale; 412 DTs, 38,400 poles spec capacity).
3. Topology Engine builds in-memory graph trees for BFS graph traversal.
4. Heartbeat background worker starts monitoring legacy and silent devices.
5. Control Room Console opens and starts listening to `/api/sse`.

### Access URLs:
- **Operator Control Room Console:** `http://localhost:3000` (or `http://localhost:5173` if running Vite locally)
- **Backend API Documentation (Swagger UI):** `http://localhost:8000/docs`
- **Health Check Endpoint:** `http://localhost:8000/api/health`

---

## 3. Local Development (Without Docker)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Start backend dev server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
```

---

## 4. Environment Variables Reference

A `.env.example` file is committed at the repository root. Copy it to `.env` if custom configurations are needed:

```bash
cp .env.example .env
```

| Variable Name | Required? | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | No | `production` | Deployment environment (`development` / `production`) |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./propel.db` | Database connection string. Supports SQLite (`sqlite+aiosqlite`) or PostgreSQL (`postgresql+asyncpg`) |
| `DATABASE_URL_SYNC` | No | `sqlite:///./propel.db` | Synchronous database connection string for Alembic migrations |
| `GEMINI_API_KEY` | Optional | `""` (Empty string) | Google Gemini API key for AI dispatch summary generation. If omitted or unreachable, structured template summaries are used seamlessly |
| `HEARTBEAT_TIMEOUT_SECONDS` | No | `1080` (18 minutes) | Timeout threshold before missing device heartbeats trigger an `UNKNOWN` state |
| `RESTORATION_THRESHOLD` | No | `0.80` (80%) | Percentage of dark poles that must report `power_restored`/`boot` to trigger automatic ticket verification |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://localhost:3000` | Allowed CORS origins (comma-separated string) |

---

## 5. System Verification & Test Suite

### Automated Testing

Run the complete Pytest suite covering all 19 localization, deduplication, noise filtering, and performance benchmark tests:

```bash
# Run pytest from the repository root
python -m pytest backend/tests/ -v
```

Actual output:
```text
backend/tests/test_localization.py::TestDeadSensorFilter::test_dark_pole_with_live_child_is_sensor_failure PASSED [  5%]
backend/tests/test_localization.py::TestDeadSensorFilter::test_dark_pole_without_live_child_is_real_fault PASSED [ 10%]
backend/tests/test_localization.py::TestBoundaryDetection::test_single_span_fault_produces_one_boundary PASSED [ 15%]
backend/tests/test_localization.py::TestBoundaryDetection::test_downstream_grouping PASSED [ 21%]
backend/tests/test_localization.py::TestBoundaryDetection::test_branched_topology_span_fault_on_main_run PASSED [ 26%]
backend/tests/test_localization.py::TestBoundaryDetection::test_branched_topology_span_fault_on_branch PASSED [ 31%]
backend/tests/test_localization.py::TestSimultaneousFaults::test_two_simultaneous_faults_on_same_line PASSED [ 36%]
backend/tests/test_localization.py::TestConfidenceScoring::test_gold_topology_full_dark_is_high_confidence PASSED [ 42%]
backend/tests/test_localization.py::TestConfidenceScoring::test_bronze_topology_is_medium_confidence PASSED [ 47%]
backend/tests/test_localization.py::TestConfidenceScoring::test_low_consistency_reduces_confidence PASSED [ 52%]
backend/tests/test_localization.py::TestConfidenceScoring::test_dt_fallback_is_low_confidence PASSED [ 57%]
backend/tests/test_localization.py::TestTopologyBoundaryEdgeCases::test_entire_dt_dark_is_dt_fault PASSED [ 63%]
backend/tests/test_localization.py::TestTopologyBoundaryEdgeCases::test_single_dark_pole_no_children_is_valid_fault PASSED [ 68%]
backend/tests/test_localization.py::TestTopologyBoundaryEdgeCases::test_empty_dark_set_no_candidates PASSED [ 73%]
backend/tests/test_localization.py::TestScheduledOutageSuppression::test_active_scheduled_outage_suppresses_detection PASSED [ 78%]
backend/tests/test_localization.py::TestRestorationVerification::test_restoration_threshold_evaluation PASSED [ 84%]
backend/tests/test_localization.py::TestEndToEndIntegration::test_end_to_end_fault_candidate_assembly PASSED [ 89%]
backend/tests/test_performance.py::test_topology_traversal_performance PASSED [ 94%]
backend/tests/test_performance.py::test_dead_sensor_filter_performance PASSED [100%]

======================== 19 passed, 1 warning in 2.45s ========================
```

### Manual System Verification Protocol

1. Open `http://localhost:3000` (or `https://propel-fault-localizer-6yq5.onrender.com`).
2. Verify that **Subdivision SD 07 Grid** stats load (Active Incidents, Live Poles, Dark Poles, Device Anomalies).
3. Click **Open Fault Simulator** in the floating bottom drawer:
   - Click **`1. Inject Span Fault (Boundary Detection)`**.
   - Verify that **1 new incident ticket** appears in the right sidebar queue with confidence score $\ge 0.85$, PIN code, ward, and red highlighted wire span on the Leaflet map.
4. Click **`2. Inject DT Fault (Entire Transformer Dark)`**:
   - Select a different DT from the dropdown and click button 2.
   - Verify a DT-level fault ticket appears in the queue.
5. Click **`3. Inject Feeder Fault (11kV Substation Outage)`**:
   - Verify a Feeder-level fault ticket is logged.
6. Click **`4. Inject Dead Sensor (Should NOT Create Ticket)`**:
   - Verify that the target pole is marked dark while children remain live, and **NO fault ticket is generated** (filtered by Dead-Sensor Paradox rule).
7. Click **`6. Inject Scheduled Outage (Suppression Test)`**:
   - Verify ticket is created with status `SUPPRESSED` and marked with planned maintenance warning notes.

---

## 6. Comprehensive Troubleshooting Guide

| Issue / Symptom | Root Cause | Solution / Fix |
| :--- | :--- | :--- |
| **Opening public URL returns `{"detail":"Not Found"}`** | Render Build Command only ran `pip install` without building the React frontend into static assets | Managed by `build.sh`. Ensure Render Build Command is set to `bash build.sh`. This orchestrates `npm install`, `npm run build`, copies dist to `backend/static/`, and installs Python requirements. |
| **Port 8000 or 3000 already in use** | Another service or local uvicorn instance is using port 8000/3000 | Stop conflicting process using `lsof -i :8000` (macOS/Linux) or `netstat -ano \| findstr :8000` (Windows), or change ports in `docker-compose.yml`. |
| **SQLite database locked (`sqlite3.OperationalError: database is locked`)** | Concurrent async writes during high-throughput batch simulation | Database is configured with `timeout=30` and write lock retries. For high concurrency production, switch `DATABASE_URL` to PostgreSQL (`postgresql+asyncpg://...`). |
| **Render Free Tier 50-second Cold Start Delay** | Render spins down free Web Services after 15 minutes of inactivity | This is normal behavior for Render free instances. Allow 30–50 seconds for the container to wake up on the first HTTP request. |
| **SSE Connection drops or offline status badge** | Browser tab went background or proxy closed idle HTTP connection | SSE stream includes automatic ping heartbeats every 15 seconds (`event: heartbeat`). Frontend automatically re-establishes connection on drop. |
| **Gemini AI summaries returning template text** | `GEMINI_API_KEY` is not set, invalid, or rate-limited | System gracefully degrades to structured string templates. Set a valid `GEMINI_API_KEY` in environment variables if LLM summaries are desired. |
| **Docker ARM (Apple Silicon M1/M2/M3) build failure** | Architecture incompatibility in native binary dependencies | Dockerfile uses standard `python:3.12-slim` and multi-arch Node images. Run `docker compose build --no-cache` to force rebuild on native architecture. |

---

## 7. Resetting to a Clean State

To wipe all data, reset database state, and re-seed the network topology from scratch:

```bash
# Docker Compose environment:
docker compose down -v
docker compose up --build

# Local environment:
rm backend/propel.db
python -c "import asyncio; from app.seed.seed_db import run_seed; asyncio.run(run_seed())"
```
