"""Tests for orchestrator/liveness.py.

All tests mock orchestrator.liveness._run_playwright_check (or the internal
check path) — no network calls are made.

Coverage
--------
- live posting    → state f1_pending, liveness.status "alive"
- HTTP 404        → state dead, reason http_404
- redirect        → state dead, reason redirect_to_jobs_home
- timeout         → state dead, reason timeout
- selector miss (no JD body)    → state dead, reason selector_miss_no_jd_body
- idempotency: role already f1_pending (liveness.status="alive") → no-op
- state transition logged with reason in decisions.log
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from orchestrator import runner, store
from orchestrator.liveness import (
    check_liveness,
    REASON_HTTP_404,
    REASON_HTTP_5XX,
    REASON_LIVE,
    REASON_REDIRECT_TO_JOBS_HOME,
    REASON_SELECTOR_MISS_NO_JD_BODY,
    REASON_TIMEOUT,
    _is_jobs_home_redirect,
)
from tests.helpers import configure_store_root, make_pipeline_row, make_role


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def jobpilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return configure_store_root(tmp_path, monkeypatch)


def _write_role(role: dict) -> None:
    store.write_role(role["role_id"], role, writer_id="A1")


def _decisions(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (root / "decisions.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _liveness_pending_role(role_id: str = "acme-coo-20260421") -> dict:
    role = make_role(role_id, "liveness_pending")
    # liveness.status defaults to "unknown" in make_role — correct for this state
    return role


# ---------------------------------------------------------------------------
# Unit tests: check_liveness return values
# ---------------------------------------------------------------------------


class TestCheckLiveness:
    """Unit tests for check_liveness().  Playwright is mocked at _run_playwright_check."""

    def test_live_posting_returns_live(self) -> None:
        role = _liveness_pending_role()
        live_result = {
            "status": "live",
            "reason": REASON_LIVE,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=live_result):
            result = check_liveness(role)

        assert result["status"] == "live"
        assert result["reason"] == REASON_LIVE

    def test_404_returns_dead_http_404(self) -> None:
        role = _liveness_pending_role()
        dead_result = {
            "status": "dead",
            "reason": REASON_HTTP_404,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            result = check_liveness(role)

        assert result["status"] == "dead"
        assert result["reason"] == REASON_HTTP_404

    def test_redirect_returns_dead_redirect_to_jobs_home(self) -> None:
        role = _liveness_pending_role()
        dead_result = {
            "status": "dead",
            "reason": REASON_REDIRECT_TO_JOBS_HOME,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            result = check_liveness(role)

        assert result["status"] == "dead"
        assert result["reason"] == REASON_REDIRECT_TO_JOBS_HOME

    def test_timeout_returns_dead_timeout(self) -> None:
        role = _liveness_pending_role()
        dead_result = {
            "status": "dead",
            "reason": REASON_TIMEOUT,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            result = check_liveness(role)

        assert result["status"] == "dead"
        assert result["reason"] == REASON_TIMEOUT

    def test_selector_miss_no_jd_body(self) -> None:
        role = _liveness_pending_role()
        dead_result = {
            "status": "dead",
            "reason": REASON_SELECTOR_MISS_NO_JD_BODY,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            result = check_liveness(role)

        assert result["status"] == "dead"
        assert result["reason"] == REASON_SELECTOR_MISS_NO_JD_BODY

    def test_idempotency_alive_role_is_noop(self) -> None:
        """check_liveness must not call Playwright when liveness is already determined."""
        role = make_role("acme-coo-20260421", "f1_pending")
        role["liveness"]["status"] = "alive"
        role["liveness"]["last_checked"] = "2026-04-23T08:00:00Z"

        with patch(
            "orchestrator.liveness._run_playwright_check"
        ) as mock_pw:
            result = check_liveness(role)
            mock_pw.assert_not_called()

        assert result["status"] == "live"
        assert result["checked_at"] == "2026-04-23T08:00:00Z"

    def test_idempotency_dead_role_is_noop(self) -> None:
        """check_liveness must not call Playwright when role is already dead."""
        role = make_role("acme-coo-20260421", "dead")
        role["liveness"]["status"] = "dead"
        role["liveness"]["last_checked"] = "2026-04-23T09:00:00Z"

        with patch(
            "orchestrator.liveness._run_playwright_check"
        ) as mock_pw:
            result = check_liveness(role)
            mock_pw.assert_not_called()

        assert result["status"] == "dead"

    def test_unknown_status_triggers_check(self) -> None:
        """Roles with liveness.status='unknown' should trigger a Playwright check."""
        role = _liveness_pending_role()
        assert role["liveness"]["status"] == "unknown"

        live_result = {
            "status": "live",
            "reason": REASON_LIVE,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch(
            "orchestrator.liveness._run_playwright_check", return_value=live_result
        ) as mock_pw:
            check_liveness(role)
            mock_pw.assert_called_once()


# ---------------------------------------------------------------------------
# Unit tests: redirect detection helper
# ---------------------------------------------------------------------------


class TestIsJobsHomeRedirect:
    def test_same_url_is_not_redirect(self) -> None:
        url = "https://acme.com/careers/director-of-engineering-123"
        assert not _is_jobs_home_redirect(url, url)

    def test_redirect_to_careers_listing(self) -> None:
        orig = "https://acme.com/careers/director-of-engineering-123"
        final = "https://acme.com/careers/"
        assert _is_jobs_home_redirect(orig, final)

    def test_redirect_to_jobs_listing(self) -> None:
        orig = "https://acme.com/jobs/coo-role-456"
        final = "https://acme.com/jobs"
        assert _is_jobs_home_redirect(orig, final)

    def test_non_listing_redirect_is_not_caught(self) -> None:
        orig = "https://acme.com/careers/director-123"
        final = "https://acme.com/login"
        assert not _is_jobs_home_redirect(orig, final)

    def test_shorter_non_listing_url_not_caught(self) -> None:
        orig = "https://acme.com/careers/director-123/apply"
        final = "https://acme.com/careers/director-123"
        assert not _is_jobs_home_redirect(orig, final)


# ---------------------------------------------------------------------------
# Integration tests: state machine transitions via runner
# ---------------------------------------------------------------------------


class TestLivenessStateMachineIntegration:
    """End-to-end tests through the runner: role file + pipeline.json + decisions.log."""

    def test_live_posting_transitions_to_f1_pending(
        self, jobpilot_root: Path
    ) -> None:
        role = _liveness_pending_role("beta-coo-20260423")
        _write_role(role)
        store.write_pipeline([make_pipeline_row(role)], writer_id="system")

        live_result = {
            "status": "live",
            "reason": REASON_LIVE,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=live_result):
            runner.run_tick()

        updated = store.read_role("beta-coo-20260423")
        assert updated["pipeline_state"] == "f1_pending"
        assert updated["liveness"]["status"] == "alive"
        assert updated["liveness"]["last_check_method"] == "playwright"

        rows = {r["role_id"]: r for r in store.read_pipeline()}
        assert rows["beta-coo-20260423"]["pipeline_state"] == "f1_pending"

    def test_dead_posting_transitions_to_dead(
        self, jobpilot_root: Path
    ) -> None:
        role = _liveness_pending_role("gamma-coo-20260423")
        _write_role(role)
        store.write_pipeline([make_pipeline_row(role)], writer_id="system")

        dead_result = {
            "status": "dead",
            "reason": REASON_HTTP_404,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            runner.run_tick()

        updated = store.read_role("gamma-coo-20260423")
        assert updated["pipeline_state"] == "dead"
        assert updated["liveness"]["status"] == "dead"
        assert updated["liveness"]["last_check_method"] == "playwright"

        rows = {r["role_id"]: r for r in store.read_pipeline()}
        assert rows["gamma-coo-20260423"]["pipeline_state"] == "dead"

    def test_state_transition_logged_with_reason(
        self, jobpilot_root: Path
    ) -> None:
        role = _liveness_pending_role("delta-coo-20260423")
        _write_role(role)
        store.write_pipeline([make_pipeline_row(role)], writer_id="system")

        dead_result = {
            "status": "dead",
            "reason": REASON_HTTP_404,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=dead_result):
            runner.run_tick()

        events = _decisions(jobpilot_root)
        transition_events = [
            e for e in events
            if e.get("event") == "state_transition"
            and e.get("role_id") == "delta-coo-20260423"
            and e.get("to") == "dead"
        ]
        assert transition_events, "expected a state_transition event to 'dead' in decisions.log"
        event = transition_events[0]
        assert event["from"] == "liveness_pending"
        assert event["reason"] == REASON_HTTP_404
        assert event["agent_id"] == "A1.4"

    def test_live_transition_reason_logged(
        self, jobpilot_root: Path
    ) -> None:
        role = _liveness_pending_role("echo-coo-20260423")
        _write_role(role)
        store.write_pipeline([make_pipeline_row(role)], writer_id="system")

        live_result = {
            "status": "live",
            "reason": REASON_LIVE,
            "checked_at": "2026-04-23T10:00:00Z",
        }
        with patch("orchestrator.liveness._run_playwright_check", return_value=live_result):
            runner.run_tick()

        events = _decisions(jobpilot_root)
        transition_events = [
            e for e in events
            if e.get("event") == "state_transition"
            and e.get("role_id") == "echo-coo-20260423"
            and e.get("to") == "f1_pending"
        ]
        assert transition_events
        assert transition_events[0]["reason"] == REASON_LIVE
        assert transition_events[0]["from"] == "liveness_pending"

    def test_already_f1_pending_role_is_noop_in_runner(
        self, jobpilot_root: Path
    ) -> None:
        """A role already past liveness check stays put; _run_playwright_check not called."""
        role = make_role("foxtrot-coo-20260423", "f1_pending")
        role["liveness"]["status"] = "alive"
        role["liveness"]["last_checked"] = "2026-04-23T08:00:00Z"
        _write_role(role)
        store.write_pipeline([make_pipeline_row(role)], writer_id="system")

        with patch(
            "orchestrator.liveness._run_playwright_check"
        ) as mock_pw:
            runner.run_tick()
            mock_pw.assert_not_called()

        updated = store.read_role("foxtrot-coo-20260423")
        # f1_pending advances to f1_passed via stub — just confirm liveness unchanged
        assert updated["liveness"]["status"] == "alive"
        assert updated["liveness"]["last_checked"] == "2026-04-23T08:00:00Z"
