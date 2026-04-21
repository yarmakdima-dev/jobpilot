"""Flat-file state store for JobPilot."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from orchestrator.lanes import LaneViolationError, normalize_path, require_lane


ROOT = Path(os.environ.get("JOBPILOT_ROOT", ".")).resolve()
ROLE_SCHEMA_PATH = ROOT / "schemas" / "role.schema.json"
PIPELINE_SCHEMA_PATH = ROOT / "schemas" / "pipeline.schema.json"
COMPANY_SCHEMA_PATH = ROOT / "company_profile_schema.json"


def read_role(role_id: str) -> dict[str, Any]:
    """Read a role record by ID."""
    return _read_json(_role_path(role_id))


def write_role(role_id: str, data: dict[str, Any], writer_id: str) -> None:
    """Validate and atomically write a role record."""
    path = _role_path(role_id)
    _require_lane_logged(writer_id, path)
    if data.get("role_id") != role_id:
        raise ValidationError("role_id in data must match the target role_id")

    with _file_lock(path):
        existing = _read_json(path) if path.exists() else None
        _validate_role_scope_logged(writer_id, path, existing, data)
        _validate_json_schema(data, ROLE_SCHEMA_PATH)
        _atomic_write_json(path, data)


def read_company(domain: str) -> dict[str, Any]:
    """Read a company profile by domain."""
    return _read_json(_company_path(domain))


def write_company(domain: str, data: dict[str, Any], writer_id: str) -> None:
    """Validate and atomically write a company profile."""
    path = _company_path(domain)
    _require_lane_logged(writer_id, path)
    _validate_json_schema(data, COMPANY_SCHEMA_PATH)
    with _file_lock(path):
        _atomic_write_json(path, data)


def append_decision(entry: dict[str, Any]) -> None:
    """Append a newline-delimited JSON decision entry."""
    path = ROOT / "decisions.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(entry)
    payload.setdefault("at", _now_iso())

    with _file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def read_pipeline() -> list[dict[str, Any]]:
    """Read the active pipeline table."""
    path = ROOT / "pipeline.json"
    if not path.exists():
        return []
    data = _read_json(path)
    _validate_json_schema(data, PIPELINE_SCHEMA_PATH)
    return data


def write_pipeline(data: list[dict[str, Any]], writer_id: str) -> None:
    """Validate and atomically write the active pipeline table."""
    path = ROOT / "pipeline.json"
    _require_lane_logged(writer_id, path)
    _validate_json_schema(data, PIPELINE_SCHEMA_PATH)
    with _file_lock(path):
        _atomic_write_json(path, data)


def _role_path(role_id: str) -> Path:
    return ROOT / "roles" / f"{role_id}.json"


def _company_path(domain: str) -> Path:
    safe_domain = domain.strip().lower()
    if "/" in safe_domain or safe_domain in {"", ".", ".."}:
        raise ValueError(f"invalid company domain: {domain!r}")
    return ROOT / "companies" / f"{safe_domain}.json"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_json_schema(data: Any, schema_path: Path) -> None:
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(data)


def _validate_role_scope(
    writer_id: str, existing: dict[str, Any] | None, new_data: dict[str, Any]
) -> None:
    if writer_id == "A1":
        if existing is not None:
            raise LaneViolationError("A1 may create role records, not update them")
        return

    if writer_id in {"F1", "F2", "A6"} and existing is None:
        raise LaneViolationError(f"{writer_id} may update existing roles only")

    if writer_id == "F1":
        _require_changed_paths_within(existing or {}, new_data, ("filter_status.f1",))
    elif writer_id == "F2":
        _require_changed_paths_within(existing or {}, new_data, ("filter_status.f2",))
    elif writer_id == "A6":
        _require_changed_paths_within(existing or {}, new_data, ("debrief_ref",))


def _validate_role_scope_logged(
    writer_id: str,
    path: Path,
    existing: dict[str, Any] | None,
    new_data: dict[str, Any],
) -> None:
    try:
        _validate_role_scope(writer_id, existing, new_data)
    except LaneViolationError as exc:
        append_decision(
            {
                "event": "lane_violation",
                "writer_id": writer_id,
                "path": normalize_path(path.relative_to(ROOT)),
                "reason": str(exc),
            }
        )
        raise


def _require_changed_paths_within(
    old: dict[str, Any], new: dict[str, Any], allowed_prefixes: tuple[str, ...]
) -> None:
    changed_paths = _changed_paths(old, new)
    illegal = [
        path
        for path in changed_paths
        if not any(path == prefix or path.startswith(f"{prefix}.") for prefix in allowed_prefixes)
    ]
    if illegal:
        raise LaneViolationError(
            f"write attempted outside allowed role fields: {', '.join(sorted(illegal))}"
        )


def _changed_paths(old: Any, new: Any, prefix: str = "") -> set[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        paths: set[str] = set()
        for key in old.keys() | new.keys():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.update(_changed_paths(old.get(key), new.get(key), child_prefix))
        return paths
    if old != new:
        return {prefix}
    return set()


def _require_lane_logged(writer_id: str, path: Path) -> None:
    try:
        require_lane(writer_id, path.relative_to(ROOT))
    except LaneViolationError as exc:
        append_decision(
            {
                "event": "lane_violation",
                "writer_id": writer_id,
                "path": normalize_path(path.relative_to(ROOT)),
                "reason": str(exc),
            }
        )
        raise


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
