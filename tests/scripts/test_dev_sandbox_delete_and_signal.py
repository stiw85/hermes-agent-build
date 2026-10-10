"""dev-sandbox.sh: --delete needs no command, and a signal ends the run with one cleanup."""
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev-sandbox.sh"


def _env(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("HERMES_DEV_SANDBOX_")}
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    env["TMPDIR"] = str(scratch)
    return env, scratch


def _checkout(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, stdin=subprocess.DEVNULL, timeout=10)
    return checkout


@pytest.mark.platforms("posix")
def test_delete_alone_removes_the_persistent_sandbox(tmp_path):
    checkout = _checkout(tmp_path)
    env, _ = _env(tmp_path)
    state = checkout / ".hermes-sandbox" / "hermes-home" / "marker"
    state.parent.mkdir(parents=True)
    state.write_text("kept", encoding="utf-8")
    declined = subprocess.run(["bash", str(SCRIPT), "--delete"], cwd=checkout, env=env, input="n\n",
                              capture_output=True, text=True, timeout=20)
    assert declined.returncode == 1 and state.exists()
    assert "Usage:" not in declined.stderr
    confirmed = subprocess.run(["bash", str(SCRIPT), "--delete"], cwd=checkout, env=env, input="y\n",
                               capture_output=True, text=True, timeout=20)
    assert confirmed.returncode == 0, confirmed.stderr
    assert not (checkout / ".hermes-sandbox").exists()


@pytest.mark.platforms("posix")
def test_term_during_the_command_exits_130_after_one_cleanup(tmp_path):
    checkout = _checkout(tmp_path)
    env, scratch = _env(tmp_path)
    # The command signals the sandbox script (its parent) and then returns, as a Ctrl-C'd child does.
    probe = "import os, signal, time; os.kill(os.getppid(), signal.SIGTERM); time.sleep(0.5)"
    result = subprocess.run(["bash", str(SCRIPT), "--", sys.executable, "-c", probe], cwd=checkout, env=env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert result.returncode == 130, result.stderr
    assert "chmod" not in result.stderr
    assert list(scratch.iterdir()) == []
