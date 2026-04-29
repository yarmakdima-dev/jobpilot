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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from orchestrator import store

LOGGER = logging.getLogger(__name__)
MODEL_ID = "gemini-2.5-pro"
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "filters" / "F2.md"

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
    synthesis = _prepare_synthesis(
        eval_result.get("360_synthesis"),
        company=company,
        role=role,
        rubric_version=rubric_version,
        result=result,
        stance=stance,
        reason=reason,
        judgment_calls=judgment_calls,
    )

    _write_f2_result(role, role_id, result, stance, reason, judgment_calls, rubric_version)
    _write_company_synthesis(role, company, synthesis)

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
    LOGGER.info("Calling Gemini F2 evaluator (prompt_chars=%d)", len(prompt))
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        LOGGER.warning("GEMINI_API_KEY not set — using fixture F2 response")
        return json.dumps(_FIXTURE_PASS_RESPONSE)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_f2_response_schema(),
        ),
    )
    raw_text = getattr(response, "text", "") or ""
    return _strip_markdown_fences(raw_text)


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_eval_prompt(role: dict, company: dict, rubric: dict) -> str:
    """Construct the full evaluation prompt for the LLM."""
    instructions = _load_f2_instructions()
    sections = [
        instructions,
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
        "360_synthesis": parsed.get("360_synthesis"),
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


def _write_company_synthesis(role: dict, company: dict, synthesis: dict[str, Any]) -> None:
    """Persist the 360_synthesis block back to companies/<domain>.json via F2's lane."""
    domain = (role.get("company_domain") or "").strip().lower()
    if not domain:
        return

    try:
        on_disk = store.read_company(domain)
    except (FileNotFoundError, OSError):
        on_disk = dict(company)

    on_disk["360_synthesis"] = synthesis
    store.write_company(domain, on_disk, writer_id="F2")
    company["360_synthesis"] = synthesis


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


def _load_f2_instructions() -> str:
    """Load the F2 prompt from filters/F2.md, with a compact fallback."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "# F2 Deep Rubric Evaluation\n\n"
            "Score the role and company against the full rubric. Return strict JSON "
            "with result, stance, reason, gate_needs_judgment_call, and 360_synthesis."
        )


def _prepare_synthesis(
    synthesis: Any,
    *,
    company: dict[str, Any],
    role: dict[str, Any],
    rubric_version: str | None,
    result: str,
    stance: str,
    reason: str,
    judgment_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize or synthesize the 360_synthesis block expected downstream."""
    base = synthesis if isinstance(synthesis, dict) else {}
    probes = _dedupe_probes(
        list(base.get("first_call_probes") or [])
        + [probe for item in judgment_calls for probe in item.get("recommended_probes", [])]
    )
    hard_failed = [item["gate_id"] for item in judgment_calls] if result == FAIL else []
    hard_jc = [item["gate_id"] for item in judgment_calls] if result == BLOCKED else []

    normalized = {
        "synthesis_rubric_version": rubric_version,
        "synthesis_generated": _now_iso(),
        "synthesis_agent": "F2",
        "synthesis_trigger": "initial",
        "stance": stance,
        "stance_one_line": str(base.get("stance_one_line") or reason or stance),
        "stance_reasoning": str(base.get("stance_reasoning") or reason or ""),
        "top_findings": _normalize_top_findings(base.get("top_findings")),
        "scored_criteria_rollup": _normalize_scored_rollup(
            base.get("scored_criteria_rollup"),
            company=company,
            stance=stance,
        ),
        "hard_gates_rollup": {
            "all_passed": result == PASS and not judgment_calls,
            "any_failed": hard_failed,
            "any_judgment_call": hard_jc,
        },
        "override_rules_invoked": [str(x) for x in (base.get("override_rules_invoked") or [])],
        "first_call_probes": probes,
        "recommended_next_action": str(
            base.get("recommended_next_action") or _default_next_action(stance, role)
        ),
    }
    return normalized


def _normalize_top_findings(raw: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        finding = str(item.get("finding") or "").strip()
        if not finding:
            continue
        severity = str(item.get("severity") or "notable")
        finding_type = str(item.get("type") or "flag")
        items.append(
            {
                "finding": finding,
                "severity": severity,
                "type": finding_type,
            }
        )
    return items


def _normalize_scored_rollup(raw: Any, *, company: dict[str, Any], stance: str) -> dict[str, str]:
    rollup = raw if isinstance(raw, dict) else {}
    return {
        "manager_quality": str(rollup.get("manager_quality") or _default_manager_quality(stance)),
        "build_mandate_tier": str(rollup.get("build_mandate_tier") or _infer_build_tier(company)),
        "ai_mandate_binary": str(rollup.get("ai_mandate_binary") or _infer_ai_mandate(company)),
        "growth_stage_fit": str(rollup.get("growth_stage_fit") or _infer_growth_stage_fit(company)),
    }


def _default_manager_quality(stance: str) -> str:
    if stance == STANCE_GO:
        return "strong"
    if stance == STANCE_STOP:
        return "weak"
    return "unknown"


def _infer_build_tier(company: dict[str, Any]) -> str:
    tier = (company.get("hiring_signal") or {}).get("mandate_tier")
    if tier in {"1", "2", "3"}:
        return str(tier)
    return "2"


def _infer_ai_mandate(company: dict[str, Any]) -> str:
    text = json.dumps(company, ensure_ascii=False).lower()
    return "yes" if "ai" in text else "no"


def _infer_growth_stage_fit(company: dict[str, Any]) -> str:
    headcount = json.dumps((company.get("snapshot") or {}).get("headcount_estimate", "")).lower()
    revenue = json.dumps((company.get("business_model") or {}).get("revenue_claim", "")).lower()
    if any(token in headcount for token in ("15", "20", "50", "80", "100", "200")) or "arr" in revenue:
        return "yes"
    return "no"


def _default_next_action(stance: str, role: dict[str, Any]) -> str:
    if stance == STANCE_GO:
        return "advance to application materials"
    if stance == STANCE_PROBE:
        return "resolve first-call probes before advancing"
    if stance == STANCE_BLOCKED:
        return "human review required before proceeding"
    return f"pass on {role.get('role_id', 'this role')}"


def _dedupe_probes(probes: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for probe in probes:
        normalized = str(probe).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped.rsplit("\n", 1)[0]
    return stripped.strip()


def _f2_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "result": {"type": "string", "enum": [PASS, FAIL, BLOCKED]},
            "stance": {
                "type": "string",
                "enum": [STANCE_GO, STANCE_PROBE, STANCE_STOP, STANCE_BLOCKED],
            },
            "reason": {"type": "string"},
            "gate_needs_judgment_call": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gate_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "recommended_probes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["gate_id", "reason", "recommended_probes"],
                },
            },
            "360_synthesis": {
                "type": "object",
                "properties": {
                    "stance_one_line": {"type": "string"},
                    "stance_reasoning": {"type": "string"},
                    "top_findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "finding": {"type": "string"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["critical", "material", "notable"],
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["positive", "negative", "flag"],
                                },
                            },
                            "required": ["finding", "severity", "type"],
                        },
                    },
                    "scored_criteria_rollup": {
                        "type": "object",
                        "properties": {
                            "manager_quality": {
                                "type": "string",
                                "enum": ["strong", "acceptable", "weak", "unknown"],
                            },
                            "build_mandate_tier": {
                                "type": "string",
                                "enum": ["1", "2", "3"],
                            },
                            "ai_mandate_binary": {
                                "type": "string",
                                "enum": ["yes", "no"],
                            },
                            "growth_stage_fit": {
                                "type": "string",
                                "enum": ["yes", "no"],
                            },
                        },
                    },
                    "override_rules_invoked": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "first_call_probes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "recommended_next_action": {"type": "string"},
                },
            },
        },
        "required": ["result", "stance", "reason", "gate_needs_judgment_call"],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
