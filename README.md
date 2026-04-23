# JobPilot

Agentic job application system for senior operator roles. LLM-native, rubric-driven, human-in-the-loop.

**Status:** Active build. Layer 1 (opportunity scoring) complete. Layers 2–5 and orchestration in progress. Not yet functional end-to-end.

---

## What this is

A personal system that sources job postings, evaluates them against an explicit values-and-fit rubric, tailors application materials, tracks pipeline state, and watches the inbox — with human approval at every decision point.

Built around three ideas:

1. **Canonical data, sliced on consumption.** A single company profile is the source of truth; downstream agents read only the slices they need.
2. **Rubric drives everything.** Scoring logic is an explicit, versioned artifact — not prompt-embedded judgment. When the rubric changes, cached decisions invalidate.
3. **Human-in-the-loop at prompt level, not just architecture.** Every agent is instructed to recommend skip over apply when fit is weak. Quality over quantity is a hard rule, not a slogan.

## Why build it in the open

Two reasons. One, the thinking is the artifact — the rubric, the schema, the session notes, the decision log. These are more interesting than the final code. Two, showing work publicly is itself a filter: people who care about how I think are the people I want to hear from.

## Architecture

Eleven agents, two filters, one orchestrator, one shared state store. Human supervision via daily report, override console, and approval queue.

```
A1 (source) → F1 (JD pre-screen) → A0 (company research) → F2 (deep rubric eval)
           → A2 (CV) + A3 (cover letter) → A4 (submit) → A8 (inbox watch)
           → A5 (interview prep) → A6 (debrief) → A7 (rubric/profile maintenance)
```

Full architecture and build order in [`backlog.md`](./backlog.md).

## Key artifacts

| File | Purpose |
|------|---------|
| [`backlog.md`](./backlog.md) | Full system design, agent catalog, build order |
| [`rubric.json`](./rubric.json) | Opportunity scoring rubric (current: v0.2) |
| [`company_profile_schema.json`](./company_profile_schema.json) | Canonical company profile schema (current: v0.2) |
| `DATA_CONTRACT.md` | User Layer vs System Layer separation rule *(coming)* |
| `CLAUDE.md` | Orchestrator instructions, HIL enforcement *(coming)* |
| [`session_notes/`](./session_notes/) | Per-session design decisions and open threads |

## Data Contract

The repo enforces a strict separation between two layers:

- **User Layer** — personal data, work product, decisions. Gitignored. Never touched by system updates.
- **System Layer** — logic, prompts, schemas, scripts. Safe to auto-update on version bumps.

This is why the repo looks thin on runtime data: by design, none of it is here. See `DATA_CONTRACT.md` (coming) and `.gitignore` for the full list.

## Prior art

- **[Career-Ops](https://github.com/santifer/career-ops)** — shipped Claude Code-based job search system, battle-tested across 740+ evaluations. JobPilot borrows the Data Contract pattern, onboarding contract, liveness check, story bank, modes-as-files principle, and prompt-level HIL enforcement. JobPilot keeps its own rubric-versioning-with-cache-invalidation, judgment-call gate state, and values-based carve-out logic.

## Setup

```bash
pip install -e ".[dev]"
playwright install chromium   # required after pip install; downloads the Chromium browser for liveness checks
```

## License

MIT. Use, fork, learn from it. If you build something downstream, a link back is appreciated but not required.

## Contact

Open an issue or find me on [LinkedIn](https://www.linkedin.com/in/yarmak-dmitry/).
