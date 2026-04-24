from __future__ import annotations

from orchestrator.state_machine import next_action


def test_next_action_returns_none_for_terminal_states() -> None:
    terminal = ["closed", "error", "f1_failed", "f2_failed", "f2_blocked", "research_failed"]
    for state in terminal:
        assert next_action({"pipeline_state": state}) is None


def test_f1_passed_transitions_to_researching() -> None:
    action = next_action({"pipeline_state": "f1_passed"})

    assert action is not None
    assert action.agent_ids == ("A0",)
    assert action.next_state == "researching"


def test_researching_transitions_to_researched_by_default() -> None:
    action = next_action({"pipeline_state": "researching"})

    assert action is not None
    assert action.agent_ids == ("A0",)
    assert action.next_state == "researched"


def test_sourced_waits_for_liveness_after_stub() -> None:
    action = next_action({"pipeline_state": "sourced"})

    assert action is not None
    assert action.agent_ids == ("A1.4",)
    assert action.next_state == "liveness_pending"


def test_f2_passed_runs_cv_and_cover_letter_bundle() -> None:
    action = next_action({"pipeline_state": "f2_passed"})

    assert action is not None
    assert action.agent_ids == ("A2", "A3")
    assert action.next_state == "ready_to_submit"

