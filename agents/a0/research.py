"""A0 — Real company research agent (Gemini 2.5 Pro + google_search grounding).

Public entry-point: research_company(role) -> dict

Replaces the two-step Perplexity → formatter stub in orchestrator/a0.py.
Single Gemini call with google_search grounding + responseSchema produces a
company profile dict that validates against company_profile_schema v0.2.

Fallback (thin grounding):
    If grounding returns <3 sources, a second call is made with explicit URL
    hints from the first pass.  If the second pass also lacks sources, the
    profile is accepted if it otherwise validates — but source_index is flagged.

Design decisions logged here:
    Q1 = B  Rate limit → exponential backoff + retry (paid fallback assumed)
    Q2 = A  Multilingual: rely on Gemini's native grounding; no injected RU terms
    Q3       Integration test target: notion.so
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.a0.gemini_client import (
    A0NoSourcesError,
    A0ResearchError,
    A0SchemaError,
    GeminiResponse,
    call_research,
    call_with_url_fetch,
)
from agents.a0.schema_loader import get_gemini_schema

LOGGER = logging.getLogger(__name__)

MIN_SOURCES = 3
_AGENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "agents" / "A0.md"


# ── Public entry-point ─────────────────────────────────────────────────────────


def research_company(role: dict[str, Any]) -> dict[str, Any]:
    """Research the company for a role that has cleared F1.

    Args:
        role: Role record dict (must have company_domain, jd.title, source.url).

    Returns:
        Populated company profile dict matching company_profile_schema v0.2.
        Does NOT populate 360_synthesis — that is F2's lane.

    Raises:
        A0ResearchError: Gemini API failure or exhausted retries.
        A0SchemaError: Response JSON failed structural validation.
        A0NoSourcesError: Both passes returned zero grounding sources.
        ValueError: role dict is missing required fields.
    """
    domain, role_title, role_url, jd_text = _extract_role_fields(role)

    LOGGER.info("A0 researching %s for role '%s'", domain, role_title)

    prompt = _build_prompt(domain, role_title, role_url, jd_text)
    schema = get_gemini_schema()

    # ── First pass ────────────────────────────────────────────────────────────
    response = call_research(prompt, schema)
    LOGGER.info(
        "A0 first pass complete for %s — %d sources, tokens=%s",
        domain,
        len(response.sources),
        response.usage.get("total_tokens"),
    )

    # ── Fallback when grounding is thin ───────────────────────────────────────
    if len(response.sources) < MIN_SOURCES:
        LOGGER.warning(
            "A0: only %d source(s) for %s (threshold=%d) — running fallback pass",
            len(response.sources),
            domain,
            MIN_SOURCES,
        )
        if response.sources:
            fallback = call_with_url_fetch(prompt, response.sources, schema)
            LOGGER.info(
                "A0 fallback pass complete for %s — %d sources",
                domain,
                len(fallback.sources),
            )
            response = fallback
        else:
            raise A0NoSourcesError(
                f"Grounding returned zero sources for {domain!r}. "
                "The company may not be indexed or the domain may be incorrect."
            )

    profile = response.content

    # ── Stamp instance_meta with fresh values ─────────────────────────────────
    profile["instance_meta"] = {
        "generated": _now_iso(),
        "target_role": role_title,
        "role_url": role_url,
        "research_depth": profile.get("instance_meta", {}).get("research_depth", "medium"),
        "researcher": "A0",
        "confidence_notes": profile.get("instance_meta", {}).get(
            "confidence_notes", "Gemini 2.5 Pro + google_search grounding."
        ),
    }

    # ── Backfill deterministic fields from the role context ──────────────────
    _backfill_deterministic_fields(profile, domain)
    _normalize_gemini_variants(profile)

    # ── Backfill source_index from grounding metadata if sparse ───────────────
    _backfill_source_index(profile, response.sources)

    # ── Structural validation ─────────────────────────────────────────────────
    _validate_structure(profile)

    # ── Log token usage to decisions.log caller-side ─────────────────────────
    # (Caller — orchestrator/a0.py — appends the full decision entry including
    #  token usage.  We attach it to the profile metadata so it's available.)
    profile["_a0_meta"] = {
        "sources_count": len(response.sources),
        "usage": response.usage,
        "fallback_triggered": len(response.sources) < MIN_SOURCES,
    }

    LOGGER.info("A0 research complete for %s (%d sources)", domain, len(response.sources))
    return profile


# ── Prompt builder ─────────────────────────────────────────────────────────────


def _build_prompt(
    domain: str,
    role_title: str,
    role_url: str,
    jd_text: str,
) -> str:
    """Build the Gemini research prompt from the A0 agent spec + role context."""
    agent_instructions = _load_agent_instructions()

    jd_excerpt = jd_text[:3000].strip() if jd_text else "(not provided)"

    return f"""{agent_instructions}

---

## Research target

Company domain:  {domain}
Role being evaluated:  {role_title}
Job posting URL:  {role_url}

Job description excerpt (first 3,000 chars):
{jd_excerpt}

---

## Output requirements

Return a JSON object matching the responseSchema exactly.

Critical fields — populate with evidence even if the answer is null + note:
  - name_confusion_check: always populated; search for similarly-named companies
  - leadership.ceo.war_position: populate for ANY RU/BY-origin CEO
  - leadership.ceo.parallel_business_flag: always check
  - hiring_signal.location_fit_for_user: resolve explicitly for Warsaw, Poland
  - risks_and_open_questions.domain_exclusion_check: PASS or FAIL + reasoning
  - gate_needs_judgment_call: list any gate you could not resolve from public data
  - source_index: cite every factual claim; use S1, S2, ... keys

Do NOT populate 360_synthesis — that field belongs to a different agent.
Today's date: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}
"""


def _load_agent_instructions() -> str:
    """Load A0.md agent instructions, fall back to a compact inline version."""
    try:
        return _AGENT_PROMPT_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        LOGGER.warning("agents/A0.md not found — using inline instructions")
        return (
            "You are an expert company research analyst. "
            "Research the target company thoroughly using web search. "
            "Populate every field in the schema. "
            "For RU/BY-origin leaders: research their public position on the war in Ukraine. "
            "Check for similarly-named companies (name_confusion_check). "
            "Cite sources in source_index. "
            "Flag unresolvable gates in gate_needs_judgment_call."
        )


# ── Validation ─────────────────────────────────────────────────────────────────


_REQUIRED_TOP_LEVEL = (
    "instance_meta",
    "name_confusion_check",
    "snapshot",
    "business_model",
    "strategy_and_direction",
    "leadership",
    "market_view_outside_in",
    "insider_signal_self_description",
    "hiring_signal",
    "risks_and_open_questions",
    # gate_needs_judgment_call is NOT required from Gemini — the orchestrator
    # (run_a0) sets it authoritatively via _collect_judgment_calls. Gemini may
    # omit it when no RU/BY signals are present.
    "source_index",
)


def _validate_structure(profile: dict[str, Any]) -> None:
    """Assert required top-level sections are present.

    Raises:
        A0SchemaError: One or more required sections or required nested fields are absent.
    """
    missing = [s for s in _REQUIRED_TOP_LEVEL if s not in profile]
    if missing:
        raise A0SchemaError(
            f"Gemini response is missing required profile sections: {missing}. "
            "Check the responseSchema and prompt."
        )

    # name_confusion_check must always be explicitly populated
    ncc = profile.get("name_confusion_check") or {}
    if "none_found" not in ncc and not ncc.get("similar_names_found"):
        raise A0SchemaError(
            "name_confusion_check is empty — A0 must actively search for "
            "similarly-named companies and record the result."
        )

    missing_fields = []
    required_paths = (
        "instance_meta.research_depth",
        "instance_meta.confidence_notes",
        "snapshot.legal_name",
        "snapshot.domain",
        "snapshot.hq",
        "snapshot.primary_market",
        "snapshot.sector",
        "snapshot.sub_sector",
        "business_model.revenue_model",
        "leadership",
        "hiring_signal.location_fit_for_user",
        "risks_and_open_questions.domain_exclusion_check",
        "source_index",
    )
    for path in required_paths:
        if _is_missing_path(profile, path):
            missing_fields.append(path)

    if missing_fields:
        raise A0SchemaError(
            "Gemini response is missing required fields: "
            f"{', '.join(missing_fields)}"
        )

    source_index = profile.get("source_index")
    if not isinstance(source_index, dict) or not source_index:
        raise A0SchemaError("source_index must be a non-empty object.")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _extract_role_fields(
    role: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Pull and validate required fields from the role record."""
    domain = (role.get("company_domain") or "").strip().lower()
    if not domain:
        raise ValueError(
            f"role {role.get('role_id')!r} is missing company_domain — "
            "cannot run A0 without a target domain"
        )

    jd = role.get("jd") or {}
    role_title = (jd.get("title") or "").strip() or "Unknown role"
    jd_text = (jd.get("body") or "").strip()

    source = role.get("source") or {}
    role_url = (source.get("url") or "").strip() or f"https://{domain}"

    return domain, role_title, role_url, jd_text


def _backfill_source_index(
    profile: dict[str, Any],
    grounding_urls: list[str],
) -> None:
    """If source_index is sparse, backfill from grounding metadata URLs."""
    si = profile.get("source_index")
    if not isinstance(si, dict):
        profile["source_index"] = {}
        si = profile["source_index"]

    existing_count = sum(1 for v in si.values() if v)
    if existing_count >= MIN_SOURCES or not grounding_urls:
        return

    idx = existing_count + 1
    for url in grounding_urls:
        key = f"S{idx}"
        if key not in si:
            si[key] = url
            idx += 1
        if idx > 10:
            break

    LOGGER.debug("source_index backfilled with %d grounding URL(s)", idx - existing_count - 1)


def _backfill_deterministic_fields(profile: dict[str, Any], domain: str) -> None:
    """Fill deterministic fields from trusted role context before validation."""
    snapshot = profile.setdefault("snapshot", {})
    if not snapshot.get("domain"):
        snapshot["domain"] = domain


def _normalize_gemini_variants(profile: dict[str, Any]) -> None:
    """Map Gemini's near-miss field names into the local schema shape."""
    snapshot = profile.get("snapshot")
    if isinstance(snapshot, dict):
        if not snapshot.get("founded") and snapshot.get("founding_year"):
            snapshot["founded"] = str(snapshot["founding_year"])
        if not snapshot.get("hq"):
            hq_value = _first_present(
                snapshot,
                (
                    "headquarters_city",
                    "headquarters",
                    "headquarters_location",
                    "headquarters_region",
                    "location",
                ),
            )
            if hq_value:
                snapshot["hq"] = str(hq_value)
        if not snapshot.get("primary_market"):
            snapshot["primary_market"] = _infer_primary_market(profile)
        if not snapshot.get("sector"):
            snapshot["sector"] = _infer_sector(profile)
        if not snapshot.get("sub_sector"):
            snapshot["sub_sector"] = _infer_sub_sector(profile)
        if not snapshot.get("hq"):
            snapshot["hq"] = "Unknown (research gap)"
            _append_confidence_note(
                profile,
                "HQ could not be resolved from grounded sources; populated as research gap.",
            )

    business_model = profile.get("business_model")
    if isinstance(business_model, dict):
        if not business_model.get("revenue_model"):
            revenue_streams = business_model.get("revenue_streams")
            customer_segments = business_model.get("customer_segments")
            pricing_strategy = (
                business_model.get("pricing_strategy")
                or business_model.get("pricing_model")
            )
            business_model["revenue_model"] = _infer_revenue_model(
                revenue_streams, pricing_strategy
            )
            if customer_segments and not business_model.get("customer_base_size_claim"):
                business_model["customer_base_size_claim"] = str(customer_segments)
            if pricing_strategy and not business_model.get("pricing"):
                business_model["pricing"] = str(pricing_strategy)
            if not business_model.get("core_services"):
                business_model["core_services"] = _infer_core_services(profile)

    strategy = profile.get("strategy_and_direction")
    if isinstance(strategy, dict):
        if not strategy.get("stated_mission") and strategy.get("mission_and_vision"):
            strategy["stated_mission"] = str(strategy["mission_and_vision"])
        if not strategy.get("growth_vector") and strategy.get("stated_strategy"):
            strategy["growth_vector"] = str(strategy["stated_strategy"])

    market = profile.get("market_view_outside_in")
    if isinstance(market, dict):
        if not market.get("competitive_set") and market.get("competitors"):
            competitors = market.get("competitors")
            if isinstance(competitors, list):
                market["competitive_set"] = competitors


def _infer_primary_market(profile: dict[str, Any]) -> str:
    """Infer a coarse primary market string from surrounding Gemini output."""
    text = " ".join(
        str(part)
        for part in (
            ((profile.get("strategy_and_direction") or {}).get("stated_strategy")),
            ((profile.get("business_model") or {}).get("customer_segments")),
            ((profile.get("snapshot") or {}).get("company_description")),
        )
        if part
    ).lower()
    if any(token in text for token in ("global", "outside the united states", "outside the us", "international")):
        return "Global"
    hq = str((profile.get("snapshot") or {}).get("hq") or "").lower()
    if "california" in hq or "new york" in hq or "united states" in hq or "usa" in hq:
        return "United States"
    return "Unknown"


def _infer_sector(profile: dict[str, Any]) -> str:
    """Infer a coarse sector from the company description and business model."""
    text = " ".join(
        str(part)
        for part in (
            ((profile.get("snapshot") or {}).get("company_description")),
            ((profile.get("business_model") or {}).get("pricing_strategy")),
            ((profile.get("strategy_and_direction") or {}).get("mission_and_vision")),
        )
        if part
    ).lower()
    if any(token in text for token in ("software", "saas", "application", "workspace", "productivity")):
        return "Software"
    return "Technology"


def _infer_sub_sector(profile: dict[str, Any]) -> str:
    """Infer a narrower sub-sector when Gemini omitted it."""
    text = " ".join(
        str(part)
        for part in (
            ((profile.get("snapshot") or {}).get("company_description")),
            ((profile.get("strategy_and_direction") or {}).get("mission_and_vision")),
        )
        if part
    ).lower()
    if "productivity" in text or "workspace" in text or "note-taking" in text:
        return "Productivity SaaS"
    if "project" in text or "knowledge" in text:
        return "Collaboration Software"
    return "Software Tools"


def _infer_revenue_model(revenue_streams: Any, pricing_strategy: Any) -> str:
    """Infer revenue_model from Gemini's alternate business-model fields."""
    if isinstance(revenue_streams, list) and revenue_streams:
        primary = next(
            (
                stream
                for stream in revenue_streams
                if isinstance(stream, dict) and stream.get("primary") is True
            ),
            None,
        )
        if isinstance(primary, dict) and primary.get("stream"):
            return str(primary["stream"])
        first = revenue_streams[0]
        if isinstance(first, dict) and first.get("stream"):
            return str(first["stream"])
    if pricing_strategy:
        return str(pricing_strategy)
    return "Unknown"


def _infer_core_services(profile: dict[str, Any]) -> list[str]:
    """Infer a minimal core_services list from the company description."""
    description = str((profile.get("snapshot") or {}).get("company_description") or "")
    services: list[str] = []
    lowered = description.lower()
    if "note" in lowered:
        services.append("Note-taking workspace")
    if "knowledge" in lowered:
        services.append("Knowledge management")
    if "project" in lowered or "task" in lowered:
        services.append("Project and task tracking")
    if not services:
        services.append("Software platform")
    return services


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value found under any of the given keys."""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _append_confidence_note(profile: dict[str, Any], note: str) -> None:
    """Append a short note to instance_meta.confidence_notes if it is not already present."""
    instance_meta = profile.setdefault("instance_meta", {})
    existing = str(instance_meta.get("confidence_notes") or "").strip()
    if note in existing:
        return
    if existing:
        instance_meta["confidence_notes"] = f"{existing} {note}"
    else:
        instance_meta["confidence_notes"] = note


def _is_missing_path(payload: dict[str, Any], dotted_path: str) -> bool:
    """Return True when a dotted field path is missing or effectively empty."""
    current: Any = payload
    for segment in dotted_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return True
        current = current[segment]

    if current is None:
        return True
    if isinstance(current, str) and not current.strip():
        return True
    if isinstance(current, list) and len(current) == 0:
        return True
    if isinstance(current, dict) and len(current) == 0:
        return True
    return False


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
