"""A0 — Company Research Agent (orchestrator entry-point).

Delegates real research to agents.a0.research.research_company(), which calls
Gemini 2.5 Pro with google_search grounding + responseSchema.

Stack (locked 2026-04-28):
    Research model:   Gemini 2.5 Pro (gemini-2.5-pro)
    Search:           native google_search grounding
    Schema:           native responseSchema (no two-step formatting)
    Rate limit:       exponential backoff + retry (Q1=B — paid fallback)
    Language:         native Gemini multilingual grounding (Q2=A)

The orchestrator layer handles:
    - Idempotency gate (skip if fresh profile exists)
    - Judgment-call detection and role flagging
    - Schema + lane validation before write
    - Decision log entry (including token usage)

Public entry-point: run_a0(role).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from orchestrator import store

LOGGER = logging.getLogger(__name__)


# ── Public entry-point ────────────────────────────────────────────────────────


def run_a0(role: dict) -> dict:
    """Run the A0 company research agent on a role that has cleared F1.

    Delegates to agents.a0.research.research_company() for the Gemini call.

    Idempotent: returns existing profile unchanged if it exists and
    ``synthesis_stale`` is not True.  Re-researches when stale.

    Writes to ``companies/{domain}.json`` via ``store.write_company()``.
    Sets ``role["gate_needs_judgment_call"]`` when signals are unresolvable.

    Returns the (potentially updated) role dict.
    """
    role_id = role.get("role_id", "<unknown>")
    domain = (role.get("company_domain") or "").strip().lower()

    if not domain:
        raise ValueError(f"role {role_id!r} is missing company_domain")

    LOGGER.info("A0 starting for role %s (domain=%s)", role_id, domain)

    # ── Idempotency gate ──────────────────────────────────────────────────────
    existing = _load_existing(domain)
    if existing is not None:
        if not existing.get("synthesis_stale", False):
            LOGGER.info("A0 no-op: fresh profile already exists for %s", domain)
            return role
        LOGGER.info("A0: stale profile detected for %s — re-researching", domain)

    # ── Delegate to real research backend ─────────────────────────────────────
    # Lazy import keeps the orchestrator decoupled from the agents package;
    # also makes unit-testing orchestrator/a0.py easier to mock.
    from agents.a0.research import research_company  # noqa: PLC0415

    LOGGER.info("A0 calling Gemini research backend for %s", domain)
    profile = research_company(role)

    # ── Pull and remove internal metadata added by research_company ───────────
    a0_meta = profile.pop("_a0_meta", {})

    # ── Judgment-call detection ───────────────────────────────────────────────
    # Authoritative pass: scan the returned profile for gates that Gemini
    # may have missed or under-specified.  Overwrites whatever Gemini put in
    # gate_needs_judgment_call so the orchestrator remains the trust boundary.
    judgment_calls = _collect_judgment_calls(profile)
    profile["gate_needs_judgment_call"] = {
        "blocked": bool(judgment_calls),
        "items": judgment_calls,
    }
    if judgment_calls:
        gate_ids = [item["gate_id"] for item in judgment_calls]
        LOGGER.warning(
            "A0: %d judgment call(s) for %s — gates: %s",
            len(judgment_calls),
            domain,
            gate_ids,
        )
        # Surface on the role so the orchestrator can hold downstream dispatch.
        role["gate_needs_judgment_call"] = judgment_calls

    # ── Validate & write ──────────────────────────────────────────────────────
    _validate_profile(profile)
    store.write_company(domain, profile, writer_id="A0")

    store.append_decision(
        {
            "agent_id": "A0",
            "event": "a0_research_complete",
            "role_id": role_id,
            "domain": domain,
            "judgment_call_count": len(judgment_calls),
            "judgment_call_gates": [item["gate_id"] for item in judgment_calls],
            "sources_count": a0_meta.get("sources_count", 0),
            "fallback_triggered": a0_meta.get("fallback_triggered", False),
            "tokens_used": a0_meta.get("usage", {}).get("total_tokens"),
        }
    )
    LOGGER.info("A0 complete for %s — profile written to companies/%s.json", role_id, domain)
    return role


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_profile(profile: dict) -> None:
    """Validate the company profile before writing.

    Two layers:
        1. JSON Schema check via store (forward-compat; becomes constraining as
           company_profile_schema.json evolves to a proper JSON Schema).
        2. Structural assertion: required top-level sections must be present.

    Raises ValueError on structural failures; jsonschema.ValidationError on
    schema violations.
    """
    # Layer 1 — JSON Schema (currently permissive; included for forward compat)
    store._validate_json_schema(profile, store.COMPANY_SCHEMA_PATH)

    # Layer 2 — required top-level sections
    _REQUIRED_SECTIONS = (
        "instance_meta",
        "name_confusion_check",
        "snapshot",
        "source_index",
        "gate_needs_judgment_call",
    )
    missing = [s for s in _REQUIRED_SECTIONS if s not in profile]
    if missing:
        raise ValueError(
            f"Company profile is missing required sections: {missing}."
        )


# ── Judgment-call detection ───────────────────────────────────────────────────


def _collect_judgment_calls(profile: dict) -> list[dict]:
    """Scan the formatted profile for unresolvable gates.

    Returns a list of judgment-call items (gate_id, reason, signals_pro,
    signals_con, recommended_probes).  De-duplicated by gate_id.

    Triggers:
        - russian_or_belarusian_market_or_business: RU/BY-origin leader with
          silent, null, or not_researched war_position.
        - russian_or_belarusian_market_or_business: Leader with active parallel
          business carrying carve_out_escalation=True.
    """
    items: list[dict] = []
    seen_gates: set[str] = set()
    leadership = profile.get("leadership") or {}

    _LEADER_KEYS = (
        "ceo",
        "co_founders",
        "c_suite",
        "board",
        "advisors_referenced_in_role",
    )

    for leader_key in _LEADER_KEYS:
        raw = leadership.get(leader_key)
        if raw is None:
            continue
        # Normalise: CEO is a single dict; others are lists
        leaders: list[dict] = [raw] if isinstance(raw, dict) else raw
        for leader in leaders:
            if not isinstance(leader, dict):
                continue
            items.extend(_check_leader_war_position(leader, seen_gates))
            items.extend(_check_leader_parallel_business(leader, seen_gates))

    return items


def _is_ru_by_origin(origin: str) -> bool:
    """Return True when the origin string indicates Russia or Belarus."""
    o = origin.strip().lower()
    return o in {
        "russia",
        "ru",
        "russian",
        "belarus",
        "by",
        "belarusian",
        "byelorussia",
    } or "russia" in o or "belarus" in o


def _check_leader_war_position(leader: dict, seen_gates: set) -> list[dict]:
    """Return judgment-call items for RU/BY-origin leaders with unclear war positions."""
    items: list[dict] = []
    gate_id = "russian_or_belarusian_market_or_business"
    if gate_id in seen_gates:
        return items

    origin = (leader.get("origin") or "").strip()
    if not _is_ru_by_origin(origin):
        return items

    war_pos = leader.get("war_position") or {}
    value = (war_pos.get("value") or "").lower().strip()

    # Explicit pro-war is a hard disqualifier — not a judgment call
    if value in ("explicit_pro_war", "accommodative"):
        return items

    # Explicit anti-war clears the gate — no judgment call needed
    if value == "explicit_anti_war":
        return items

    # Silent, not-researched, null, or empty → unresolvable from public research
    if value in ("silent", "not_researched", "") or value is None:
        leader_name = leader.get("name") or "unknown leader"
        is_by = "belarus" in origin.lower() or origin.lower() in ("by", "belarusian")
        items.append(
            {
                "gate_id": gate_id,
                "reason": (
                    f"{leader_name} ({origin} origin) has war_position='{value}'. "
                    f"{'BY-origin silence is context-dependent per rubric asymmetry. ' if is_by else ''}"
                    "Cannot distinguish 'haven't found statements' from 'actively silent' "
                    "without a direct probe."
                ),
                "signals_pro": [],
                "signals_con": [f"{origin}-origin leader; no public anti-war statement found"],
                "recommended_probes": [
                    "Does the company currently serve Russian or Belarusian customers?",
                    "What is your personal position on the war in Ukraine?",
                    "Does the company have any operational infrastructure in Russia or Belarus?",
                ],
            }
        )
        seen_gates.add(gate_id)

    return items


def _check_leader_parallel_business(leader: dict, seen_gates: set) -> list[dict]:
    """Return judgment-call items for leaders with active RU/BY parallel businesses."""
    items: list[dict] = []
    gate_id = "russian_or_belarusian_market_or_business"
    if gate_id in seen_gates:
        return items

    pb = leader.get("parallel_business_flag") or {}
    for biz in pb.get("businesses") or []:
        if not isinstance(biz, dict):
            continue
        if biz.get("active") and biz.get("carve_out_escalation"):
            jur = biz.get("jurisdiction") or "unknown"
            leader_name = leader.get("name") or "unknown leader"
            items.append(
                {
                    "gate_id": gate_id,
                    "reason": (
                        f"{leader_name} has an active parallel business in {jur} "
                        f"({biz.get('name', 'unnamed')}, role: {biz.get('role', 'unknown')}). "
                        "Probe: structural separation, data/PHI overlap, and dependence of "
                        "primary business on the parallel operation."
                    ),
                    "signals_pro": [],
                    "signals_con": [f"Active {jur} parallel business"],
                    "recommended_probes": [
                        "What is the structural separation between the two businesses?",
                        "Is there any data, infrastructure, or PHI overlap?",
                        "Does this company's operations depend on the parallel business?",
                    ],
                }
            )
            seen_gates.add(gate_id)
            break  # one item per gate_id

    return items


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_existing(domain: str) -> dict | None:
    """Load an existing company profile for *domain*, or return None."""
    try:
        return store.read_company(domain)
    except (FileNotFoundError, OSError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
