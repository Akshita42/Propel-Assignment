# Propel AI Assignment — Full Panel Evaluation Report

---

## PHASE 1 — Assignment Understanding

### What the assignment is ACTUALLY testing

This is not a "build a CRUD app" exercise. The assignment is testing:

1. **Can you solve a hard inference problem?** You have node-level binary data (live/dark) and must infer edge-level faults on a tree. The 60% missing topology is the central design question — not a footnote.
2. **Can you distinguish signal from noise?** Dead sensors, scheduled outages, 30% missing messages, legacy firmware silence, duplicate/stale telemetry. A system that alerts on noise is worse than no system.
3. **Product judgment over engineering volume.** They explicitly say a plain UI with correct localization scores higher than a beautiful dashboard that alerts on every dark pole.
4. **Can you hand off work?** Documentation is 15% of the grade. The reviewer has 45 minutes and will not chase you.
5. **Do you understand what you shipped?** The follow-up call will probe whether you actually grasp the code or just generated it.

### Hidden expectations

- The `consistency_ratio` field is never mentioned in the assignment but is critical for honest confidence reporting.
- The self-check list in `03-deliverables` is effectively a regression test suite the reviewer will run.
- "Make it run" is a gate, not a category. If `docker compose up` fails, nothing else is scored.
- The 5-minute demo video is insurance against deployment failures — it's not optional.

---

## PHASE 2 — Repository Review

### Architecture

**Verdict: Appropriate and well-structured.**

| Aspect | Assessment |
|--------|-----------|
| Stack choice | FastAPI + PostgreSQL + React — pragmatic, fast to build, handles async well |
| Separation | Clean: `core/` (topology_engine, fault_detector, incident_manager), `api/` (routes), `models/`, `seed/` |
| Over-engineering | The Bronze/Silver/Gold topology tiering is genuinely good design, not over-engineering — it directly addresses the 60% problem |
| Under-engineering | SSE implementation is minimal but functional. No WebSocket complexity — good tradeoff for assignment scope |
| Maintainability | High. Each file has a clear responsibility. Docstrings explain the "why" not just the "what" |

### Backend — Code Quality

| Aspect | Score | Notes |
|--------|-------|-------|
| Folder structure | Good | `api/`, `core/`, `models/`, `schemas/`, `seed/` — clean and navigable |
| Separation of concerns | Good | Fault detection is in `core/`, not in API handlers. Incident creation is separate from detection |
| Readability | Very good | Comments explain domain reasoning (e.g., "power cannot skip a pole"). Docstrings on all major functions |
| Error handling | Adequate | Background tasks catch and log exceptions. Rollback on failure. Some edge cases could be tighter |
| Scalability concerns | Medium | The `detect_all_faults` function iterates every DT on every `power_lost` — at 412 DTs × 39 msg/s this would be a bottleneck. For the demo scale (40 DTs) it's fine |

### Fault Localization — HIGHEST PRIORITY

This is 25% of the score.

**Correctness:**
- ✅ Boundary detection (live parent → dark child) is correctly implemented in `get_upstream_boundary()`
- ✅ Downstream grouping works — all dark poles below a boundary edge are grouped into one incident
- ✅ Multiple simultaneous faults produce multiple boundaries → multiple tickets

**Missing topology handling:**
- ✅ The Gold/Bronze/Silver tiering is a sophisticated and defensible answer to the 60% problem
- ✅ PCA-based geometric inference for Bronze is plausible for linear LT lines
- ✅ Co-occurrence validation for Silver promotion is a genuinely clever idea
- 🟡 The PCA approach will fail on DTs with multiple branches at right angles (it projects to 1D). The `_build_bronze_topology` looks at only the last 10 placed poles for nearest-neighbor, which could produce incorrect edges on branched networks. This is a known failure mode that should be documented but isn't explicitly called out.

**Noise handling:**
- ✅ Dead-sensor paradox filter: dark pole with live child → DEVICE_FAILURE, no ticket
- ✅ Scheduled outage suppression with ±20 minute grace window
- ✅ Deduplication via `(pole_id, seq)` unique constraint
- ✅ Out-of-order messages handled via `seq > last_seq` check
- ✅ Heartbeat timeout background job marks silent poles as UNKNOWN
- 🟡 The ±20 minute grace could mask a real fault during a scheduled outage window. The assignment says "~10% of outages are cancelled without the feed being updated" — the code suppresses fully rather than adding a warning flag (despite the comment claiming otherwise at line 95-96)

**False positive handling:**
- ✅ Dead-sensor filter prevents single-device failures from generating tickets
- ✅ Scheduled outage suppression prevents load-shedding tickets
- 🟡 No explicit debouncing/windowing for the grouping of rapid-fire `power_lost` messages. The fault detection runs on every single `power_lost` event. In a 5000-message burst, this means ~5000 fault detection runs within seconds.

**Confidence handling:**
- ✅ Three-tier confidence (HIGH/MEDIUM/LOW) based on score thresholds
- ✅ Confidence weighted by topology source (Gold=1.0, Silver=0.85, Bronze=0.60) × consistency ratio
- ✅ Consistency ratio (actual_dark / expected_dark) accounts for missing devices and legacy firmware
- ✅ UI displays confidence level prominently with color coding

**Edge cases:**
- ✅ Leaf pole going dark (no children) — correctly treated as valid fault
- ✅ All poles dark (DT fault) — handled before span detection
- ✅ Feeder fault (all DTs on feeder dark) — merged into single feeder ticket
- 🟡 A pole with no device on the fault boundary is not explicitly addressed in the code or documentation

### Simulator

| Aspect | Assessment |
|--------|-----------|
| Realism | Good — models 70% success rate for dying messages, firmware 1.2.x silence, timestamp skew |
| Fault types | All required: span, DT, feeder, device failure |
| Noise generation | Duplicate, out-of-order, and stale message injection |
| Repair simulation | Sends boot + power_restored for affected poles |
| UI drivability | Excellent — dropdown for DT selection, labeled buttons for each scenario |
| Missing | No explicit scheduled outage injection from the UI simulator (outages are seeded but not dynamically injectable) |

### Database Schema

**Verdict: Well-designed.**

- Poles table cleanly separates static asset data from runtime state
- Telemetry events are append-only (audit trail)
- `(pole_id, seq)` unique constraint handles deduplication at the DB level
- `incident_poles` junction table is the right design for many-to-many
- `pole_cooccurrence` table for Silver layer — forward-thinking
- Appropriate indexes on frequently queried columns
- `consistency_ratio` stored on incidents — good for post-hoc analysis

### Frontend

| Aspect | Assessment |
|--------|-----------|
| UI quality | Professional. Dark theme, clean typography, proper hierarchy |
| Information hierarchy | Good — map dominates, incident queue on right, detail panel on click |
| Operator usability | Good — GPS coordinates, PIN code, and AI summary are front and center for dispatch |
| Confidence visualization | Excellent — colored badges (CONFIRMED SPAN 98%, ESTIMATED ZONE 53%) |
| Map visualization | Good — grey wire topology lines, red dashed fault spans, pole markers |
| Workflow actions | Appropriate — Acknowledge → Assign Crew → Mark Fixed progression |
| Telemetry guard | Excellent — blocks manual resolution when poles are still dark, with clear error message |

**Weaknesses:**
- No keyboard shortcuts for operators
- No sound/notification for new incidents (2 a.m. operator might miss silent updates)
- The incident list doesn't show "time since detection" which is critical for an operator prioritizing response
- No "resolve all" or bulk actions

### AI Usage

| Aspect | Assessment |
|--------|-----------|
| Where AI is used | Gemini generates plain-English dispatch summaries for control room operators |
| Is it appropriate? | Yes — this is the right spot. The assignment explicitly warns against LLM-based fault localization |
| Cost awareness | Comment says ~$0.001 per summary — reasonable |
| Graceful degradation | Falls back to template summary when Gemini API is unavailable |
| Overuse? | No — one call per incident, not in the hot path |

**However:** The AI feature is somewhat thin. A stronger use case might include pattern recognition across historical incidents, or natural-language querying of the fault log. The current template fallback produces nearly identical output to the Gemini version, undermining the argument that the LLM "earns its keep."

### Documentation

> [!CAUTION]
> **CRITICAL FINDING: ALL FIVE REQUIRED DOCUMENTATION FILES ARE MISSING.**
>
> The assignment requires these files at the repo root:
> - `README.md` — ❌ Missing
> - `ARCHITECTURE.md` — ❌ Missing
> - `DEPLOYMENT.md` — ❌ Missing
> - `DECISIONS.md` — ❌ Missing
> - `AI-WORKFLOW.md` — ❌ Missing
>
> Only `frontend/README.md` exists (Vite boilerplate, not the project README).
>
> **Documentation is 15% of the total score and also gates reviewability.**
> A reviewer opening this repo sees no README, no architecture diagram, no deployment instructions, no decision log.
> This is a **submission-critical gap**.

---

## PHASE 3 — Assignment Compliance Checklist

### Acceptance Gates

| Gate | Requirement | Status | Notes |
|------|-------------|--------|-------|
| G1 | Public GitHub repository | 🟡 Unknown | Not verified — need to check if repo is public |
| G2 | `docker compose up` brings up everything | ✅ Done | Works (verified during this session) |
| G3 | Seeded on startup with synthetic network | ✅ Done | 40 DTs, ~2200 poles, 40/60 Gold/Bronze split |
| G4 | Public URL | ❌ Missing | No evidence of deployment to a public URL |
| G5 | Simulator runnable from public URL | ❌ Missing | No public URL exists |
| G6 | 5-minute demo video | ❌ Missing | No video link found |

### Core Requirements

| Requirement | Status | Evidence |
|-------------|--------|----------|
| **Ingest telemetry** | ✅ Done | `POST /api/ingest` and `/api/ingest/batch`. Dedup, out-of-order, clock skew handled |
| **Detect and localize faults** | ✅ Done | Boundary detection, span identification, GPS coordinates, PIN code, downstream count, confidence |
| **Group symptoms into one incident** | ✅ Done | All dark poles downstream of one boundary → one incident |
| **Multiple simultaneous faults** | ✅ Done | Multiple boundaries → multiple tickets. Tests verify this |
| **Don't cry wolf (dead sensor)** | ✅ Done | Dead-sensor paradox filter removes physically impossible dark poles |
| **Don't cry wolf (scheduled outage)** | ✅ Done | Active outage suppression with ±20min grace |
| **Ticket lifecycle** | ✅ Done | DETECTED → ACKNOWLEDGED → CREW_ASSIGNED → RESOLVED → VERIFIED → CLOSED |
| **Telemetry-verified restoration** | ✅ Done | `check_restoration()` auto-verifies when ≥80% poles are LIVE. Blocks manual resolution when dark |
| **Operator console** | ✅ Done | React + Leaflet map + incident queue + detail panel + confidence badges |
| **Fault simulator** | ✅ Done | Span, DT, feeder, device failure, repair, noise — all from UI |
| **Handle 60% missing topology** | ✅ Done | PCA-based geometric inference (Bronze), co-occurrence validation (Silver) |
| **PIN code output** | ✅ Done | Stored per pole, aggregated per incident |
| **GPS coordinates for dispatch** | ✅ Done | Midpoint of fault span |
| **Confidence reporting** | ✅ Done | HIGH/MEDIUM/LOW with score, displayed in UI |

### Documentation Requirements

| Document | Status | Notes |
|----------|--------|-------|
| `README.md` | ❌ Missing | No project README at root |
| `ARCHITECTURE.md` | ❌ Missing | No architecture diagram, no algorithm explanation |
| `DEPLOYMENT.md` | ❌ Missing | No deployment instructions, no troubleshooting |
| `DECISIONS.md` | ❌ Missing | No decision log, no documented assumptions |
| `AI-WORKFLOW.md` | ❌ Missing | No AI workflow documentation |
| `.env.example` | ✅ Done | Present at repo root |
| Tests on localization logic | ✅ Done | `test_localization.py` — 13 test cases covering core scenarios |
| Real commit history | 🟡 Partial | 6 commits with meaningful messages, but very few — looks like large batches |
| No secrets in repo | ✅ Done | `.env.example` has placeholder values |

### Self-Check Items from Assignment

| Check | Status | Notes |
|-------|--------|-------|
| `docker compose up` works from fresh clone | ✅ Pass | Verified |
| Public URL works in private browsing | ❌ Fail | No public URL |
| Inject span fault → one correct ticket | ✅ Pass | After `consistency_ratio` fix |
| Three simultaneous faults → three tickets | 🟡 Untested | Logic is correct per unit tests, but not integration-tested |
| Kill device telemetry → no fault ticket | ✅ Pass | Dead-sensor filter works |
| Scheduled outage → no fault ticket | ✅ Pass | Suppression logic works |
| Repair fault → ticket auto-verified | ✅ Pass | `check_restoration()` works |
| Mark resolved while dark → system pushes back | ✅ Pass | `validate_manual_resolution()` blocks it |
| All five documents present | ❌ Fail | Zero of five present |
| Architecture diagram matches code | ❌ Fail | No diagram exists |

### Performance Targets

| Metric | Target | Status | Notes |
|--------|--------|--------|-------|
| Fault → ticket visible < 120s | Not measured | ❌ Not documented | Likely met (background task takes <5s), but no measurement |
| Ingest ≥ 500 msg/s | Not measured | ❌ Not documented | Single-message processing per request; batch endpoint exists but throughput not benchmarked |
| 5000 msg burst in 10s | Not measured | ❌ Not documented | |
| Console load < 2s | Not measured | ❌ Not documented | Likely met for 40 DTs, but not measured |
| Restoration → auto-verified < 120s | Not measured | ❌ Not documented | |

> [!WARNING]
> The assignment says: "You will not be penalised for missing a target you have measured, documented, and explained. You will be penalised for **claiming one you never tested**."
> Since there is no documentation at all, there are no claims — but also no measurements. The absence of documentation means the reviewer cannot assess performance at all.

---

## PHASE 4 — Engineering Thinking

| Question | Assessment |
|----------|-----------|
| **Did you understand the real problem?** | Yes. The code demonstrates genuine understanding of radial network topology, the inference challenge, and the operational context |
| **Did you over-engineer?** | No. The Bronze/Silver/Gold tiering is the right level of complexity for the 60% problem. No unnecessary microservices or message queues |
| **Did you under-engineer?** | The code itself is appropriately engineered. The massive under-investment is in documentation and deployment |
| **Good trade-offs?** | SSE over WebSockets — good. PCA for geometric inference — reasonable. Background task for fault detection — appropriate |
| **Solved right problems first?** | Mostly. Fault localization and simulator are solid. But documentation (15% of score) was completely skipped |
| **Trust on a production team?** | The code quality suggests competence. The missing documentation suggests poor prioritization or time management |
| **Would you believe this was actually built by the candidate?** | The 6 commits with large batches + code quality suggests heavy AI generation. The `consistency_ratio` bug (field missing from dataclass but used in constructor) is exactly the kind of error that happens when AI generates code and the human doesn't fully review it |
| **Can you defend this in an interview?** | The algorithm is sound and testable. You can explain the boundary detection, the dead-sensor paradox, and the topology tiering. The `consistency_ratio` bug would be a tough question |

### Excellent design decisions
- Dead-sensor paradox filter — directly from the assignment's physical reasoning
- Gold/Bronze/Silver topology tiering with co-occurrence learning
- Telemetry-verified restoration that blocks manual override
- Gemini AI used for dispatch summaries, not fault localization

### Weak decisions
- Running full `detect_all_faults()` on every single `power_lost` message — should debounce
- No documentation at all — the assignment explicitly says this is 15% of the score
- No public deployment — this is an acceptance gate
- `consistency_ratio` field was missing from the dataclass — a compilation-level bug that blocked core functionality

### Interview challenges I would raise
1. "Your `detect_all_faults` runs across all 40 DTs on every power_lost message. At 412 DTs and 39 msg/s, that's 16,000 DT scans per second. How would you optimize this?"
2. "Your PCA projects poles onto a single axis. Show me what happens with a DT that has a T-shaped branch topology."
3. "The co-occurrence Silver layer — when does it actually get populated? I see the table and the query, but where do you write to `pole_cooccurrence`?"
4. "Walk me through what happens when a scheduled outage is cancelled but the feed isn't updated. Your code fully suppresses. The assignment says 10% are cancelled."
5. "The `consistency_ratio` was missing from `FaultCandidate` and the system was silently creating zero tickets. How did you not catch this before submission?"

---

## PHASE 5 — Product Thinking

| Question | Assessment |
|----------|-----------|
| **Solves the department's problem?** | Yes — reduces 2-hour identification to seconds. GPS coordinates precise enough to drive to |
| **Would operators use it?** | Likely yes. The UI is clean and information hierarchy is appropriate. The confidence badges communicate uncertainty honestly |
| **Would it reduce outage response time?** | Significantly. Span-level localization eliminates the pole-by-pole walk |
| **Inspires confidence?** | The telemetry verification guard is a trust-building feature. Operators learn the system doesn't lie |
| **Missing product decisions** | No audio/visual alert for new incidents. No incident age/timer. No recurring-fault flagging. No export/reporting. No dark mode toggle (always dark). No mobile responsiveness consideration |

---

## PHASE 6 — Code Review (Staff Engineer)

### Bug risks
1. **`consistency_ratio` bug** — was a TypeError that silently killed all incident creation. Fixed in this session but demonstrates insufficient testing of the integration path
2. **SSE event format mismatch** — backend sends named events but the SSE endpoint yields `{"data": message}` without extracting the event name. The frontend had to use `addEventListener` for named events, but the SSE endpoint doesn't set the `event` field in the yield dict — it's embedded in the raw message string. This is fragile
3. **Race condition in simulator** — `_send_power_lost_batch` commits the session, then `background_tasks.add_task(_run_fault_detection)` runs after the response. But the background task creates a NEW session. If there's any delay, the new session may see stale data

### Logic flaws
4. **Co-occurrence table never populated** — `PoleCooccurrence` model exists, `_get_edge_confidence` queries it, but no code anywhere writes to it. The Silver layer can never activate. This is dead infrastructure
5. **`detect_all_faults` scans all DTs every time** — no scoping to the affected DT. This is O(n_DTs × n_poles_per_DT) on every message
6. **Outage suppression is binary** — the comment says "we add a warning flag instead" but the code returns `[]` (full suppression)

### Performance bottlenecks
7. **No debouncing** — 5000 `power_lost` messages in 10 seconds triggers 5000 `_run_fault_detection` background tasks
8. **Topology fetch per DT per incident** — `detect_faults_for_dt` does 3 DB queries per DT (pole states, DT info, outage check)

### Testing gaps
9. **No integration tests** — unit tests mock everything. The `consistency_ratio` TypeError was an integration-level bug that unit tests missed
10. **No test for scheduled outage suppression** — T5 is listed in the docstring but not implemented as a test
11. **No test for feeder-level fault** — the merging logic in `detect_all_faults` is untested
12. **No test for restoration auto-verification** — T7 is listed but not implemented

### Security issues
13. **No rate limiting on ingest endpoint** — an attacker could flood the system
14. **No input validation on simulator endpoints** — arbitrary pole_ids could be injected

### Dead code
15. **`PoleCooccurrence` table and `_get_edge_confidence`** — infrastructure for Silver layer that never activates because nothing writes to the co-occurrence table

---

## PHASE 7 — Scoring

| Category | Score (out of 10) | Weight | Weighted |
|----------|:-:|:-:|:-:|
| **Fault Localization** | 7.5 | 25% | 1.88 |
| **Product Judgment** | 7.0 | 20% | 1.40 |
| **Architecture & Data Design** | 7.5 | 20% | 1.50 |
| **Operator Experience** | 7.0 | 15% | 1.05 |
| **Documentation & Reproducibility** | 1.5 | 15% | 0.23 |
| **Engineering Craft & AI Leverage** | 4.0 | 5% | 0.20 |
| **Overall Weighted** | | | **6.26/10** |

### Score justifications

- **Fault Localization (7.5):** Algorithm is sound. Boundary detection, grouping, dead-sensor filter, confidence scoring all work. Deducted for: Silver layer being dead code, PCA limitations undocumented, `consistency_ratio` bug that broke the entire system.
- **Product Judgment (7.0):** Correct priorities. AI used appropriately. Telemetry-verified restoration is excellent. Deducted for: missing audio/visual alerts, no incident aging, thin AI feature justification.
- **Architecture (7.5):** Clean separation, appropriate tech choices, good schema. Deducted for: no debouncing, full-scan on every message, co-occurrence table never populated.
- **Operator Experience (7.0):** Professional UI, good information hierarchy, confidence badges. Deducted for: no new-incident alerts, no keyboard shortcuts, no mobile consideration.
- **Documentation (1.5):** `.env.example` exists. Code has good inline comments and docstrings. But zero of the five required documents exist. This is catastrophic for a category worth 15%.
- **Engineering Craft (4.0):** Tests exist and are good, but only cover unit-level. 6 commits with large batches. `consistency_ratio` bug shows insufficient integration testing. No AI workflow documentation.

### Overall Recruiter Impression

> **Borderline.** The engineering is genuinely good — the fault localization algorithm is thoughtful, the topology tiering is sophisticated, and the UI is professional. But the complete absence of documentation, public URL, and demo video means three acceptance gates fail. A reviewer with 45 minutes opens this repo, sees no README, and has to reverse-engineer everything from code. That's a significant negative signal regardless of code quality.
>
> **If the five documents were present and a public URL existed, this would score 7.5–8.0 and be a strong shortlist candidate.** As submitted, it risks being filtered out at the gate check.

---

## PHASE 8 — Interview Simulation

### Questions I would ask (in order of difficulty)

**1. Walk me through your localization algorithm.**
"Start from the moment a `power_lost` message arrives. What happens step by step until a ticket appears in the operator's queue?"

**2. The consistency_ratio field was missing from FaultCandidate. Every fault detection run was silently failing with a TypeError. How did you test this system?**

**3. Your Silver topology layer — I see the `pole_cooccurrence` table and the `_get_edge_confidence` function that reads from it. Where do you write to this table?**
*(Expected answer: nowhere — it's dead infrastructure. Follow-up: "So the Silver layer can never activate. How does that affect your confidence scores for the 60% of DTs with Bronze topology?")*

**4. The PCA-based Bronze topology inference projects all poles onto a single principal component. What happens with a DT that has an L-shaped or T-shaped line?**
*(This is the weakness — PCA projects to 1D, so a right-angle branch gets interleaved with the main run. The nearest-neighbor chain with MAX_SPACING_M=120m partially mitigates this, but the ordering will be wrong at branch points.)*

**5. Your `detect_all_faults` scans all 40 DTs every time any pole sends `power_lost`. At the assignment's full scale of 412 DTs and 39 msg/s, you'd be doing 16,000+ DT scans per second. How would you fix this?**
*(Expected answer: scope detection to the affected DT using `pole_to_dt` mapping, or debounce with a grouping window.)*

**6. The assignment says scheduled outages are cancelled ~10% of the time without the feed being updated. Your code fully suppresses detection during outage windows. What's the failure mode?**
*(A real fault during a "cancelled but still listed" outage window gets silently ignored.)*

**7. Change the problem: the department gives you current flow direction data from new sensors on 20% of poles. How does your algorithm change?**

**8. You have no documentation. If I'm an engineer joining your team tomorrow and I need to understand how the topology engine works, what do I read?**

---

## PHASE 9 — Improvement Roadmap

### Priority 1 — MUST fix before submission

| Item | Impact | Effort | Details |
|------|--------|--------|---------|
| Write `README.md` | Critical (gate) | 1 hour | Front door. One-command start, public URL, demo video link, doc map |
| Write `ARCHITECTURE.md` | Critical (15% weight) | 2 hours | Data flow diagram, algorithm explanation (boundary detection, topology tiering, confidence), API surface, AI feature justification |
| Write `DEPLOYMENT.md` | Critical (15% weight) | 1 hour | Prerequisites, exact commands, env vars, troubleshooting section |
| Write `DECISIONS.md` | Critical (15% weight) | 1.5 hours | Decision log (topology approach, SSE vs WebSocket, AI placement), documented assumptions, known weaknesses |
| Write `AI-WORKFLOW.md` | Critical (5% weight) | 1 hour | Tools used, what was delegated, concrete AI failure examples, code generation estimate |
| Deploy to public URL | Critical (gate) | 1-2 hours | Render.com free tier or similar. Test SSE through proxy |
| Record 5-minute demo video | Critical (gate) | 30 min | Inject fault → detect → ticket → repair → auto-verify |

### Priority 2 — Would noticeably improve score

| Item | Impact | Effort |
|------|--------|--------|
| Fix Silver layer (populate `pole_cooccurrence` on fault detection) | High | 2 hours |
| Add debouncing/grouping window for fault detection | High | 1 hour |
| Scope `detect_all_faults` to affected DT only | Medium | 30 min |
| Add integration test (inject fault → verify ticket created) | Medium | 1 hour |
| Implement test T5 (scheduled outage suppression) and T7 (restoration) | Medium | 1 hour |
| Add more commits with meaningful messages | Medium | Ongoing |
| Measure and document performance targets | Medium | 1 hour |

### Priority 3 — Nice-to-have

| Item | Impact | Effort |
|------|--------|--------|
| Audio notification for new incidents | Low | 30 min |
| Incident age timer in UI | Low | 30 min |
| Scheduled outage injection from simulator UI | Low | 1 hour |
| Fix outage suppression to add warning flag instead of full suppress | Low | 30 min |
| Add OpenAPI/Swagger docs generation | Low | 30 min |
| Mobile-responsive layout | Low | 2 hours |
