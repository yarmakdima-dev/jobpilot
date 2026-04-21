from __future__ import annotations

import copy
import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from orchestrator import store
from orchestrator.lanes import LaneViolationError


ROLE_ID = "acme-coo-20260421"


@pytest.fixture()
def jobpilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / "roles").mkdir()
    (tmp_path / "companies").mkdir()
    (tmp_path / "schemas").mkdir()
    shutil.copy(repo_root / "schemas" / "role.schema.json", tmp_path / "schemas")
    shutil.copy(repo_root / "schemas" / "pipeline.schema.json", tmp_path / "schemas")
    shutil.copy(repo_root / "company_profile_schema.json", tmp_path)
    (tmp_path / "decisions.log").write_text("", encoding="utf-8")
    (tmp_path / "pipeline.json").write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "ROLE_SCHEMA_PATH", tmp_path / "schemas" / "role.schema.json")
    monkeypatch.setattr(
        store, "PIPELINE_SCHEMA_PATH", tmp_path / "schemas" / "pipeline.schema.json"
    )
    monkeypatch.setattr(
        store, "COMPANY_SCHEMA_PATH", tmp_path / "company_profile_schema.json"
    )
    return tmp_path


@pytest.fixture()
def valid_role() -> dict:
    return {
        "role_id": ROLE_ID,
        "company_domain": "acme.com",
        "source": {
            "url": "https://acme.com/jobs/coo",
            "platform": "company_site",
            "discovered_at": "2026-04-21T10:00:00Z",
        },
        "jd": {
            "title": "Chief Operating Officer",
            "body": "Lead operations for a scaling AI company.",
            "location_stated": "Warsaw hybrid",
            "comp_stated": None,
        },
        "liveness": {
            "last_checked": None,
            "status": "unknown",
            "last_check_method": None,
        },
        "filter_status": {
            "f1": {
                "status": "pending",
                "failed_gates": [],
                "checked_at": None,
                "rubric_version": None,
            },
            "f2": {
                "status": "pending",
                "stance": None,
                "checked_at": None,
                "rubric_version": None,
                "synthesis_ref": None,
            },
        },
        "pipeline_state": "sourced",
        "state_history": [],
        "debrief_ref": None,
    }


def test_write_and_read_valid_role(jobpilot_root: Path, valid_role: dict) -> None:
    store.write_role(ROLE_ID, valid_role, writer_id="A1")

    assert store.read_role(ROLE_ID) == valid_role
    assert (jobpilot_root / "roles" / f"{ROLE_ID}.json").exists()


def test_schema_violation_rejects_invalid_role(
    jobpilot_root: Path, valid_role: dict
) -> None:
    invalid_role = copy.deepcopy(valid_role)
    invalid_role["pipeline_state"] = "side_quest"

    with pytest.raises(ValidationError):
        store.write_role(ROLE_ID, invalid_role, writer_id="A1")

    assert not (jobpilot_root / "roles" / f"{ROLE_ID}.json").exists()


def test_lane_violation_raises_and_logs(
    jobpilot_root: Path, valid_role: dict
) -> None:
    with pytest.raises(LaneViolationError):
        store.write_role(ROLE_ID, valid_role, writer_id="A2")

    lines = (jobpilot_root / "decisions.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "lane_violation"
    assert entry["writer_id"] == "A2"
    assert entry["path"] == f"roles/{ROLE_ID}.json"


def test_filter_can_update_only_its_status(
    jobpilot_root: Path, valid_role: dict
) -> None:
    store.write_role(ROLE_ID, valid_role, writer_id="A1")
    updated = copy.deepcopy(valid_role)
    updated["filter_status"]["f1"] = {
        "status": "pass",
        "failed_gates": [],
        "checked_at": "2026-04-21T11:00:00Z",
        "rubric_version": "0.2",
    }

    store.write_role(ROLE_ID, updated, writer_id="F1")
    assert store.read_role(ROLE_ID)["filter_status"]["f1"]["status"] == "pass"

    illegal = copy.deepcopy(updated)
    illegal["pipeline_state"] = "f1_passed"
    with pytest.raises(LaneViolationError):
        store.write_role(ROLE_ID, illegal, writer_id="F1")
    logged = [
        json.loads(line)
        for line in (jobpilot_root / "decisions.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert logged[-1]["event"] == "lane_violation"
    assert "pipeline_state" in logged[-1]["reason"]


def test_atomic_write_cleans_up_tmp_on_schema_failure(
    jobpilot_root: Path, valid_role: dict
) -> None:
    invalid_role = copy.deepcopy(valid_role)
    invalid_role["jd"]["body"] = ""

    with pytest.raises(ValidationError):
        store.write_role(ROLE_ID, invalid_role, writer_id="A1")

    assert list((jobpilot_root / "roles").glob("*.tmp")) == []


def test_append_decision_is_newline_delimited_json(jobpilot_root: Path) -> None:
    store.append_decision({"event": "override", "role_id": ROLE_ID})
    store.append_decision({"event": "transition", "role_id": ROLE_ID})

    entries = [
        json.loads(line)
        for line in (jobpilot_root / "decisions.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [entry["event"] for entry in entries] == ["override", "transition"]
    assert all("at" in entry for entry in entries)


def test_pipeline_round_trip(jobpilot_root: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = [
        {
            "role_id": ROLE_ID,
            "company_domain": "acme.com",
            "pipeline_state": "sourced",
            "updated_at": now,
        }
    ]

    store.write_pipeline(rows, writer_id="system")

    assert store.read_pipeline() == rows


def test_concurrent_pipeline_writes_leave_valid_json(jobpilot_root: Path) -> None:
    rows_a = [
        {
            "role_id": ROLE_ID,
            "company_domain": "acme.com",
            "pipeline_state": "sourced",
            "updated_at": "2026-04-21T10:00:00Z",
        }
    ]
    rows_b = [
        {
            "role_id": "beta-cpo-20260421",
            "company_domain": "beta.com",
            "pipeline_state": "researched",
            "updated_at": "2026-04-21T10:01:00Z",
        }
    ]

    threads = [
        threading.Thread(target=store.write_pipeline, args=(rows_a, "system")),
        threading.Thread(target=store.write_pipeline, args=(rows_b, "system")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    on_disk = json.loads((jobpilot_root / "pipeline.json").read_text(encoding="utf-8"))
    assert on_disk in (rows_a, rows_b)
    assert store.read_pipeline() in (rows_a, rows_b)
