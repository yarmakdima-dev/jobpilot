"""Write-lane enforcement for JobPilot user-layer files."""

from __future__ import annotations

from pathlib import Path


class LaneViolationError(PermissionError):
    """Raised when an actor attempts to write outside its allowed lane."""


WRITE_LANES: dict[str, tuple[str, ...]] = {
    "A0": ("companies/*.json",),
    "A1": ("roles/*.json",),
    "F1": ("roles/*.json",),
    "F2": ("roles/*.json",),
    "A2": ("output/*",),
    "A3": ("output/*",),
    "A6": ("reports/*", "roles/*.json"),
    "A7": ("decisions.log", "companies/*.json"),
    "A8": ("inbox_events/*",),
    "human": (
        "cv.md",
        "voice_pack.md",
        "config/profile.yml",
        "rubric.json",
        "pipeline.json",
        "roles/*.json",
        "companies/*.json",
        "decisions.log",
    ),
    "system": ("pipeline.json", "decisions.log", "roles/*.json"),
}


def normalize_path(path: str | Path) -> str:
    """Return a stable repo-relative path string for lane checks."""
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(Path.cwd())
        except ValueError:
            pass
    return candidate.as_posix()


def check_lane(writer_id: str, path: str | Path) -> bool:
    """Return whether ``writer_id`` may write ``path`` under the data contract."""
    normalized = normalize_path(path)
    return any(Path(normalized).match(pattern) for pattern in WRITE_LANES.get(writer_id, ()))


def require_lane(writer_id: str, path: str | Path) -> None:
    """Raise if ``writer_id`` cannot write ``path``."""
    if not check_lane(writer_id, path):
        normalized = normalize_path(path)
        raise LaneViolationError(
            f"{writer_id!r} is not allowed to write {normalized!r}"
        )
