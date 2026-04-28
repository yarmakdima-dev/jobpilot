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
    "gate_needs_judgment_call",
    "source_index",
)


def _validate_structure(profile: dict[str, Any]) -> None:
    """Assert required top-level sections are present.

    Raises:
        ValueError: One or more required sections are absent.
    """
    missing = [s for s in _REQUIRED_TOP_LEVEL if s not in profile]
    if missing:
        raise ValueError(
            f"Gemini response is missing required profile sections: {missing}. "
            "Check the responseSchema and prompt."
        )

    # name_confusion_check must always be explicitly populated
    ncc = profile.get("name_confusion_check") or {}
    if "none_found" not in ncc and not ncc.get("similar_names_found"):
        raise ValueError(
            "name_confusion_check is empty — A0 must actively search for "
            "similarly-named companies and record the result."
        )

    # gate_needs_judgment_call must have both fields
    gnj = profile.get("gate_needs_judgment_call") or {}
    if "blocked" not in gnj or "items" not in gnj:
        raise ValueError(
            "gate_needs_judgment_call must contain 'blocked' and 'items' fields."
        )


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


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
