# JobPilot — MEMORY.md

**Last updated:** 2026-04-28
**Purpose:** Repo session memory. Read at session start. Captures current state, recent decisions, and what to do next so any operator (Cowork, Codex, future Dima) picks up without rebuilding context.

---

## What JobPilot is

Agentic, LLM-native job application pipeline targeting senior operator roles (operations / delivery / transformation leadership) at scale-up companies. Rubric-driven, human-in-the-loop. The system sources postings, scores them, tailors materials, tracks pipeline state, and watches inbox — but never acts on the outside world without Dima's approval.

The thinking artifacts (rubric, schema, Data Contract, agent prompts) are primary value alongside the code. The project doubles as a portfolio piece.

**Repo:** github.com/yarmakdima-dev/jobpilot · public · MIT

---

## Current state (end of 2026-04-28)

**Codex audit confirms:** foundation merged, intake/research spine wired with stubs, A0 + F2 + F1 are stub-wired (real boundaries, placeholder data), A1 sourcing not started, `pipeline.json` empty. 112 tests passing.

### What's shipped (code on main)

- Phase 0 complete: DATA_CONTRACT.md (v0.5), CLAUDE.md, MEMORY.md, onboarding contract spec, executable `scripts/preflight_check.py`
- Phase 1 complete: state store (S1), pipeline runner with `--tick`/`--daemon` and file lock (S2), daily report generator (S3)
- A1.4 liveness check: Playwright wired, dead/active detection working
- F1, A0, F2: boundaries wired, all three return placeholder data
- Hygiene batch (closed 2026-04-28): `.gitignore` updated for Dispatch scratch files, doc drift fixed (A1.md, runner.md, state_store.md), preflight script implemented
- DATA_CONTRACT enforcement decision: **runtime validation is canonical**. Pre-commit hooks deferred to dev hygiene only.
- User Layer files exist locally: `cv.md`, `voice_pack.md`, `story_bank.md`, `config/profile.yml`

### What's prompt-only (Cowork track shipped)

All 13 agent/filter prompts: A0, A1, A1.4, A2, A3, A4, A5, A6, A7, A8, F1, F2, _shared. Voice pack shipped. Story bank format defined. Rubric at v0.3.

### What's not started

- A1.1–A1.3 (sourcing code)
- A2/A3 (CV + cover letter generation code)
- A4 (submission adapters)
- A8 (inbox watcher code; Gmail OAuth scaffolded only)
- A5/A6 (interview prep + debrief code)
- A7 (maintenance code)
- Real backends for A0, F2, F1

---

## The next-work surface

The system can ingest a manually-placed role through liveness → F1 stub → A0 stub → F2 stub → daily report. That's the working skeleton. **The skeleton produces nothing useful yet because three agents are stubs.**

### Stubs to replace, in priority order

1. **A0 (real)** — Perplexity Research-mode call, schema v0.2 population, two-step JSON formatting (Perplexity → Claude/GPT-4 for schema discipline). Highest leverage. Prompt is written, schema is locked.
2. **F2 (real)** — LLM scoring against rubric v0.3, override rule application, `360_synthesis` generation with `synthesis_rubric_version` tag, `gate_needs_judgment_call` resolution. **First moment the system produces output Dima can't get manually.**
3. **F1 (real)** — LLM-based hard-gate check on JD text. Lower priority; stub is good enough for smoke test.

### First real end-to-end use case

Paste role URL → receive scored profile + stance.

Path: real A0 + real F2 + manual paste of `roles/*.json`. **A1 sourcing is NOT required for first use case.**

### Proposed next step order

1. Real A0 backend (terminal Codex)
2. Real F2 evaluator (terminal Codex)
3. Manual paste smoke test — first real end-to-end run
4. A1 ingestion (manual CSV → scheduled sources)
5. Real F1 (slot in anywhere after #3)
6. Phase 4 (A2/A3) — only after F2 produces stances worth tailoring against

---

## Tooling split (decided 2026-04-28)

- **Cowork (Dima + Day, mobile-friendly):** prompts, specs, ticket drafting, architecture decisions, PR verification
- **Desktop Codex:** small clean tickets, doc reconciliation, sandbox-friendly hygiene work
- **Terminal Codex:** anything network-dependent or environment-dependent — real API integrations, Python 3.11+ setup, `pip install`, real backend builds

A0 onward is terminal Codex territory. Desktop Codex hit the wall on Python 3.11 install and network restrictions during the hygiene batch — that wall hits harder for real A0/F2.

---

## Open architectural questions (deferred until they matter)

- **VPS migration** — defer until real A0 + F2 are stable locally
- **Cost budget per role** (F1 + A0 + F2 + A2 + A3 × daily volume) — becomes urgent once A0 is real
- **A1 source strategy** — RSS + job board APIs + direct career pages first; LinkedIn last
- **Inbox access model** — Gmail OAuth scaffolded; finalize before A8 wiring
- **MEDvidi re-synthesis** — profile produced against rubric v0.1; re-run against v0.3 once real A0/F2 live

---

## Decisions worth remembering

- **DATA_CONTRACT enforcement: runtime validation, not pre-commit.** Trust boundary lives in the system-owned write wrapper. Pre-commit is dev hygiene.
- **Build order: replace stubs before A1.** A1 ingestion into stubbed pipeline gives nothing Dima can't already do by hand. Real A0/F2 produces value Dima can't get manually.
- **Hybrid C synthesis model (locked 2026-04-21).** Research agent populates facts. Scoring agent writes `360_synthesis` tagged with `synthesis_rubric_version`. Downstream agents trigger re-synthesis on rubric version change or manual refresh.
- **Asymmetric RU/BY war-position scoring (rubric v0.2+).** RU silence = negative. BY silence = informational unless co-signals. Reflects real personal-risk asymmetry.
- **Gate_needs_judgment_call pattern.** Some gates can't be resolved from public research. Profile field flags them; downstream work blocks until human resolves or explicitly overrides.
- **Voice (cover letter):** reflective, direct, specific. No "passionate about," "excited to," "I believe." No bullets/headers in letter body. Minimal em-dash.

---

## Recent session log

- **2026-04-20** — Layer 1 session: rubric v0.1, scoring architecture (manager quality as gating multiplier), hard gates, override rules
- **2026-04-21** — Rubric v0.2 (asymmetric RU/BY logic), schema v0.2 (name_confusion_check, war_position, parallel_business_flag, gate_needs_judgment_call), backlog v0.2 (Data Contract, Phase 0, A1.4, A5.3)
- **2026-04-22** — Cowork briefs scoped: P0.1, P0.3, P0.2, voice pack, agent/filter prompts
- **2026-04-23** — 19 backlog items closed in one day. Phase 0 + Phase 1 done, A1.4 + A2.1–A2.2 + A3.1–A3.2 + A5.1–A5.3 + A6.1–A6.2 + A8.1–A8.4 prompts shipped. S2 PR #1 + S3 PR #2 ready to merge.
- **2026-04-28** — Codex repo audit reconciles state. Hygiene batch closed: `.gitignore`, preflight script, doc drift fixes, DATA_CONTRACT enforcement decided. Backlog → v0.3. Tooling split decided: terminal Codex for real backends. Next: A0 ticket.
