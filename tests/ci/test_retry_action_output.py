"""The retry action shows what a failed attempt printed, and still retries and captures."""
import os
import subprocess
from pathlib import Path

import pytest
import hermes_yaml as yaml

ROOT = Path(__file__).resolve().parents[2]


def _retry(tmp_path, command, attempts="2"):
    action = yaml.safe_load((ROOT / ".github/actions/retry/action.yml").read_text(encoding="utf-8"))
    (step,) = action["runs"]["steps"]
    output = tmp_path / "github-output"
    output.touch()
    env = {**os.environ, "_CMD": command, "_ATTEMPTS": attempts, "_DELAY": "0", "GITHUB_OUTPUT": str(output)}
    result = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=60)
    return result, output.read_text(encoding="utf-8")


@pytest.mark.platforms("posix")
def test_failed_attempts_show_their_stdout(tmp_path):
    result, captured = _retry(tmp_path, "printf 'diag%s\\n' nostic; exit 3")
    assert result.returncode == 1
    assert result.stdout.count("diagnostic\n") == 2  # one per attempt; the echoed command never spells it
    assert captured == ""


@pytest.mark.platforms("posix")
def test_success_after_a_failure_captures_only_the_successful_stdout(tmp_path):
    command = "if [ -e seen ]; then echo second; else touch seen; echo first; exit 1; fi"
    result, captured = _retry(tmp_path, command, attempts="3")
    assert result.returncode == 0
    assert "attempt 2/3" in result.stdout and "attempt 3/3" not in result.stdout
    assert captured == "stdout<<__RETRY_STDOUT_EOF__\nsecond\n__RETRY_STDOUT_EOF__\n"
