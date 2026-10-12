"""A name freed by ``profile delete`` must be usable again by every path that creates a profile dir.

``delete_profile`` leaves a tombstone beside the profile dir; ``create_profile`` clears it, and
rename/import onto the same name have to as well, or the profile exists on disk but is unlisted,
unresolvable via ``-p`` and refused by ``profile create``.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.profiles import (
    create_profile, delete_profile, export_profile, import_profile, list_profile_names,
    profile_exists, rename_profile, resolve_profile_env,
)


@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    default_home = tmp_path / ".hermes"
    default_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(default_home))
    return tmp_path


def test_rename_onto_previously_deleted_name_is_live(profile_env):
    create_profile("alpha", no_alias=True)
    delete_profile("alpha", yes=True)
    create_profile("beta", no_alias=True)

    with patch("hermes_cli.profiles.check_alias_collision", return_value="skip"):
        new_dir = rename_profile("beta", "alpha")

    assert new_dir.is_dir()
    assert profile_exists("alpha")
    assert "alpha" in list_profile_names()
    assert resolve_profile_env("alpha") == str(new_dir)


def test_import_onto_previously_deleted_name_is_live(profile_env):
    create_profile("gamma", no_alias=True)
    archive = export_profile("gamma", str(profile_env / "gamma-backup.tar.gz"))
    delete_profile("gamma", yes=True)

    restored = import_profile(str(archive))

    assert restored.is_dir()
    assert profile_exists("gamma")
    assert "gamma" in list_profile_names()
