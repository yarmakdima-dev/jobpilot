"""Minimal FastAPI operator console for JobPilot."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from orchestrator import report, runner, store


APP_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="JobPilot Console")


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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    roles = _load_roles()
    rows = _build_role_rows(roles)
    latest_report = _latest_report_path()
    counters = _build_counters(rows)
    queue = {
        "blocked": [row for row in rows if row.pipeline_state == "f2_blocked"],
        "ready": [row for row in rows if row.pipeline_state == "ready_to_submit"],
        "errors": [row for row in rows if row.pipeline_state in {"error", "research_failed"}],
    }
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "rows": rows,
            "counters": counters,
            "queue": queue,
            "latest_report": latest_report.name if latest_report else None,
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
    return TEMPLATES.TemplateResponse(
        request,
        "role_detail.html",
        {
            "role": role,
            "company": company,
            "company_json": _pretty_json(company),
            "role_json": _pretty_json(role),
            "synthesis_json": _pretty_json((company or {}).get("360_synthesis")),
            "judgment_calls": role.get("gate_needs_judgment_call") or [],
            "decisions": decisions,
        },
    )


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
            if all(cell.startswith("---") or cell.endswith("---:") or cell == "---:" for cell in cells):
                continue
            tag = "th" if not any("<tr>" in row for row in out[-1:]) and len(out) >= 1 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</tbody></table>")
            in_table = False

        if not stripped:
            out.append("")
            continue

        if stripped.startswith("# "):
            out.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            out.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            out.append(f"<p>&bull; {html.escape(stripped[2:])}</p>")
        else:
            out.append(f"<p>{html.escape(stripped)}</p>")

    if in_table:
        out.append("</tbody></table>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def main() -> None:
    uvicorn.run("ui.app:app", host="127.0.0.1", port=8008, reload=False)


if __name__ == "__main__":
    main()
