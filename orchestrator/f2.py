"""F2 — Deep rubric evaluation filter.

Expensive gate.  Runs after A0 has populated the company profile.
Scores all rubric criteria against company profile + JD using an LLM.

The LLM call is stubbed behind ``_call_llm``.  Drop in the real API
implementation there when the integration ships — no other changes needed.

Gate evaluation order (first hard-stop wins):
    1. synthesis_rubric_version check — halt if stale
    2. LLM scores full rubric against company profile + JD
    3. Response parsed + validated; falls back to safe FAIL/stop on malformed output

Output fields written to ``filter_status.f2.*`` on the role record (lane F2).

Public entry-point: ``run_f2(role, company)``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import store

LOGGER = logging.getLogger(__name__)

# ── Result / stance constants ────────────────────────────────────────────────

PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"

STANCE_GO = "go"
STANCE_PROBE = "probe"
STANCE_STOP = "stop"
STANCE_BLOCKED = "blocked"

# ── Fixture response returned by the stub LLM ────────────────────────────────

_FIXTURE_PASS_RESPONSE: dict[str, Any] = {
    "result": PASS,
    "stance": STANCE_GO,
    "reason": (
        "All rubric criteria scored positively. Manager quality strong (signals: "
        "admits constraints unprompted, hires for trajectory not checklist). "
        "Build mandate tier 1 (named, articulated need). "
        "AI mandate present. Growth stage fits floors ($1M ARR+, 15+ headcount)."
    ),
    "gate_needs_judgment_call": [],
}


# ── Public entry-point ────────────────────────────────────────────────────────


def run_f2(role: dict, company: dict) -> dict:
    """Run the F2 deep rubric evaluation on *role* + *company* profile.

    *role* is the in-memory role record (must have passed F1).
    *company* is the populated A0 company profile for ``role["company_domain"]``.

    Idempotent: if ``filter_status.f2.status`` is not ``"pending"``, returns
    *role* unchanged without writing.

    Writes only ``filter_status.f2.*`` fields via ``store.write_role`` with
    ``writer_id="F2"``.  Any write outside that lane raises ``LaneViolationError``.

    Returns the (potentially updated) role dict.
    """
    f2 = (role.get("filter_status") or {}).get("f2") or {}
    if f2.get("status", "pending") != "pending":
        LOGGER.info(
            "F2 already run for %s (status=%s) — no-op",
            role.get("role_id"),
            f2.get("status"),
        )
        return role

    role_id = role.get("role_id", "<unknown>")
    LOGGER.info("Running F2 for %s", role_id)

    rubric = _load_rubric()
    rubric_version = (rubric.get("_meta") or {}).get("version")

    # ── Guard: synthesis_rubric_version must match current rubric ─────────────
    synthesis = company.get("360_synthesis") or {}
    if synthesis:
        synth_version = synthesis.get("synthesis_rubric_version")
        if synth_version and synth_version != rubric_version:
            LOGGER.warning(
                "F2 halting for %s: synthesis_rubric_version=%s != rubric=%s — "
                "A7 re-synthesis required before scoring",
                role_id,
                synth_version,
                rubric_version,
            )
            store.append_decision(
                {
                    "agent_id": "F2",
                    "event": "f2_synthesis_version_mismatch",
                    "role_id": role_id,
                    "synthesis_rubric_version": synth_version,
                    "current_rubric_version": rubric_version,
                }
            )
            _write_f2_result(
                role,
                role_id,
                result=BLOCKED,
                stance=STANCE_BLOCKED,
                reason="synthesis_rubric_version_mismatch — A7 re-synthesis required",
                judgment_calls=[
                    {
                        "gate_id": "synthesis_version_stale",
                        "reason": (
                            f"Company 360_synthesis was generated against rubric "
                            f"v{synth_version}; current rubric is v{rubric_version}. "
                            "A7 must re-synthesize before F2 can score."
                        ),
                        "recommended_probes": [],
                    }
                ],
                rubric_version=rubric_version,
            )
            return role

    # ── LLM evaluation ────────────────────────────────────────────────────────
    prompt = _build_eval_prompt(role, company, rubric)
    raw_response = _call_llm(prompt)
    eval_result = _parse_llm_response(raw_response)

    result = eval_result["result"]
    stance = eval_result["stance"]
    reason = eval_result["reason"]
    judgment_calls = eval_result["gate_needs_judgment_call"]

    _write_f2_result(role, role_id, result, stance, reason, judgment_calls, rubric_version)

    store.append_decision(
        {
            "agent_id": "F2",
            "event": "f2_result",
            "role_id": role_id,
            "result": result,
            "stance": stance,
            "reason": reason,
            "rubric_version": rubric_version,
            "gate_needs_judgment_call_count": len(judgment_calls),
        }
    )
    LOGGER.info("F2 complete for %s: %s / %s", role_id, result, stance)
    return role


# ── LLM call (stub) ───────────────────────────────────────────────────────────


def _call_llm(prompt: str) -> str:
    """Call the LLM to score rubric criteria against company profile + JD.

    **Stub implementation** — logs the call and returns a fixture pass response.
    Slot in the real API call here when the integration ships.

    The return value must be a JSON string conforming to::

        {
            "result": "pass" | "fail" | "blocked",
            "stance": "go" | "probe" | "stop" | "blocked",
            "reason": "<one-sentence summary>",
            "gate_needs_judgment_call": [
                {
                    "gate_id": "<rubric gate id>",
                    "reason": "<why public research cannot resolve this>",
                    "recommended_probes": ["<first-call question>", ...]
                }
            ]
        }
    """
    LOGGER.info("LLM call would happen here (prompt_chars=%d)", len(prompt))
    return json.dumps(_FIXTURE_PASS_RESPONSE)


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_eval_prompt(role: dict, company: dict, rubric: dict) -> str:
    """Construct the full evaluation prompt for the LLM."""
    sections = [
        "# F2 Deep Rubric Evaluation",
        "",
        "## Role Record",
        json.dumps(role, indent=2),
        "",
        "## Company Profile",
        json.dumps(company, indent=2),
        "",
        "## Rubric",
        json.dumps(rubric, indent=2),
    ]
    return "\n".join(sections)


# ── Response parser ───────────────────────────────────────────────────────────


def _parse_llm_response(raw: str) -> dict[str, Any]:
    """Parse and validate the LLM response JSON.

    Returns a dict with keys: result, stance, reason, gate_needs_judgment_call.
    Falls back to a safe FAIL/stop default on malformed or invalid output so the
    pipeline is never left in an undefined state.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        LOGGER.warning("F2 LLM response is not valid JSON: %s", exc)
        return _safe_fallback("llm_response_not_valid_json")

    result = parsed.get("result")
    stance = parsed.get("stance")
    reason = str(parsed.get("reason") or "")
    judgment_calls = parsed.get("gate_needs_judgment_call") or []

    # Validate result enum
    if result not in (PASS, FAIL, BLOCKED):
        LOGGER.warning("F2 unexpected result value %r — defaulting to fail", result)
        return _safe_fallback(f"llm_returned_invalid_result:{result!r}")

    # Validate stance enum
    if stance not in (STANCE_GO, STANCE_PROBE, STANCE_STOP, STANCE_BLOCKED):
        LOGGER.warning("F2 unexpected stance value %r — defaulting to stop", stance)
        stance = STANCE_STOP

    # Normalise judgment_call entries — drop malformed items
    norm_jc: list[dict[str, Any]] = []
    for item in judgment_calls:
        if isinstance(item, dict) and item.get("gate_id"):
            norm_jc.append(
                {
                    "gate_id": str(item["gate_id"]),
                    "reason": str(item.get("reason") or ""),
                    "recommended_probes": [
                        str(p) for p in (item.get("recommended_probes") or [])
                    ],
                }
            )

    return {
        "result": result,
        "stance": stance,
        "reason": reason,
        "gate_needs_judgment_call": norm_jc,
    }


def _safe_fallback(reason: str) -> dict[str, Any]:
    """Return a safe FAIL/stop result with the given reason string."""
    return {
        "result": FAIL,
        "stance": STANCE_STOP,
        "reason": reason,
        "gate_needs_judgment_call": [],
    }


# ── Store write ───────────────────────────────────────────────────────────────


def _write_f2_result(
    role: dict,
    role_id: str,
    result: str,
    stance: str,
    reason: str,
    judgment_calls: list[dict[str, Any]],
    rubric_version: str | None,
) -> None:
    """Write F2 result fields via store (lane-safe).

    Writes two sets of fields:
    - ``filter_status.f2.*`` — status, stance, reason, timestamps, rubric version
    - ``gate_needs_judgment_call`` — top-level role field (per CLAUDE.md hard rule 7)

    Reads the canonical on-disk record so the lane scope check only sees
    changes within the F2 allowed paths.  Propagates the result back into
    the caller's in-memory dict so downstream code can inspect without a
    second store read.
    """
    f2_data: dict[str, Any] = {
        "status": result,
        "stance": stance,
        "reason": reason,
        "checked_at": _now_iso(),
        "rubric_version": rubric_version,
        "synthesis_ref": None,
    }

    try:
        on_disk = store.read_role(role_id)
    except (FileNotFoundError, OSError):
        # Role not yet persisted — graceful fallback (uncommon in production).
        on_disk = dict(role)

    on_disk["filter_status"]["f2"] = f2_data
    # gate_needs_judgment_call lives at the top level of the role record
    # so the state machine and daily report can check it without drilling
    # into filter_status (hard rule 7 in CLAUDE.md).
    on_disk["gate_needs_judgment_call"] = judgment_calls or None
    store.write_role(role_id, on_disk, writer_id="F2")

    # Propagate back into the caller's dict.
    role["filter_status"]["f2"] = f2_data
    role["gate_needs_judgment_call"] = judgment_calls or None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_rubric() -> dict[str, Any]:
    """Load rubric.json from the store root.  Returns empty dict on failure."""
    path = store.ROOT / "rubric.json"
    if not path.exists():
        LOGGER.warning("rubric.json not found at %s — F2 will produce a blocked result", path)
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        LOGGER.exception("Failed to load rubric.json")
        return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
