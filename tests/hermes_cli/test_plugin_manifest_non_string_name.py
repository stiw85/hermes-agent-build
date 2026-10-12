"""A plugin.yaml whose ``name`` is not a string must not take the other plugins down.

``name: [a]`` used to reach the registry as an unhashable key: discovery raised for every
plugin, and ``hermes plugins list`` died on the same manifest.
"""

import os
from pathlib import Path

import pytest

from hermes_cli.plugins import PluginManager


def _plugin(root: Path, directory: str, manifest: str) -> None:
    plugin_dir = root / directory
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(manifest)
    (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n")


@pytest.fixture
def user_plugins() -> Path:
    home = Path(os.environ["HERMES_HOME"])  # the hermetic conftest sandbox
    (home / "config.yaml").write_text("plugins:\n  enabled: [good]\n")
    _plugin(home / "plugins", "good", "name: good\nversion: 1.0.0\n")
    return home / "plugins"


@pytest.mark.parametrize("name_line", ["name: [a]", "name: {a: b}", "name: 5", "name:"])
def test_bad_name_falls_back_to_the_directory_and_spares_the_rest(user_plugins, name_line):
    _plugin(user_plugins, "odd", f"{name_line}\nversion: 1.0.0\n")

    manager = PluginManager()
    manager.discover_and_load()

    assert manager._plugins["good"].enabled is True
    assert manager._plugins["odd"].manifest.name == "odd"


@pytest.mark.parametrize("name_line", ["name: [a]", "name:"])
def test_plugins_list_scan_survives_a_bad_name(user_plugins, name_line):
    from hermes_cli.plugins_cmd import _discover_all_plugins

    _plugin(user_plugins, "odd", f"{name_line}\nversion: 1.0.0\n")

    keys = {entry[5] for entry in _discover_all_plugins()}

    assert {"good", "odd"} <= keys
