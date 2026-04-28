#!/usr/bin/env python3
"""Read-only JobPilot pre-flight check."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in missing dependency envs
    yaml = None


def main(argv: list[str] | None = None) -> int:
    """Run the pre-flight check and return a process exit code."""
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else ".").resolve()

    print("JobPilot Pre-Flight Check")
    print("=========================")

    fails = 0
    warns = 0

    ok, message = _check_cv(root)
    print(message)
    fails += 0 if ok else 1

    ok, message = _check_profile(root)
    print(message)
    fails += 0 if ok else 1

    ok, message = _check_rubric(root)
    print(message)
    fails += 0 if ok else 1

    ok, message = _check_voice_pack(root)
    print(message)
    warns += 0 if ok else 1

    print()
    if fails:
        print(f"{fails} check(s) failed. Enter onboarding mode: see onboarding/ONBOARDING.md")
        return 1
    if warns:
        print(f"All required checks passed. {warns} warning(s). Pipeline ready.")
        return 0
    print("All checks passed. Pipeline ready.")
    return 0


def _check_cv(root: Path) -> tuple[bool, str]:
    path = root / "cv.md"
    if _is_file(path):
        return True, "[PASS] cv.md — found"
    return False, f"[FAIL] cv.md — file not found at {path}"


def _check_profile(root: Path) -> tuple[bool, str]:
    path = root / "config" / "profile.yml"
    if not _is_file(path):
        return False, f"[FAIL] config/profile.yml — file not found at {path}"
    if yaml is None:
        return (
            False,
            "[FAIL] config/profile.yml — ERROR: PyYAML is required. "
            "Install with: pip install pyyaml",
        )
    try:
        with path.open(encoding="utf-8") as handle:
            yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        return False, f"[FAIL] config/profile.yml — found but YAML parse error: {exc}"
    return True, "[PASS] config/profile.yml — found and parseable"


def _check_rubric(root: Path) -> tuple[bool, str]:
    path = root / "rubric.json"
    if not _is_file(path):
        return False, f"[FAIL] rubric.json — file not found at {path}"
    try:
        with path.open(encoding="utf-8") as handle:
            rubric: Any = json.load(handle)
    except json.JSONDecodeError as exc:
        return False, f"[FAIL] rubric.json — found but JSON parse error: {exc}"

    version = None
    if isinstance(rubric, dict):
        meta = rubric.get("_meta")
        if isinstance(meta, dict):
            version = meta.get("version")
    if not isinstance(version, str) or not version.strip():
        return (
            False,
            "[FAIL] rubric.json — found and parseable, but version field "
            "missing at _meta.version",
        )
    return True, f"[PASS] rubric.json — found, version {version}"


def _check_voice_pack(root: Path) -> tuple[bool, str]:
    path = root / "voice_pack.md"
    if _is_file(path):
        return True, "[PASS] voice_pack.md — found"
    return (
        False,
        "[WARN] voice_pack.md — file not found (non-blocking; Layer 2 pending)",
    )


def _is_file(path: Path) -> bool:
    return path.exists() and path.is_file()


if __name__ == "__main__":
    raise SystemExit(main())
