"""The vendored Herald OS bridge is discovered by Hermes, stays off until enabled, and then registers its tools.

Real imports in subprocesses against a temporary HERMES_HOME, so the plugin loader and the
``plugins enable`` CLI run exactly as a user's install would.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BRIDGE = REPO / "integrations" / "herald-os" / "plugins" / "herald-os-bridge"

_DISCOVER = """
import json
from hermes_cli import plugins as P
mgr = P.PluginManager()
mgr.discover_and_load(force=True)
p = mgr._plugins["herald-os-bridge"]
print(json.dumps({
    "enabled": bool(p.enabled),
    "error": p.error,
    "tools": sorted(getattr(p, "tools_registered", None) or getattr(p, "tools", None) or []),
}))
"""


def _env(home: Path) -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HERMES_RUNTIME_DIR"] = str(home.parent / "runtime")
    env["PYTHONPATH"] = str(REPO)
    return env


def _run(args, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=REPO, env=_env(home),
        capture_output=True, text=True, timeout=110,
    )


@pytest.fixture
def home(tmp_path):
    if not BRIDGE.is_dir():
        pytest.skip("integrations/herald-os is not vendored in this checkout")
    home = tmp_path / "home"
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "herald-os-bridge").symlink_to(BRIDGE, target_is_directory=True)
    return home


def _discover(home: Path) -> dict:
    result = _run(["-c", _DISCOVER], home)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_bridge_stays_off_until_the_user_enables_it(home):
    state = _discover(home)
    assert state["enabled"] is False
    assert "not enabled in config" in state["error"]


def test_enabling_the_bridge_registers_its_system_tools(home):
    enable = _run(["-m", "hermes_cli.main", "plugins", "enable", "herald-os-bridge"], home)
    assert enable.returncode == 0, enable.stderr[-2000:]

    state = _discover(home)
    assert state["enabled"] is True
    assert state["error"] is None
    assert {"system_info", "system_processes", "system_files", "canvas"} <= set(state["tools"])
