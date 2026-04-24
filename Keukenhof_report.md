# Keukenhof Day — JobPilot Session Report
**Date:** 2026-04-23
**Location:** Keukenhof, Netherlands (mobile) → Hotel room → Back at laptop

---

## The Setup

Dima spent the day at Keukenhof — one of the world's largest flower gardens — while running a full engineering and product session on JobPilot entirely from his phone via the Claude Dispatch mobile interface. Laptop was back at the hotel, screen locked for security (locked remotely mid-session). All coordination happened through short mobile messages; Claude handled execution autonomously between check-ins.

The session demonstrated a genuinely new working pattern: a non-technical professional directing an agentic build from a garden, reviewing outputs on a phone, and returning to a laptop with a day's worth of shipped work waiting.

---

## What Was Built Today

### Foundation wrap-up
- **S1 + S2 + S3 merged to main** — the full pipeline foundation (state store, runner, daily report generator) landed cleanly. All PRs reviewed and merged.

### Agent prompt library — complete
All 13 agent prompt files written and reviewed in a single session:

| File | Agent |
|------|-------|
| `agents/_shared.md` | Shared rules injected into every agent |
| `agents/A0.md` | Company research (Perplexity → Claude two-step) |
| `agents/A1.md` | Job sourcing |
| `agents/A1_4_liveness.md` | Liveness check spec |
| `agents/A2.md` | CV tailoring |
| `agents/A3.md` | Cover letter generation |
| `agents/A4.md` | Submission (auto / assisted / manual) |
| `agents/A5.md` | Interview prep (stage-aware, 9 sections) |
| `agents/A6.md` | Post-interview debrief capture |
| `agents/A7.md` | Rubric/profile maintenance |
| `agents/A8.md` | Inbox watcher (Gmail OAuth) |
| `filters/F1.md` | JD pre-screen |
| `filters/F2.md` | Deep rubric evaluation |

### Voice pack — Layer 2
`voice_pack.md` written from scratch through a live interview session. Dima's writing patterns extracted from LinkedIn posts, then refined through Q&A:
- Confirmed structural moves: situation-first opening, numbers as proof, verdict close, "The question isn't X — it's Y" reframe
- One correction: "negative contrast" pattern was misattributed and removed
- Cover letter opening and close locked (Option A and B respectively)
- 9 dos, 8 don'ts, 4 sentence-level tells, 5 annotated exemplars

### Layer 3 — Decision overrides
`rubric.json` bumped to v0.3:
- "Results rule" elevated to top-level meta-principle
- Case-by-case gates (war-related, labor-exploitation) got 3-tier sub-rules so F2 can score autonomously
- Domain edge cases resolved: crypto-adjacent fintech ✅, fantasy sports/skill games ✅, professional/friendship matching ✅
- Comp range: full range surfaced, no pre-filtering

### Gmail OAuth
`scripts/gmail_auth.py` written — `get_gmail_service()` handles first-run consent, token save, silent refresh. `docs/gmail_oauth_setup.md` with step-by-step instructions. Dependencies added to `pyproject.toml`. Decision logged in `decisions.log`.

### A1.4 Liveness check — built and tested
`orchestrator/liveness.py` — Playwright module, 38/38 tests green:
- Idempotent check via `check_liveness(role)`
- Reason enum: live, http_404, http_5xx, timeout, redirect_to_jobs_home, selector_miss_no_jd_body, selector_miss_no_apply_button
- State machine wired: `liveness_pending` → `f1_pending` (live) or `dead`
- All tests mock Playwright — no network hits
- PR #3 open: [github.com/yarmakdima-dev/jobpilot/pull/3](https://github.com/yarmakdima-dev/jobpilot/pull/3)

### config/profile.yml — populated
First real User Layer file with Dima's actual values:
- Titles: COO, COO, VP Operations, Managing Director, General Manager, Head of Operations, Director of Operations, Chief of Staff
- Warsaw / remote-first / no relocation
- $3K/month floor, ~$200K/year target
- 15+ headcount, scale-ups preferred
- English primary, Polish acceptable

### Backlog + memory
- 19 backlog items ticked off
- `MEMORY.md` created in the JobPilot folder
- `DATA_CONTRACT.md` advanced to v0.5

---

## How We Worked Together

**The pattern:** Dima sent short mobile messages. Claude read context, made decisions, executed, and reported outcomes. No hand-holding required on either side.

Key moments that show the working style:

- **Screen lock:** Dima locked his laptop remotely mid-session for security. Claude confirmed it was done, then kept working through file and shell access — the screen being locked didn't interrupt anything.
- **Stuck code session:** A code session (Claude Code) got stuck waiting for desktop approval. Rather than waiting for Dima to return, Claude switched approach — built A1.4 directly via shell and file tools, delivered the same result without the desktop.
- **Mobile Q&A:** The voice pack interview, Layer 3 decisions, and profile.yml all happened through short mobile exchanges. "B", "Yes", "That's not mine" — Dima gave minimal inputs; Claude extracted maximum signal.
- **Parallel tracks:** While the voice pack session ran interactively, Claude was tracking other completed sessions (agent prompts, preflight check, onboarding docs) and surfacing their outputs without prompting.
- **Decision quality:** Contract conflicts were flagged and resolved (A5 write lane, story_bank.md ownership, A4 pipeline.json authority) rather than silently glossed over.

**Total sessions run today:** ~8 parallel Cowork sessions + 1 code session
**Files created or updated:** 25+
**Tests written and passing:** 38

---

## What's Next

1. Merge PR #3 (A1.4)
2. Implement A1 — job sourcing code (first real agent that puts roles into the pipeline)
3. Implement F1 — JD pre-screen
4. Resolve enforcement mechanism TBD in DATA_CONTRACT (pre-commit vs runtime)

---

*Report generated 2026-04-23. Source for LinkedIn post.*
