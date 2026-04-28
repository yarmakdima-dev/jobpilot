"""Operator workbench for JobPilot."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from orchestrator import report, runner, store
from orchestrator.a0 import run_a0
from orchestrator.f2 import run_f2
from orchestrator.state_machine import TERMINAL_STATES, next_action


APP_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="JobPilot Workbench")

PIPELINE_STATES = [
    "sourced",
    "liveness_pending",
    "dead",
    "f1_pending",
    "f1_passed",
    "f1_failed",
    "f1_near_miss",
    "researching",
    "researched",
    "research_failed",
    "f2_passed",
    "f2_failed",
    "f2_blocked",
    "ready_to_submit",
    "applied",
    "first_call",
    "interview_scheduled",
    "post_interview",
    "closed",
    "error",
]


@dataclass(frozen=True)
class RoleRow:
    role_id: str
    company_domain: str
    title: str
    pipeline_state: str
    f1_status: str
    f2_status: str
    f2_stance: str | None
    judgment_call_count: int
    updated_at: str | None
    source_url: str | None


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    rows = _build_role_rows(_load_roles())
    latest_report = _latest_report_path()
    counters = _build_counters(rows)
    queue = _build_queue(rows)
    active_rows = [row for row in rows if row.pipeline_state not in TERMINAL_STATES]
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "rows": rows,
            "active_rows": active_rows,
            "counters": counters,
            "queue": queue,
            "latest_report": latest_report.name if latest_report else None,
        },
    )


@app.get("/intake", response_class=HTMLResponse)
def intake(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "intake.html",
        {
            "state_options": ["sourced", "liveness_pending", "f1_pending", "researching", "researched"],
        },
    )


@app.post("/intake")
def create_role_action(
    company_domain: str = Form(...),
    source_url: str = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    location_stated: str = Form(""),
    comp_stated: str = Form(""),
    platform: str = Form("company_site"),
    initial_state: str = Form("sourced"),
) -> RedirectResponse:
    role = _build_new_role(
        company_domain=company_domain,
        source_url=source_url,
        title=title,
        body=body,
        location_stated=location_stated,
        comp_stated=comp_stated or None,
        platform=platform,
        initial_state=initial_state,
    )
    store.write_role(role["role_id"], role, writer_id="A1")
    _upsert_pipeline_row(role)
    store.append_decision(
        {
            "event": "human_intake_create_role",
            "agent_id": "human",
            "role_id": role["role_id"],
            "company_domain": role["company_domain"],
            "pipeline_state": role["pipeline_state"],
        }
    )
    return RedirectResponse(f"/roles/{role['role_id']}", status_code=303)


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request) -> HTMLResponse:
    rows = _build_role_rows(_load_roles())
    return TEMPLATES.TemplateResponse(
        request,
        "queue.html",
        {
            "queue": _build_queue(rows),
        },
    )


@app.get("/roles/{role_id}", response_class=HTMLResponse)
def role_detail(request: Request, role_id: str) -> HTMLResponse:
    try:
        role = store.read_role(role_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"role {role_id!r} not found") from exc

    company = _safe_read_company(role.get("company_domain"))
    decisions = _role_decisions(role_id)
    role_rows = {row.role_id: row for row in _build_role_rows(_load_roles())}
    role_row = role_rows.get(role_id)
    action = next_action(role)
    return TEMPLATES.TemplateResponse(
        request,
        "role_detail.html",
        {
            "role": role,
            "row": role_row,
            "company": company,
            "company_json": _pretty_json(company),
            "role_json": _pretty_json(role),
            "synthesis_json": _pretty_json((company or {}).get("360_synthesis")),
            "judgment_calls": role.get("gate_needs_judgment_call") or [],
            "decisions": decisions,
            "next_action_label": action.agent_id if action else None,
            "state_options": PIPELINE_STATES,
        },
    )


@app.post("/roles/{role_id}/run-next")
def run_next_action(role_id: str) -> RedirectResponse:
    role = store.read_role(role_id)
    action = next_action(role)
    if action is None:
        store.append_decision(
            {
                "event": "human_run_next_skipped",
                "agent_id": "human",
                "role_id": role_id,
                "reason": "no_next_action",
            }
        )
        return RedirectResponse(f"/roles/{role_id}", status_code=303)

    row = _pipeline_row(role_id, fallback_role=role)
    result = action.handler(role)
    target_state = result.next_state if result.next_state is not None else action.next_state
    reason = result.reason if result.reason != "stub_success" else action.reason
    role = _transition_role(role, target_state, reason)
    store.write_role(role_id, role, writer_id="system")
    _sync_pipeline_row(row, role, last_error=None)
    return RedirectResponse(f"/roles/{role_id}", status_code=303)


@app.post("/roles/{role_id}/run-a0")
def run_a0_action(role_id: str) -> RedirectResponse:
    role = store.read_role(role_id)
    _delete_company_profile(role.get("company_domain"))
    role["pipeline_state"] = "researching"
    try:
        run_a0(role)
        role = _transition_role(role, "researched", "human_triggered_a0_rerun")
        _sync_pipeline_row(_pipeline_row(role_id, fallback_role=role), role, last_error=None)
        store.write_role(role_id, role, writer_id="system")
    except Exception as exc:
        role = _transition_role(role, "research_failed", f"A0 rerun failed: {exc}")
        _sync_pipeline_row(_pipeline_row(role_id, fallback_role=role), role, last_error=str(exc))
        store.write_role(role_id, role, writer_id="system")
        store.append_decision(
            {
                "event": "human_run_a0_failed",
                "agent_id": "human",
                "role_id": role_id,
                "error": str(exc),
            }
        )
    return RedirectResponse(f"/roles/{role_id}", status_code=303)


@app.post("/roles/{role_id}/run-f2")
def run_f2_action(role_id: str) -> RedirectResponse:
    role = store.read_role(role_id)
    role["filter_status"]["f2"] = {
        "status": "pending",
        "stance": None,
        "checked_at": None,
        "rubric_version": None,
        "synthesis_ref": None,
        "reason": None,
    }
    role["gate_needs_judgment_call"] = None
    store.write_role(role_id, role, writer_id="human")
    company = _safe_read_company(role.get("company_domain")) or {}
    run_f2(role, company)
    next_state = {
        "pass": "f2_passed",
        "fail": "f2_failed",
        "blocked": "f2_blocked",
    }.get(role["filter_status"]["f2"]["status"], "f2_failed")
    role = store.read_role(role_id)
    role = _transition_role(role, next_state, "human_triggered_f2_rerun")
    store.write_role(role_id, role, writer_id="system")
    _sync_pipeline_row(_pipeline_row(role_id, fallback_role=role), role, last_error=None)
    return RedirectResponse(f"/roles/{role_id}", status_code=303)


@app.post("/roles/{role_id}/advance")
def advance_role_action(
    role_id: str,
    target_state: str = Form(...),
    reason: str = Form("manual_operator_update"),
) -> RedirectResponse:
    if target_state not in PIPELINE_STATES:
        raise HTTPException(status_code=400, detail=f"invalid target_state {target_state!r}")
    role = store.read_role(role_id)
    role = _transition_role(role, target_state, reason)
    store.write_role(role_id, role, writer_id="system")
    _sync_pipeline_row(_pipeline_row(role_id, fallback_role=role), role, last_error=None)
    store.append_decision(
        {
            "event": "human_manual_transition",
            "agent_id": "human",
            "role_id": role_id,
            "to": target_state,
            "reason": reason,
        }
    )
    return RedirectResponse(f"/roles/{role_id}", status_code=303)


@app.post("/roles/{role_id}/judgment/clear")
def clear_judgment_calls_action(role_id: str) -> RedirectResponse:
    role = store.read_role(role_id)
    role["gate_needs_judgment_call"] = None
    store.write_role(role_id, role, writer_id="human")
    store.append_decision(
        {
            "event": "human_cleared_judgment_calls",
            "agent_id": "human",
            "role_id": role_id,
        }
    )
    return RedirectResponse(f"/roles/{role_id}", status_code=303)


@app.get("/reports/latest", response_class=HTMLResponse)
def latest_report(request: Request) -> HTMLResponse:
    latest = _latest_report_path()
    if latest is None:
        body = "No report generated yet."
        report_name = None
    else:
        body = latest.read_text(encoding="utf-8")
        report_name = latest.name
    return TEMPLATES.TemplateResponse(
        request,
        "report.html",
        {
            "report_name": report_name,
            "report_html": _markdownish_to_html(body),
            "raw_report": body,
        },
    )


@app.get("/api/pipeline")
def api_pipeline() -> list[dict[str, Any]]:
    return [row.__dict__ for row in _build_role_rows(_load_roles())]


@app.get("/api/role/{role_id}")
def api_role(role_id: str) -> dict[str, Any]:
    role = store.read_role(role_id)
    company = _safe_read_company(role.get("company_domain"))
    return {
        "role": role,
        "company": company,
        "decisions": _role_decisions(role_id),
    }


@app.post("/runner/tick")
def run_tick_action() -> RedirectResponse:
    runner.run_tick()
    return RedirectResponse("/", status_code=303)


@app.post("/reports/generate")
def generate_report_action() -> RedirectResponse:
    report.write_daily_report()
    return RedirectResponse("/reports/latest", status_code=303)


def _load_roles() -> list[dict[str, Any]]:
    roles_dir = store.ROOT / "roles"
    if not roles_dir.exists():
        return []
    roles: list[dict[str, Any]] = []
    for path in sorted(roles_dir.glob("*.json")):
        roles.append(store._read_json(path))
    return roles


def _build_role_rows(roles: list[dict[str, Any]]) -> list[RoleRow]:
    pipeline_rows = {row["role_id"]: row for row in store.read_pipeline()}
    results: list[RoleRow] = []
    for role in sorted(roles, key=lambda item: item["role_id"]):
        f1 = (role.get("filter_status") or {}).get("f1") or {}
        f2 = (role.get("filter_status") or {}).get("f2") or {}
        queue = role.get("gate_needs_judgment_call") or []
        pipeline = pipeline_rows.get(role["role_id"], {})
        results.append(
            RoleRow(
                role_id=role["role_id"],
                company_domain=role.get("company_domain", ""),
                title=((role.get("jd") or {}).get("title") or "—"),
                pipeline_state=role.get("pipeline_state", "unknown"),
                f1_status=f1.get("status", "—"),
                f2_status=f2.get("status", "—"),
                f2_stance=f2.get("stance"),
                judgment_call_count=len(queue),
                updated_at=pipeline.get("updated_at"),
                source_url=((role.get("source") or {}).get("url")),
            )
        )
    return results


def _build_counters(rows: list[RoleRow]) -> dict[str, int]:
    tracked_states = [
        "sourced",
        "researching",
        "researched",
        "f2_blocked",
        "ready_to_submit",
        "error",
    ]
    return {
        state: sum(1 for row in rows if row.pipeline_state == state) for state in tracked_states
    }


def _build_queue(rows: list[RoleRow]) -> dict[str, list[RoleRow]]:
    return {
        "blocked": [row for row in rows if row.pipeline_state == "f2_blocked"],
        "ready": [row for row in rows if row.pipeline_state == "ready_to_submit"],
        "errors": [row for row in rows if row.pipeline_state in {"error", "research_failed"}],
        "active": [row for row in rows if row.pipeline_state not in TERMINAL_STATES],
    }


def _latest_report_path() -> Path | None:
    reports_dir = store.ROOT / "reports"
    if not reports_dir.exists():
        return None
    reports = sorted(reports_dir.glob("daily_*.md"))
    return reports[-1] if reports else None


def _safe_read_company(domain: str | None) -> dict[str, Any] | None:
    if not domain:
        return None
    try:
        return store.read_company(domain)
    except FileNotFoundError:
        return None


def _role_decisions(role_id: str) -> list[dict[str, Any]]:
    path = store.ROOT / "decisions.log"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("role_id") == role_id:
            entries.append(entry)
    return entries[-30:]


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) if value is not None else "null"


def _markdownish_to_html(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    in_table = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        if line.startswith("|") and line.endswith("|"):
            cells = [html.escape(cell.strip()) for cell in line.strip("|").split("|")]
            if not in_table:
                out.append("<table><tbody>")
                in_table = True
            if set(cells[0]) == {"-"} if cells else False:
                continue
            out.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</tbody></table>")
            in_table = False

        if stripped.startswith("# "):
            out.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            out.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            if not out or not out[-1].startswith("<ul"):
                out.append("<ul>")
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
        elif not stripped:
            if out and out[-1] == "</ul>":
                pass
            else:
                out.append("<p></p>")
        else:
            if out and out[-1].startswith("<li>"):
                out.append("</ul>")
            out.append(f"<p>{html.escape(stripped)}</p>")

    if in_table:
        out.append("</tbody></table>")
    if in_code:
        out.append("</code></pre>")
    if out and out[-1].startswith("<li>"):
        out.append("</ul>")
    return "\n".join(out)


def _build_new_role(
    *,
    company_domain: str,
    source_url: str,
    title: str,
    body: str,
    location_stated: str,
    comp_stated: str | None,
    platform: str,
    initial_state: str,
) -> dict[str, Any]:
    if initial_state not in PIPELINE_STATES:
        raise HTTPException(status_code=400, detail=f"invalid initial_state {initial_state!r}")

    clean_domain = company_domain.strip().lower()
    slug = _slugify(Path(clean_domain).stem or clean_domain)
    title_slug = _slugify(title) or "role"
    role_date = date.today().strftime("%Y%m%d")
    role_id = _next_available_role_id(f"{slug}-{title_slug}", role_date)
    discovered_at = _now_iso()
    return {
        "role_id": role_id,
        "company_domain": clean_domain,
        "source": {
            "url": source_url.strip(),
            "platform": platform,
            "discovered_at": discovered_at,
        },
        "jd": {
            "title": title.strip(),
            "body": body.strip(),
            "location_stated": location_stated.strip(),
            "comp_stated": comp_stated,
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
        "pipeline_state": initial_state,
        "state_history": [],
        "debrief_ref": None,
    }


def _next_available_role_id(prefix: str, role_date: str) -> str:
    candidate = f"{prefix}-{role_date}"
    index = 2
    while (store.ROOT / "roles" / f"{candidate}.json").exists():
        candidate = f"{prefix}-{index}-{role_date}"
        index += 1
    return candidate


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "role"


def _transition_role(role: dict[str, Any], to_state: str, reason: str) -> dict[str, Any]:
    from_state = role.get("pipeline_state", "unknown")
    if from_state == to_state:
        return role
    updated = dict(role)
    updated["pipeline_state"] = to_state
    updated["state_history"] = [
        *role.get("state_history", []),
        {"from": from_state, "to": to_state, "at": _now_iso(), "reason": reason},
    ]
    store.append_decision(
        {
            "event": "state_transition",
            "agent_id": "human",
            "role_id": role.get("role_id"),
            "from": from_state,
            "to": to_state,
            "reason": reason,
        }
    )
    return updated


def _pipeline_row(role_id: str, *, fallback_role: dict[str, Any]) -> dict[str, Any]:
    for row in store.read_pipeline():
        if row["role_id"] == role_id:
            return row
    return {
        "role_id": role_id,
        "company_domain": fallback_role.get("company_domain", ""),
        "pipeline_state": fallback_role.get("pipeline_state", "sourced"),
        "updated_at": _now_iso(),
        "last_error": None,
    }


def _upsert_pipeline_row(role: dict[str, Any]) -> None:
    rows = store.read_pipeline()
    now = _now_iso()
    replacement = {
        "role_id": role["role_id"],
        "company_domain": role["company_domain"],
        "pipeline_state": role["pipeline_state"],
        "updated_at": now,
        "last_error": None,
    }
    updated = [row for row in rows if row["role_id"] != role["role_id"]]
    updated.append(replacement)
    updated.sort(key=lambda item: item["role_id"])
    store.write_pipeline(updated, writer_id="human")


def _sync_pipeline_row(row: dict[str, Any], role: dict[str, Any], *, last_error: str | None) -> None:
    rows = store.read_pipeline()
    replacement = dict(row)
    replacement["company_domain"] = role["company_domain"]
    replacement["pipeline_state"] = role["pipeline_state"]
    replacement["updated_at"] = _now_iso()
    replacement["last_error"] = last_error
    updated = [item for item in rows if item["role_id"] != role["role_id"]]
    updated.append(replacement)
    updated.sort(key=lambda item: item["role_id"])
    store.write_pipeline(updated, writer_id="human")


def _delete_company_profile(domain: str | None) -> None:
    if not domain:
        return
    safe = domain.strip().lower()
    if not safe:
        return
    path = store.ROOT / "companies" / f"{safe}.json"
    if path.exists():
        path.unlink()
        store.append_decision(
            {
                "event": "human_deleted_company_profile",
                "agent_id": "human",
                "domain": safe,
            }
        )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    uvicorn.run("ui.app:app", host="127.0.0.1", port=8008, reload=False)


if __name__ == "__main__":
    main()
