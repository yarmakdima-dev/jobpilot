# JobPilot — Backlog

**Version:** 0.3
**Created:** 2026-04-21
**Updated:** 2026-04-28
**Owner:** Dima
**Purpose:** Agentic job application system for senior operator roles. Sources postings, evaluates against rubric, tailors CV + cover letter, tracks pipeline, watches inbox. Human-in-the-loop at decision points.

**Changelog:**
- v0.3 (2026-04-28): Reflects ground-truth state from Codex repo audit. Phase 0, Phase 1, Phase 2 (intake spine), and Phase 3 wiring all merged. Hygiene batch closed. DATA_CONTRACT enforcement decided: runtime validation canonical, pre-commit deferred to dev hygiene. Status of every ticket reconciled to one of three states: code-shipped, prompt-only-stub-wired, or not-started. New "Stubs to replace" section captures the real next-work surface. Build order reordered to prioritize real A0 → real F2 → manual smoke test before A1 ingestion.
- v0.2 (2026-04-21): Added Data Contract layer (User vs System file separation). Added Phase 0 (pre-flight: onboarding contract + DATA_CONTRACT.md). Added A1.4 (liveness check) to intake. Added A5.3 (story bank) to feedback loop. Added "Operating principles" section covering modes-as-files and prompt-level HIL enforcement. Driven by Career-Ops (santifer/career-ops) prior-art review.
- v0.1 (2026-04-21): Initial backlog.

---

## Status legend

- ✅ **Shipped** — code merged to main, tests green, runs end-to-end for what it covers
- 🟡 **Stub wired** — real boundary in code, returns placeholder data, ready for backend swap-in
- 📝 **Prompt-only** — agent/filter markdown exists; no code yet
- ⬜ **Not started**

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
- `voice_pack.md` — voice constraints and exemplars
- `story_bank.md` — accumulating master stories (A5.3 artifact)
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
- `scripts/*` — utilities (preflight check, merge, dedup, verify)
- `templates/*` — CV templates, cover letter scaffolds, daily report template
- `DATA_CONTRACT.md` — this contract, canonical
- `CLAUDE.md` / `AGENTS.md` — orchestrator instructions

**The rule:** If a file is User Layer, no update process or agent reads, modifies, or deletes it outside its designated write lane. If a file is System Layer, it can be replaced with the latest version without risk.

**Enforcement (decided 2026-04-28):** Runtime validation is canonical. Every agent write goes through the system-owned wrapper that validates against the lane table before touching disk. Pre-commit hooks are deferred to developer hygiene only — not the trust boundary.

**Write lanes (User Layer, per-agent):**
- A0 → `companies/*.json` (create/update)
- A1 → `roles/*.json` (create)
- F1, F2 → `roles/*.json` (update filter_status fields only; F2 also writes `gate_needs_judgment_call`)
- A2, A3 → `output/*` (create)
- A6 → `reports/*` (create), `roles/*.json` (update debrief field)
- A7 → `decisions.log` (append), `companies/*.json` (invalidate synthesis cache)
- A8 → `inbox_events/*` (create)
- Human only → `cv.md`, `voice_pack.md`, `story_bank.md`, `config/profile.yml`, `rubric.json`

Canonical definition lives in `DATA_CONTRACT.md`.

### Layer 1 — State store

Single source of truth. Flat files. Upgrade trigger = >100 active roles or multi-device access needed.

- `companies/` — one `company_profile.json` per company (schema v0.2), keyed by domain
- `roles/` — one record per role; links to company; holds JD, URL, F1/F2 results, pipeline state, submission mode
- `pipeline.json` — flat table of all active roles with state
- `rubric.json` — current version (v0.3); bumping invalidates `360_synthesis` caches
- `decisions.log` — every override and state transition, with reason (training data for rubric evolution)
- `inbox_events/` — A8's output queue, awaiting review

### Layer 2 — Orchestration

Pipeline runner (state machine) with `--tick` and `--daemon` modes. File lock prevents concurrent runners. Sequential dispatch per tick. Role-level failure does not halt the runner.

State transitions:
```
sourced → liveness_pending → live → F1_passed → researched → F2_passed → ready_to_submit
       → applied → first_call → interview_scheduled → post_interview → closed
```

Each transition logged to `decisions.log`. Failures move the role to `error` with reason.

### Layer 3 — Human-in-the-loop surfaces

1. **Daily report** — morning digest, scannable in 5 minutes (shipped)
2. **Override console** — `/override [role_id] [new_state] [reason]`, reason mandatory
3. **Approval queue** — cover letters, email replies, manual submission packages

**No agent acts on the outside world without approval.** A4 auto-submits only on pre-authorized channels. A8 never replies autonomously.

### Layer 4 — Observability

- Funnel metrics (sourced → F1 → F2 → applied → first call → offer), weekly
- Rubric version tracking (which version scored which role)
- Override rate (tuning signal)

---

## Agent catalog

| ID | Name | Prompt | Code |
|----|------|--------|------|
| A0 | Company research | 📝 | 🟡 stub wired |
| A1 | Job sourcing | 📝 | ⬜ not started |
| A1.4 | Liveness check | 📝 | ✅ shipped |
| F1 | JD pre-screen | 📝 | 🟡 stub wired |
| F2 | Deep rubric eval | 📝 | 🟡 stub wired |
| A2 | CV tailoring | 📝 | ⬜ not started |
| A3 | Cover letter | 📝 | ⬜ not started |
| A4 | Submission | 📝 | ⬜ not started |
| A5 | Interview prep | 📝 | ⬜ not started |
| A6 | Debrief capture | 📝 | ⬜ not started |
| A7 | Rubric/profile maintenance | 📝 | ⬜ not started |
| A8 | Inbox watcher | 📝 | ⬜ Gmail OAuth scaffolded only |

---

## Build order — current state

### Phase 0 — Pre-flight ✅ COMPLETE
- [x] **P0.1.** `DATA_CONTRACT.md` — canonical, v0.5, runtime validation locked as enforcement
- [x] **P0.2.** Onboarding contract — orchestrator pre-flight check; spec written
- [x] **P0.3.** `CLAUDE.md` — orchestrator operating prompt; HIL enforcement baked in
- [x] **P0.4.** `scripts/preflight_check.py` — executable preflight, tests green (added 2026-04-28)

### Phase 1 — Foundation ✅ COMPLETE
- [x] **S1.** State store schemas
- [x] **S2.** Pipeline runner (state machine, `--tick` / `--daemon`, file lock, agent stubs, 16 tests)
- [x] **S3.** Daily report generator (`orchestrator/report.py`, Jinja2 template, 20 tests)

### Phase 2 — Intake (partial)
- [ ] **A1.1.** Job sourcing — source list ⬜
- [ ] **A1.2.** Job sourcing — dedup logic ⬜
- [ ] **A1.3.** Job sourcing — schedule + ingestion ⬜
- [x] **A1.4.** Liveness check — Playwright wired, dead/active detection
- [x] **F1.1.** JD pre-screen — boundary wired 🟡 stub returns placeholder pass/fail
- [x] **F1.2.** F1 config file — tunable thresholds
- [ ] **F1.3.** F1 near-miss bucket — daily report integration ⬜

### Phase 3 — Research loop (partial)
- [x] **A0.1.** Company research — boundary wired 🟡 **stub returns placeholder profile, no Perplexity yet**
- [ ] **A0.2.** Schema v0.2 population — schema exists, real population pending real backend
- [ ] **A0.3.** Two-step JSON formatting (Perplexity → Claude/GPT-4) — pending real backend
- [x] **F2.1.** Deep rubric eval — boundary wired 🟡 **stub returns placeholder stance, no LLM scoring yet**
- [x] **F2.2.** `gate_needs_judgment_call` — write path live in code
- [x] **F2.3.** F2 config — tunable
- [ ] **F2.4.** `360_synthesis` generation + version tagging — pending real F2 backend

### Phase 4 — Application production (prompt-only)
- [ ] **A2.1.** CV tailoring — consume profile slices 📝
- [ ] **A2.2.** CV tailoring — output format 📝
- [ ] **A3.1.** Cover letter — voice constraints 📝
- [ ] **A3.2.** Cover letter — profile-slice-driven content 📝

### Phase 5 — Submission (not started)
- [ ] **A4.1.** Submission mode classifier ⬜
- [ ] **A4.2.** Auto-submit adapters ⬜
- [ ] **A4.3.** Assisted-submit packages ⬜
- [ ] **A4.4.** Manual submission queue + daily nudge ⬜

### Phase 6 — Feedback loop (prompts only, except A8 OAuth)
- [ ] **A8.1.** Inbox watcher — Gmail/Outlook access (OAuth scaffolded, not wired) 📝
- [ ] **A8.2.** Classification 📝
- [ ] **A8.3.** Draft replies (never auto-send) 📝
- [ ] **A8.4.** Pipeline state updates from email events 📝
- [ ] **A5.1.** Interview prep — profile slice selection 📝
- [ ] **A5.2.** Interview prep — probe list from `gate_needs_judgment_call` 📝
- [x] **A5.3.** Story bank — `story_bank.md` artifact exists, format defined
- [ ] **A6.1.** Debrief capture — post-interview prompts 📝
- [ ] **A6.2.** Debrief capture — profile + rubric feedback loop 📝

### Phase 7 — Maintenance (not started)
- [ ] **A7.1.** Rubric version bump → invalidate `360_synthesis` caches ⬜
- [ ] **A7.2.** Override logging → decisions.log ⬜
- [ ] **A7.3.** Override analysis ⬜
- [ ] **A7.4.** Funnel metrics dashboard ⬜
- [ ] **A7.5.** Rubric evolution process ⬜

---

## Stubs to replace (the real next-work surface)

Three agents have boundaries wired but return placeholder data. Replacing these is what unlocks the first real end-to-end use case.

| Agent | What stub does now | What real version needs |
|-------|-------------------|-------------------------|
| **A0** | Returns placeholder company profile | Perplexity Research-mode call → schema v0.2 population (incl. `name_confusion_check`, `war_position`, `parallel_business_flag`) → two-step JSON formatting via Claude/GPT-4 |
| **F2** | Returns placeholder stance | LLM scoring against rubric v0.3 → override rule application → `360_synthesis` generation + `synthesis_rubric_version` tag → `gate_needs_judgment_call` resolution logic |
| **F1** | Returns placeholder pass/fail | LLM-based hard-gate check on JD text (location, comp if stated, domain exclusions, seniority signal). Lower priority than A0/F2 — F1 stub is good enough for smoke test if we manually feed it valid JDs. |

---

## Next steps — proposed order (post-hygiene)

1. **Real A0 backend** — terminal Codex (network + API access required). Highest leverage. Schema is locked, prompt is written.
2. **Real F2 evaluator** — terminal Codex. First moment system produces output you can't get manually. Depends on real A0 producing real profiles.
3. **Manual paste smoke test** — drop one `roles/*.json` by hand → liveness → F1 stub → real A0 → real F2 → daily report. **First real end-to-end run.** No A1 needed.
4. **A1 ingestion** — once pipeline produces real output, A1 becomes high-leverage (feeds working machine instead of stubbed one). Start with manual CSV/curated URL list, then add scheduled sources.
5. **Real F1** — replace stub with LLM-based pre-screen. Can slot in any time after step 3.
6. **Phase 4 (A2/A3)** — CV + cover letter generation. Only after real F2 produces stances worth tailoring against.

**Tooling note (added 2026-04-28):** Switching to terminal Codex for A0 onward. Desktop Codex sandbox blocks `pip install`, real API calls, and Python 3.11+ environment setup — bottlenecks for any agent that talks to external services. Cowork stays for prompt/spec work; desktop Codex stays for small clean tickets; terminal Codex handles network-dependent or env-dependent builds.

---

## Open questions

- **Store choice:** Flat files vs SQLite vs Postgres. Start flat; upgrade trigger = >100 active roles or multi-device access needed.
- **Orchestration host:** Local machine vs small VPS. Defer until real A0 + F2 are stable and tested locally.
- **A1 source strategy:** LinkedIn is hostile to agents. Start with RSS + job board APIs + direct company career pages. LinkedIn last, manual-assisted.
- **Submission mode registry:** Which channels are auto, which assisted, which manual? Build this table as we encounter them.
- **Inbox access model:** Gmail OAuth scaffolded; need to confirm auth flow + scope before A8 wiring.
- **Cost budget:** Per-role compute cost (F1 + A0 + F2 + A2 + A3) × daily volume. Cap before it runs away. Becomes urgent once A0 is real.
- **MEDvidi re-synthesis:** Profile was produced against rubric v0.1. Re-run against v0.3 once real A0/F2 are live.

---

## Known constraints and operating principles

- **Canonical profile is the single source of truth.** Downstream agents consume slices, not full profile. Re-synthesize when rubric version changes.
- **Structured JSON over prose.** Agent-ready outputs first; human-readable summaries are secondary artifacts.
- **Data Contract is enforced at runtime.** User Layer files are never touched by system updates. Agents write only within their designated lanes, validated by the system-owned wrapper.
- **Modes are composable files, not embedded logic.** Each agent's prompt lives in a standalone, human-readable, human-editable markdown file (`agents/A0.md`, `agents/A2.md`, etc.). Same principle for filters (`filters/F1.md`, `filters/F2.md`). A shared context file (`agents/_shared.md`) holds common rules.
- **HIL is enforced at the prompt level, not just architecturally.** Every agent prompt includes: never submit without human review; discourage low-fit applications explicitly (below scored threshold = recommend skip); quality over quantity is an operating rule, not a slogan. A4 auto-submits only on pre-authorized channels. A8 never replies autonomously.
- **Overrides are training data.** Every override logged with reason, clustered for rubric evolution.
- **Rubric drives synthesis, synthesis is cache.** Hybrid C model locked 2026-04-21.
- **Liveness before research.** Dead postings never reach A0. Playwright verifies, not WebSearch.
- **Tooling split:** Cowork = prompts/specs (mobile-friendly). Desktop Codex = small clean tickets. Terminal Codex = anything network/env-dependent (real backends).

---

## Related artifacts

- `rubric_v0_3.json` — opportunity scoring rubric (current)
- `company_profile_schema_v0_2.json` — canonical company profile schema
- `DATA_CONTRACT.md` — v0.5, repo root
- `CLAUDE.md` — orchestrator operating prompt
- `MEMORY.md` — repo session memory
- `voice_pack.md` — voice constraints and exemplars
- `story_bank.md` — master stories
- `config/profile.yml` — identity + preferences
- `20_04_2026_session_notes.md` — Layer 1 (rubric) session notes

## Prior art reviewed

- **Career-Ops** (github.com/santifer/career-ops) — shipped Claude Code-based job search system, battle-tested across 740+ evaluations. JobPilot borrows: Data Contract pattern (Layer 0), onboarding contract (Phase 0), liveness check (A1.4), story bank (A5.3), modes-as-files operating principle, prompt-level HIL enforcement. JobPilot keeps its own: rubric versioning + synthesis cache invalidation, `gate_needs_judgment_call` state, values-based carve-out logic.
