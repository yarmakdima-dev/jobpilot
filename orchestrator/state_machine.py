"""Pipeline state machine for S2 runner dispatch."""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.agents import AgentHandler, AgentResult, run_agent
from orchestrator.liveness import check_liveness


@dataclass(frozen=True)
class Action:
    """Next action for a role state."""

    agent_ids: tuple[str, ...]
    next_state: str
    reason: str
    handler: AgentHandler

    @property
    def agent_id(self) -> str:
        """Compatibility label for single-action call sites and logs."""
        return "+".join(self.agent_ids)


TERMINAL_STATES = {
    "closed",
    "dead",
    "error",
    "f1_failed",
    "f2_failed",
    "f2_blocked",
}


def _single_agent(agent_id: str) -> AgentHandler:
    return lambda role: run_agent(agent_id, role)


def _liveness_handler(role: dict) -> AgentResult:
    """Run the Playwright liveness check and return a dynamic-state AgentResult.

    Updates ``role["liveness"]`` in-place so the runner's subsequent
    ``write_role`` persists the result.  Returns ``next_state="f1_pending"``
    when the posting is live and ``next_state="dead"`` when it is not.
    """
    result = check_liveness(role)
    liveness = role.setdefault("liveness", {})
    liveness["status"] = "alive" if result["status"] == "live" else "dead"
    liveness["last_checked"] = result["checked_at"]
    liveness["last_check_method"] = "playwright"
    next_state = "f1_pending" if result["status"] == "live" else "dead"
    return AgentResult(success=True, reason=result["reason"], next_state=next_state)


def _agent_bundle(agent_ids: tuple[str, ...]) -> AgentHandler:
    def run_bundle(role: dict):
        result = None
        for agent_id in agent_ids:
            result = run_agent(agent_id, role)
            if not result.success:
                return result
        if result is None:
            raise RuntimeError("empty agent bundle")
        return result

    return run_bundle


TRANSITIONS: dict[str, Action] = {
    "sourced": Action(
        agent_ids=("A1.4",),
        next_state="liveness_pending",
        reason="liveness_check_stubbed_pending_a1_4",
        handler=_single_agent("A1.4"),
    ),
    "liveness_pending": Action(
        agent_ids=("A1.4",),
        # Default next_state for the live path; the dead path is returned via
        # AgentResult.next_state so the runner picks it up dynamically.
        next_state="f1_pending",
        reason="liveness_check_complete",
        handler=_liveness_handler,
    ),
    "f1_pending": Action(
        agent_ids=("F1",),
        next_state="f1_passed",
        reason="stub_f1_pass",
        handler=_single_agent("F1"),
    ),
    "f1_passed": Action(
        agent_ids=("A0",),
        next_state="researched",
        reason="stub_company_research_complete",
        handler=_single_agent("A0"),
    ),
    "researched": Action(
        agent_ids=("F2",),
        next_state="f2_passed",
        reason="stub_f2_pass",
        handler=_single_agent("F2"),
    ),
    "f2_passed": Action(
        agent_ids=("A2", "A3"),
        next_state="ready_to_submit",
        reason="stub_application_materials_ready",
        handler=_agent_bundle(("A2", "A3")),
    ),
    "ready_to_submit": Action(
        agent_ids=("A4",),
        next_state="applied",
        reason="stub_submission_complete",
        handler=_single_agent("A4"),
    ),
    "applied": Action(
        agent_ids=("A8",),
        next_state="first_call",
        reason="stub_inbox_watch_detected_first_call",
        handler=_single_agent("A8"),
    ),
    "first_call": Action(
        agent_ids=("A5",),
        next_state="interview_scheduled",
        reason="stub_interview_prep_complete",
        handler=_single_agent("A5"),
    ),
    "interview_scheduled": Action(
        agent_ids=("A5",),
        next_state="post_interview",
        reason="stub_interview_prep_complete",
        handler=_single_agent("A5"),
    ),
    "post_interview": Action(
        agent_ids=("A6",),
        next_state="closed",
        reason="stub_debrief_complete",
        handler=_single_agent("A6"),
    ),
}


def next_action(role: dict) -> Action | None:
    """Return the next action for a role, or None for terminal/waiting states."""
    state = role.get("pipeline_state")
    if state in TERMINAL_STATES:
        return None
    return TRANSITIONS.get(state)

