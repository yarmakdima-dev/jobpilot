from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator import store


def configure_store_root(tmp_path: Path, monkeypatch) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / "roles").mkdir()
    (tmp_path / "companies").mkdir()
    (tmp_path / "schemas").mkdir()
    (tmp_path / "orchestrator").mkdir()
    shutil.copy(repo_root / "schemas" / "role.schema.json", tmp_path / "schemas")
    shutil.copy(repo_root / "schemas" / "pipeline.schema.json", tmp_path / "schemas")
    shutil.copy(repo_root / "company_profile_schema.json", tmp_path)
    shutil.copy(repo_root / "orchestrator" / "config.yml", tmp_path / "orchestrator")
    if (repo_root / "templates").exists():
        shutil.copytree(repo_root / "templates", tmp_path / "templates")
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


def make_role(role_id: str, state: str = "f1_pending") -> dict:
    company = role_id.split("-")[0]
    return {
        "role_id": role_id,
        "company_domain": f"{company}.com",
        "source": {
            "url": f"https://{company}.com/jobs/{role_id}",
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
        "pipeline_state": state,
        "state_history": [],
        "debrief_ref": None,
    }


def make_pipeline_row(role: dict) -> dict:
    return {
        "role_id": role["role_id"],
        "company_domain": role["company_domain"],
        "pipeline_state": role["pipeline_state"],
        "updated_at": "2026-04-21T10:00:00Z",
    }
