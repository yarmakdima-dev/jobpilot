"""Daily markdown report generation for JobPilot."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from orchestrator import store


SNAPSHOT_STATES = [
    "sourced",
    "f1_passed",
    "researched",
    "f2_passed",
    "ready_to_submit",
    "applied",
    "first_call",
    "interview_scheduled",
    "post_interview",
]

FUNNEL_STEPS = [
    ("sourced", "f1_passed", "sourced -> f1_passed"),
    ("f1_passed", "f2_passed", "f1_passed -> f2_passed"),
    ("f2_passed", "applied", "f2_passed -> applied"),
    ("applied", "first_call", "applied -> first_call"),
]


@dataclass(frozen=True)
class FunnelMetric:
    """Rendered funnel metric row."""

    label: str
    numerator: int
    denominator: int

    @property
    def rate(self) -> str:
        if self.denominator == 0:
            return "—"
        return f"{(self.numerator / self.denominator) * 100:.0f}%"


def generate_report(date: date | str | None = None) -> str:
    """Render the daily report as markdown."""
    report_date = _coerce_date(date)
    context = build_report_context(report_date)
    template = _template_environment().get_template("daily_report.md.j2")
    return template.render(**context)


def write_daily_report(
    report_date: date | str | None = None, out: Path | None = None
) -> Path:
    """Generate and write a daily report file, returning its path."""
    actual_date = _coerce_date(report_date)
    out_path = out or store.ROOT / "reports" / f"daily_{actual_date.isoformat()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_report(actual_date), encoding="utf-8")
    return out_path


def build_report_context(report_date: date) -> dict[str, Any]:
    """Build the template context from flat-file state."""
    roles = _read_all_roles()
    role_by_id = {role["role_id"]: role for role in roles}
    pipeline = store.read_pipeline()
    decisions = _read_decisions()
    now = datetime.combine(report_date, time.max, tzinfo=UTC)
    seven_days_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)

    state_counts = {
        state: sum(1 for row in pipeline if row.get("pipeline_state") == state)
        for state in SNAPSHOT_STATES
    }
    ready_to_submit = _role_ids_in_state(roles, "ready_to_submit")
    f2_blocked = [
        role["role_id"]
        for role in roles
        if role.get("filter_status", {}).get("f2", {}).get("stance") == "blocked"
    ]
    error_roles = _role_ids_in_state(roles, "error")

    return {
        "report_date": report_date.isoformat(),
        "pipeline_total": len(pipeline),
        "state_counts": state_counts,
        "stuck_roles": _stuck_roles(roles, pipeline, now),
        "ready_to_submit": ready_to_submit,
        "f2_blocked": sorted(f2_blocked),
        "error_roles": error_roles,
        "inbox_events": _inbox_events(),
        "funnel_metrics": _funnel_metrics(roles, seven_days_ago),
        "near_misses": _near_misses(roles, day_ago),
        "overrides": _overrides(decisions, day_ago),
        "errors": _errors(roles, pipeline, role_by_id),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a JobPilot daily report.")
    parser.add_argument("--date", dest="report_date", help="report date as YYYY-MM-DD")
    parser.add_argument("--out", type=Path, help="output markdown path")
    args = parser.parse_args(argv)

    write_daily_report(args.report_date, args.out)
    return 0


def _template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(store.ROOT / "templates"),
        autoescape=select_autoescape(enabled_extensions=()),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _read_all_roles() -> list[dict[str, Any]]:
    roles_path = store.ROOT / "roles"
    if not roles_path.exists():
        return []
    roles = []
    for path in sorted(roles_path.glob("*.json")):
        roles.append(store._read_json(path))
    return roles


def _read_decisions() -> list[dict[str, Any]]:
    path = store.ROOT / "decisions.log"
    if not path.exists():
        return []
    decisions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decisions.append(json.loads(line))
    return decisions


def _role_ids_in_state(roles: list[dict[str, Any]], state: str) -> list[str]:
    return sorted(
        role["role_id"] for role in roles if role.get("pipeline_state") == state
    )


def _stuck_roles(
    roles: list[dict[str, Any]], pipeline: list[dict[str, Any]], now: datetime
) -> list[str]:
    row_by_id = {row["role_id"]: row for row in pipeline}
    stuck = []
    for role in roles:
        state = role.get("pipeline_state")
        if state in {"closed", "error", "f1_failed", "f2_failed", "f2_blocked"}:
            continue
        entered_at = _state_entered_at(role, row_by_id.get(role["role_id"]))
        if entered_at and now - entered_at > timedelta(days=7):
            stuck.append(f"{role['role_id']} ({state})")
    return sorted(stuck)


def _state_entered_at(
    role: dict[str, Any], row: dict[str, Any] | None
) -> datetime | None:
    current = role.get("pipeline_state")
    for item in reversed(role.get("state_history", [])):
        if item.get("to") == current:
            return _parse_datetime(item.get("at"))
    if row:
        return _parse_datetime(row.get("updated_at"))
    return _parse_datetime(role.get("source", {}).get("discovered_at"))


def _funnel_metrics(roles: list[dict[str, Any]], since: datetime) -> list[FunnelMetric]:
    reached_by_role = {
        role["role_id"]: _states_reached_since(role, since) for role in roles
    }
    metrics = []
    for source, target, label in FUNNEL_STEPS:
        denominator = sum(
            1 for reached in reached_by_role.values() if source in reached
        )
        numerator = sum(
            1
            for reached in reached_by_role.values()
            if source in reached and target in reached
        )
        metrics.append(FunnelMetric(label, numerator, denominator))
    return metrics


def _states_reached_since(role: dict[str, Any], since: datetime) -> set[str]:
    states = set()
    discovered_at = _parse_datetime(role.get("source", {}).get("discovered_at"))
    if discovered_at and discovered_at >= since:
        states.add("sourced")
    for item in role.get("state_history", []):
        at = _parse_datetime(item.get("at"))
        if at and at >= since:
            states.add(item.get("to", ""))
    return states


def _near_misses(roles: list[dict[str, Any]], since: datetime) -> list[dict[str, str]]:
    items = []
    for role in roles:
        f1 = role.get("filter_status", {}).get("f1", {})
        checked_at = _parse_datetime(f1.get("checked_at"))
        if f1.get("status") == "near_miss" and checked_at and checked_at >= since:
            items.append(
                {
                    "role_id": role["role_id"],
                    "checked_at": _display_datetime(checked_at),
                    "failed_gates": ", ".join(f1.get("failed_gates", [])) or "—",
                }
            )
    return sorted(items, key=lambda item: item["role_id"])


def _overrides(
    decisions: list[dict[str, Any]], since: datetime
) -> list[dict[str, str]]:
    items = []
    for decision in decisions:
        event = str(decision.get("event", ""))
        at = _parse_datetime(decision.get("at"))
        if "override" not in event.lower() or not at or at < since:
            continue
        items.append(
            {
                "at": _display_datetime(at),
                "role_id": str(decision.get("role_id", "—")),
                "event": event,
                "reason": str(decision.get("reason", "—")),
            }
        )
    return sorted(items, key=lambda item: item["at"])


def _errors(
    roles: list[dict[str, Any]],
    pipeline: list[dict[str, Any]],
    role_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    row_reason = {
        row["role_id"]: row.get("last_error")
        for row in pipeline
        if row.get("pipeline_state") == "error"
    }
    error_ids = set(row_reason) | {
        role["role_id"] for role in roles if role.get("pipeline_state") == "error"
    }
    items = []
    for role_id in sorted(error_ids):
        role = role_by_id.get(role_id, {})
        reason = row_reason.get(role_id) or _last_error_reason(role) or "—"
        items.append({"role_id": role_id, "reason": reason})
    return items


def _last_error_reason(role: dict[str, Any]) -> str | None:
    for item in reversed(role.get("state_history", [])):
        if item.get("to") == "error":
            return item.get("reason")
    return None


def _inbox_events() -> list[str]:
    inbox_path = store.ROOT / "inbox_events"
    if not inbox_path.exists():
        return []
    return sorted(path.name for path in inbox_path.iterdir() if path.is_file())


def _coerce_date(value: date | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _display_datetime(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
