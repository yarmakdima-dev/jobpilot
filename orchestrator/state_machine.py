"""Pipeline state machine for S2 runner dispatch."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from orchestrator import store
from orchestrator.agents import AgentHandler, AgentResult, run_agent
from orchestrator.liveness import check_liveness

LOGGER = logging.getLogger(__name__)


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
    "research_failed",  # hold state: log reason, surface in daily report
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


def _f1_handler(role: dict) -> AgentResult:
    """Run the F1 pre-screen filter and return a dynamic-state AgentResult.

    Calls ``run_f1`` which updates ``role["filter_status"]["f1"]`` in-place
    and persists the F1 fields.  The runner subsequently transitions
    pipeline_state and appends state_history.

    Possible next states:
        f1_passed   — all gates passed
        f1_failed   — a hard gate fired (terminal)
        f1_near_miss — ambiguous gate (hold; surfaces in daily report)
    """
    from orchestrator.f1 import run_f1  # lazy import avoids circular dependency

    run_f1(role)  # modifies role in-place
    f1 = (role.get("filter_status") or {}).get("f1") or {}
    status = f1.get("status", "fail")
    failed_gates = f1.get("failed_gates") or []
    reason = failed_gates[0] if failed_gates else "all_gates_passed"

    _STATE_MAP = {"pass": "f1_passed", "fail": "f1_failed", "near_miss": "f1_near_miss"}
    next_state = _STATE_MAP.get(status, "f1_failed")
    return AgentResult(success=True, reason=reason, next_state=next_state)


def _research_init_handler(role: dict) -> AgentResult:
    """Transition f1_passed → researching.

    No agent runs here; this is a book-keeping step that marks the role as
    'research in progress' before A0 is dispatched on the next tick.
    """
    return AgentResult(
        success=True,
        reason="research_initiated",
        next_state="researching",
    )


def _a0_handler(role: dict) -> AgentResult:
    """Run the A0 company research agent and return a dynamic-state AgentResult.

    Calls ``run_a0`` which writes the company profile and may set
    ``role["gate_needs_judgment_call"]`` in-place.

    Possible next states:
        researched      — profile written successfully
        research_failed — agent errored (hold state; logged; surfaces in daily report)
    """
    from orchestrator.a0 import run_a0  # lazy import avoids circular dependency

    try:
        run_a0(role)  # modifies role in-place (gate_needs_judgment_call if set)
        return AgentResult(
            success=True,
            reason="company_research_complete",
            next_state="researched",
        )
    except Exception as exc:
        role_id = role.get("role_id", "<unknown>")
        LOGGER.error("A0 failed for %s: %s", role_id, exc, exc_info=True)
        store.append_decision(
            {
                "event": "AGENT_ERROR",
                "agent_id": "A0",
                "role_id": role_id,
                "error": str(exc),
            }
        )
        # Return success=True so the runner uses next_state instead of raising.
        # research_failed is a hold state — surfaced in daily report, not auto-retried.
        return AgentResult(
            success=True,
            reason=str(exc),
            next_state="research_failed",
        )


def _f2_handler(role: dict) -> AgentResult:
    """Run the F2 deep rubric filter and return a dynamic-state AgentResult.

    Loads the company profile from the store, calls ``run_f2``, then maps
    the F2 status to the appropriate pipeline state.

    Possible next states:
        f2_passed  — all gates cleared, scored criteria net positive
        f2_failed  — hard gate fired or manager quality weak (terminal)
        f2_blocked — gate_needs_judgment_call items pending human review (hold)
    """
    from orchestrator.f2 import run_f2  # lazy import avoids circular dependency

    company_domain = role.get("company_domain", "")
    try:
        company = store.read_company(company_domain)
    except (FileNotFoundError, OSError):
        company = {}

    run_f2(role, company)  # modifies role["filter_status"]["f2"] in-place

    f2 = (role.get("filter_status") or {}).get("f2") or {}
    status = f2.get("status", "fail")

    _STATE_MAP = {
        "pass": "f2_passed",
        "fail": "f2_failed",
        "blocked": "f2_blocked",
    }
    next_state = _STATE_MAP.get(status, "f2_failed")

    reason = f2.get("reason") or status
    jc = role.get("gate_needs_judgment_call") or []
    if jc:
        reason = f"{reason} ({len(jc)} judgment_call(s) pending)"

    return AgentResult(success=True, reason=reason, next_state=next_state)


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
        # Default next_state for logging; actual target is returned by the
        # handler dynamically (pass / fail / near_miss).
        next_state="f1_passed",
        reason="f1_filter_complete",
        handler=_f1_handler,
    ),
    "f1_passed": Action(
        agent_ids=("A0",),
        next_state="researching",
        reason="research_initiated",
        handler=_research_init_handler,
    ),
    "researching": Action(
        agent_ids=("A0",),
        # Default next_state for success path; research_failed is returned
        # dynamically by _a0_handler on error.
        next_state="researched",
        reason="company_research_complete",
        handler=_a0_handler,
    ),
    "researched": Action(
        agent_ids=("F2",),
        # Default next_state for logging; actual target returned dynamically
        # by _f2_handler (f2_passed / f2_failed / f2_blocked).
        next_state="f2_passed",
        reason="f2_filter_complete",
        handler=_f2_handler,
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
