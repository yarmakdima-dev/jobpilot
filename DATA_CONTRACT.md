# DATA_CONTRACT.md

**Version:** 0.6 | **Status:** Canonical | **Last updated:** 2026-04-28

---

## Purpose

This file is the authoritative definition of which files in JobPilot belong to the User Layer and which belong to the System Layer, and which agents may write to which paths. It exists to prevent one specific class of failure: system updates, version bumps, or agent logic changes touching user work product. Every agent, orchestrator, build process, and Codex session that operates on this repo must treat this contract as binding. When this file and any other source disagree, this file wins.

---

## The Rule

**User Layer files are owned by the user.** No agent, script, orchestrator, or update process may read, modify, or delete a User Layer file except through its explicitly designated write lane as defined in this contract. Write lanes are narrow by default; widening one requires a human edit to this file plus a changelog entry. System Layer files may be replaced in full on any version bump without risk to user data or pipeline state.

---

## User Layer File Inventory

Files containing personal data, work product, pipeline state, and human decisions. Never overwritten by system updates.

| Path | Purpose | Who writes | Who reads |
|------|---------|-----------|----------|
| `cv.md` | Canonical CV; source of truth for all tailoring | Human only | A2, A3, A5 |
| `voice_pack.md` | Voice constraints and exemplars; governs tone across all outputs | Human only (Layer 2 output pending) | A2, A3, A5 |
| `config/profile.yml` | Identity, compensation targets, location, preferences | Human only | A1, A2, A3, A5, F1 |
| `companies/*.json` | Populated company profiles, one file per domain (schema v0.2) | A0 (create/update); A7 (synthesis cache invalidation fields only) | F2, A2, A3, A4, A5, A6, A7 |
| `roles/*.json` | Role records — JD, URL, F1/F2 results, pipeline state, submission mode | A1 (create); F1 (filter_status fields only); F2 (filter_status fields only); A6 (debrief field only) | F1, F2, A2, A3, A4, A5, A6, A7, A8, orchestrator |
| `pipeline.json` | Flat table of all active roles with current state | Orchestrator (state machine transitions only); Human (override console) — **A4 does not write to pipeline.json. Resolved Phase 5: A4 signals the orchestrator on confirmed auto-submission; the orchestrator writes the `applied` transition. All other transitions remain orchestrator-owned.** | A1 (dedup read), A4 (read only), A7 (read only), A8 (read only), human |
| `decisions.log` | All overrides and state transitions with mandatory reasons; training data for rubric evolution | A7 (append only); Human (override console) | A7, human |
| `inbox_events/*` | A8 output queue — classified inbox events awaiting human review | A8 (create only) | Human |
| `reports/*` | 360 syntheses, interview debriefs, post-interview notes | A6 (create only) | A5, human |
| `output/*` | Generated CVs, cover letters, submission packages | A2 (create); A3 (create) | A4, human (approval queue) |
| `story_bank.md` | Accumulating master story library in STAR format; grows across interviews; A5 reads, A6 writes | A6 (append only) | A5 (read), A6 (read before appending), human |

---

## System Layer File Inventory

Files containing logic, prompts, schemas, and scripts. Safe to auto-replace on version bumps. `rubric.json` is user-editable but versioned as System Layer because downstream synthesis caches depend on its version string.

| Path | Purpose | Who writes | Who reads |
|------|---------|-----------|----------|
| `rubric.json` | Opportunity scoring rubric; version string triggers synthesis cache invalidation | Human (direct edit); A7 (version bump logging via `decisions.log` only) | F1, F2, A0, A5, A7 |
| `company_profile_schema.json` | Schema definition for `companies/*.json` | Human / build process | A0, F2 |
| `agents/*.md` | Agent prompt files, one per agent; composable, human-editable | Human / build process | Each respective agent; orchestrator |
| `agents/_shared.md` | Shared rules injected into every agent prompt | Human / build process | All agents |
| `filters/*.md` | F1 and F2 prompt files | Human / build process | F1, F2 |
| `orchestrator/*` | Pipeline runner, state machine, cron scheduler | Human / build process | Orchestrator, human |
| `scripts/*` | Utilities: merge, dedup, liveness-check, verify | Human / build process | Agents as invoked |
| `templates/*` | CV templates, cover letter scaffolds, daily report template | Human / build process | A2, A3, orchestrator |
| `DATA_CONTRACT.md` | This file; canonical write-lane authority | Human only | All agents, orchestrator, build process |
| `CLAUDE.md` / `AGENTS.md` | Orchestrator instructions; bakes HIL enforcement and operating rules | Human only | Orchestrator |

---

## Write Lanes

One row per agent. The "forbidden from" column is explicit: if a path is not listed under "writes to" or "read-only," the agent must not touch it — no exceptions, no inferred permissions.

| Agent | Writes to | Read-only access to | Forbidden from |
|-------|-----------|---------------------|----------------|
| **A0** Company research | `companies/*.json` (create, update) | `company_profile_schema.json`, `rubric.json`, `config/profile.yml`, `roles/*.json` (role URL/context) | `cv.md`, `voice_pack.md`, `pipeline.json`, `decisions.log`, `inbox_events/*`, `reports/*`, `output/*`, all `agents/`, `filters/`, `scripts/`, `templates/` |
| **A1** Job sourcing | `roles/*.json` (create new records only; no field updates on existing records) | `config/profile.yml`, `pipeline.json` (dedup read) | `cv.md`, `voice_pack.md`, `companies/*.json`, `decisions.log`, `inbox_events/*`, `reports/*`, `output/*`, all system-layer prompt files |
| **F1** JD pre-screen | `roles/*.json` (`filter_status.f1.*` only) | `roles/*.json` (full read), `rubric.json`, `config/profile.yml`, `filters/F1.md` | `cv.md`, `voice_pack.md`, `companies/*.json`, `pipeline.json`, `decisions.log`, `inbox_events/*`, `reports/*`, `output/*` |
| **F2** Deep rubric eval | `roles/*.json` (`filter_status.f2.*` and top-level `gate_needs_judgment_call` only); `companies/*.json` (`360_synthesis` block only, to be enabled with the real F2 backend) | `roles/*.json` (full read), `companies/*.json` (full read), `rubric.json`, `config/profile.yml`, `filters/F2.md` | `cv.md`, `voice_pack.md`, `pipeline.json`, `decisions.log`, `inbox_events/*`, `reports/*`, `output/*` |
| **A2** CV tailoring | `output/*` (create tailored CV packages) | `cv.md`, `voice_pack.md`, `config/profile.yml`, `companies/*.json`, `roles/*.json`, `rubric.json`, `templates/*`, `agents/A2.md`, `agents/_shared.md` | `companies/*.json` (no write), `roles/*.json` (no write), `pipeline.json`, `decisions.log`, `inbox_events/*`, `reports/*` |
| **A3** Cover letter | `output/*` (create cover letters) | `cv.md`, `voice_pack.md`, `config/profile.yml`, `companies/*.json`, `roles/*.json`, `rubric.json`, `templates/*`, `agents/A3.md`, `agents/_shared.md` | `companies/*.json` (no write), `roles/*.json` (no write), `pipeline.json`, `decisions.log`, `inbox_events/*`, `reports/*` |
| **A4** Submission | `roles/*.json` (submission-state fields only: `submission_mode`, `submitted_at`, `submission_channel` — **note: these three fields require a role schema version bump before A4 ships**); `inbox_events/*` (assisted-path email draft and manual-path nudge only) | `output/*`, `roles/*.json` (full read), `pipeline.json` (read only — A4 never writes), `config/profile.yml`, `agents/A4.md`, `agents/_shared.md` | `cv.md`, `voice_pack.md`, `companies/*.json`, `pipeline.json` (no write — ever), `decisions.log`, `reports/*` — **A4 never writes pipeline.json. Approval gate: pipeline_state must be `ready_to_submit` (set by orchestrator after human approval) before A4 runs. Auto-submit only on pre-authorized channels in config/profile.yml.** |
| **A5** Interview prep | `reports/*` (create only — stage-specific prep docs: `{role_id}_prep_first_call.md`, `{role_id}_prep_interview_{date}.md`; does not overwrite without confirmation) | `cv.md`, `voice_pack.md`, `config/profile.yml`, `companies/*.json` (profile slices only — stage-specific; see A5.md), `roles/*.json`, `rubric.json`, `story_bank.md` (read only), `reports/*` (read prior debriefs), `agents/A5.md`, `agents/_shared.md` | `pipeline.json`, `decisions.log`, `inbox_events/*`, `output/*`, `story_bank.md` (no write — A6's lane), `companies/*.json` (no write), `roles/*.json` (no write) — **write-lane conflict resolved in v0.4: A5 was read-only in v0.1–v0.3; updated to write reports/* after Layer 5 design session. See decisions.log.** |
| **A6** Debrief capture | `reports/*` (create debrief documents); `roles/*.json` (debrief field only: `debrief_ref`, `debrief_date`) | `cv.md`, `voice_pack.md`, `config/profile.yml`, `companies/*.json`, `roles/*.json`, `rubric.json`, `agents/A6.md`, `agents/_shared.md` | `cv.md` (no write), `voice_pack.md` (no write), `pipeline.json`, `decisions.log`, `inbox_events/*`, `output/*` |
| **A7** Rubric/profile maintenance | `decisions.log` (append only); `companies/*.json` (`synthesis_rubric_version` and `synthesis_stale` fields only); `reports/rubric_signals_{date}.md` (create — clustering report) | `rubric.json`, `pipeline.json`, `roles/*.json`, `companies/*.json`, `reports/*` (read — debrief scanning for RUBRIC_TUNING_SIGNAL and RE_SYNTHESIS_RECOMMENDED blocks), `agents/A7.md`, `agents/_shared.md` | `cv.md`, `voice_pack.md`, `config/profile.yml`, `output/*`, `inbox_events/*`, `story_bank.md` — **A7 never edits `rubric.json` directly; it drafts proposed changes in the clustering report and signals re-synthesis. `reports/*` read access added v0.5 to support debrief scanning.** |
| **A8** Inbox watcher | `inbox_events/*` (create event records only) | `pipeline.json`, `roles/*.json`, `agents/A8.md`, `agents/_shared.md` | `cv.md`, `voice_pack.md`, `config/profile.yml`, `companies/*.json`, `roles/*.json` (no write), `decisions.log`, `reports/*`, `output/*` — **A8 never sends replies; draft generation is for human review only** |
| **Human** | `cv.md`, `voice_pack.md`, `config/profile.yml`, `rubric.json`, `decisions.log` (override entries), `pipeline.json` (override console), `DATA_CONTRACT.md` (write-lane changes) | All files | Nothing — human has full authority and is the only principal that may widen a write lane |

---

## Enforcement

**Decision:** runtime validation is the authoritative enforcement mechanism. Pre-commit validation is optional developer hygiene and must never be the only guard protecting User Layer files.

**Runtime check (implemented):** Before any agent write, the orchestrator/store layer confirms the `(agent, path)` pair is permitted by this contract. Implemented code lives in `orchestrator/lanes.py` and `orchestrator/store.py`. Violations raise `LaneViolationError`, halt that agent's write, and append a `lane_violation` entry to `decisions.log`. Role writes also enforce field-level scopes for implemented lanes: A1 creates only; F1 updates `filter_status.f1.*`; F2 updates `filter_status.f2.*` plus top-level `gate_needs_judgment_call`; A6 updates `debrief_ref`.

**Pre-commit hook (future):** A hook may be added later to catch obvious staged-file mistakes during development, but it is advisory relative to runtime enforcement. It should fail closed on attempted commits to ignored User Layer paths and should not write to `decisions.log`, because commit-time checks are outside the running pipeline.

**Rationale:** runtime validation protects the actual production path, including manual smoke tests, scheduled runner ticks, and future API-backed agents. A pre-commit hook only protects Git commits and cannot stop a running agent from writing the wrong file.

---

## Changelog

- **v0.6 (2026-04-28):** Resolved enforcement decision. Runtime lane validation is canonical and already implemented in `orchestrator/lanes.py` / `orchestrator/store.py`; pre-commit remains a future developer guard only. Updated F1/F2 lane field names to match the current role schema.
- **v0.5 (2026-04-23):** Added `reports/*` read access to A7's lane to support debrief scanning (RUBRIC_TUNING_SIGNAL and RE_SYNTHESIS_RECOMMENDED block extraction). Added `reports/rubric_signals_{date}.md` to A7's write lane for periodic clustering reports. Prior v0.4 had A7 forbidden from reports/* — this was incorrect given the A6→A7 signal routing design established in the same session.
- **v0.4 (2026-04-23):** Resolved A5 write-lane conflict. A5 was designated read-only in v0.1–v0.3; updated to write `reports/*` (create only) after Layer 5 design session. Rationale: prep docs must persist for use during calls and for A6 reference — in-session-only delivery is operationally insufficient. Added `story_bank.md` to User Layer inventory with A6 as append-only writer and A5 as reader. A6's provisional write to story_bank.md is now formally contracted.
- **v0.3 (2026-04-23):** Resolved A4 + pipeline.json TBD. A4 does not write pipeline.json — ever. Orchestrator owns all pipeline.json state transitions. A4 writes submission metadata to roles/*.json and emits a completion signal; orchestrator acts on the signal. Approval gate resolved: pipeline_state `ready_to_submit` (written by orchestrator after human approval in the approval queue) is the approval signal A4 checks. A4 write lane updated to include inbox_events/* for assisted-path drafts and manual-path nudges. Role schema flagged for version bump to add three submission fields.
- **v0.2 (2026-04-22):** Initial contract, extracted from `backlog.md` Layer 0 and Operating Principles sections. Write-lane table expanded to include explicit "forbidden from" column for all agents. A4 and `pipeline.json` write scope flagged TBD pending Phase 5 design. Enforcement approach flagged for Codex to specify.
