from __future__ import annotations

import json
from pathlib import Path

from scripts import preflight_check


def _write_valid_setup(root: Path) -> None:
    (root / "config").mkdir()
    (root / "cv.md").write_text("# CV\n", encoding="utf-8")
    (root / "config" / "profile.yml").write_text("identity:\n  name: Dima\n", encoding="utf-8")
    (root / "rubric.json").write_text(
        json.dumps({"_meta": {"version": "0.3"}}),
        encoding="utf-8",
    )
    (root / "voice_pack.md").write_text("# Voice\n", encoding="utf-8")


def test_preflight_passes_when_required_files_exist(tmp_path: Path, capsys) -> None:
    _write_valid_setup(tmp_path)

    assert preflight_check.main([str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "[PASS] cv.md — found" in output
    assert "[PASS] rubric.json — found, version 0.3" in output
    assert "All checks passed. Pipeline ready." in output


def test_preflight_warns_but_passes_without_voice_pack(tmp_path: Path, capsys) -> None:
    _write_valid_setup(tmp_path)
    (tmp_path / "voice_pack.md").unlink()

    assert preflight_check.main([str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "[WARN] voice_pack.md — file not found" in output
    assert "All required checks passed. 1 warning(s). Pipeline ready." in output


def test_preflight_fails_with_full_picture_for_missing_required_files(
    tmp_path: Path, capsys
) -> None:
    _write_valid_setup(tmp_path)
    (tmp_path / "cv.md").unlink()
    (tmp_path / "rubric.json").write_text("{}", encoding="utf-8")

    assert preflight_check.main([str(tmp_path)]) == 1

    output = capsys.readouterr().out
    assert "[FAIL] cv.md — file not found" in output
    assert "version field missing at _meta.version" in output
    assert "2 check(s) failed. Enter onboarding mode: see onboarding/ONBOARDING.md" in output


def test_preflight_fails_on_invalid_profile_yaml(tmp_path: Path, capsys) -> None:
    _write_valid_setup(tmp_path)
    (tmp_path / "config" / "profile.yml").write_text("identity: [\n", encoding="utf-8")

    assert preflight_check.main([str(tmp_path)]) == 1

    output = capsys.readouterr().out
    assert "[FAIL] config/profile.yml — found but YAML parse error:" in output
