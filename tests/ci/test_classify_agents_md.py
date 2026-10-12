"""An AGENTS.md edit reaches the lint lane, whose size guard caps every tracked AGENTS.md."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "classify_changes.py"
_spec = importlib.util.spec_from_file_location("classify_changes", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.mark.parametrize("files", [["AGENTS.md"], ["tools/AGENTS.md"], ["gateway/AGENTS.md", "README.md"]])
def test_agents_md_change_runs_the_python_lints(files):
    assert _mod.classify(files)["python"] is True


def test_other_prose_still_skips_python():
    assert _mod.classify(["README.md", "docs/guide.md"])["python"] is False
