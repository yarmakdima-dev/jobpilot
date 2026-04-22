"""Agent registry with no-op S2 handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from orchestrator import store


@dataclass(frozen=True)
class AgentResult:
    """Result returned by an agent handler."""

    success: bool = True
    reason: str = "stub_success"


class AgentHandler(Protocol):
    def __call__(self, role: dict) -> AgentResult: ...


def _stub(agent_id: str, role: dict) -> AgentResult:
    role_id = role.get("role_id", "<unknown>")
    store.append_decision(
        {
            "event": "agent_stub",
            "role_id": role_id,
            "agent_id": agent_id,
            "message": f"would run {agent_id} for role {role_id}",
        }
    )
    return AgentResult()


def _handler(agent_id: str) -> AgentHandler:
    return lambda role: _stub(agent_id, role)


REGISTRY: dict[str, AgentHandler] = {
    "A0": _handler("A0"),
    "A1": _handler("A1"),
    "A1.4": _handler("A1.4"),
    "F1": _handler("F1"),
    "F2": _handler("F2"),
    "A2": _handler("A2"),
    "A3": _handler("A3"),
    "A4": _handler("A4"),
    "A5": _handler("A5"),
    "A6": _handler("A6"),
    "A7": _handler("A7"),
    "A8": _handler("A8"),
}


def run_agent(agent_id: str, role: dict) -> AgentResult:
    """Run a registered stub handler."""
    return REGISTRY[agent_id](role)

