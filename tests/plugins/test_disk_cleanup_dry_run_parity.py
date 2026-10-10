"""disk-cleanup ``dry_run()`` previews exactly what ``quick()`` deletes: an entry
``quick()`` re-classifies and refuses is not listed as an auto-delete."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def dg(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    lib = Path(__file__).resolve().parents[2] / "plugins" / "disk-cleanup" / "disk_cleanup.py"
    spec = importlib.util.spec_from_file_location("disk_cleanup_dry_run_parity", lib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, home


def test_dry_run_omits_test_entry_that_quick_refuses(dg):
    mod, home = dg
    scratch = home / "scratch"
    scratch.mkdir()
    kept = scratch / "report_draft.json"  # stored as "test", but not a test_* name
    kept.write_text("{}", encoding="utf-8")
    disposable = scratch / "test_probe.py"
    disposable.write_text("x", encoding="utf-8")
    mod.track(str(kept), "test", silent=True)
    mod.track(str(disposable), "test", silent=True)

    auto, _prompt = mod.dry_run()
    previewed = sorted(Path(item["path"]).name for item in auto)
    summary = mod.quick()

    assert previewed == ["test_probe.py"]
    assert summary["deleted"] == len(previewed)
    assert kept.exists() and not disposable.exists()
