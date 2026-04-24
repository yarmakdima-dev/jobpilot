# JobPilot — Backlog

**Version:** 0.2
**Created:** 2026-04-21
**Updated:** 2026-04-21
**Owner:** Dima
**Purpose:** Agentic job application system for senior operator roles. Sources postings, evaluates against rubric, tailors CV + cover letter, tracks pipeline, watches inbox. Human-in-the-loop at decision points.

**Changelog:**
- v0.2 (2026-04-21): Added Data Contract layer (User vs System file separation). Added Phase 0 (pre-flight: onboarding contract + DATA_CONTRACT.md). Added A1.4 (liveness check) to intake. Added A5.3 (story bank) to feedback loop. Added "Operating principles" section covering modes-as-files and prompt-level HIL enforcement. Driven by Career-Ops (santifer/career-ops) prior-art review.
- v0.1 (2026-04-21): Initial backlog.

---

## System overview

Eleven agents + two filters + one orchestrator, operating over a shared state store. Human supervision via daily report, override console, and approval queue.

```
A1 (source) → F1 (JD pre-screen) → A0 (company research) → F2 (deep rubric eval)
           → A2 (CV) + A3 (cover letter) → A4 (submit) → A8 (inbox watch)
           → A5 (interview prep) → A6 (debrief) → A7 (rubric/profile maintenance)
```

---

## Architecture layers

### Layer 0 — Data contract

Every file in the system belongs to one of two layers. This separation is architectural, not organizational.

**User Layer** — personal data, work product, decisions. NEVER touched by system updates or agent writes outside their designated lanes.

- `cv.md` — canonical CV
- `voice_pack.md` — voice constraints and exemplars (Layer 2 output, pending)
- `config/profile.yml` — identity, comp targets, location, preferences
- `companies/*.json` — populated company profiles
- `roles/*.json` — role records + pipeline state
- `pipeline.json` — active pipeline table
- `decisions.log` — overrides, state transitions, reasons
- `inbox_events/*` — A8 output queue
- `reports/*` — 360 syntheses, interview debriefs
- `output/*` — generated CVs, cover letters, submission packages

**System Layer** — logic, prompts, schemas, scripts. Safe to auto-update on version bumps.

- `rubric.json` — current scoring rubric (user edits, but versioned as system)
- `company_profile_schema.json` — schema definition
- `agents/*.md` — agent prompt files (one file per agent, composable)
- `filters/*.md` — F1 and F2 prompts
- `orchestrator/*` — pipeline runner, state machine
- `scripts/*` — utilities (merge, dedup, liveness-check, verify)
- `templates/*` — CV templates, cover letter scaffolds, daily report template
- `DATA_CONTRACT.md` — this contract, canonical
- `CLAUDE.md` / `AGENTS.md` — orchestrator instructions

**The rule:** If a file is User Layer, no update process or agent reads, modifies, or deletes it outside its designated write lane. If a file is System Layer, it can be replaced with the latest version without risk.

**Write lanes (User Layer, per-agent):**
- A0 → `companies/*.json` (create/update)
- A1 → `roles/*.json` (create)
- F1, F2 → `roles/*.json` (update filter_status fields only)
- A2, A3 → `output/*` (create)
- A6 → `reports/*` (create), `roles/*.json` (update debrief field)
- A7 → `decisions.log` (append), `companies/*.json` (invalidate synthesis cache)
- A8 → `inbox_events/*` (create)
- Human only → `cv.md`, `voice_pack.md`, `config/profile.yml`, `rubric.json`

Canonical definition lives in `DATA_CONTRACT.md` (Phase 0 deliverable).

### Layer 1 — State store

Single source of truth. Flat files to start, upgrade only when volume demands.

- `companies/` — one `company_profile.json` per company (schema v0.2), keyed by domain
- `roles/` — one record per role; links to company; holds JD, URL, F1/F2 results, pipeline state, submission mode
- `pipeline.json` — flat table of all active roles with state
- `rubric.json` — current version; bumping invalidates `360_synthesis` caches
- `decisions.log` — every override and state transition, with reason (training data for rubric evolution)
- `inbox_events/` — A8's output queue, awaiting review

### Layer 2 — Orchestration

Pipeline runner (cron + state machine). Scheduler scans `pipeline.json` every N minutes, dispatches agents based on role state. Simple, debuggable, restartable.

State transitions:
```
sourced → F1_passed → researched → F2_passed → ready_to_submit
       → applied → first_call → interview_scheduled → post_interview → closed
```

Each transition logged. Failures halt that role but don't break the pipeline.

### Layer 3 — Human-in-the-loop surfaces

1. **Daily report** — morning digest, scannable in 5 minutes
2. **Override console** — `/override [role_id] [new_state] [reason]`, reason mandatory
3. **Approval queue** — cover letters, email replies, manual submission packages

**No agent acts on the outside world without approval.** A4 auto-submits only on pre-authorized channels. A8 never replies autonomously.

### Layer 4 — Observability

- Funnel metrics (sourced → F1 → F2 → applied → first call → offer), weekly
- Rubric version tracking (which version scored which role)
- Override rate (tuning signal)

---

## Agent catalog

| ID | Name | Role |
|----|------|------|
| A0 | Company research | Populates `company_profile.json` (schema v0.2) |
| A1 | Job sourcing | Finds new postings, 24/7 or scheduled |
| F1 | JD pre-screen | Cheap filter on JD text; hard gates only; visible + tunable |
| F2 | Deep rubric eval | Full rubric scoring on populated profile; outputs stance |
| A2 | CV tailoring | Tailors CV per role using profile slices |
| A3 | Cover letter | Drafts cover letter per role using profile slices |
| A4 | Submission | Auto / assisted / manual modes per channel |
| A5 | Interview prep | Uses profile slices + resolves `gate_needs_judgment_call` probes |
| A6 | Debrief capture | Post-interview; feeds profile + rubric learning |
| A7 | Rubric/profile maintenance | Invalidates caches on rubric bump; logs overrides |
| A8 | Inbox watcher | Classifies, extracts, queues replies; never auto-sends |

---

## Build order

Don't build all eleven at once. Build the spine; each stage is usable on its own.

### Phase 0 — Pre-flight
- [x] **P0.1.** Write `DATA_CONTRACT.md` — canonical list of User vs System files, write-lane table per agent, the rule
- [x] **P0.2.** Onboarding contract — orchestrator checks before any agent runs:
  - `cv.md` exists?
  - `config/profile.yml` exists?
  - `rubric.json` exists and version is known?
  - `voice_pack.md` exists? (warn-only until Layer 2 ships)
  If any required file is missing, enter onboarding mode and walk user through setup. No agent runs until pre-flight passes.
- [x] **P0.3.** `CLAUDE.md` / orchestrator prompt — bakes HIL enforcement, quality-over-quantity rule, and never-auto-submit into the agent's operating instructions (not just architecture). Principles are hard-coded, not advisory.

### Phase 1 — Foundation
- [x] **S1.** State store schemas (flat files, minimal)
- [x] **S2.** Pipeline runner (state machine, cron-based)
- [x] **S3.** Daily report template + generator

### Phase 2 — Intake
- [ ] **A1.1.** Job sourcing — source list (LinkedIn, job boards, company pages, aggregators)
- [ ] **A1.2.** Job sourcing — dedup logic (same role posted multiple places)
- [ ] **A1.3.** Job sourcing — schedule + ingestion
- [x] **A1.4.** Liveness check — verify posting is still open before F1 spends budget. Use Playwright (navigate + snapshot), not WebSearch (unreliable for dead postings). Dead = footer/navbar only, no JD body. Active = title + description + apply button. Lightweight; runs between A1 and F1.
- [ ] **F1.1.** JD pre-screen — hard gate checks (location, comp if stated, domain exclusions, seniority)
- [ ] **F1.2.** F1 config file (tunable thresholds without code changes)
- [ ] **F1.3.** F1 near-miss bucket (logged separately in daily report)

### Phase 3 — Research loop
- [ ] **A0.1.** Company research — Perplexity Research mode pipeline
- [ ] **A0.2.** Company research — schema v0.2 population (incl. `name_confusion_check`, `war_position`, `parallel_business_flag`)
- [ ] **A0.3.** Company research — two-step JSON formatting (Perplexity → Claude/GPT-4 for schema discipline)
- [ ] **F2.1.** Deep rubric eval — scored criteria + override rules
- [ ] **F2.2.** Deep rubric eval — `gate_needs_judgment_call` resolution logic
- [ ] **F2.3.** F2 config (tunable weights/thresholds)
- [ ] **F2.4.** `360_synthesis` generation + `synthesis_rubric_version` tagging

### Phase 4 — Application production
- [x] **A2.1.** CV tailoring — consume profile slices, not full profile
- [x] **A2.2.** CV tailoring — output format
- [x] **A3.1.** Cover letter — voice constraints (reflective, direct, specific; no "passionate about," no bullets)
- [x] **A3.2.** Cover letter — profile-slice-driven content

### Phase 5 — Submission
- [ ] **A4.1.** Submission mode classifier (auto / assisted / manual) per channel
- [ ] **A4.2.** Auto-submit adapters (email, clean ATS APIs)
- [ ] **A4.3.** Assisted-submit packages (pre-filled + ready-to-paste)
- [ ] **A4.4.** Manual submission queue + daily nudge

### Phase 6 — Feedback loop
- [x] **A8.1.** Inbox watcher — Gmail/Outlook access
- [x] **A8.2.** Inbox watcher — classification (reply to application, cold outreach, rejection, scheduling, follow-up needed)
- [x] **A8.3.** Inbox watcher — draft replies (never auto-send)
- [x] **A8.4.** Inbox watcher — pipeline state updates from email events
- [x] **A5.1.** Interview prep — profile slice selection per stage
- [x] **A5.2.** Interview prep — probe list from `gate_needs_judgment_call`
- [x] **A5.3.** Story bank — accumulating artifact across interviews and evaluations. Format: 5–10 master stories (situation, task, action, result, reflection) that answer any behavioral question. Grows over time; A5 pulls from it, A6 feeds into it. Lives in User Layer (`voice_pack.md` companion or standalone `story_bank.md`).
- [x] **A6.1.** Debrief capture — post-interview prompts
- [x] **A6.2.** Debrief capture — profile + rubric feedback loop

### Phase 7 — Maintenance
- [ ] **A7.1.** Rubric version bump → invalidate `360_synthesis` caches
- [ ] **A7.2.** Override logging → decisions.log
- [ ] **A7.3.** Override analysis (cluster overrides → rubric tuning signals)
- [ ] **A7.4.** Funnel metrics dashboard
- [ ] **A7.5.** Rubric evolution process (v0.3 and beyond)

---

## Open questions

- **Store choice:** Flat files vs SQLite vs Postgres. Start flat; upgrade trigger = >100 active roles or multi-device access needed.
- **Orchestration host:** Where does the pipeline runner live? Local machine (simple, fragile) vs small VPS (reliable, adds ops). Probably VPS once Phase 3 is stable.
- **A1 source strategy:** LinkedIn is hostile to agents. Start with RSS + job board APIs + direct company career pages. LinkedIn last, manual-assisted.
- **Submission mode registry:** Which channels are auto, which assisted, which manual? Build this table as we encounter them.
- **Inbox access model:** OAuth to Gmail vs IMAP vs forwarding rule. Resolve before A8.
- **Cost budget:** Per-role compute cost (F1 + A0 + F2 + A2 + A3) × daily volume. Cap before it runs away.

---

## Known constraints and operating principles

- **Canonical profile is the single source of truth.** Downstream agents consume slices, not full profile. Re-synthesize when rubric version changes.
- **Structured JSON over prose.** Agent-ready outputs first; human-readable summaries are secondary artifacts.
- **Data Contract is enforced.** User Layer files are never touched by system updates. Agents write only within their designated lanes.
- **Modes are composable files, not embedded logic.** Each agent's prompt lives in a standalone, human-readable, human-editable markdown file (`agents/A0.md`, `agents/A2.md`, etc.). Same principle for filters (`filters/F1.md`, `filters/F2.md`). A shared context file (`agents/_shared.md`) holds common rules. This keeps prompts tunable without code changes and makes agent behavior auditable.
- **HIL is enforced at the prompt level, not just architecturally.** Every agent prompt includes: never submit without human review; discourage low-fit applications explicitly (below scored threshold = recommend skip); quality over quantity is an operating rule, not a slogan. A4 auto-submits only on pre-authorized channels. A8 never replies autonomously.
- **Overrides are training data.** Every override logged with reason, clustered for rubric evolution.
- **Rubric drives synthesis, synthesis is cache.** Hybrid C model locked 2026-04-21.
- **Liveness before research.** Dead postings never reach A0. Playwright verifies, not WebSearch.

---

## Related artifacts

- `rubric_v0_2.json` — opportunity scoring rubric
- `company_profile_schema_v0_2.json` — canonical company profile schema
- `20_04_2026_session_notes.md` — Layer 1 session notes; Layers 2–5 pending
- `DATA_CONTRACT.md` — pending (Phase 0 deliverable)

## Prior art reviewed

- **Career-Ops** (github.com/santifer/career-ops) — shipped Claude Code-based job search system, battle-tested across 740+ evaluations. JobPilot borrows: Data Contract pattern (Layer 0), onboarding contract (Phase 0), liveness check (A1.4), story bank (A5.3), modes-as-files operating principle, prompt-level HIL enforcement. JobPilot keeps its own: rubric versioning + synthesis cache invalidation, `gate_needs_judgment_call` state, values-based carve-out logic.
