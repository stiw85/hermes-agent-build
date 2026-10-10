"""``hermes_yaml.safe_dump`` output must reload to the value that was dumped, without noise.

Same class as #119844 (a fold right after an escape reloads with an extra space), on the
emitter behind ``atomic_yaml_write``: profile descriptions, blueprint prompts, skins.
"""

import io
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import hermes_yaml as yaml
from utils import atomic_yaml_write

# Forced into double quotes by the tab, long enough to cross the fold column inside the path.
_WINDOWS_PATH_NOTE = (
    "Build agent.\tWorks in C:\\Users\\dev\\projects\\hermes-agent\\build\\output\\nightly and ships every night"
)


@pytest.mark.parametrize("value", [
    _WINDOWS_PATH_NOTE,
    "x xxxxxxxxxxxxxxxxxxxx\\xxxxxxxxxxxx\"xxxxxxxxxxxxxxx xxxxxxxxx\t\txxxxxxxxx\\x x",
])
def test_safe_dump_round_trips_long_escaped_strings(value):
    data = {"description": value, "items": [value]}
    assert yaml.safe_load(yaml.safe_dump(data, sort_keys=False)) == data


def test_atomic_yaml_write_preserves_a_windows_path_value(tmp_path):
    path = tmp_path / "profile.yaml"
    atomic_yaml_write(path, {"description": _WINDOWS_PATH_NOTE}, sort_keys=False)
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"description": _WINDOWS_PATH_NOTE}


@pytest.mark.parametrize("value", [1e-05, 3e-06, 1e16, 1.5e300])
def test_exponent_floats_written_by_hermes_reload_without_warnings(value):
    """``hermes config set x 0.00001`` stores ``1e-05``; reading it back must stay silent."""
    edited = io.StringIO()
    yaml.roundtrip_yaml().dump({"value": value}, edited)
    with warnings.catch_warnings(record=True) as caught:
        assert yaml.safe_load(yaml.safe_dump({"value": value})) == {"value": value}
        assert yaml.safe_load(edited.getvalue()) == {"value": value}
        assert yaml.roundtrip_yaml().load(edited.getvalue())["value"] == value
    assert caught == []


def test_hand_written_exponent_float_loads_silently_in_a_fresh_interpreter():
    """A config that already holds ``1e-5`` must not print a parser warning on every command."""
    result = subprocess.run(
        [sys.executable, "-c", "import hermes_yaml; print(hermes_yaml.safe_load('value: 1e-5')['value'])"],
        cwd=Path(yaml.__file__).parent, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "1e-05", "")
