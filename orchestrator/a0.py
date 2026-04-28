"""A0 — Company Research Agent.

Two-step pipeline:

    Step 1 — _research(domain, role_title, jd_text) -> str
        Calls Perplexity Research API to gather raw company intelligence.
        In stub mode: logs intent and returns a plausible fixture response.

    Step 2 — _format_to_schema(raw_research, schema) -> dict
        Calls Claude/GPT-4 to format raw research into schema-compliant JSON.
        In stub mode: returns a minimal but valid company profile dict.

The agent validates output against company_profile_schema.json, writes to
companies/{domain}.json via store.write_company(), and populates
gate_needs_judgment_call on the role when unresolvable signals are found.

Idempotent: returns existing profile if fresh; re-runs when synthesis_stale=True.

Public entry-point: run_a0(role).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from orchestrator import store

LOGGER = logging.getLogger(__name__)

# ── Fixture: raw research text returned by the Perplexity stub ───────────────

_FIXTURE_RAW_RESEARCH = """\
COMPANY RESEARCH REPORT — ACME CORPORATION (acme.com)

OVERVIEW
Acme Corporation is a B2B SaaS company founded in 2018 and headquartered in New York, USA.
The company provides enterprise operations management software used by 500+ enterprise customers
across North America and Europe. Revenue is reported at $20M ARR (self-reported, 2025).
Funding: $30M Series C closed Q4 2025 (lead: Sequoia Capital).

LEADERSHIP
CEO & Co-founder: Jane Smith (origin: United States; base: New York, USA).
Prior: Senior PM at Google (2014–2018), two prior startup exits (both acquired).
Public voice: active on LinkedIn, pragmatic and direct tone, no war-adjacent public positions
(N/A — non-RU/BY origin). No parallel businesses detected.

BUSINESS MODEL
SaaS subscription; pricing $500–5,000/month per seat. Core services: operations automation,
workflow management, reporting dashboards. Structure: C-Corp, Delaware. Customer satisfaction:
4.5/5 on G2 (as of 2025).

STRATEGY
Mission: Automate enterprise operations. Growth vector: enterprise expansion + AI features.
Recent move: 2025-Q4 raised $30M Series C. Strategic bet: AI-powered automation.
TAM claim: $50B (self-reported).

MARKET
Competitive set: Asana, Monday.com, Notion. Low regulatory exposure. Macro tailwinds:
AI adoption in enterprise; post-COVID operational complexity. Headwinds: market saturation
in project management tools.

HIRING SIGNAL
Role: COO / VP Operations. Hybrid policy (Warsaw or New York). Warsaw-compatible confirmed.
Greenfield mandate. Direct CEO report. Comp: not stated in JD. Mandate tier: 1 (diagnosed need).

RISKS
Regulatory risk: low (standard SaaS). Litigation risk: low (no active cases found).
Domain exclusion check: PASS — B2B SaaS; no gambling, dating, crypto, adult content,
tobacco/alcohol, or MLM patterns detected.

SOURCES
S1: https://acme.com/about
S2: https://linkedin.com/company/acme
S3: https://techcrunch.com/2025/10/01/acme-raises-series-c
"""

# ── Fixture: minimal but valid company profile returned by the formatter stub ─

_FIXTURE_COMPANY_PROFILE: dict[str, Any] = {
    "instance_meta": {
        "generated": "2026-04-24T00:00:00Z",
        "target_role": "COO",
        "role_url": "https://example.com/jobs",
        "research_depth": "light",
        "researcher": "A0",
        "confidence_notes": "Fixture data from stub — not real research.",
    },
    "name_confusion_check": {
        "none_found": True,
        "similar_names_found": [],
    },
    "snapshot": {
        "legal_name": "Acme Corporation",
        "dba": None,
        "domain": "acme.com",
        "secondary_domains": [],
        "founded": "2018",
        "hq": "New York, USA",
        "primary_market": "USA",
        "sector": "B2B SaaS",
        "sub_sector": "Operations tooling",
        "headcount_estimate": "200-500 (2026 estimate)",
        "funding_stage": "Series C",
        "profitability_claim": "Near profitability (self-reported, 2025)",
    },
    "business_model": {
        "revenue_model": "SaaS subscription",
        "pricing": "$500-5000/month per seat",
        "core_services": ["Operations automation", "Workflow management"],
        "structure": "C-Corp, Delaware",
        "customer_base_size_claim": "500+ enterprise customers (self-reported)",
        "revenue_claim": "$20M ARR (self-reported, 2025)",
        "customer_satisfaction_signals": "4.5/5 on G2 (as of 2025)",
    },
    "strategy_and_direction": {
        "stated_mission": "Automate enterprise operations",
        "growth_vector": "Enterprise expansion and AI features",
        "recent_moves": ["2025-Q4: Raised $30M Series C"],
        "strategic_bets": ["AI-powered automation"],
        "tam_claim": "$50B (self-reported)",
    },
    "leadership": {
        "ceo": {
            "name": "Jane Smith",
            "title": "CEO & Co-founder",
            "origin": "United States",
            "current_base": "New York, USA",
            "background": "Ex-Google PM; 2 prior startup exits",
            "public_voice_signal": "Active on LinkedIn; pragmatic, direct tone",
            "war_position": {
                "applies": False,
                "value": None,
                "evidence": "N/A — non-RU/BY origin",
                "research_scope": "N/A",
                "confidence": "high",
            },
            "parallel_business_flag": {
                "present": False,
                "businesses": [],
            },
            "concentration_risk_notes": "CEO is primary public voice; key-person risk manageable.",
        },
        "co_founders": [],
        "c_suite": [],
        "board": [],
        "advisors_referenced_in_role": [],
        "leadership_pattern_observations": ["Founder-led; hiring for operational depth"],
    },
    "market_view_outside_in": {
        "competitive_set": ["Asana", "Monday.com", "Notion"],
        "market_regulatory_context": "Low regulatory exposure; standard SaaS compliance",
        "macro_tailwinds": ["AI adoption in enterprise"],
        "macro_headwinds": ["Market saturation in project management tools"],
    },
    "insider_signal_self_description": {
        "jd_language_excerpts": ["Build the ops function from scratch"],
        "ceo_recent_public_voice": ["2025-09: 'We need to rebuild ops at scale'"],
        "dissonance_flags": [],
    },
    "hiring_signal": {
        "role_seniority": "VP / C-suite equivalent",
        "comp_range": "Not stated in JD",
        "location_policy": "Hybrid (Warsaw or New York)",
        "location_fit_for_user": "Warsaw-compatible — hybrid policy confirmed",
        "mandate_tier": "1",
        "hand_off_test_status": "unknown — test in call",
        "red_flags_in_jd": [],
        "green_flags_in_jd": ["Greenfield mandate", "Direct CEO report"],
    },
    "risks_and_open_questions": {
        "regulatory_risk": {
            "level": "low",
            "notes": "Standard SaaS; no regulated sector.",
        },
        "litigation_risk": {
            "level": "low",
            "active_cases": [],
        },
        "governance_flags": [],
        "domain_exclusion_check": "PASS — B2B SaaS; no excluded domain patterns detected.",
    },
    "gate_needs_judgment_call": {
        "blocked": False,
        "items": [],
    },
    "source_index": {
        "S1": "https://acme.com/about",
        "S2": "https://linkedin.com/company/acme",
        "S3": "https://techcrunch.com/2025/10/01/acme-raises-series-c",
    },
}


# ── Public entry-point ────────────────────────────────────────────────────────


def run_a0(role: dict) -> dict:
    """Run the A0 company research agent on a role that has cleared F1.

    Two-step pipeline:
        1. _research() — Perplexity Research API (stubbed).
        2. _format_to_schema() — Claude/GPT-4 formatting (stubbed).

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

    jd_text: str = (role.get("jd") or {}).get("body") or ""
    role_title: str = (role.get("jd") or {}).get("title") or ""
    role_url: str = (role.get("source") or {}).get("url") or ""

    # ── Step 1: raw research (Perplexity) ─────────────────────────────────────
    LOGGER.info("A0 Step 1 — raw research for %s", domain)
    raw_research = _research(domain, role_title, jd_text)

    # ── Step 2: format to schema (Claude / GPT-4) ─────────────────────────────
    LOGGER.info("A0 Step 2 — formatting research to schema for %s", domain)
    schema = _load_company_schema()
    profile = _format_to_schema(raw_research, schema)

    # Override instance_meta with fresh values
    profile["instance_meta"] = {
        "generated": _now_iso(),
        "target_role": role_title,
        "role_url": role_url,
        "research_depth": profile.get("instance_meta", {}).get("research_depth", "light"),
        "researcher": "A0",
        "confidence_notes": (
            profile.get("instance_meta", {}).get("confidence_notes", "")
            or "Stub data — real research pending Perplexity + formatter integration."
        ),
    }

    # ── Judgment-call detection ───────────────────────────────────────────────
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
        }
    )
    LOGGER.info("A0 complete for %s — profile written to companies/%s.json", role_id, domain)
    return role


# ── Step 1 — raw research ─────────────────────────────────────────────────────


def _research(domain: str, role_title: str, jd_text: str) -> str:
    """Build the research prompt and call Perplexity Research API.

    Returns the raw research text for Step 2.
    """
    prompt = (
        f"Research the company at domain '{domain}'. "
        f"We are evaluating a '{role_title}' role.\n\n"
        f"Populate: company snapshot, business model, strategy, leadership "
        f"(including war_position for any RU/BY-origin leaders; "
        f"parallel business flags for all leaders), market context, "
        f"hiring signals, risks, and open questions.\n\n"
        f"Job description excerpt:\n{jd_text[:2000]}\n\n"
        f"Check for similarly-named companies that could contaminate research "
        f"(name_confusion_check). Build a source_index with IDs for every claim."
    )
    return _call_perplexity(prompt)


def _call_perplexity(prompt: str) -> str:  # pragma: no cover (stub)
    """Call Perplexity Research API.

    STUB — logs intent and returns a plausible fixture response.
    Replace with real API call when Perplexity integration is wired in.
    """
    LOGGER.info(
        "[STUB] Perplexity call would happen here. Prompt length: %d chars. "
        "Returning fixture response.",
        len(prompt),
    )
    return _FIXTURE_RAW_RESEARCH


# ── Step 2 — schema formatting ────────────────────────────────────────────────


def _format_to_schema(raw_research: str, schema: dict) -> dict:
    """Pass raw research to Claude/GPT-4 to format into schema-compliant JSON.

    Raises ValueError if the model returns unparseable or non-object JSON.
    """
    prompt = (
        "Format the following research into valid JSON conforming to this schema. "
        "Populate every field. Where data is unavailable, use null with a "
        "confidence_notes entry — do not omit fields. "
        "Do NOT populate the 360_synthesis block — that belongs to F2.\n\n"
        f"Schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Research:\n{raw_research}"
    )
    raw_json = _call_formatter(prompt)
    try:
        profile = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Formatter returned unparseable JSON: {exc}") from exc
    if not isinstance(profile, dict):
        raise ValueError(
            f"Formatter must return a JSON object; got {type(profile).__name__}"
        )
    return profile


def _call_formatter(prompt: str) -> str:  # pragma: no cover (stub)
    """Call Claude/GPT-4 to format raw research into schema JSON.

    STUB — logs intent and returns a minimal but valid fixture JSON string.
    Replace with real LLM call when the formatter is wired in.
    """
    LOGGER.info(
        "[STUB] Formatter (Claude/GPT-4) call would happen here. "
        "Prompt length: %d chars. Returning fixture profile.",
        len(prompt),
    )
    return json.dumps(_FIXTURE_COMPANY_PROFILE)


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_profile(profile: dict) -> None:
    """Validate the company profile before writing.

    Two layers:
        1. JSON Schema check via store (will become constraining as the schema
           evolves to a proper JSON Schema definition).
        2. Structural assertion: required top-level sections must be present.

    Raises ValueError on structural failures; jsonschema.ValidationError on
    schema violations.
    """
    # Layer 1 — JSON Schema (currently non-constraining; included for forward compat)
    store._validate_json_schema(profile, store.COMPANY_SCHEMA_PATH)

    # Layer 2 — required top-level sections
    _REQUIRED_SECTIONS = (
        "instance_meta",
        "snapshot",
        "source_index",
        "gate_needs_judgment_call",
    )
    missing = [s for s in _REQUIRED_SECTIONS if s not in profile]
    if missing:
        raise ValueError(
            f"Company profile is missing required sections: {missing}. "
            "The formatter must populate all schema sections."
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


def _load_company_schema() -> dict:
    """Load company_profile_schema.json from the store root."""
    path = store.ROOT / "company_profile_schema.json"
    if not path.exists():
        LOGGER.warning("company_profile_schema.json not found at %s", path)
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
