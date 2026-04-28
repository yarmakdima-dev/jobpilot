"""F1 — JD pre-screen filter.

Cheap, fast gate.  Applies hard exclusions only — no company research,
no rubric scoring.  Gate order (first to fire wins):

    a. Missing JD text            → fail: no_jd_text
    b. Location incompatibility   → fail | near_miss
    c. Domain exclusions          → fail
    d. Compensation below floor   → fail   (pass + note if unstated)
    e. Seniority below floor      → fail

Public entry-point: ``run_f1(role)``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import store

LOGGER = logging.getLogger(__name__)

# ── Result constants ────────────────────────────────────────────────────────
PASS = "pass"
FAIL = "fail"
NEAR_MISS = "near_miss"

# Compensation floor: monthly net USD — mirrors rubric.json compensation_floor gate
COMP_FLOOR_MONTHLY_USD = 3_000

# ── Location: geographic qualifiers that imply non-Warsaw residency ─────────
# When combined with "remote" or "hybrid", these trigger a near-miss.
_REMOTE_NEAR_MISS_QUALIFIERS: tuple[str, ...] = (
    r"\busa\b",
    r"\bus\s+only\b",
    r"\bunited\s+states\b",
    r"\bnorth\s+america\b",
    r"\buk\b",
    r"\bunited\s+kingdom\b",
    r"\baustralia\b",
    r"\bcanada\b",
    r"\bindia\b",
    r"\bsingapore\b",
    r"\bjapan\b",
    r"\bchina\b",
    r"\bgermany\b",
    r"\bfrance\b",
    r"\bspain\b",
    r"\bnetherlands\b",
    r"\bsweden\b",
    r"\bdenmark\b",
    r"\bfinland\b",
    r"\bswitzerland\b",
    r"\baustria\b",
    r"\bbrazil\b",
    r"\bmexico\b",
    r"\bisrael\b",
    r"\bnew\s+york\b",
    r"\blos\s+angeles\b",
    r"\bsan\s+francisco\b",
    r"\bseattle\b",
)

# European/global tags — remote with these qualifiers is Warsaw-compatible
_EUROPE_PASS_QUALIFIERS: tuple[str, ...] = (
    r"\beurope\b",
    r"\beuropean\b",
    r"\beu\b",
    r"\bemea\b",
    r"\bcet\b",
    r"\bcest\b",
    r"\beast.*europe\b",
    r"\bworldwide\b",
    r"\bglobal\b",
    r"\banywhere\b",
    r"\binternational\b",
)

# ── Domain exclusions: (rubric gate_id, keyword patterns) ───────────────────
_DOMAIN_EXCLUSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "excluded_domain_gambling",
        (
            r"\bcasino\b",
            r"\bgambling\b",
            r"\bonline\s+betting\b",
            r"\bsportsbook\b",
            r"\bsports\s+betting\b",
            r"\bigaming\b",
            r"\bi-gaming\b",
            r"\bbookmaker\b",
            r"\blottery\b",
            r"\bslot\s+(game|machine)\b",
            r"\bpoker\s+platform\b",
        ),
    ),
    (
        "excluded_domain_dating",
        (
            r"\bdating\s+(platform|app|service|site|company)\b",
            r"\bromantic\s+matching\b",
            r"\bmatchmaking\s+(app|platform|service|company)\b",
            r"\badult\s+dating\b",
        ),
    ),
    (
        "excluded_domain_tobacco_alcohol_vaping_cannabis",
        (
            r"\btobacco\s+(company|brand|product)\b",
            r"\bcigarette\s+(brand|company|product)\b",
            r"\bvap(ing|e)\s+(company|brand|product|platform)\b",
            r"\bcannabis\s+(company|brand|dispensary|product|platform)\b",
            r"\bmarijuana\s+(company|brand|dispensary|product)\b",
            r"\bbrewer(y|ies)\b",
            r"\bdistiller(y|ies)\b",
            r"\balcohol\s+(brand|company|platform|manufacturer)\b",
        ),
    ),
    (
        "excluded_domain_adult_content",
        (
            r"\bpornograph(y|ic|er)\b",
            r"\badult\s+content\s+(platform|company|site|network)\b",
            r"\badult\s+entertainment\b",
            r"\bsex\s+industry\b",
            r"\bonlyfans\b",
        ),
    ),
    (
        "excluded_domain_crypto_speculative_finance",
        (
            r"\bcrypto(currency)?\s+(exchange|trading|platform|protocol|wallet|company|startup)\b",
            r"\bdefi\s+(protocol|platform|project|company)\b",
            r"\bnft\s+(platform|marketplace|project)\b",
            r"\bweb3\s+(company|platform|project|startup)\b",
            r"\btoken\s+(sale|trading|offering|issuance)\b",
            r"\bspeculative\s+finance\b",
        ),
    ),
    (
        "excluded_domain_mlm",
        (
            r"\bmulti-?level\s+marketing\b",
            r"\bmlm\b",
            r"\bnetwork\s+marketing\s+(company|business|platform)\b",
            r"\bdirect\s+sales\s+(network|opportunity|business)\b",
        ),
    ),
)

# ── Seniority patterns ───────────────────────────────────────────────────────
# Explicit junior signals — title containing any of these is clearly below floor
_JUNIOR_PATTERNS: tuple[str, ...] = (
    r"\bjunior\b",
    r"\bentry[\s\-]?level\b",
    r"\bintern\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bjr\.\b",
    r"\bjr\b",
)

# At-or-above-floor seniority signals
_SENIOR_PATTERNS: tuple[str, ...] = (
    r"\bvp\b",
    r"\bvice\s+president\b",
    r"\bdirector\b",
    r"\bhead\s+of\b",
    r"\bcoo\b",
    r"\bcfo\b",
    r"\bceo\b",
    r"\bcto\b",
    r"\bcpo\b",
    r"\bchief\b",
    r"\bmanaging\s+(director|partner)\b",
    r"\bpresident\b",
    r"\bsenior\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bmanager\b",
    r"\bpartner\b",
    r"\bexecutive\b",
    r"\bgeneral\s+manager\b",
)


# ── Public entry-point ───────────────────────────────────────────────────────


def run_f1(role: dict) -> dict:
    """Run the F1 pre-screen filter on *role*.

    Gate evaluation runs against the provided *role* dict (the caller's
    in-memory version).  The store write, however, always builds on top of
    the canonical on-disk record so that lane enforcement only sees changes
    within ``filter_status.f1.*`` — regardless of any other in-memory edits
    the caller may have made.

    Updates ``role["filter_status"]["f1"]`` in-place and persists the change
    via ``store.write_role(..., writer_id="F1")``.

    Idempotent: if ``filter_status.f1.status`` is not ``"pending"``, returns
    *role* unchanged without writing.

    Returns the (potentially updated) role dict.
    """
    f1 = (role.get("filter_status") or {}).get("f1") or {}
    if f1.get("status", "pending") != "pending":
        LOGGER.info(
            "F1 already run for %s (status=%s) — no-op",
            role.get("role_id"),
            f1.get("status"),
        )
        return role

    role_id = role.get("role_id", "<unknown>")
    LOGGER.info("Running F1 for %s", role_id)

    rubric = _load_rubric()
    rubric_version = (rubric.get("_meta") or {}).get("version")

    # Evaluate gates against the caller's version of the role.
    result, failed_gates = _evaluate_gates(role, rubric)

    f1_data: dict[str, Any] = {
        "status": result,
        "failed_gates": failed_gates,
        "checked_at": _now_iso(),
        "rubric_version": rubric_version,
    }

    # Persist: apply F1 fields onto the canonical on-disk record.
    # Reading fresh from the store ensures the lane scope check only sees
    # filter_status.f1.* changes, even if the caller modified other fields
    # (e.g. jd.body set to "" in-memory to exercise the no_jd_text gate).
    try:
        on_disk = store.read_role(role_id)
    except (FileNotFoundError, OSError):
        # Role not yet persisted (uncommon in production; graceful fallback).
        on_disk = dict(role)
    on_disk["filter_status"]["f1"] = f1_data
    store.write_role(role_id, on_disk, writer_id="F1")

    # Propagate F1 result back into the caller's dict so downstream code
    # (state machine handler, tests) can inspect it without an extra read.
    role["filter_status"]["f1"] = f1_data

    store.append_decision(
        {
            "agent_id": "F1",
            "event": "f1_result",
            "failed_gates": failed_gates,
            "result": result,
            "role_id": role_id,
            "rubric_version": rubric_version,
        }
    )
    LOGGER.info("F1 complete for %s: %s (%s)", role_id, result, failed_gates)
    return role


# ── Gate evaluation ──────────────────────────────────────────────────────────


def _evaluate_gates(role: dict, rubric: dict) -> tuple[str, list[str]]:
    """Evaluate all F1 gates in order.  Returns ``(status, failed_gates)``."""

    # Gate a — missing JD text
    jd_body = ((role.get("jd") or {}).get("body") or "").strip()
    if not jd_body:
        return FAIL, ["no_jd_text"]

    # Gate b — location
    loc = _check_location(role)
    if loc is not None:
        return loc[0], [loc[1]]

    # Gate c — domain exclusions
    dom = _check_domain(role, rubric)
    if dom is not None:
        return dom[0], [dom[1]]

    # Gate d — compensation floor
    notes: list[str] = []
    comp_stated = (role.get("jd") or {}).get("comp_stated")
    if comp_stated:
        comp = _check_comp(comp_stated)
        if comp is not None:
            return comp[0], [comp[1]]
    else:
        notes.append("comp_unstated")

    # Gate e — seniority floor
    sen = _check_seniority(role)
    if sen is not None:
        return sen[0], [sen[1]]

    return PASS, notes


# ── Individual gate checks ───────────────────────────────────────────────────


def _check_location(role: dict) -> tuple[str, str] | None:
    """Return ``(result, reason)`` if the location gate fires, else ``None``."""
    location = ((role.get("jd") or {}).get("location_stated") or "").strip()

    if not location:
        return None  # no info — pass gate

    loc = location.lower()

    # Warsaw / Poland → explicit pass
    if any(kw in loc for kw in ("warsaw", "wrocław", "krakow", "kraków", "poland", "polska")):
        return None

    has_remote = "remote" in loc or "wfh" in loc or "work from home" in loc
    has_hybrid = "hybrid" in loc

    if has_remote or has_hybrid:
        # European / global qualifiers → Warsaw-compatible → pass
        for pattern in _EUROPE_PASS_QUALIFIERS:
            if re.search(pattern, loc, re.IGNORECASE):
                return None

        # Specific non-Warsaw geography alongside remote/hybrid → near-miss
        for pattern in _REMOTE_NEAR_MISS_QUALIFIERS:
            if re.search(pattern, loc, re.IGNORECASE):
                return (
                    NEAR_MISS,
                    f"location_ambiguous: '{location}' — may require non-Warsaw "
                    "residency; clarification needed",
                )

        # Generic remote/hybrid with no geographic restriction → pass
        return None

    # No remote/hybrid/Warsaw signal → likely on-site elsewhere → fail
    return FAIL, f"location_requires_relocation: '{location}'"


def _check_domain(role: dict, rubric: dict) -> tuple[str, str] | None:
    """Return ``(FAIL, reason)`` if any domain exclusion gate fires, else ``None``.

    Searches JD body text and company_domain.  Fires even when the role itself
    is a non-domain function (e.g. CFO at a gambling company).
    """
    # Build the search corpus from JD body + company domain
    jd_body = ((role.get("jd") or {}).get("body") or "").lower()
    company_domain = (role.get("company_domain") or "").lower()
    # Treat domain tokens (e.g. "betway", "casino") as searchable words
    domain_tokens = " ".join(re.split(r"[\.\-_]", company_domain))
    corpus = f"{jd_body} {domain_tokens}"

    # Determine which gate IDs are actually present in the rubric
    rubric_gate_ids = {g["id"] for g in (rubric.get("hard_gates") or [])}

    for gate_id, patterns in _DOMAIN_EXCLUSIONS:
        if gate_id not in rubric_gate_ids:
            continue  # gate not active in current rubric version
        for pattern in patterns:
            if re.search(pattern, corpus, re.IGNORECASE):
                return FAIL, f"{gate_id}: pattern matched in JD/domain"

    return None


def _check_comp(comp_stated: str) -> tuple[str, str] | None:
    """Return ``(FAIL, reason)`` if stated comp is below floor, else ``None``."""
    monthly = _parse_monthly_usd(comp_stated)
    if monthly is None:
        return None  # can't parse → do not fail on this gate
    if monthly < COMP_FLOOR_MONTHLY_USD:
        return (
            FAIL,
            f"comp_below_floor: '{comp_stated}' ≈ ${monthly:.0f}/month "
            f"(floor ${COMP_FLOOR_MONTHLY_USD})",
        )
    return None


def _check_seniority(role: dict) -> tuple[str, str] | None:
    """Return ``(FAIL, reason)`` if the role is clearly below the seniority floor."""
    title = ((role.get("jd") or {}).get("title") or "").strip()

    if not title:
        return None  # no title — do not fail on this gate

    title_lower = title.lower()

    # Explicit junior signals override everything → fail immediately
    for pattern in _JUNIOR_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return FAIL, f"seniority_below_floor: '{title}' signals junior level"

    # If any senior/at-floor signal is present → pass
    for pattern in _SENIOR_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return None

    # No junior signal and no senior signal — ambiguous; do not auto-fail
    return None


# ── Internal helpers ─────────────────────────────────────────────────────────


def _parse_monthly_usd(comp_text: str) -> float | None:
    """Parse a compensation string to approximate monthly net USD.

    Returns ``None`` when the string cannot be reliably parsed.
    Handles patterns like '$5,000/month', '$120k/year', '$60/hour'.
    """
    if not comp_text:
        return None

    text = comp_text.lower().replace(",", "").replace(" ", "")

    # Extract the leading number (with optional 'k' multiplier)
    m = re.search(r"(\d+(?:\.\d+)?)k?", text)
    if not m:
        return None

    amount = float(m.group(1))
    if text[m.end() - 1 : m.end()] == "k" or (
        m.end() < len(text) and text[m.end()] == "k"
    ):
        amount *= 1_000

    # Determine the pay period and normalise to monthly
    if re.search(r"(per\s*month|/mo|monthly)", text):
        return amount
    if re.search(r"(per\s*year|/yr|/year|annual|p\.?a\.?)", text):
        return amount / 12
    if re.search(r"(per\s*hour|/hr|/h\b|hourly)", text):
        return amount * 160  # 40 h/week × 4 weeks

    # Heuristic: large number is probably annual; small number monthly
    if amount > 15_000:
        return amount / 12
    return amount


def _load_rubric() -> dict[str, Any]:
    """Load rubric.json from the store root.  Returns empty dict on failure."""
    path = store.ROOT / "rubric.json"
    if not path.exists():
        LOGGER.warning("rubric.json not found at %s — domain gate will be skipped", path)
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        LOGGER.exception("Failed to load rubric.json")
        return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
