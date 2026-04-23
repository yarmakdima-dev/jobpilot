"""Cron-friendly pipeline runner."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import logging
import time
from datetime import UTC, datetime, time as datetime_time
from pathlib import Path
from typing import Iterator

import yaml

from orchestrator import report
from orchestrator import store
from orchestrator.state_machine import next_action


LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = {
    "tick_seconds": 300,
    "daily_report_time": "07:00",
}


class RunnerLockError(RuntimeError):
    """Raised when another runner is already ticking."""


def run_tick() -> None:
    """Run one scheduler pass over all active pipeline rows."""
    pipeline_path = store.ROOT / "pipeline.json"
    with _pipeline_tick_lock(pipeline_path):
        rows = _read_pipeline_for_tick(pipeline_path)
        updated_rows = []
        for row in rows:
            updated_rows.append(_process_row(row))
        _write_pipeline_for_tick(pipeline_path, updated_rows)


def run_daemon(interval_seconds: int | None = None) -> None:
    """Run ticks forever, sleeping between passes."""
    config = load_config()
    sleep_for = interval_seconds or int(config["tick_seconds"])
    last_report_date = None
    while True:
        try:
            run_tick()
            last_report_date = maybe_generate_daily_report(
                config, last_report_date=last_report_date
            )
        except RunnerLockError:
            LOGGER.warning("another runner is active; skipping this tick")
        except Exception:
            LOGGER.exception("runner tick failed")
        time.sleep(sleep_for)


def load_config(path: Path | None = None) -> dict:
    """Load runner config, defaulting sparse or missing config values."""
    config_path = path or store.ROOT / "orchestrator" / "config.yml"
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_CONFIG, **data}


def maybe_generate_daily_report(
    config: dict,
    *,
    now: datetime | None = None,
    last_report_date: str | None = None,
) -> str | None:
    """Generate today's report once the configured local time has passed."""
    current = now or datetime.now().astimezone()
    current_date = current.date().isoformat()
    if last_report_date == current_date:
        return last_report_date

    report_time = _parse_report_time(str(config["daily_report_time"]))
    if current.timetz().replace(tzinfo=None) < report_time:
        return last_report_date

    report_path = store.ROOT / "reports" / f"daily_{current_date}.md"
    if report_path.exists():
        return current_date

    report.write_daily_report(current.date())
    return current_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the JobPilot pipeline runner.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tick", action="store_true", help="run one scheduler pass")
    mode.add_argument("--daemon", action="store_true", help="run continuously")
    parser.add_argument(
        "--sleep",
        type=int,
        default=None,
        help="daemon sleep interval in seconds; defaults to orchestrator/config.yml",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    if args.tick:
        run_tick()
    else:
        run_daemon(interval_seconds=args.sleep)
    return 0


def _process_row(row: dict) -> dict:
    role_id = row["role_id"]
    try:
        role = store.read_role(role_id)
        action = next_action(role)
        if action is None:
            return _sync_row(row, role)

        result = action.handler(role)
        if not result.success:
            raise RuntimeError(result.reason)
        # Prefer a dynamic next_state from the result (e.g. A1.4 liveness
        # check chooses between f1_pending and dead at runtime).
        target_state = result.next_state if result.next_state is not None else action.next_state
        # Prefer the agent's reason when it is informative; fall back to the
        # static Action reason for stub handlers.
        effective_reason = (
            result.reason if result.reason != "stub_success" else action.reason
        )
        updated_role = _transition_role(
            role, target_state, effective_reason, action.agent_id
        )
        store.write_role(role_id, updated_role, writer_id="system")
        return _sync_row(row, updated_role)
    except Exception as exc:
        LOGGER.exception("failed processing role %s", role_id)
        return _mark_role_error(row, str(exc))


def _transition_role(role: dict, to_state: str, reason: str, agent_id: str) -> dict:
    from_state = role["pipeline_state"]
    if from_state == to_state:
        return role

    at = _now_iso()
    updated = dict(role)
    updated["pipeline_state"] = to_state
    updated["state_history"] = [
        *role.get("state_history", []),
        {"from": from_state, "to": to_state, "at": at, "reason": reason},
    ]
    store.append_decision(
        {
            "event": "state_transition",
            "role_id": role["role_id"],
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "agent_id": agent_id,
        }
    )
    return updated


def _sync_row(row: dict, role: dict) -> dict:
    synced = dict(row)
    synced["company_domain"] = role["company_domain"]
    synced["pipeline_state"] = role["pipeline_state"]
    synced["updated_at"] = _now_iso()
    synced["last_error"] = None
    return synced


def _mark_role_error(row: dict, reason: str) -> dict:
    role_id = row["role_id"]
    at = _now_iso()
    updated_row = dict(row)
    from_state = row.get("pipeline_state", "unknown")
    updated_row["pipeline_state"] = "error"
    updated_row["updated_at"] = at
    updated_row["last_error"] = reason

    with contextlib.suppress(Exception):
        role = store.read_role(role_id)
        role["pipeline_state"] = "error"
        role["state_history"] = [
            *role.get("state_history", []),
            {"from": from_state, "to": "error", "at": at, "reason": reason},
        ]
        store.write_role(role_id, role, writer_id="system")

    store.append_decision(
        {
            "event": "state_transition",
            "role_id": role_id,
            "from": from_state,
            "to": "error",
            "reason": reason,
            "agent_id": "runner",
        }
    )
    return updated_row


@contextlib.contextmanager
def _pipeline_tick_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerLockError("another runner holds pipeline.json lock") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _read_pipeline_for_tick(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = store._read_json(path)
    store._validate_json_schema(data, store.PIPELINE_SCHEMA_PATH)
    return data


def _write_pipeline_for_tick(path: Path, rows: list[dict]) -> None:
    store.require_lane("system", path.relative_to(store.ROOT))
    store._validate_json_schema(rows, store.PIPELINE_SCHEMA_PATH)
    store._atomic_write_json(path, rows)


def _parse_report_time(value: str) -> datetime_time:
    return datetime.strptime(value, "%H:%M").time()


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
