"""Liveness check module for A1.4 — Playwright-based posting verification.

Selector inventory
------------------
JD body selectors (description container, ≥ MIN_JD_BODY_CHARS characters of
inner text in main/article region). Checked in order; first match with
sufficient text wins.

    "main [class*='description']"
    "article [class*='description']"
    "[class*='jobDescription']"
    "[class*='job-description']"
    "[id='job-description']"
    "[data-testid*='description']"
    ".job-details__description"
    "section.description"
    ".posting-description"
    "[class*='job-detail']"

Apply button / link selectors. Any match is sufficient.

    "a[href*='apply']"
    "button[class*='apply']"
    "[data-testid*='apply']"
    "[aria-label*='Apply']"
    ".apply-button"
    "a[class*='apply']"
    "#apply-button"
    "button[class*='Apply']"

Dead-posting heuristic
----------------------
A posting is considered dead when BOTH of the following are absent:

  (a) A description container matching any JD body selector with ≥ 200
      characters of inner text in the main/article region.
  (b) An apply button / link matching any apply selector.

If the JD body is missing the posting is immediately marked dead with reason
``selector_miss_no_jd_body``.  If the JD body is present but the apply
button is absent the posting is marked dead with reason
``selector_miss_no_apply_button``.

This two-stage check gives distinct reason codes and keeps the "live" bar
high: a live posting must have both signals.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import yaml

from orchestrator import store


LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reason constants — kept as plain strings so callers can import and compare.
# ---------------------------------------------------------------------------
REASON_LIVE = "live"
REASON_HTTP_404 = "http_404"
REASON_HTTP_5XX = "http_5xx"
REASON_TIMEOUT = "timeout"
REASON_REDIRECT_TO_JOBS_HOME = "redirect_to_jobs_home"
REASON_SELECTOR_MISS_NO_JD_BODY = "selector_miss_no_jd_body"
REASON_SELECTOR_MISS_NO_APPLY_BUTTON = "selector_miss_no_apply_button"

# Minimum characters of inner text for a description container to count.
MIN_JD_BODY_CHARS = 200

# ---------------------------------------------------------------------------
# Selector lists
# ---------------------------------------------------------------------------
JD_BODY_SELECTORS: tuple[str, ...] = (
    "main [class*='description']",
    "article [class*='description']",
    "[class*='jobDescription']",
    "[class*='job-description']",
    "[id='job-description']",
    "[data-testid*='description']",
    ".job-details__description",
    "section.description",
    ".posting-description",
    "[class*='job-detail']",
)

APPLY_BUTTON_SELECTORS: tuple[str, ...] = (
    "a[href*='apply']",
    "button[class*='apply']",
    "[data-testid*='apply']",
    "[aria-label*='Apply']",
    ".apply-button",
    "a[class*='apply']",
    "#apply-button",
    "button[class*='Apply']",
)

# URL path segments that indicate a jobs listing home page (not a specific
# posting).  Used by the redirect-to-jobs-home heuristic.
_LISTING_SEGMENTS = frozenset(
    {
        "jobs",
        "careers",
        "vacancies",
        "open-positions",
        "open-roles",
        "positions",
        "opportunities",
        "work-with-us",
        "join-us",
        "apply",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_liveness(role: dict) -> dict[str, str]:
    """Check whether a job posting URL is still live.

    Returns a dict with keys:
        status      "live" | "dead"
        reason      one of the REASON_* constants
        checked_at  ISO-8601 UTC timestamp

    Idempotent: if ``role["liveness"]["status"]`` is already ``"alive"`` or
    ``"dead"`` the function returns without re-running Playwright.  Roles in
    ``liveness_pending`` state have ``status == "unknown"`` and will be
    re-checked on every call.
    """
    existing_status = role.get("liveness", {}).get("status", "unknown")
    if existing_status in {"alive", "dead"}:
        LOGGER.info(
            "liveness already determined for %s: %s — skipping (no-op)",
            role.get("role_id"),
            existing_status,
        )
        existing_reason = _infer_existing_reason(existing_status)
        existing_checked_at = (
            role.get("liveness", {}).get("last_checked") or _now_iso()
        )
        return {
            "status": "live" if existing_status == "alive" else "dead",
            "reason": existing_reason,
            "checked_at": existing_checked_at,
        }

    url = role.get("source", {}).get("url")
    if not url:
        LOGGER.warning(
            "no source URL for role %s; marking dead", role.get("role_id")
        )
        return {
            "status": "dead",
            "reason": REASON_SELECTOR_MISS_NO_JD_BODY,
            "checked_at": _now_iso(),
        }

    cfg = _load_liveness_config()
    nav_timeout_ms = int(cfg.get("nav_timeout_ms", 15_000))
    selector_timeout_ms = int(cfg.get("selector_timeout_ms", 5_000))

    LOGGER.info(
        "running liveness check for %s (nav_timeout=%dms, selector_timeout=%dms)",
        url,
        nav_timeout_ms,
        selector_timeout_ms,
    )
    return _run_playwright_check(url, nav_timeout_ms, selector_timeout_ms)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_liveness_config() -> dict[str, Any]:
    """Return the ``liveness:`` sub-section of orchestrator/config.yml."""
    config_path = store.ROOT / "orchestrator" / "config.yml"
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("liveness", {})


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _infer_existing_reason(existing_status: str) -> str:
    return REASON_LIVE if existing_status == "alive" else REASON_SELECTOR_MISS_NO_JD_BODY


def _run_playwright_check(
    url: str, nav_timeout_ms: int, selector_timeout_ms: int
) -> dict[str, str]:
    """Execute the Playwright liveness check against *url*.

    Separated from ``check_liveness`` so tests can patch it directly without
    mocking the full Playwright context manager.

    Uses only the lightweight Playwright surface:
        page.goto()     — navigate and capture HTTP response
        page.url        — final URL after redirects
        page.content()  — raw HTML (retained for future heuristics)
        page.query_selector() — element presence and inner_text checks
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeout  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    checked_at = _now_iso()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()

                # ── Navigation ─────────────────────────────────────────────
                try:
                    response = page.goto(url, timeout=nav_timeout_ms)
                except PlaywrightTimeout:
                    LOGGER.info("navigation timeout for %s", url)
                    return {
                        "status": "dead",
                        "reason": REASON_TIMEOUT,
                        "checked_at": checked_at,
                    }

                if response is None:
                    LOGGER.warning("null response for %s", url)
                    return {
                        "status": "dead",
                        "reason": REASON_TIMEOUT,
                        "checked_at": checked_at,
                    }

                # ── HTTP status ─────────────────────────────────────────────
                status_code = response.status
                LOGGER.debug("HTTP %d for %s", status_code, url)
                if status_code == 404:
                    return {
                        "status": "dead",
                        "reason": REASON_HTTP_404,
                        "checked_at": checked_at,
                    }
                if status_code >= 500:
                    return {
                        "status": "dead",
                        "reason": REASON_HTTP_5XX,
                        "checked_at": checked_at,
                    }

                # ── Redirect detection ──────────────────────────────────────
                final_url = page.url
                if _is_jobs_home_redirect(url, final_url):
                    LOGGER.info(
                        "redirect to jobs home detected: %s → %s", url, final_url
                    )
                    return {
                        "status": "dead",
                        "reason": REASON_REDIRECT_TO_JOBS_HOME,
                        "checked_at": checked_at,
                    }

                # Capture raw HTML (available for future heuristics).
                _content = page.content()  # noqa: F841

                # ── Selector checks ─────────────────────────────────────────
                if not _has_jd_body(page, selector_timeout_ms):
                    return {
                        "status": "dead",
                        "reason": REASON_SELECTOR_MISS_NO_JD_BODY,
                        "checked_at": checked_at,
                    }

                if not _has_apply_button(page, selector_timeout_ms):
                    return {
                        "status": "dead",
                        "reason": REASON_SELECTOR_MISS_NO_APPLY_BUTTON,
                        "checked_at": checked_at,
                    }

                LOGGER.info("posting confirmed live: %s", url)
                return {
                    "status": "live",
                    "reason": REASON_LIVE,
                    "checked_at": checked_at,
                }

            finally:
                browser.close()

    except Exception:
        LOGGER.exception("unexpected error during liveness check for %s", url)
        return {
            "status": "dead",
            "reason": REASON_TIMEOUT,
            "checked_at": checked_at,
        }


def _has_jd_body(page: Any, selector_timeout_ms: int) -> bool:  # noqa: ARG001
    """Return True if any JD body selector matches with ≥ MIN_JD_BODY_CHARS chars.

    The *selector_timeout_ms* parameter is accepted for API consistency with
    ``_has_apply_button`` and is available for callers that wish to wait for
    dynamic content; the current implementation uses non-blocking
    ``query_selector`` since the page is already fully navigated.
    """
    for selector in JD_BODY_SELECTORS:
        try:
            el = page.query_selector(selector)
            if el is not None:
                text = (el.inner_text() or "").strip()
                if len(text) >= MIN_JD_BODY_CHARS:
                    LOGGER.debug("JD body found via selector %r (%d chars)", selector, len(text))
                    return True
        except Exception:
            LOGGER.debug("query_selector failed for JD selector %r", selector, exc_info=True)
            continue
    return False


def _has_apply_button(page: Any, selector_timeout_ms: int) -> bool:  # noqa: ARG001
    """Return True if any apply button / link selector matches."""
    for selector in APPLY_BUTTON_SELECTORS:
        try:
            el = page.query_selector(selector)
            if el is not None:
                LOGGER.debug("apply button found via selector %r", selector)
                return True
        except Exception:
            LOGGER.debug("query_selector failed for apply selector %r", selector, exc_info=True)
            continue
    return False


def _is_jobs_home_redirect(original_url: str, final_url: str) -> bool:
    """Return True if *final_url* looks like a jobs listing home page.

    # PR_REVIEW: This heuristic detects redirects from a specific job posting
    # to a generic jobs listing page, which indicates the posting has been
    # taken down.
    #
    # Current rule: the final URL's last non-empty path segment is a known
    # listing keyword AND the final path is strictly shorter (fewer segments)
    # than the original URL's path.  This catches the common pattern where
    # /careers/director-of-engineering-12345 redirects to /careers/.
    #
    # Known gaps:
    #   - Does not catch redirects to the site root ("/").
    #   - Does not catch sub-section redirects (e.g., /careers/engineering/).
    #   - Site-specific slug patterns may produce false negatives.
    #
    # Recommended next steps: build a site-specific override map keyed by
    # company_domain once false-positive/negative data accumulates from real
    # runs.  Flag with a ``liveness_needs_review`` field on the role for
    # manual inspection.
    """
    if original_url == final_url:
        return False
    try:
        orig_parts = [p for p in urlparse(original_url).path.split("/") if p]
        final_parts = [p for p in urlparse(final_url).path.split("/") if p]
        if not final_parts:
            return False
        last_segment = final_parts[-1].lower().rstrip("/")
        is_listing_segment = last_segment in _LISTING_SEGMENTS
        is_shorter = len(final_parts) < len(orig_parts)
        return is_listing_segment and is_shorter
    except Exception:
        LOGGER.debug("redirect detection failed", exc_info=True)
        return False
