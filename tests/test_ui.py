from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator import store
from tests.helpers import configure_store_root, make_pipeline_row, make_role
from ui.app import app


def _write_role(role: dict) -> None:
    store.write_role(role["role_id"], role, writer_id="A1")


def test_dashboard_renders_pipeline_table(tmp_path: Path, monkeypatch) -> None:
    configure_store_root(tmp_path, monkeypatch)
    role = make_role("acme-coo-20260428", "researched")
    _write_role(role)
    store.write_pipeline([make_pipeline_row(role)], writer_id="system")

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "JobPilot Console" in response.text
    assert "acme-coo-20260428" in response.text


def test_role_detail_renders_synthesis_and_decisions(tmp_path: Path, monkeypatch) -> None:
    configure_store_root(tmp_path, monkeypatch)
    role = make_role("beta-cpo-20260428", "f2_blocked")
    role["gate_needs_judgment_call"] = [
        {
            "gate_id": "relocation_required",
            "reason": "Need remote clarification",
            "recommended_probes": ["Can they hire in Poland?"],
        }
    ]
    _write_role(role)
    company = {
        "instance_meta": {
            "generated": "2026-04-28T10:00:00Z",
            "target_role": "Chief Product Officer",
            "role_url": "https://beta.com/jobs/cpo",
            "research_depth": "medium",
            "researcher": "A0",
            "confidence_notes": "Complete",
        },
        "name_confusion_check": {"none_found": True, "similar_names_found": []},
        "snapshot": {
            "legal_name": "Beta Inc.",
            "domain": "beta.com",
            "secondary_domains": [],
            "founded": "2020",
            "hq": "Remote",
            "primary_market": "Global",
            "sector": "Software",
            "sub_sector": "Productivity SaaS",
            "headcount_estimate": "80",
            "funding_stage": "Series B",
            "profitability_claim": "Unknown",
        },
        "business_model": {"revenue_model": "SaaS", "core_services": ["Productivity"], "pricing": None, "structure": None, "customer_base_size_claim": None, "revenue_claim": None, "customer_satisfaction_signals": None},
        "strategy_and_direction": {"stated_mission": "Ship tools", "growth_vector": "Enterprise", "recent_moves": [], "strategic_bets": [], "tam_claim": None},
        "leadership": {"leadership_pattern_observations": []},
        "market_view_outside_in": {"competitive_set": [], "market_regulatory_context": None, "macro_tailwinds": [], "macro_headwinds": []},
        "insider_signal_self_description": {"jd_language_excerpts": [], "ceo_recent_public_voice": [], "dissonance_flags": []},
        "hiring_signal": {"role_seniority": "exec", "comp_range": "unknown", "location_policy": "remote", "location_fit_for_user": "needs review", "mandate_tier": "1", "hand_off_test_status": "unknown", "red_flags_in_jd": [], "green_flags_in_jd": []},
        "risks_and_open_questions": {"regulatory_risk": {"level": "low", "notes": ""}, "litigation_risk": {"level": "low", "active_cases": []}, "governance_flags": [], "domain_exclusion_check": "PASS"},
        "gate_needs_judgment_call": {"blocked": True, "items": []},
        "360_synthesis": {"stance": "probe", "synthesis_agent": "F2", "synthesis_rubric_version": "0.2", "synthesis_generated": "2026-04-28T11:00:00Z", "synthesis_trigger": "initial", "stance_one_line": "Probe location", "stance_reasoning": "Need to resolve location.", "top_findings": [], "scored_criteria_rollup": {"manager_quality": "acceptable", "build_mandate_tier": "1", "ai_mandate_binary": "yes", "growth_stage_fit": "yes"}, "hard_gates_rollup": {"all_passed": False, "any_failed": [], "any_judgment_call": ["relocation_required"]}, "override_rules_invoked": [], "first_call_probes": ["Can they hire in Poland?"], "recommended_next_action": "Probe location"},
        "source_index": {"S1": "https://beta.com"},
    }
    store.write_company("beta.com", company, writer_id="A0")
    store.append_decision({"role_id": role["role_id"], "event": "f2_result"})

    client = TestClient(app)
    response = client.get(f"/roles/{role['role_id']}")

    assert response.status_code == 200
    assert "Probe location" in response.text
    assert "relocation_required" in response.text
    assert "f2_result" in response.text
