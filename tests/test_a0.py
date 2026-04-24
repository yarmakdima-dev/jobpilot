"""Tests for orchestrator/a0.py — A0 company research agent.

All external calls (Perplexity, formatter LLM) are mocked.  The file-system
store is exercised through a tmp-path root so every test is isolated and
repeatable.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from orchestrator import a0 as a0_mod
from orchestrator import store
from orchestrator.a0 import run_a0
from tests.helpers import configure_store_root, make_role


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def jobpilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure an isolated store root with all required files."""
    root = configure_store_root(tmp_path, monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "rubric.json", tmp_path / "rubric.json")
    return root


def _write_role_a1(role: dict) -> None:
    store.write_role(role["role_id"], role, writer_id="A1")


def _decisions(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (root / "decisions.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _make_a0_role(
    role_id: str = "acme-coo-20260424",
    company_domain: str = "acme.com",
    state: str = "researching",
) -> dict:
    """Build a minimal valid role dict ready for A0."""
    role = make_role(role_id, state=state)
    role["company_domain"] = company_domain
    return role


# ── Fixture profile builder ───────────────────────────────────────────────────


def _clean_profile() -> dict:
    """Return the default fixture profile (no judgment-call signals)."""
    return json.loads(json.dumps(a0_mod._FIXTURE_COMPANY_PROFILE))


def _ru_leader_profile() -> dict:
    """Return a profile with a Russian-origin CEO whose war_position is silent."""
    profile = _clean_profile()
    profile["leadership"]["ceo"] = {
        "name": "Ivan Petrov",
        "title": "CEO & Co-founder",
        "origin": "Russia",
        "current_base": "Berlin, Germany",
        "background": "Ex-Yandex engineer; relocated 2022",
        "public_voice_signal": "Minimal public presence",
        "war_position": {
            "applies": True,
            "value": "silent",
            "evidence": "No public statements found on LinkedIn, web, or Russian-language sources.",
            "research_scope": "LinkedIn + web + Russian-language sources + published interviews",
            "confidence": "medium",
        },
        "parallel_business_flag": {
            "present": False,
            "businesses": [],
        },
        "concentration_risk_notes": "Founder-led; limited public presence.",
    }
    return profile


def _ru_parallel_business_profile() -> dict:
    """Return a profile with a leader who has an active RU parallel business."""
    profile = _clean_profile()
    profile["leadership"]["ceo"] = {
        "name": "Sergei Volkov",
        "title": "CEO",
        "origin": "Russia",
        "current_base": "Tallinn, Estonia",
        "background": "Fintech founder",
        "public_voice_signal": "Occasional LinkedIn posts",
        "war_position": {
            "applies": True,
            "value": "explicit_anti_war",
            "evidence": "Signed open letter condemning invasion in March 2022.",
            "research_scope": "LinkedIn + web + Russian-language sources",
            "confidence": "high",
        },
        "parallel_business_flag": {
            "present": True,
            "businesses": [
                {
                    "name": "RuTech LLC",
                    "role": "founder",
                    "jurisdiction": "Russia",
                    "active": True,
                    "overlap_risk": "Unknown — possible engineering overlap",
                    "carve_out_escalation": True,
                }
            ],
        },
        "concentration_risk_notes": "Parallel RU business requires structural probe.",
    }
    return profile


# ── New company: creates companies/{domain}.json ──────────────────────────────


def test_new_company_creates_profile(jobpilot_root: Path) -> None:
    """A0 creates companies/acme.com.json for a domain with no existing profile."""
    role = _make_a0_role()
    _write_role_a1(role)

    result = run_a0(role)

    profile_path = jobpilot_root / "companies" / "acme.com.json"
    assert profile_path.exists(), "companies/acme.com.json should be created"

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["instance_meta"]["researcher"] == "A0"
    assert profile["snapshot"]["legal_name"] is not None
    assert isinstance(profile["source_index"], dict)
    assert isinstance(profile["gate_needs_judgment_call"], dict)
    assert result is role  # returns the same role dict


def test_new_company_logs_decision(jobpilot_root: Path) -> None:
    """A0 appends an a0_research_complete event to decisions.log."""
    role = _make_a0_role()
    _write_role_a1(role)

    run_a0(role)

    events = _decisions(jobpilot_root)
    a0_events = [e for e in events if e.get("event") == "a0_research_complete"]
    assert len(a0_events) == 1
    assert a0_events[0]["agent_id"] == "A0"
    assert a0_events[0]["domain"] == "acme.com"


# ── Existing fresh company: no-op ─────────────────────────────────────────────


def test_existing_fresh_company_noop(jobpilot_root: Path) -> None:
    """Existing profile without synthesis_stale is returned unchanged."""
    role = _make_a0_role()
    _write_role_a1(role)

    # First run — creates the profile
    run_a0(role)
    profile_path = jobpilot_root / "companies" / "acme.com.json"
    mtime_1 = profile_path.stat().st_mtime

    # Give the OS at least a tick so a re-write would produce a different mtime
    time.sleep(0.05)

    # Second run — must be no-op
    run_a0(role)
    mtime_2 = profile_path.stat().st_mtime

    assert mtime_2 == mtime_1, "Profile must not be re-written when fresh"


def test_fresh_company_no_additional_decisions(jobpilot_root: Path) -> None:
    """No-op run must not append a second a0_research_complete event."""
    role = _make_a0_role()
    _write_role_a1(role)

    run_a0(role)
    run_a0(role)

    events = _decisions(jobpilot_root)
    a0_events = [e for e in events if e.get("event") == "a0_research_complete"]
    assert len(a0_events) == 1


# ── Existing stale company: re-researches ─────────────────────────────────────


def test_stale_company_reruns_research(jobpilot_root: Path) -> None:
    """Profile with synthesis_stale=True triggers re-research and new timestamp."""
    role = _make_a0_role()
    _write_role_a1(role)

    run_a0(role)

    # Mark profile as stale (simulating A7 cache invalidation)
    profile_path = jobpilot_root / "companies" / "acme.com.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["synthesis_stale"] = True
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    mtime_before = profile_path.stat().st_mtime
    time.sleep(0.05)

    run_a0(role)
    mtime_after = profile_path.stat().st_mtime

    assert mtime_after > mtime_before, "Stale profile should be re-written"

    refreshed = json.loads(profile_path.read_text(encoding="utf-8"))
    # synthesis_stale is cleared/overwritten by the new profile write
    assert "synthesis_stale" not in refreshed or not refreshed.get("synthesis_stale")


def test_stale_company_logs_second_decision(jobpilot_root: Path) -> None:
    """Re-research appends a second a0_research_complete event."""
    role = _make_a0_role()
    _write_role_a1(role)

    run_a0(role)

    profile_path = jobpilot_root / "companies" / "acme.com.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["synthesis_stale"] = True
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    run_a0(role)

    events = _decisions(jobpilot_root)
    a0_events = [e for e in events if e.get("event") == "a0_research_complete"]
    assert len(a0_events) == 2, "Should log two research_complete events"


# ── Schema validation: invalid LLM output ────────────────────────────────────


def test_invalid_formatter_json_raises(jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_call_formatter returning invalid JSON raises ValueError from _format_to_schema."""
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: "not valid json {{{")

    role = _make_a0_role()
    _write_role_a1(role)

    with pytest.raises((ValueError, json.JSONDecodeError)):
        run_a0(role)


def test_invalid_formatter_non_object_raises(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_call_formatter returning a JSON array (not object) raises ValueError."""
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: json.dumps([1, 2, 3]))

    role = _make_a0_role()
    _write_role_a1(role)

    with pytest.raises(ValueError, match="JSON object"):
        run_a0(role)


def test_invalid_formatter_missing_required_section_raises(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Formatter output missing a required section raises ValueError from _validate_profile."""
    incomplete = {"snapshot": {"legal_name": "Acme"}}  # missing instance_meta, source_index, gate_needs_judgment_call
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: json.dumps(incomplete))

    role = _make_a0_role()
    _write_role_a1(role)

    with pytest.raises(ValueError, match="missing required sections"):
        run_a0(role)


# ── gate_needs_judgment_call populated on role ────────────────────────────────


def test_judgment_call_set_for_ru_silent_leader(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RU-origin CEO with silent war_position triggers judgment call on role."""
    profile = _ru_leader_profile()
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: json.dumps(profile))

    role = _make_a0_role()
    _write_role_a1(role)

    result = run_a0(role)

    assert "gate_needs_judgment_call" in result, "gate_needs_judgment_call must be set on role"
    calls = result["gate_needs_judgment_call"]
    assert len(calls) >= 1
    gate_ids = [item["gate_id"] for item in calls]
    assert "russian_or_belarusian_market_or_business" in gate_ids


def test_judgment_call_set_for_ru_parallel_business(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leader with active RU parallel business (carve_out_escalation) triggers judgment call."""
    profile = _ru_parallel_business_profile()
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: json.dumps(profile))

    role = _make_a0_role("acme-coo-20260424")
    _write_role_a1(role)

    result = run_a0(role)

    calls = result.get("gate_needs_judgment_call") or []
    assert len(calls) >= 1
    gate_ids = [item["gate_id"] for item in calls]
    assert "russian_or_belarusian_market_or_business" in gate_ids


def test_no_judgment_call_for_clean_profile(jobpilot_root: Path) -> None:
    """Clean profile (US-origin CEO, no parallel businesses) must not set judgment calls."""
    role = _make_a0_role()
    _write_role_a1(role)

    result = run_a0(role)

    assert not result.get("gate_needs_judgment_call"), (
        "No judgment calls expected for a clean non-RU/BY profile"
    )


def test_judgment_call_written_to_company_profile(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gate_needs_judgment_call in company profile has blocked=True when calls exist."""
    profile = _ru_leader_profile()
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: json.dumps(profile))

    role = _make_a0_role()
    _write_role_a1(role)
    run_a0(role)

    saved = json.loads(
        (jobpilot_root / "companies" / "acme.com.json").read_text(encoding="utf-8")
    )
    gcj = saved["gate_needs_judgment_call"]
    assert gcj["blocked"] is True
    assert len(gcj["items"]) >= 1


def test_no_judgment_call_written_when_clean(jobpilot_root: Path) -> None:
    """Clean profile: gate_needs_judgment_call has blocked=False and items=[]."""
    role = _make_a0_role()
    _write_role_a1(role)
    run_a0(role)

    saved = json.loads(
        (jobpilot_root / "companies" / "acme.com.json").read_text(encoding="utf-8")
    )
    gcj = saved["gate_needs_judgment_call"]
    assert gcj["blocked"] is False
    assert gcj["items"] == []


# ── State machine: _a0_handler ────────────────────────────────────────────────


def test_a0_handler_returns_researched_on_success(jobpilot_root: Path) -> None:
    """_a0_handler returns next_state='researched' when run_a0 succeeds."""
    from orchestrator.state_machine import _a0_handler

    role = _make_a0_role()
    _write_role_a1(role)

    result = _a0_handler(role)

    assert result.success is True
    assert result.next_state == "researched"


def test_a0_handler_returns_research_failed_on_error(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_a0_handler returns next_state='research_failed' when run_a0 raises."""
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: "not valid json {{{")

    from orchestrator.state_machine import _a0_handler

    role = _make_a0_role()
    _write_role_a1(role)

    result = _a0_handler(role)

    assert result.success is True  # agent ran; error handled gracefully
    assert result.next_state == "research_failed"


def test_a0_handler_logs_agent_error_to_decisions(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_a0_handler logs an AGENT_ERROR event to decisions.log on failure."""
    monkeypatch.setattr(a0_mod, "_call_formatter", lambda _prompt: "not valid json {{{")

    from orchestrator.state_machine import _a0_handler

    role = _make_a0_role()
    _write_role_a1(role)

    _a0_handler(role)

    events = _decisions(jobpilot_root)
    error_events = [e for e in events if e.get("event") == "AGENT_ERROR"]
    assert any(e.get("agent_id") == "A0" for e in error_events)


# ── State transitions logged ──────────────────────────────────────────────────


def test_f1_passed_to_researching_via_state_machine(jobpilot_root: Path) -> None:
    """next_action for f1_passed returns the research_init handler → researching."""
    from orchestrator.state_machine import next_action

    role = _make_a0_role(state="f1_passed")
    action = next_action(role)

    assert action is not None
    assert action.agent_ids == ("A0",)
    assert action.next_state == "researching"


def test_research_failed_is_terminal(jobpilot_root: Path) -> None:
    """research_failed is a terminal hold state — next_action returns None."""
    from orchestrator.state_machine import next_action

    role = _make_a0_role(state="research_failed")
    assert next_action(role) is None


def test_state_transition_logged_to_decisions(jobpilot_root: Path) -> None:
    """Runner logs the f1_passed→researching transition to decisions.log."""
    import shutil as _shutil
    from orchestrator import runner

    _shutil.copy(
        Path(__file__).resolve().parents[1] / "rubric.json",
        jobpilot_root / "rubric.json",
    )
    from tests.helpers import make_pipeline_row

    role = _make_a0_role(state="f1_passed")
    _write_role_a1(role)
    store.write_pipeline([make_pipeline_row(role)], writer_id="system")

    runner.run_tick()

    events = _decisions(jobpilot_root)
    transitions = [e for e in events if e.get("event") == "state_transition"]
    to_states = [t["to"] for t in transitions]
    assert "researching" in to_states, "Transition to 'researching' must be logged"


# ── Idempotency under concurrent domain ──────────────────────────────────────


def test_missing_company_domain_raises(jobpilot_root: Path) -> None:
    """run_a0 raises ValueError immediately when company_domain is missing."""
    role = _make_a0_role()
    role["company_domain"] = ""  # invalid
    _write_role_a1(make_role("acme-coo-20260424", "researching"))  # write valid to disk

    with pytest.raises(ValueError, match="company_domain"):
        run_a0(role)
