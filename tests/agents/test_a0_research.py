"""Tests for A0 real backend — agents/a0/research.py and orchestrator/a0.py.

Unit tests use cached fixtures and mock Gemini calls (no network).
Integration tests hit live Gemini — gated behind --run-integration flag.

Usage:
    pytest tests/agents/test_a0_research.py              # unit tests only
    pytest --run-integration tests/agents/test_a0_research.py  # + integration
    pytest --run-integration --save-fixtures tests/agents/test_a0_research.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Test configuration ────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "a0"


def pytest_addoption(parser):
    """Register --run-integration and --save-fixtures flags."""
    # pytest_addoption must live in conftest.py; we add it there if missing.
    # Included here as a reminder; actual registration is in conftest.py.


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration (requires live Gemini API, --run-integration)",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def clean_profile() -> dict[str, Any]:
    """Load the clean happy-path Gemini response fixture."""
    with (FIXTURES_DIR / "gemini_response_clean.json").open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def thin_sources_profile() -> dict[str, Any]:
    """Load the thin-sources Gemini response fixture."""
    with (FIXTURES_DIR / "gemini_response_thin_sources.json").open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def malformed_profile() -> dict[str, Any]:
    """Load the malformed Gemini response fixture."""
    with (FIXTURES_DIR / "gemini_response_malformed.json").open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def base_role() -> dict[str, Any]:
    """Minimal valid role record for A0 testing."""
    return {
        "role_id": "acmecorp-coo-20260428",
        "company_domain": "acmecorp.io",
        "source": {
            "url": "https://acmecorp.io/jobs/coo",
            "platform": "company_site",
            "discovered_at": "2026-04-28T08:00:00Z",
        },
        "jd": {
            "title": "Chief Operating Officer",
            "body": "We are hiring a COO to build the operational backbone of our Series B startup.",
            "location_stated": "Warsaw hybrid",
            "comp_stated": None,
        },
        "liveness": {"status": "alive", "last_checked": "2026-04-28T08:00:00Z",
                     "last_check_method": "playwright"},
        "filter_status": {
            "f1": {"status": "pass", "failed_gates": [], "checked_at": "2026-04-28T09:00:00Z",
                   "rubric_version": "0.3"},
            "f2": {"status": "pending", "stance": None, "checked_at": None,
                   "rubric_version": None, "synthesis_ref": None},
        },
        "pipeline_state": "researching",
        "state_history": [],
        "debrief_ref": None,
    }


@pytest.fixture()
def ru_origin_role() -> dict[str, Any]:
    """Role for a company with a RU-origin CEO (silent war_position) — triggers judgment call."""
    return {
        "role_id": "rucompany-coo-20260428",
        "company_domain": "rucompany.com",
        "source": {"url": "https://rucompany.com/jobs/coo", "platform": "company_site",
                   "discovered_at": "2026-04-28T08:00:00Z"},
        "jd": {"title": "COO", "body": "Lead operations.", "location_stated": "Remote",
               "comp_stated": None},
        "liveness": {"status": "alive", "last_checked": "2026-04-28T08:00:00Z",
                     "last_check_method": "playwright"},
        "filter_status": {
            "f1": {"status": "pass", "failed_gates": [], "checked_at": "2026-04-28T09:00:00Z",
                   "rubric_version": "0.3"},
            "f2": {"status": "pending", "stance": None, "checked_at": None,
                   "rubric_version": None, "synthesis_ref": None},
        },
        "pipeline_state": "researching",
        "state_history": [],
        "debrief_ref": None,
    }


def _make_gemini_response(content: dict, sources: list[str] | None = None):
    """Build a mock GeminiResponse."""
    from agents.a0.gemini_client import GeminiResponse
    if sources is None:
        sources = ["https://s1.example.com", "https://s2.example.com", "https://s3.example.com"]
    return GeminiResponse(
        content=content,
        sources=sources,
        usage={"prompt_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
    )


def _ru_profile(silent: bool = True) -> dict[str, Any]:
    """Return a profile with a RU-origin CEO and configurable war_position."""
    with (FIXTURES_DIR / "gemini_response_clean.json").open(encoding="utf-8") as fh:
        p = json.load(fh)
    p["snapshot"]["domain"] = "rucompany.com"
    p["leadership"]["ceo"] = {
        "name": "Ivan Petrov",
        "title": "CEO & Founder",
        "origin": "Russia",
        "current_base": "Amsterdam, Netherlands",
        "background": "Ex-Yandex engineering lead",
        "public_voice_signal": "Rare public posts; no war-related statements found",
        "war_position": {
            "applies": True,
            "value": "silent" if silent else "explicit_anti_war",
            "evidence": (
                "No public statements found on LinkedIn, web, or Russian-language sources."
                if silent
                else "Published open letter in 2022 condemning the invasion (source: S3)"
            ),
            "research_scope": "LinkedIn, web, Russian-language sources (Meduza, Novaya Gazeta)",
            "confidence": "medium",
        },
        "parallel_business_flag": {"present": False, "businesses": []},
        "concentration_risk_notes": None,
    }
    p["name_confusion_check"] = {"none_found": True, "similar_names_found": []}
    return p


# ── Unit tests — research_company ─────────────────────────────────────────────


class TestResearchCompanyUnit:
    """Unit tests for agents.a0.research.research_company — no live API calls."""

    def test_happy_path_returns_valid_profile(self, base_role, clean_profile):
        """research_company returns a fully populated profile that passes structural checks."""
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        assert profile["snapshot"]["domain"] == "acmecorp.io"
        assert profile["instance_meta"]["researcher"] == "A0"
        assert profile["name_confusion_check"]["none_found"] is True
        assert isinstance(profile["source_index"], dict)
        assert len(profile["source_index"]) >= 3

    def test_name_confusion_check_always_present(self, base_role, clean_profile):
        """name_confusion_check is populated even when none_found=True."""
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        ncc = profile["name_confusion_check"]
        assert "none_found" in ncc
        assert "similar_names_found" in ncc

    def test_gate_judgment_call_present(self, base_role, clean_profile):
        """gate_needs_judgment_call has required structure."""
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        gnj = profile["gate_needs_judgment_call"]
        assert "blocked" in gnj
        assert "items" in gnj
        assert isinstance(gnj["items"], list)

    def test_fallback_triggers_on_thin_sources(self, base_role, clean_profile,
                                               thin_sources_profile):
        """Fallback call is made when first pass returns <3 grounding sources."""
        thin_response = _make_gemini_response(thin_sources_profile, sources=["https://s1.example.com"])
        full_response = _make_gemini_response(clean_profile)

        with (
            patch("agents.a0.research.call_research", return_value=thin_response),
            patch("agents.a0.research.call_with_url_fetch", return_value=full_response) as mock_fallback,
        ):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        mock_fallback.assert_called_once()
        # Fallback response's profile is used
        assert profile["snapshot"]["funding_stage"] == "Series B"

    def test_no_sources_raises_no_sources_error(self, base_role, thin_sources_profile):
        """A0NoSourcesError raised when grounding returns zero sources."""
        zero_source_response = _make_gemini_response(thin_sources_profile, sources=[])
        with (
            patch("agents.a0.research.call_research", return_value=zero_source_response),
            pytest.raises(Exception, match="zero sources"),
        ):
            from agents.a0.research import research_company
            research_company(base_role)

    def test_malformed_response_raises_value_error(self, base_role, malformed_profile):
        """ValueError raised when Gemini response is missing required sections."""
        mock_response = _make_gemini_response(malformed_profile)
        with (
            patch("agents.a0.research.call_research", return_value=mock_response),
            pytest.raises(ValueError, match="missing required"),
        ):
            from agents.a0.research import research_company
            research_company(base_role)

    def test_missing_company_domain_raises(self):
        """ValueError raised when role has no company_domain."""
        bad_role = {"role_id": "test-role", "company_domain": ""}
        with pytest.raises(ValueError, match="missing company_domain"):
            from agents.a0.research import research_company
            research_company(bad_role)

    def test_instance_meta_is_overwritten(self, base_role, clean_profile):
        """instance_meta.researcher is always 'A0', not whatever Gemini returned."""
        clean_profile["instance_meta"]["researcher"] = "SomeOtherAgent"
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        assert profile["instance_meta"]["researcher"] == "A0"

    def test_source_index_backfilled_from_grounding(self, base_role, thin_sources_profile):
        """source_index is backfilled from grounding URLs when sparse."""
        thin_sources_profile["source_index"] = {}  # empty
        grounding_urls = ["https://g1.example.com", "https://g2.example.com",
                          "https://g3.example.com"]
        thin_response = _make_gemini_response(thin_sources_profile, sources=grounding_urls)
        full_response = _make_gemini_response(thin_sources_profile, sources=grounding_urls)

        with (
            patch("agents.a0.research.call_research", return_value=thin_response),
            patch("agents.a0.research.call_with_url_fetch", return_value=full_response),
        ):
            from agents.a0.research import research_company
            profile = research_company(base_role)

        si = profile["source_index"]
        populated = [v for v in si.values() if v]
        assert len(populated) >= 1


# ── Unit tests — orchestrator/a0.py (run_a0) ─────────────────────────────────


class TestRunA0Orchestrator:
    """Unit tests for orchestrator.a0.run_a0 — tests the orchestrator layer."""

    def _setup_store(self, tmp_path, monkeypatch):
        """Set up isolated store for A0 tests."""
        import shutil
        from orchestrator import store
        repo_root = Path(__file__).resolve().parents[2]
        (tmp_path / "companies").mkdir()
        (tmp_path / "roles").mkdir()
        (tmp_path / "schemas").mkdir()
        shutil.copy(repo_root / "schemas" / "role.schema.json", tmp_path / "schemas")
        shutil.copy(repo_root / "schemas" / "pipeline.schema.json", tmp_path / "schemas")
        shutil.copy(repo_root / "company_profile_schema.json", tmp_path)
        (tmp_path / "decisions.log").write_text("", encoding="utf-8")
        (tmp_path / "pipeline.json").write_text("[]\n", encoding="utf-8")
        monkeypatch.setattr(store, "ROOT", tmp_path)
        monkeypatch.setattr(store, "ROLE_SCHEMA_PATH", tmp_path / "schemas" / "role.schema.json")
        monkeypatch.setattr(store, "PIPELINE_SCHEMA_PATH",
                            tmp_path / "schemas" / "pipeline.schema.json")
        monkeypatch.setattr(store, "COMPANY_SCHEMA_PATH",
                            tmp_path / "company_profile_schema.json")

    def test_profile_written_to_companies_dir(self, tmp_path, monkeypatch, base_role,
                                               clean_profile):
        """run_a0 writes profile to companies/<domain>.json."""
        self._setup_store(tmp_path, monkeypatch)
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from orchestrator.a0 import run_a0
            run_a0(base_role)

        profile_path = tmp_path / "companies" / "acmecorp.io.json"
        assert profile_path.exists()
        written = json.loads(profile_path.read_text(encoding="utf-8"))
        assert written["snapshot"]["domain"] == "acmecorp.io"

    def test_idempotent_fresh_profile_skips_research(self, tmp_path, monkeypatch,
                                                       base_role, clean_profile):
        """run_a0 skips Gemini call when fresh profile already exists."""
        self._setup_store(tmp_path, monkeypatch)
        # Pre-write a profile (not stale)
        profile_path = tmp_path / "companies" / "acmecorp.io.json"
        profile_path.write_text(json.dumps(clean_profile, indent=2), encoding="utf-8")

        with patch("agents.a0.research.call_research") as mock_call:
            from orchestrator.a0 import run_a0
            run_a0(base_role)
            mock_call.assert_not_called()

    def test_stale_profile_triggers_re_research(self, tmp_path, monkeypatch,
                                                base_role, clean_profile):
        """run_a0 re-researches when existing profile has synthesis_stale=True."""
        self._setup_store(tmp_path, monkeypatch)
        stale = dict(clean_profile, synthesis_stale=True)
        profile_path = tmp_path / "companies" / "acmecorp.io.json"
        profile_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")

        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response) as mock_call:
            from orchestrator.a0 import run_a0
            run_a0(base_role)
            mock_call.assert_called_once()

    def test_judgment_call_detected_for_silent_ru_ceo(self, tmp_path, monkeypatch,
                                                       ru_origin_role):
        """gate_needs_judgment_call is populated when RU-origin CEO has silent war_position."""
        self._setup_store(tmp_path, monkeypatch)
        ru_profile = _ru_profile(silent=True)
        mock_response = _make_gemini_response(ru_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from orchestrator.a0 import run_a0
            updated_role = run_a0(ru_origin_role)

        assert "gate_needs_judgment_call" in updated_role
        gates = updated_role["gate_needs_judgment_call"]
        assert len(gates) == 1
        assert gates[0]["gate_id"] == "russian_or_belarusian_market_or_business"

    def test_no_judgment_call_for_anti_war_ru_ceo(self, tmp_path, monkeypatch,
                                                    ru_origin_role):
        """gate_needs_judgment_call is empty when RU-origin CEO has explicit_anti_war."""
        self._setup_store(tmp_path, monkeypatch)
        ru_profile = _ru_profile(silent=False)  # explicit_anti_war
        mock_response = _make_gemini_response(ru_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from orchestrator.a0 import run_a0
            updated_role = run_a0(ru_origin_role)

        assert updated_role.get("gate_needs_judgment_call", []) == []

    def test_decision_log_entry_written(self, tmp_path, monkeypatch, base_role, clean_profile):
        """run_a0 appends a decision log entry on success."""
        self._setup_store(tmp_path, monkeypatch)
        mock_response = _make_gemini_response(clean_profile)
        with patch("agents.a0.research.call_research", return_value=mock_response):
            from orchestrator.a0 import run_a0
            run_a0(base_role)

        log_path = tmp_path / "decisions.log"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        a0_entries = [e for e in entries if e.get("event") == "a0_research_complete"]
        assert len(a0_entries) == 1
        entry = a0_entries[0]
        assert entry["domain"] == "acmecorp.io"
        assert "tokens_used" in entry

    def test_write_lane_violation_a0_cannot_write_roles(self, tmp_path, monkeypatch):
        """A0 raising a lane violation when attempting to write to roles/*.json."""
        self._setup_store(tmp_path, monkeypatch)
        from orchestrator.lanes import LaneViolationError
        from orchestrator import store

        with pytest.raises(LaneViolationError):
            store.write_role(
                "some-role-id",
                {"role_id": "some-role-id"},
                writer_id="A0",
            )


# ── Integration tests — live Gemini API ───────────────────────────────────────


@pytest.mark.integration
class TestA0Integration:
    """Integration tests — hit live Gemini 2.5 Pro. Require --run-integration flag."""

    def test_notion_research(self, tmp_path, monkeypatch, request):
        """Live call: research notion.so for a COO role and validate the profile."""
        if not request.config.getoption("--run-integration", default=False):
            pytest.skip("Pass --run-integration to run live Gemini tests")

        if not os.environ.get("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")

        import shutil
        from orchestrator import store
        repo_root = Path(__file__).resolve().parents[2]
        (tmp_path / "companies").mkdir()
        (tmp_path / "roles").mkdir()
        (tmp_path / "schemas").mkdir()
        shutil.copy(repo_root / "schemas" / "role.schema.json", tmp_path / "schemas")
        shutil.copy(repo_root / "schemas" / "pipeline.schema.json", tmp_path / "schemas")
        shutil.copy(repo_root / "company_profile_schema.json", tmp_path)
        (tmp_path / "decisions.log").write_text("", encoding="utf-8")
        (tmp_path / "pipeline.json").write_text("[]\n", encoding="utf-8")
        monkeypatch.setattr(store, "ROOT", tmp_path)
        monkeypatch.setattr(store, "ROLE_SCHEMA_PATH", tmp_path / "schemas" / "role.schema.json")
        monkeypatch.setattr(store, "PIPELINE_SCHEMA_PATH",
                            tmp_path / "schemas" / "pipeline.schema.json")
        monkeypatch.setattr(store, "COMPANY_SCHEMA_PATH",
                            tmp_path / "company_profile_schema.json")

        notion_role = {
            "role_id": "notion-coo-20260428",
            "company_domain": "notion.so",
            "source": {"url": "https://notion.so/jobs/coo", "platform": "company_site",
                       "discovered_at": "2026-04-28T08:00:00Z"},
            "jd": {
                "title": "Chief Operating Officer",
                "body": (
                    "Notion is looking for a COO to partner with the CEO and help "
                    "scale operations globally. You will own P&L, lead cross-functional "
                    "teams, and drive operational excellence across the company."
                ),
                "location_stated": "San Francisco or remote",
                "comp_stated": None,
            },
            "liveness": {"status": "alive", "last_checked": "2026-04-28T08:00:00Z",
                         "last_check_method": "playwright"},
            "filter_status": {
                "f1": {"status": "pass", "failed_gates": [], "checked_at": "2026-04-28T09:00:00Z",
                       "rubric_version": "0.3"},
                "f2": {"status": "pending", "stance": None, "checked_at": None,
                       "rubric_version": None, "synthesis_ref": None},
            },
            "pipeline_state": "researching",
            "state_history": [],
            "debrief_ref": None,
        }

        from orchestrator.a0 import run_a0
        result_role = run_a0(notion_role)

        # Profile was written
        profile_path = tmp_path / "companies" / "notion.so.json"
        assert profile_path.exists(), "Profile file not written"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))

        # Structural checks
        assert profile["snapshot"]["domain"] == "notion.so"
        assert profile["instance_meta"]["researcher"] == "A0"
        assert profile["name_confusion_check"] is not None
        assert len(profile.get("source_index", {})) >= 3, (
            f"Expected ≥3 sources, got {len(profile.get('source_index', {}))}"
        )

        # Decision log entry
        log_path = tmp_path / "decisions.log"
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        a0_entries = [e for e in entries if e.get("event") == "a0_research_complete"]
        assert len(a0_entries) == 1

        tokens = a0_entries[0].get("tokens_used")
        print(f"\n[integration] Notion research: tokens={tokens}, "
              f"sources={a0_entries[0].get('sources_count')}, "
              f"fallback={a0_entries[0].get('fallback_triggered')}")

        # Save fixtures if requested
        if request.config.getoption("--save-fixtures", default=False):
            fixture_path = FIXTURES_DIR / "gemini_response_clean.json"
            # Preserve fixture note
            profile["_fixture_note"] = (
                "Captured from live Gemini integration test against notion.so. "
                f"Tokens: {tokens}. Date: 2026-04-28."
            )
            fixture_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            print(f"[integration] Fixture saved to {fixture_path}")
