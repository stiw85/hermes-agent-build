"""Alias wrappers stay recognisable when the ``hermes`` executable path needs shell quoting.

The POSIX wrapper is ``exec <shlex.quote(path)> -p <profile> "$@"``; with a space in the path
the quote sits between ``hermes`` and ``-p``. The readers must still see it as a Hermes wrapper,
or delete/rename orphan it and ``profile list`` loses the alias.
"""

from pathlib import Path

import pytest

from hermes_cli import profiles
from hermes_cli.profiles import build_alias_map, create_wrapper_script, find_alias_for_profile, remove_wrapper_script

pytestmark = pytest.mark.platforms("posix")


@pytest.fixture()
def spaced_hermes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    exe = tmp_path / "my tools" / "bin" / "hermes"
    monkeypatch.setattr(profiles.shutil, "which", lambda name: str(exe) if name == "hermes" else None)
    return exe


def test_wrapper_with_quoted_path_is_found_and_removed(spaced_hermes):
    wrapper = create_wrapper_script("coder")
    assert f"'{spaced_hermes}' -p coder" in wrapper.read_text(encoding="utf-8")

    assert find_alias_for_profile("coder") == "coder"
    assert remove_wrapper_script("coder") is True
    assert not wrapper.exists()


def test_custom_alias_with_quoted_path_maps_to_its_profile(spaced_hermes):
    create_wrapper_script("c", target="coder")

    assert build_alias_map() == {"coder": "c"}
