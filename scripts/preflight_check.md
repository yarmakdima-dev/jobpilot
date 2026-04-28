# Spec: `scripts/preflight_check.py`

**Version:** 0.1
**Status:** Implemented in `scripts/preflight_check.py`
**Implements:** CLAUDE.md § 3 (Pre-Flight Check) and backlog.md P0.2

---

## Purpose

The preflight check is the gate that runs before any agent is dispatched. It verifies that all required user-layer files exist and are readable. If any required file is missing or unreadable, the orchestrator must not proceed — it enters onboarding mode instead. The script is read-only. It makes no changes to any file.

---

## Inputs

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `repo_root` | positional CLI arg (string, path) | No | Current working directory |

**CLI usage:**

```
python scripts/preflight_check.py [repo_root]
```

If `repo_root` is omitted, default to `os.getcwd()`.

---

## Checks

Run in this exact order. Earlier failures do not stop later checks — run all four and report the full picture.

### Check 1 — `cv.md` present

- **Path:** `{repo_root}/cv.md`
- **Test:** File exists and is a regular file (not a directory, not a symlink to a missing target).
- **Status on pass:** PASS
- **Status on fail:** FAIL (blocking)
- **Action on fail:** Increment fail counter; print failure line; continue to next check.

### Check 2 — `config/profile.yml` present and parseable

- **Path:** `{repo_root}/config/profile.yml`
- **Test 1:** File exists and is a regular file.
- **Test 2:** File can be parsed as valid YAML without error (use PyYAML `yaml.safe_load`). An empty file that parses to `None` is acceptable at this stage — the check is structural, not semantic.
- **Status on pass:** PASS
- **Status on fail (missing):** FAIL (blocking)
- **Status on fail (parse error):** FAIL (blocking); include the YAML error message in the output line.
- **Action on fail:** Increment fail counter; print failure line; continue.

### Check 3 — `rubric.json` present and version field readable

- **Path:** `{repo_root}/rubric.json`
- **Test 1:** File exists and is a regular file.
- **Test 2:** File can be parsed as valid JSON (use `json.load`).
- **Test 3:** Parsed JSON contains a top-level `_meta` key, which contains a `version` key with a non-empty string value.
- **Status on pass:** PASS; include the version string in the output line (e.g., `[PASS] rubric.json — version 0.2`).
- **Status on fail (missing or not parseable):** FAIL (blocking)
- **Status on fail (version field absent or empty):** FAIL (blocking); note which sub-check failed.
- **Action on fail:** Increment fail counter; print failure line; continue.

### Check 4 — `voice_pack.md` present

- **Path:** `{repo_root}/voice_pack.md`
- **Test:** File exists and is a regular file.
- **Status on pass:** PASS
- **Status on fail:** WARN (non-blocking)
- **Action on fail:** Increment warn counter (not fail counter); print warning line; continue.
- **Note:** This check never causes exit 1. Layer 2 output is pending; the file is expected to be absent in early setup.

---

## Output — stdout format

Print one line per check. Use a consistent prefix: `[PASS]`, `[FAIL]`, or `[WARN]`.

Example output (all passing):

```
JobPilot Pre-Flight Check
=========================
[PASS] cv.md — found
[PASS] config/profile.yml — found and parseable
[PASS] rubric.json — found, version 0.2
[PASS] voice_pack.md — found

All checks passed. Pipeline ready.
```

Example output (cv.md missing, voice_pack.md missing):

```
JobPilot Pre-Flight Check
=========================
[FAIL] cv.md — file not found at /path/to/repo/cv.md
[PASS] config/profile.yml — found and parseable
[PASS] rubric.json — found, version 0.2
[WARN] voice_pack.md — file not found (non-blocking; Layer 2 pending)

1 check(s) failed. Enter onboarding mode: see onboarding/ONBOARDING.md
```

Example output (rubric.json parse error):

```
[FAIL] rubric.json — found but JSON parse error: Expecting value: line 3 column 1 (char 5)
```

Example output (rubric version field missing):

```
[FAIL] rubric.json — found and parseable, but version field missing at _meta.version
```

**Summary line rules:**
- If fail counter is 0 and warn counter is 0: `All checks passed. Pipeline ready.`
- If fail counter is 0 and warn counter > 0: `All required checks passed. {n} warning(s). Pipeline ready.`
- If fail counter > 0: `{n} check(s) failed. Enter onboarding mode: see onboarding/ONBOARDING.md`

---

## Exit codes

| Condition | Exit code |
|-----------|-----------|
| All required checks pass (warns OK) | `0` |
| One or more required checks fail | `1` |

---

## Side effects

None. The script is strictly read-only. It does not create, modify, or delete any file. It does not write to `decisions.log`. It does not initialize any agent. It does not mutate state.

---

## Dependencies

Standard library only, plus PyYAML. No other packages.

```python
import sys
import os
import json
import yaml  # PyYAML — already in pyproject.toml or add it
```

If PyYAML is not available, the script must fail with a clear message: `ERROR: PyYAML is required. Install with: pip install pyyaml`

---

## Called by

- **Orchestrator** — at the start of every agent session, before any agent is dispatched. If exit code is 1, the orchestrator enters onboarding mode and stops.
- **Human (manual)** — `python scripts/preflight_check.py` from the repo root, to verify setup before starting a session. Documented in `onboarding/ONBOARDING.md`.

---

## What this script does NOT do

- It does not validate the content of `config/profile.yml` beyond parseability. Semantic validation (required fields, value ranges) is a Phase 1 concern.
- It does not validate the content or schema of `rubric.json` beyond JSON validity and the presence of `_meta.version`.
- It does not check agent prompt files, filter files, templates, or any system-layer files.
- It does not check network access, API keys, or credentials.
- It does not run onboarding — it only signals that onboarding is needed.
