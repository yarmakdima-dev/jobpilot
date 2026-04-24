"""Tests for orchestrator/f1.py — F1 JD pre-screen filter.

All tests use fixture role dicts.  No external services are called.
The file-system store is exercised through a tmp-path root so every test is
isolated and repeatable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orchestrator import f1, store
from orchestrator.f1 import FAIL, NEAR_MISS, PASS, run_f1
from tests.helpers import configure_store_root, make_role


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def jobpilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure an isolated store root with schemas + rubric."""
    root = configure_store_root(tmp_path, monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "rubric.json", tmp_path / "rubric.json")
    return root


def _write_role_a1(role: dict) -> None:
    """Persist a role using A1 writer (creation)."""
    store.write_role(role["role_id"], role, writer_id="A1")


def _decisions(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (root / "decisions.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── Role builder helpers ─────────────────────────────────────────────────────


def _make_f1_role(
    role_id: str = "acme-coo-20260421",
    *,
    title: str = "Chief Operating Officer",
    body: str = "We are a B2B SaaS company building operational tooling for enterprises.",
    location_stated: str = "Remote",
    comp_stated: str | None = None,
    company_domain: str = "acme.com",
) -> dict:
    """Build a minimal valid role dict ready for F1."""
    role = make_role(role_id, state="f1_pending")
    role["company_domain"] = company_domain
    role["jd"]["title"] = title
    role["jd"]["body"] = body
    role["jd"]["location_stated"] = location_stated
    role["jd"]["comp_stated"] = comp_stated
    return role


# ── Pass: clean role ──────────────────────────────────────────────────────────


def test_pass_clean_role(jobpilot_root: Path) -> None:
    """Clean JD, Warsaw remote, no domain exclusion, no comp stated, senior title."""
    role = _make_f1_role(
        title="Chief Operating Officer",
        body="B2B SaaS platform for enterprise resource planning.",
        location_stated="Warsaw / Remote",
        comp_stated=None,
    )
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == PASS
    assert f1_status["failed_gates"] == ["comp_unstated"]
    assert f1_status["checked_at"] is not None
    assert f1_status["rubric_version"] is not None


# ── Location gate ─────────────────────────────────────────────────────────────


def test_fail_location_requires_relocation(jobpilot_root: Path) -> None:
    """On-site only in a non-Warsaw city → fail."""
    role = _make_f1_role(location_stated="New York, NY (on-site required)")
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert any("location_requires_relocation" in g for g in f1_status["failed_gates"])


def test_near_miss_location_remote_usa(jobpilot_root: Path) -> None:
    """'Remote - USA' is ambiguous → near_miss, not fail."""
    role = _make_f1_role(location_stated="Remote - USA")
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == NEAR_MISS
    assert any("location_ambiguous" in g for g in f1_status["failed_gates"])


def test_pass_location_warsaw_hybrid(jobpilot_root: Path) -> None:
    """Warsaw hybrid is a clear pass."""
    role = _make_f1_role(location_stated="Warsaw hybrid")
    _write_role_a1(role)
    assert run_f1(role)["filter_status"]["f1"]["status"] == PASS


def test_pass_location_remote_europe(jobpilot_root: Path) -> None:
    """Remote - Europe is Warsaw-compatible → pass."""
    role = _make_f1_role(location_stated="Remote - Europe")
    _write_role_a1(role)
    assert run_f1(role)["filter_status"]["f1"]["status"] == PASS


# ── Domain exclusion gate ─────────────────────────────────────────────────────


def test_fail_domain_gambling(jobpilot_root: Path) -> None:
    """Company core business is online gambling → fail regardless of role title."""
    role = _make_f1_role(
        role_id="betway-coo-20260421",
        title="Chief Financial Officer",
        body=(
            "Betway is a leading online gambling platform offering sports betting, "
            "casino games, and poker.  We are hiring a CFO to lead financial strategy."
        ),
        company_domain="betway.com",
    )
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert any("excluded_domain_gambling" in g for g in f1_status["failed_gates"])


def test_fail_domain_crypto_speculative(jobpilot_root: Path) -> None:
    """Crypto exchange / DeFi platform → fail."""
    role = _make_f1_role(
        role_id="dex-coo-20260421",
        title="Head of Operations",
        body=(
            "We run a leading crypto exchange and DeFi protocol "
            "enabling token trading and yield farming at scale."
        ),
        company_domain="defiswap.io",
    )
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert any("excluded_domain_crypto" in g for g in f1_status["failed_gates"])


def test_pass_domain_nonspeculative_fintech(jobpilot_root: Path) -> None:
    """Non-speculative fintech (payments / digital banking) must NOT trigger crypto gate."""
    role = _make_f1_role(
        role_id="stripe-coo-20260421",
        title="VP of Operations",
        body=(
            "We build payment processing infrastructure for online businesses.  "
            "Our platform handles card payments, bank transfers, and fraud detection."
        ),
        company_domain="stripe.com",
    )
    _write_role_a1(role)

    result = run_f1(role)
    assert result["filter_status"]["f1"]["status"] == PASS


# ── Compensation gate ──────────────────────────────────────────────────────────


def test_fail_comp_below_floor(jobpilot_root: Path) -> None:
    """Stated comp below $3K/month → fail."""
    role = _make_f1_role(comp_stated="$1,500/month")
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert any("comp_below_floor" in g for g in f1_status["failed_gates"])


def test_pass_comp_not_stated(jobpilot_root: Path) -> None:
    """Comp not stated → pass gate; 'comp_unstated' noted in failed_gates."""
    role = _make_f1_role(comp_stated=None)
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == PASS
    assert "comp_unstated" in f1_status["failed_gates"]


def test_pass_comp_above_floor(jobpilot_root: Path) -> None:
    """Comp clearly above floor → pass gate, no comp note in failed_gates."""
    role = _make_f1_role(comp_stated="$150,000/year")
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == PASS
    assert "comp_unstated" not in f1_status["failed_gates"]


# ── Seniority gate ─────────────────────────────────────────────────────────────


def test_fail_seniority_clearly_junior(jobpilot_root: Path) -> None:
    """Explicitly junior title → fail."""
    role = _make_f1_role(title="Junior Operations Coordinator")
    _write_role_a1(role)

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert any("seniority_below_floor" in g for g in f1_status["failed_gates"])


def test_fail_seniority_intern(jobpilot_root: Path) -> None:
    """Intern title → fail."""
    role = _make_f1_role(title="Operations Intern")
    _write_role_a1(role)
    assert run_f1(role)["filter_status"]["f1"]["status"] == FAIL


# ── Missing JD text ───────────────────────────────────────────────────────────


def test_fail_missing_jd_text(jobpilot_root: Path) -> None:
    """Empty jd.body in-memory → fail with reason 'no_jd_text'.

    The schema requires jd.body minLength=1, so we persist a valid placeholder
    and then set body="" in-memory only.  run_f1 evaluates the in-memory version
    and writes back via the on-disk canonical (lane-safe).
    """
    role = _make_f1_role(body="Placeholder for schema compliance.")
    _write_role_a1(role)
    role["jd"]["body"] = ""  # override in-memory only after disk write

    result = run_f1(role)

    f1_status = result["filter_status"]["f1"]
    assert f1_status["status"] == FAIL
    assert f1_status["failed_gates"] == ["no_jd_text"]


def test_fail_whitespace_only_jd(jobpilot_root: Path) -> None:
    """Whitespace-only jd.body is treated as missing."""
    role = _make_f1_role(body="Placeholder for schema compliance.")
    _write_role_a1(role)
    role["jd"]["body"] = "   \n\t  "  # set in-memory only after disk write

    result = run_f1(role)
    assert result["filter_status"]["f1"]["status"] == FAIL


# ── Idempotency ────────────────────────────────────────────────────────────────


def test_idempotent_existing_pass(jobpilot_root: Path) -> None:
    """Role with existing f1_result='pass' is a no-op on second call."""
    role = _make_f1_role()
    _write_role_a1(role)

    first = run_f1(role)
    first_checked_at = first["filter_status"]["f1"]["checked_at"]

    # Calling again must return unchanged and not re-write
    second = run_f1(first)
    assert second["filter_status"]["f1"]["checked_at"] == first_checked_at


def test_idempotent_existing_fail(jobpilot_root: Path) -> None:
    """Role with existing f1_result='fail' is a no-op on second call."""
    role = _make_f1_role(location_stated="Chicago, IL (on-site only)")
    _write_role_a1(role)

    first = run_f1(role)
    assert first["filter_status"]["f1"]["status"] == FAIL

    checked_at = first["filter_status"]["f1"]["checked_at"]
    second = run_f1(first)
    assert second["filter_status"]["f1"]["checked_at"] == checked_at


# ── Near-miss produces near_miss, not fail ────────────────────────────────────


def test_near_miss_result_is_not_fail(jobpilot_root: Path) -> None:
    """Ambiguous location sets f1_result to 'near_miss', never 'fail'."""
    role = _make_f1_role(location_stated="Remote - UK")
    _write_role_a1(role)

    result = run_f1(role)
    assert result["filter_status"]["f1"]["status"] == NEAR_MISS
    assert result["filter_status"]["f1"]["status"] != FAIL


# ── Decisions.log integration ──────────────────────────────────────────────────


def test_f1_result_logged_to_decisions(jobpilot_root: Path) -> None:
    """run_f1 appends an f1_result event to decisions.log."""
    role = _make_f1_role()
    _write_role_a1(role)

    run_f1(role)

    events = _decisions(jobpilot_root)
    f1_events = [e for e in events if e.get("event") == "f1_result"]
    assert len(f1_events) == 1
    assert f1_events[0]["agent_id"] == "F1"
    assert f1_events[0]["result"] == PASS


def test_f1_fail_logged_to_decisions(jobpilot_root: Path) -> None:
    """Failed roles also get an f1_result entry in decisions.log."""
    role = _make_f1_role(location_stated="San Francisco (on-site)")
    _write_role_a1(role)

    run_f1(role)

    events = _decisions(jobpilot_root)
    f1_events = [e for e in events if e.get("event") == "f1_result"]
    assert any(e["result"] == FAIL for e in f1_events)


# ── State machine integration ──────────────────────────────────────────────────


def test_state_machine_transitions_f1_pass(jobpilot_root: Path) -> None:
    """State machine _f1_handler returns next_state='f1_passed' on pass."""
    from orchestrator.state_machine import _f1_handler

    role = _make_f1_role()
    _write_role_a1(role)

    result = _f1_handler(role)

    assert result.success is True
    assert result.next_state == "f1_passed"


def test_state_machine_transitions_f1_fail(jobpilot_root: Path) -> None:
    """State machine _f1_handler returns next_state='f1_failed' on hard fail."""
    from orchestrator.state_machine import _f1_handler

    # Use an on-site location to trigger a deterministic FAIL (avoids schema
    # issues with empty body — lane check would see jd.body changed).
    role = _make_f1_role(location_stated="Berlin (on-site only)")
    _write_role_a1(role)

    result = _f1_handler(role)

    assert result.success is True
    assert result.next_state == "f1_failed"


def test_state_machine_transitions_f1_near_miss(jobpilot_root: Path) -> None:
    """State machine _f1_handler returns next_state='f1_near_miss' on near_miss."""
    from orchestrator.state_machine import _f1_handler

    role = _make_f1_role(location_stated="Remote - USA")
    _write_role_a1(role)

    result = _f1_handler(role)

    assert result.success is True
    assert result.next_state == "f1_near_miss"
