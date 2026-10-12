"""scripts/lint_diff.py: which diagnostics a change introduced, fixed, or carried over."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lint_diff.py"
_spec = importlib.util.spec_from_file_location("lint_diff", SCRIPT)
lint_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_diff)


def _ruff(root: Path, row: int, code: str = "E722", message: str = "Do not use bare `except`") -> dict:
    return {"code": code, "filename": str(root / "pkg" / "a.py"), "location": {"row": row}, "message": message}


def test_base_scanned_in_another_worktree_matches_the_same_files(tmp_path):
    """CI scans the base revision in a separate worktree; ruff reports absolute paths."""
    head_root, base_root = tmp_path / "workspace", tmp_path / "lint-base"
    head_root.mkdir()
    base_root.mkdir()
    (head_root / "head.json").write_text(json.dumps([_ruff(head_root, 8), _ruff(head_root, 3, "F401", "`os` unused")]))
    (head_root / "base.json").write_text(json.dumps([_ruff(base_root, 8)]))
    (head_root / "empty.json").write_text("[]")
    out = head_root / "summary.md"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--base-ruff", "base.json", "--head-ruff", "head.json",
         "--base-ty", "empty.json", "--head-ty", "empty.json", "--base-root", str(base_root), "--output", str(out)],
        cwd=head_root, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    ruff_section = out.read_text(encoding="utf-8").split("## ty")[0]
    assert "New issues (1)" in ruff_section
    assert "Fixed issues:** none" in ruff_section
    assert "**Unchanged:** 1 " in ruff_section


def test_a_second_identical_violation_in_one_file_is_new():
    def entry(line: int) -> dict:
        return {"tool": "ruff", "rule": "E722", "path": "pkg/a.py", "line": line, "message": "bare except"}

    new, fixed, unchanged = lint_diff._diff([entry(8)], [entry(8), entry(12)])
    assert (len(new), len(fixed), len(unchanged)) == (1, 0, 1)
    new, fixed, unchanged = lint_diff._diff([entry(8), entry(12)], [entry(8)])
    assert (len(new), len(fixed), len(unchanged)) == (0, 1, 1)
