# JobPilot — First-Time Setup

**Triggered when:** `scripts/preflight_check.py` exits with code 1.

The preflight check told you something is missing. This document walks you through exactly what's needed and nothing more. If you already have a file in place and preflight still fails, the relevant section tells you what it checks so you can diagnose the gap.

---

## How this works

Preflight checks four files. If any of the first three are absent or broken, it stops everything and points here. The fourth (`voice_pack.md`) only produces a warning — it won't block you.

This document covers all four. If preflight only flagged one or two, you don't need to read the rest.

---

## 1. `cv.md`

**What preflight checks:** file exists at the repo root. Nothing else — it doesn't read the content.

**Where it goes:** `cv.md` at the repo root (same folder as `CLAUDE.md`, `rubric.json`, etc.).

**Format:** plain Markdown.

**Structure:** no rigid template. What the downstream agents (A2 for CV tailoring, A3 for cover letters) need from your CV is:

- Role headings (company name, title, dates)
- Bullet points under each role covering what you owned, what you changed, and what the measurable outcome was
- A summary or positioning statement at the top (optional but useful)

Keep it in the format you'd actually send to a recruiter. A2 tailors from it; it doesn't reformat it from scratch. If your CV is already in a clean text or Markdown format, paste it in.

**What not to do:** don't try to structure it as JSON or YAML. Markdown or plain prose only. The agents read it as text.

**This file is human-only.** No agent writes to it, ever.

---

## 2. `config/profile.yml`

**What preflight checks:** file exists at `config/profile.yml` and is valid YAML (parseable without error).

**Where it goes:** `config/profile.yml`.

Complete template below. Fill in your values, delete the comments when you're done. Required fields are marked `# REQUIRED`.

```yaml
# JobPilot — Personal Profile
# Human-only user-layer file. No agent writes to this.
# Version: 0.1

identity:
  name: Dima  # REQUIRED
  email: yarmakdima@gmail.com  # REQUIRED — used by A4 for submission metadata
  location: Warsaw, Poland  # REQUIRED — used by F1 for relocation gate

compensation:
  floor_monthly_net_usd: 3000  # REQUIRED — hard floor; no flex for equity, learning, or runway
  target_annual_usd: 200000    # REQUIRED — total comp target across all forms

# Domains that are hard no. Roles in these sectors are rejected at F1.
# These match the rubric hard gates exactly. Do not remove any.
excluded_domains:
  - gambling
  - dating_romantic
  - tobacco_alcohol_vaping_cannabis
  - adult_content
  - crypto_speculative
  - mlm

# Domains that are case-by-case. F2 will flag and escalate, not auto-reject.
case_by_case_domains:
  - war_related
  - labor_exploitation

# Relocation
relocation:
  ok: false                        # Full relocation from Warsaw — hard no
  travel_ok: true                  # Occasional travel (up to ~1 week) — fine
  travel_max_days_per_trip: 7

# Submission channels approved for auto-submit (A4). Leave empty until you've
# explicitly decided to authorize a channel. Each entry is a channel identifier
# (e.g., "email_direct", "ashbyhq", etc.). Authorization is yours to set; no
# agent adds to this list.
preferred_channels: []

# How A8 (inbox watcher) should access your email.
# Options: oauth_gmail | oauth_outlook | imap | forwarding_rule | TBD
inbox_access_method: TBD
```

Save the file. Run `python scripts/preflight_check.py` — if it parses, check 2 passes.

**Common parse failure:** trailing tabs, mixed indentation (YAML uses spaces only), or a colon inside a value without quotes. If preflight reports a parse error, it will include the line number. Fix it there.

---

## 3. `rubric.json`

**What preflight checks:** file exists, parses as valid JSON, and has a non-empty `_meta.version` string.

**What to do:** the rubric is already in the repo as `rubric.json`. If it's there, preflight should pass this check automatically. The current version is `0.2`.

If preflight is failing on this check, the most likely causes:

- `rubric.json` was accidentally deleted or moved. Restore it from version control.
- The file was edited and the JSON is now malformed. Run `python -m json.tool rubric.json` in the terminal to see the parse error.
- The `_meta.version` field was removed. It needs to exist: `"_meta": { "version": "0.2", ... }`.

**Do not edit `rubric.json` to fix a parse error by hand unless you're comfortable with JSON.** Ask for help with the specific error instead.

**On rubric versioning:** the system is designed around a versioned rubric. When you bump the version (e.g., from `0.2` to `0.3`), all company synthesis caches are invalidated and re-run. This is intentional. The version string in `_meta.version` is what triggers it — don't remove it or leave it empty.

For the moment, the rubric file is both the versioned artifact (`rubric_v0_2.json` in the session notes) and the live working file (`rubric.json`). The orchestrator reads `rubric.json`. Keep the versioned filename around as a snapshot if you want a reference, but `rubric.json` is what matters for the pipeline.

---

## 4. `voice_pack.md`

**What preflight checks:** file exists at the repo root. This is a warning-only check — preflight passes even if this file is missing. The pipeline runs without it.

**What it is:** a set of voice constraints that govern tone across all agent outputs — CV tailoring (A2), cover letters (A3), and interview prep (A5). It's the Layer 2 output, meaning it comes out of a dedicated session focused on your communication style, exemplars, and anti-patterns.

**Status:** pending. Layer 2 hasn't run yet.

**For now:** you can create a stub that satisfies the check without doing the full Layer 2 session. The stub doesn't need to be complete — it just needs to exist.

Stub template:

```markdown
# voice_pack.md — Stub

**Status:** Stub. Full voice pack pending Layer 2 session.

## Known constraints (from preferences and rubric session)

- Direct. No hand-holding.
- First-person, active voice. No passive constructions ("was responsible for").
- No "passionate about," no "results-driven," no "dynamic."
- No bullet lists in cover letters — prose only, specific and concrete.
- Reflective, not self-promotional. The work speaks; you name what you learned.
- Honest about constraints. Don't oversell mandates you don't have.

## Anti-patterns

- Opening sentences that restate the job title back at the reader.
- Fluffy openers: "I am excited to apply for..."
- Vague impact claims without numbers or context.
```

Save this to `voice_pack.md` at the repo root. Preflight warning goes away. When Layer 2 runs, replace the stub with the full pack.

---

## 5. Verification

Once you've set up the missing files, run:

```
python scripts/preflight_check.py
```

From the repo root. You should see:

```
JobPilot Pre-Flight Check
=========================
[PASS] cv.md — found
[PASS] config/profile.yml — found and parseable
[PASS] rubric.json — found, version 0.2
[PASS] voice_pack.md — found

All checks passed. Pipeline ready.
```

Or, if `voice_pack.md` is still missing:

```
All required checks passed. 1 warning(s). Pipeline ready.
```

Either output means the pipeline can start. `1 warning(s)` on `voice_pack.md` is expected and not a problem.

If any `[FAIL]` lines remain, the preflight output will tell you exactly which file and what failed. Fix that specific thing and re-run.
