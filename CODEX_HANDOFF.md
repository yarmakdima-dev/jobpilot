# Codex Handoff — JobPilot Foundation

**Repo:** github.com/yarmakdima-dev/jobpilot
**Stream:** System Layer code (Dima + Claude build System Layer prompts/specs in parallel — no file collision)
**Starting tickets:** S1, S2, S3, A1.4
**PR model:** One PR per ticket. Small, reviewable, independently mergeable.

---

## Context you need before writing code

JobPilot is an agentic job application system. This handoff covers the foundation: a state store, a pipeline runner, a daily report generator, and a liveness check for job postings. You are not building agents yet — you are building the substrate agents will run on.

Read these files in the repo before starting:

- `backlog.md` — system overview, agent catalog, build order
- `rubric.json` — scoring rubric (you don't implement scoring, but S1 schemas reference rubric version)
- `company_profile_schema.json` — canonical schema for `companies/*.json`

Architecture summary: eleven agents + two filters + one orchestrator, operating over a shared state store. Human-in-the-loop at decision points. No agent acts on the outside world without approval.

---

## Data Contract (spec — canonical doc ships separately)

Every file in the system belongs to one of two layers. Enforce this separation in code.

### User Layer — never auto-modified

Personal data and work product. System updates never touch these files. Agents write only within designated lanes.

```
cv.md
voice_pack.md
config/profile.yml
companies/*.json
roles/*.json
pipeline.json
decisions.log
inbox_events/*
reports/*
output/*
```

### System Layer — safe to replace on version bumps

Logic, prompts, schemas, scripts.

```
rubric.json                        # user edits, versioned as system
company_profile_schema.json
agents/*.md
filters/*.md
orchestrator/*
scripts/*
templates/*
DATA_CONTRACT.md
CLAUDE.md / AGENTS.md
```

### Write lanes (enforce in pipeline runner)

| Agent / Actor | Can write |
|---|---|
| A0 | `companies/*.json` (create/update) |
| A1 | `roles/*.json` (create) |
| F1, F2 | `roles/*.json` (update filter_status fields only) |
| A2, A3 | `output/*` (create) |
| A6 | `reports/*` (create), `roles/*.json` (debrief field) |
| A7 | `decisions.log` (append), `companies/*.json` (invalidate synthesis cache) |
| A8 | `inbox_events/*` (create) |
| Human only | `cv.md`, `voice_pack.md`, `config/profile.yml`, `rubric.json` |

**Rule:** The pipeline runner validates write lanes before any agent executes. Lane violations halt the role and log to `decisions.log`.

`DATA_CONTRACT.md` will ship in parallel and becomes the canonical source. Build S1 to this spec; the runner can load the canonical doc when it lands without schema churn.

---

## Repo layout to create

```
/
├── companies/                 # User Layer
├── roles/                     # User Layer
├── reports/                   # User Layer
├── output/                    # User Layer
├── inbox_events/              # User Layer
├── config/
│   └── profile.yml            # User Layer (stub for now)
├── agents/                    # System Layer (empty; Dima + Claude populate)
├── filters/                   # System Layer (empty)
├── orchestrator/              # System Layer — your code lives here
│   ├── runner.py
│   ├── state_machine.py
│   ├── lanes.py
│   └── report.py
├── scripts/                   # System Layer
│   └── liveness_check.py
├── templates/                 # System Layer
│   └── daily_report.md.j2
├── schemas/                   # System Layer
│   ├── role.schema.json
│   └── pipeline.schema.json
├── tests/
├── rubric.json                # exists
├── company_profile_schema.json # exists
├── pipeline.json              # User Layer (runtime)
├── decisions.log              # User Layer (runtime)
└── DATA_CONTRACT.md           # System Layer (Dima ships in parallel)
```

---

## Ticket S1 — State store schemas and I/O

**Goal:** Flat-file state store with strict schemas, safe read/write helpers, and lane enforcement.

### Deliverables

1. **JSON schemas** in `schemas/`:
   - `role.schema.json` — see structure below
   - `pipeline.schema.json` — flat table of active roles
   - Reference `company_profile_schema.json` (already in repo) for companies; do not redefine

2. **I/O module** `orchestrator/store.py`:
   - `read_role(role_id) -> dict`
   - `write_role(role_id, data, writer_id)` — validates schema + lane
   - `read_company(domain) -> dict`
   - `write_company(domain, data, writer_id)` — validates schema + lane
   - `append_decision(entry)` — appends to `decisions.log`
   - `read_pipeline() -> list[dict]` / `write_pipeline(data, writer_id)`

3. **Lane enforcement** `orchestrator/lanes.py`:
   - `WRITE_LANES` constant matching the table above
   - `check_lane(writer_id, path) -> bool`
   - Lane violation raises `LaneViolationError`, logs to `decisions.log`

### Role schema (draft — finalize in implementation)

```json
{
  "role_id": "string (slug: company-title-yyyymmdd)",
  "company_domain": "string (foreign key → companies/{domain}.json)",
  "source": {
    "url": "string",
    "platform": "string (linkedin | indeed | company_site | rss | other)",
    "discovered_at": "ISO-8601"
  },
  "jd": {
    "title": "string",
    "body": "string (raw text)",
    "location_stated": "string",
    "comp_stated": "string | null"
  },
  "liveness": {
    "last_checked": "ISO-8601 | null",
    "status": "alive | dead | unknown",
    "last_check_method": "playwright | manual | null"
  },
  "filter_status": {
    "f1": {
      "status": "pending | pass | fail | near_miss",
      "failed_gates": ["string"],
      "checked_at": "ISO-8601 | null",
      "rubric_version": "string | null"
    },
    "f2": {
      "status": "pending | pass | fail | blocked",
      "stance": "go | probe | stop | blocked | null",
      "checked_at": "ISO-8601 | null",
      "rubric_version": "string | null",
      "synthesis_ref": "string | null"
    }
  },
  "pipeline_state": "sourced | f1_passed | researched | f2_passed | ready_to_submit | applied | first_call | interview_scheduled | post_interview | closed",
  "state_history": [
    { "from": "string", "to": "string", "at": "ISO-8601", "reason": "string" }
  ],
  "debrief_ref": "string | null"
}
```

### Acceptance criteria

- [ ] Schemas validate with `jsonschema` library; invalid writes raise clear errors
- [ ] Lane enforcement: writing to a path outside the writer's lane raises `LaneViolationError` and logs to `decisions.log`
- [ ] `write_role` is atomic (write to `.tmp`, rename) — no partial writes on crash
- [ ] `decisions.log` is append-only, newline-delimited JSON
- [ ] Unit tests cover: valid writes, schema violations, lane violations, atomic write, concurrent-write safety (file lock)
- [ ] README section `docs/state_store.md` documents the API

### Out of scope

- No database. Flat files only. Upgrade path is a future ticket.
- No schema migrations. v0.1 schema is fine; versioning comes later.

---

## Ticket S2 — Pipeline runner (state machine, cron-based)

**Goal:** A scheduler that scans `pipeline.json` on a cron, dispatches agents based on role state, logs transitions. Agents do not exist yet — stub them with no-op handlers that log "would run A0 for role X."

### Deliverables

1. **State machine** `orchestrator/state_machine.py`:
   - Transition table mapping `pipeline_state` → next agent/filter to invoke
   - `next_action(role) -> (agent_id, callable) | None`
   - Terminal states (`closed`) return `None`

2. **Runner** `orchestrator/runner.py`:
   - CLI entrypoint: `python -m orchestrator.runner --tick` (one pass) and `--daemon` (loop with sleep)
   - Scans `pipeline.json`, determines next action per role, dispatches
   - Single-writer guarantee: file lock on `pipeline.json` during a tick
   - Failures halt the individual role (mark state as `error`, log reason) but do not crash the runner
   - Restartable: state lives in files, not memory

3. **Agent registry** `orchestrator/agents.py`:
   - Stub handlers for A0, A1, F1, F2, A2, A3, A4, A5, A6, A7, A8
   - Each stub: logs "would run {agent_id} for role {role_id}" to `decisions.log`, does nothing else
   - Real agent code slots in later by replacing the stub

4. **Transition log:**
   - Every state change appended to `decisions.log` as `{ role_id, from, to, at, reason, agent_id }`
   - Also reflected in the role's `state_history`

### State transition table

```
sourced              → liveness_check (A1.4)  → f1_pending
f1_pending           → F1                     → f1_passed | f1_failed
f1_passed            → A0                     → researched
researched           → F2                     → f2_passed | f2_failed | f2_blocked
f2_passed            → A2 + A3                → ready_to_submit
ready_to_submit      → A4                     → applied
applied              → A8 (watches)           → first_call | closed
first_call           → A5                     → interview_scheduled
interview_scheduled  → A5                     → post_interview
post_interview       → A6                     → closed
```

Failed states (`f1_failed`, `f2_failed`, `closed`) are terminal unless a human override bumps them via the override console (future ticket).

### Acceptance criteria

- [ ] `--tick` runs one pass, processes all roles, exits cleanly
- [ ] `--daemon` loops every N seconds (config: `orchestrator/config.yml`, default 300s)
- [ ] File lock prevents concurrent runners on same `pipeline.json`
- [ ] Agent stub invocation logged to `decisions.log` with `role_id`, `agent_id`, `at`
- [ ] Role-level failure does not halt the runner; failed role's state becomes `error` with reason
- [ ] Tests cover: single tick with mixed-state roles, restart mid-pipeline, lane violation during dispatch, concurrent-runner prevention
- [ ] README section `docs/runner.md` documents `--tick`, `--daemon`, config, how to plug real agents in later

### Out of scope

- No real agent code. All stubs.
- No parallel dispatch. Sequential per tick is fine; upgrade later if needed.
- No retry logic. Failed = failed until human override.

---

## Ticket S3 — Daily report template + generator

**Goal:** A morning digest Dima can scan in 5 minutes. Aggregates pipeline state, funnel metrics, approval queue, near-misses.

### Deliverables

1. **Template** `templates/daily_report.md.j2` (Jinja2):
   - Sections: Pipeline snapshot, Needs your attention, Funnel metrics (7-day), Near-misses, Overrides logged, Errors
   - Markdown format (so Dima can read in Cowork, email, or terminal)

2. **Generator** `orchestrator/report.py`:
   - `generate_report(date=today) -> str` — returns rendered markdown
   - CLI: `python -m orchestrator.report --date YYYY-MM-DD --out reports/daily_YYYY-MM-DD.md`
   - Pulls from `pipeline.json`, `decisions.log`, `roles/*.json`

3. **Scheduled run:**
   - Runner's daemon mode invokes report generation once per day at configured time (default 07:00 local)
   - Report written to `reports/daily_YYYY-MM-DD.md`

### Report sections (spec)

**Pipeline snapshot**
- Count by state: sourced, f1_passed, researched, f2_passed, ready_to_submit, applied, first_call, interview_scheduled, post_interview
- Flag any role stuck in a state > 7 days

**Needs your attention**
- Roles in `ready_to_submit` awaiting human approval
- Roles with `f2.stance = "blocked"` (judgment-call gates)
- Roles in `error` state
- Inbox events awaiting review (from `inbox_events/`)

**Funnel metrics (7-day)**
- sourced → f1_passed rate
- f1_passed → f2_passed rate
- f2_passed → applied rate
- applied → first_call rate

**Near-misses**
- F1 near-miss roles from last 24h (from `filter_status.f1.status = "near_miss"`)

**Overrides logged**
- Overrides from `decisions.log` in last 24h (human overrides of agent decisions)

**Errors**
- Roles in `error` state with reason

### Acceptance criteria

- [ ] Report renders even when state is sparse (empty pipeline → clean "nothing yet" message, not a crash)
- [ ] All sections present; empty sections show "—" not disappear
- [ ] 7-day funnel calculated from `state_history` across all roles (including closed)
- [ ] Report is markdown; renders cleanly in a text editor and in any markdown viewer
- [ ] Tests cover: empty state, partial state (some roles mid-pipeline), full state with all sections populated
- [ ] README section `docs/daily_report.md` documents what's in it and how to customize

### Out of scope

- No email delivery. Dima reads from `reports/` directly.
- No charts. Markdown text tables only.
- No historical trending beyond 7 days.

---

## Ticket A1.4 — Liveness check

**Goal:** Verify a job posting is still open before F1 spends budget on it. Dead postings never reach A0.

**Why Playwright, not WebSearch:** WebSearch is unreliable for dead postings — cached snippets show content that no longer exists. Playwright navigates the actual URL and inspects the live DOM.

### Deliverables

1. **Module** `scripts/liveness_check.py`:
   - `check_liveness(url) -> { status: "alive" | "dead" | "unknown", evidence: str, checked_at: ISO-8601 }`
   - Uses Playwright (headless Chromium) to navigate and snapshot the page
   - Heuristics:
     - **Dead:** page is footer/navbar only, no JD body text; 404/410 HTTP status; redirect to generic careers landing; common dead-posting signals ("This job is no longer available", "Position filled", "Expired")
     - **Alive:** title + description body + apply button (or apply link) present
     - **Unknown:** page loads but heuristics inconclusive (e.g., paywall, login wall, JS didn't render) — flag for manual review, don't auto-fail

2. **Integration with runner:**
   - New pipeline state `liveness_pending` inserted between `sourced` and `f1_pending`
   - State machine routes `sourced` → `liveness_check` → `f1_pending` (alive) | `closed` (dead, reason: "posting_dead") | human queue (unknown)

3. **Config** `scripts/liveness_config.yml`:
   - Per-platform heuristic overrides (LinkedIn, Greenhouse, Lever, Workday have different dead-posting patterns)
   - Timeout per check (default 30s)

### Acceptance criteria

- [ ] Correctly classifies ≥8/10 known-dead test URLs as `dead`
- [ ] Correctly classifies ≥8/10 known-alive test URLs as `alive`
- [ ] Ambiguous cases go to `unknown`, not a false positive/negative
- [ ] Timeout protection: no single check hangs the pipeline
- [ ] Playwright runs headless; installable via `playwright install chromium` documented in README
- [ ] Dead postings bypass A0 entirely (no research budget spent)
- [ ] Tests include fixture HTML pages (alive, dead, unknown variants) to avoid hitting live URLs in CI
- [ ] README section `docs/liveness_check.md` documents heuristics, config, how to add platform-specific rules

### Out of scope

- No retry logic for unknown → alive/dead. One check, one result, human resolves unknown.
- No platform-specific scraping beyond dead/alive classification. JD extraction stays in A1.
- No auth-walled postings. Dima provides JD manually for those.

---

## Conventions for all four tickets

- **Language:** Python 3.11+
- **Style:** `ruff` for lint, `black` for format, type hints on public functions
- **Tests:** `pytest`, fixtures in `tests/fixtures/`, CI runs on PR
- **Dependencies:** pin in `pyproject.toml`, keep minimal — `jsonschema`, `pyyaml`, `jinja2`, `playwright`, `pytest`
- **Logging:** stdlib `logging`, structured where practical (JSON lines for machine-readable logs)
- **Commits:** conventional commits (`feat:`, `fix:`, `chore:`, `test:`)
- **PRs:** one ticket per PR, description references ticket ID, acceptance criteria as checklist in PR body

---

## Build order within this handoff

Dependencies:
- S1 is a hard prerequisite for S2, S3, A1.4 (they all read/write via `orchestrator/store.py`)
- S2 is a prerequisite for A1.4 integration (A1.4's module can be built standalone, but wiring into the runner needs S2)
- S3 can be built in parallel with S2 once S1 lands

Suggested order: **S1 → S2 + S3 in parallel → A1.4**

---

## Questions for Dima before you start

If anything in the Data Contract, schemas, or state transitions is ambiguous, raise a GitHub issue tagged `question` before writing code. Don't guess on lane boundaries or state transitions — those are expensive to refactor after agents land on them.
