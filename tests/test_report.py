from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from orchestrator import report, runner, store
from tests.helpers import configure_store_root, make_pipeline_row, make_role


def _write_role(role: dict) -> None:
    store.write_role(role["role_id"], role, writer_id="A1")


def test_empty_daily_report_renders_all_sections(tmp_path: Path, monkeypatch) -> None:
    configure_store_root(tmp_path, monkeypatch)

    rendered = report.generate_report("2026-04-22")

    assert "Nothing yet." in rendered
    assert "## Pipeline snapshot" in rendered
    assert "## Needs your attention" in rendered
    assert "## Funnel metrics (7-day)" in rendered
    assert "## Near-misses" in rendered
    assert "## Overrides logged" in rendered
    assert "## Errors" in rendered
    assert "—" in rendered


def test_partial_daily_report_lists_counts_attention_and_stuck_roles(
    tmp_path: Path, monkeypatch
) -> None:
    configure_store_root(tmp_path, monkeypatch)
    stuck = make_role("acme-coo-20260410", "ready_to_submit")
    stuck["state_history"] = [
        {
            "from": "f2_passed",
            "to": "ready_to_submit",
            "at": "2026-04-10T09:00:00Z",
            "reason": "materials_ready",
        }
    ]
    blocked = make_role("beta-cpo-20260421", "researched")
    blocked["filter_status"]["f2"]["stance"] = "blocked"
    errored = make_role("coda-cfo-20260421", "error")
    errored["state_history"] = [
        {
            "from": "f1_pending",
            "to": "error",
            "at": "2026-04-21T09:00:00Z",
            "reason": "lane violation",
        }
    ]
    for role in [stuck, blocked, errored]:
        _write_role(role)
    error_row = make_pipeline_row(errored)
    error_row["last_error"] = "handler failed"
    store.write_pipeline(
        [make_pipeline_row(stuck), make_pipeline_row(blocked), error_row],
        writer_id="system",
    )

    rendered = report.generate_report("2026-04-22")

    assert "| ready_to_submit | 1 |" in rendered
    assert "acme-coo-20260410 (ready_to_submit)" in rendered
    assert "| Ready to submit | acme-coo-20260410 |" in rendered
    assert "| F2 blocked | beta-cpo-20260421 |" in rendered
    assert "| Errors | coda-cfo-20260421 |" in rendered
    assert "| coda-cfo-20260421 | handler failed |" in rendered


def test_full_daily_report_populates_funnel_near_misses_overrides_and_inbox(
    tmp_path: Path, monkeypatch
) -> None:
    root = configure_store_root(tmp_path, monkeypatch)
    (root / "inbox_events").mkdir()
    (root / "inbox_events" / "reply.json").write_text("{}", encoding="utf-8")

    applied = make_role("delta-coo-20260421", "applied")
    applied["state_history"] = [
        {
            "from": "sourced",
            "to": "f1_passed",
            "at": "2026-04-21T09:00:00Z",
            "reason": "pass",
        },
        {
            "from": "f1_passed",
            "to": "f2_passed",
            "at": "2026-04-21T10:00:00Z",
            "reason": "pass",
        },
        {
            "from": "f2_passed",
            "to": "applied",
            "at": "2026-04-21T11:00:00Z",
            "reason": "submitted",
        },
    ]
    near_miss = make_role("echo-cpo-20260421", "f1_pending")
    near_miss["filter_status"]["f1"] = {
        "status": "near_miss",
        "failed_gates": ["remote"],
        "checked_at": "2026-04-22T06:00:00Z",
        "rubric_version": "0.1",
    }
    for role in [applied, near_miss]:
        _write_role(role)
    store.write_pipeline(
        [make_pipeline_row(applied), make_pipeline_row(near_miss)], "system"
    )
    store.append_decision(
        {
            "event": "human_override",
            "role_id": "delta-coo-20260421",
            "reason": "manual go",
            "at": "2026-04-22T06:30:00Z",
        }
    )

    rendered = report.generate_report("2026-04-22")

    assert "| sourced -> f1_passed | 50% | 1/2 |" in rendered
    assert "| f2_passed -> applied | 100% | 1/1 |" in rendered
    assert "| echo-cpo-20260421 | 2026-04-22T06:00:00Z | remote |" in rendered
    assert (
        "| 2026-04-22T06:30:00Z | delta-coo-20260421 | human_override | manual go |"
        in rendered
    )
    assert "| Inbox events | reply.json |" in rendered


def test_daemon_report_hook_writes_once_after_configured_time(
    tmp_path: Path, monkeypatch
) -> None:
    configure_store_root(tmp_path, monkeypatch)

    before = runner.maybe_generate_daily_report(
        {"daily_report_time": "07:00"},
        now=datetime(2026, 4, 22, 6, 59, tzinfo=UTC),
    )
    first = runner.maybe_generate_daily_report(
        {"daily_report_time": "07:00"},
        now=datetime(2026, 4, 22, 7, 0, tzinfo=UTC),
        last_report_date=before,
    )
    second = runner.maybe_generate_daily_report(
        {"daily_report_time": "07:00"},
        now=datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
        last_report_date=first,
    )

    assert before is None
    assert first == "2026-04-22"
    assert second == "2026-04-22"
    assert (tmp_path / "reports" / "daily_2026-04-22.md").exists()
    assert len(list((tmp_path / "reports").glob("daily_2026-04-22.md"))) == 1
