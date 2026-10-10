"""The installers, the Docker first boot and ``hermes doctor --fix`` copy cli-config.yaml.example to
config.yaml verbatim, so an uncommented value there is every fresh install's setting. A seeded home
must keep the pre-update safety snapshot exactly as a home with no config.yaml does."""

from argparse import Namespace
from pathlib import Path

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _resolved_mode() -> str:
    from hermes_cli.update_cmd_maint import _resolve_pre_update_backup_mode

    return _resolve_pre_update_backup_mode(Namespace(no_backup=False, backup=False))


def test_seeded_config_keeps_the_default_pre_update_backup_mode(hermes_home):
    from hermes_cli.config import seed_config_file

    without_config = _resolved_mode()
    assert seed_config_file(hermes_home / "config.yaml")  # the shipped template was copied

    assert _resolved_mode() == without_config


def test_seeded_config_still_takes_the_pre_update_snapshot(hermes_home):
    from hermes_cli.config import seed_config_file
    from hermes_cli.update_cmd import _run_pre_update_backup

    assert seed_config_file(hermes_home / "config.yaml")

    snapshot_id = _run_pre_update_backup(Namespace(no_backup=False, backup=False))

    assert snapshot_id
    assert (hermes_home / "state-snapshots" / snapshot_id).is_dir()
