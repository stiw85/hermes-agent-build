"""``hermes skills update`` skips locally edited hub skills; running one is not an edit.

A helper script that imports a sibling module leaves ``__pycache__`` behind. Bundled skills
already ignore such runtime caches when deciding "user-modified"; hub skills must too.
"""

import pytest

from hermes_cli.skills_hub import _has_local_edits
from tools.skills_guard import scan_skill
from tools.skills_hub import HubLockFile
from tools.skills_hub_install import install_from_quarantine, quarantine_bundle
from tools.skills_hub_models import SkillBundle

FILES = {
    "SKILL.md": "---\nname: demo\ndescription: d.\n---\nRun scripts/run.py\n",
    "scripts/run.py": "import helper\nprint(helper.X)\n",
    "scripts/helper.py": "X = 1\n",
}


@pytest.fixture
def installed(monkeypatch, tmp_path):
    import tools.skills_hub as hub

    hub_dir = tmp_path / "skills" / ".hub"
    monkeypatch.setattr(hub, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(hub, "HUB_DIR", hub_dir)
    monkeypatch.setattr(hub, "LOCK_FILE", hub_dir / "lock.json")
    monkeypatch.setattr(hub, "QUARANTINE_DIR", hub_dir / "quarantine")
    monkeypatch.setattr(hub, "AUDIT_LOG", hub_dir / "audit.log")
    monkeypatch.setattr(hub, "TAPS_FILE", hub_dir / "taps.json")
    monkeypatch.setattr(hub, "INDEX_CACHE_DIR", hub_dir / "index-cache")

    def install(files: dict):
        bundle = SkillBundle(name="demo", files=files, source="github", identifier="o/r/demo",
                             trust_level="community", metadata={})
        quarantined = quarantine_bundle(bundle)
        skill_dir = install_from_quarantine(quarantined, "demo", "", bundle, scan_skill(quarantined, "o/r/demo"))
        return skill_dir, HubLockFile().get_installed("demo")
    return install


def _leave_bytecode(skill_dir) -> None:
    cache = skill_dir / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "helper.cpython-313.pyc").write_bytes(b"\x00bytecode")


def test_runtime_cache_is_not_a_local_edit(installed):
    skill_dir, entry = installed(FILES)
    assert _has_local_edits(entry) is False

    _leave_bytecode(skill_dir)

    assert _has_local_edits(entry) is False


def test_a_real_edit_is_still_detected_next_to_a_runtime_cache(installed):
    skill_dir, entry = installed(FILES)
    _leave_bytecode(skill_dir)

    (skill_dir / "scripts" / "helper.py").write_text("X = 2\n")

    assert _has_local_edits(entry) is True


def test_a_bundle_that_ships_cache_files_is_pristine_as_installed(installed):
    _skill_dir, entry = installed({**FILES, "scripts/__pycache__/vendored.pyc": b"\x00shipped"})

    assert _has_local_edits(entry) is False
