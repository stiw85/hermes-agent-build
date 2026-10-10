"""``@folder:`` renders a tree: every entry sits under its parent and the folder is not its own child."""

import subprocess
from pathlib import Path

import pytest

from agent import context_references
from agent.context_references import preprocess_context_references

_EXPECTED = [
    "proj/",
    "- README.md",
    "- docs/",
    "  - guide.md",
    "- src/",
    "  - core/",
    "    - util.py",
    "  - main.py",
    "- zz.txt",
]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel in ("README.md", "docs/guide.md", "src/main.py", "src/core/util.py", "zz.txt"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    return root


def _listing(tree: Path) -> list[str]:
    result = preprocess_context_references("@folder:proj", cwd=tree.parent, context_length=100_000)
    assert not result.warnings
    block = result.message.split("--- Attached Context ---\n\n", 1)[1]
    return [line.split(" (", 1)[0] for line in block.split("\n")[1:]]


def test_ripgrep_listing_nests_entries_under_their_parent(tree: Path):
    assert _listing(tree) == _EXPECTED


def test_walk_fallback_listing_nests_entries_under_their_parent(tree: Path, monkeypatch):
    real_popen = subprocess.Popen

    def no_rg(cmd, *args, **kwargs):
        if cmd[0] == "rg":
            raise FileNotFoundError("rg")
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(context_references.subprocess, "Popen", no_rg)
    assert _listing(tree) == _EXPECTED
