"""run-workspace-checks.mjs never reports green over a concurrency value that starts no worker."""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "run-workspace-checks.mjs"


@pytest.mark.parametrize("args", [["--concurrency", "abc"], ["--concurrency"]])
def test_non_numeric_concurrency_is_a_usage_error(args):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    # Rejected before any workspace is read, so no check starts and npm is not needed.
    result = subprocess.run([node, str(SCRIPT), *args], cwd=SCRIPT.parents[2], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "--concurrency" in result.stderr
    assert "checks passed" not in result.stdout
