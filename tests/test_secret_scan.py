from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[1]


def _scan_step() -> dict:
    workflow = yaml.safe_load(
        (REPOSITORY / ".github/workflows/security.yml").read_text(encoding="utf-8")
    )
    return next(
        step
        for step in workflow["jobs"]["audit"]["steps"]
        if step.get("name") == "Scan checkout for secrets"
    )


def _scan_command() -> list[str]:
    command = _scan_step()["run"].split(">", 1)[0].replace("\\\n", "")
    return shlex.split(command)


def _scan(directory: Path) -> dict:
    command = _scan_command()
    result = subprocess.run(
        [sys.executable, *command[1:]],
        cwd=directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "The offline scanner could not run."
    assert not result.stderr, "The scanner must not silently skip unreadable files."
    return json.loads(result.stdout)


def _check_report(tmp_path: Path, report: dict) -> subprocess.CompletedProcess[str]:
    run = _scan_step()["run"]
    checker = run.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    (tmp_path / "detect-secrets-report.json").write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", checker],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_scan_workflow_keeps_utf8_offline_detection_and_narrow_exclusions() -> None:
    step = _scan_step()
    command = _scan_command()
    assert command[:6] == ["python", "-X", "utf8", "-m", "detect_secrets", "scan"]
    assert command[6:9] == ["--all-files", "--no-verify", "--exclude-files"]
    assert len(command) == 10, "Do not add broad exclusions or disable detectors."
    exclusion = command[9]
    for excluded in (".git/config", "tests/test_case.py", r"nested\tests\fixture.txt"):
        assert re.search(exclusion, excluded)
    for included in ("README.md", "README.en.md", "src/pkg.egg-info/PKG-INFO", "contests/a"):
        assert not re.search(exclusion, included)
    assert step["env"]["PYTHONUTF8"] == "1"
    assert '> "$RUNNER_TEMP/detect-secrets-report.json"' in step["run"]


def test_readme_and_installed_metadata_placeholders_are_safe(tmp_path: Path) -> None:
    for filename in ("README.md", "README.en.md"):
        content = (REPOSITORY / filename).read_text(encoding="utf-8")
        assert "<your_api_key>" in content
        assert "example-api-key" not in content
        (tmp_path / filename).write_text(content, encoding="utf-8")

    metadata = tmp_path / "src" / "demo.egg-info" / "PKG-INFO"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        "Metadata-Version: 2.4\nName: synthetic-demo\n\n中文安装元数据示例。\n"
        + (REPOSITORY / "README.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert not _scan(tmp_path)["results"]


@pytest.mark.parametrize("filename", ["README.md", "src/demo.egg-info/PKG-INFO"])
def test_scan_still_detects_tokens_in_unicode_documents(tmp_path: Path, filename: str) -> None:
    # A runtime-only synthetic token proves the fix does not suppress real-shaped findings.
    token = "ghp_" + secrets.token_hex(20)
    document = tmp_path / filename
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(f"中文离线测试。\nGITHUB_TOKEN={token}\n", encoding="utf-8")

    report = _scan(tmp_path)

    assert report["results"], "Expected a finding for the runtime-only synthetic token."
    normalized_results = {
        Path(path).as_posix(): findings for path, findings in report["results"].items()
    }
    assert any(item["line_number"] == 2 for item in normalized_results[filename])
    if token in json.dumps(report):
        pytest.fail("The scanner report disclosed the runtime-only synthetic token.")


def test_report_checker_succeeds_only_for_no_findings(tmp_path: Path) -> None:
    result = _check_report(tmp_path, {"results": {}})

    assert result.returncode == 0
    assert result.stdout.strip() == "detect-secrets found no unaudited results."
    assert not result.stderr


def test_report_checker_prints_only_location_and_type_of_findings(tmp_path: Path) -> None:
    token = secrets.token_hex(20)
    secret_hash = secrets.token_hex(20)
    report = {
        "results": {
            "README.md": [
                {
                    "line_number": 17,
                    "type": "Secret Keyword",
                    "hashed_secret": secret_hash,
                    "secret": token,
                    "arbitrary_metadata": "must-not-be-logged",
                }
            ],
            "README.en.md": [{"line_number": 19, "type": "Secret Keyword"}],
        }
    }

    result = _check_report(tmp_path, report)

    assert result.returncode == 1
    assert not result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "detect-secrets found 2 unaudited result(s)."
    assert {json.dumps(json.loads(line), sort_keys=True) for line in lines[1:]} == {
        json.dumps({"file": "README.md", "line": 17, "type": "Secret Keyword"}, sort_keys=True),
        json.dumps({"file": "README.en.md", "line": 19, "type": "Secret Keyword"}, sort_keys=True),
    }
    if any(value in result.stdout for value in (token, secret_hash, "hashed_secret")):
        pytest.fail("The report checker disclosed sensitive finding data.")


def test_report_checker_does_not_accept_missing_results(tmp_path: Path) -> None:
    result = _check_report(tmp_path, {})

    assert result.returncode != 0
    assert "no unaudited results" not in result.stdout
