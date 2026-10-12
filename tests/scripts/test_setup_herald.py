"""scripts/setup-herald.sh: valid bash, and a dry run plans the right steps in the right order.

The real run (install + Herald bootstrap + launcher) needs the network and half a gigabyte of
dependencies, so these tests exercise the plan, not the installs: HERALD_SETUP_DRY_RUN=1 prints
every step it would take and changes nothing.
"""
from pathlib import Path
import os
import subprocess

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "setup-herald.sh"


def _dry_run(home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(home),
        "HERALD_SETUP_DRY_RUN": "1",
    }
    env.pop("HERMES_HOME", None)
    env.pop("HERMES_INSTALL_DIR", None)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False
    )


def test_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_dry_run_plans_install_bootstrap_and_launcher(tmp_path):
    result = _dry_run(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # The fork and branch are the defaults, and the installer is the one beside the script.
    install_at = out.index("scripts/install.sh --branch claude/native-memory")
    assert "HERMES_REPO_URL=https://github.com/stiw85/hermes-agent-build.git" in out
    # Herald's own bootstrap runs from the installed checkout, after the install.
    bootstrap_at = out.index("integrations/herald-os/scripts/bootstrap.sh")
    launcher_at = out.index(f"write {tmp_path}/.local/bin/herald")
    assert install_at < bootstrap_at < launcher_at
    assert "write" in out and "herald-os.desktop" in out
    # A dry run must not create anything.
    assert not (tmp_path / ".hermes").exists()
    assert not (tmp_path / ".local").exists()


def test_dry_run_honours_repo_and_branch_overrides(tmp_path):
    result = _dry_run(
        tmp_path,
        {
            "HERMES_REPO_URL": "https://github.com/example/hermes-fork.git",
            "HERMES_BRANCH": "my-branch",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "HERMES_REPO_URL=https://github.com/example/hermes-fork.git" in result.stdout
    assert "--branch my-branch" in result.stdout
