from __future__ import annotations

import fcntl
import json
import multiprocessing
import time
from pathlib import Path

import pytest

from orchestrator import runner, store
from orchestrator.agents import AgentResult
from orchestrator.lanes import LaneViolationError
from orchestrator.state_machine import Action
from tests.helpers import configure_store_root, make_pipeline_row, make_role


@pytest.fixture()
def jobpilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return configure_store_root(tmp_path, monkeypatch)


def _write_role(role: dict) -> None:
    store.write_role(role["role_id"], role, writer_id="A1")


def _decisions(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (root / "decisions.log").read_text(encoding="utf-8").splitlines()
    ]


def test_tick_processes_mixed_state_roles(jobpilot_root: Path) -> None:
    sourced = make_role("acme-coo-20260421", "sourced")
    f1_pending = make_role("beta-cpo-20260421", "f1_pending")
    closed = make_role("gamma-cfo-20260421", "closed")
    for role in [sourced, f1_pending, closed]:
        _write_role(role)
    store.write_pipeline(
        [make_pipeline_row(role) for role in [sourced, f1_pending, closed]],
        writer_id="system",
    )

    runner.run_tick()

    rows = {row["role_id"]: row for row in store.read_pipeline()}
    assert rows["acme-coo-20260421"]["pipeline_state"] == "liveness_pending"
    assert rows["beta-cpo-20260421"]["pipeline_state"] == "f1_passed"
    assert rows["gamma-cfo-20260421"]["pipeline_state"] == "closed"
    assert store.read_role("beta-cpo-20260421")["state_history"][0]["to"] == "f1_passed"

    events = _decisions(jobpilot_root)
    assert any(event.get("agent_id") == "A1.4" for event in events)
    assert any(event.get("agent_id") == "F1" for event in events)


def test_restart_mid_pipeline_advances_from_persisted_state(jobpilot_root: Path) -> None:
    """f1_passed → researching (tick 1) → researched (tick 2) → f2_passed (tick 3)."""
    import shutil
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "rubric.json", jobpilot_root / "rubric.json")

    role = make_role("delta-coo-20260421", "f1_passed")
    _write_role(role)
    store.write_pipeline([make_pipeline_row(role)], writer_id="system")

    runner.run_tick()
    assert store.read_role("delta-coo-20260421")["pipeline_state"] == "researching"

    runner.run_tick()
    assert store.read_role("delta-coo-20260421")["pipeline_state"] == "researched"

    runner.run_tick()
    assert store.read_role("delta-coo-20260421")["pipeline_state"] == "f2_passed"


def test_role_failure_marks_error_and_continues(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = make_role("echo-coo-20260421", "f1_pending")
    healthy = make_role("foxtrot-cpo-20260421", "f1_pending")
    for role in [broken, healthy]:
        _write_role(role)
    store.write_pipeline(
        [make_pipeline_row(role) for role in [broken, healthy]], writer_id="system"
    )

    def fake_next_action(role: dict):
        if role["role_id"] == "echo-coo-20260421":
            return Action(
                agent_ids=("F1",),
                next_state="f1_passed",
                reason="test_failure",
                handler=lambda _role: (_ for _ in ()).throw(RuntimeError("boom")),
            )
        return Action(
            agent_ids=("F1",),
            next_state="f1_passed",
            reason="test_success",
            handler=lambda _role: AgentResult(),
        )

    monkeypatch.setattr(runner, "next_action", fake_next_action)

    runner.run_tick()

    rows = {row["role_id"]: row for row in store.read_pipeline()}
    assert rows["echo-coo-20260421"]["pipeline_state"] == "error"
    assert rows["echo-coo-20260421"]["last_error"] == "boom"
    assert rows["foxtrot-cpo-20260421"]["pipeline_state"] == "f1_passed"


def test_lane_violation_during_dispatch_marks_role_error(
    jobpilot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = make_role("hotel-coo-20260421", "f1_pending")
    _write_role(role)
    store.write_pipeline([make_pipeline_row(role)], writer_id="system")

    def raise_lane(_role: dict) -> AgentResult:
        raise LaneViolationError("test lane violation")

    monkeypatch.setattr(
        runner,
        "next_action",
        lambda _role: Action(
            agent_ids=("F1",),
            next_state="f1_passed",
            reason="lane_test",
            handler=raise_lane,
        ),
    )

    runner.run_tick()

    row = store.read_pipeline()[0]
    assert row["pipeline_state"] == "error"
    assert row["last_error"] == "test lane violation"


def _hold_lock(lock_path: str, hold_seconds: float, ready_queue) -> None:
    with Path(lock_path).open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        ready_queue.put("locked")
        time.sleep(hold_seconds)


def test_concurrent_runner_lock_prevents_second_tick(jobpilot_root: Path) -> None:
    lock_path = jobpilot_root / "pipeline.json.lock"
    ready_queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_hold_lock, args=(str(lock_path), 0.5, ready_queue)
    )
    process.start()
    assert ready_queue.get(timeout=2) == "locked"

    try:
        with pytest.raises(runner.RunnerLockError):
            runner.run_tick()
    finally:
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()

