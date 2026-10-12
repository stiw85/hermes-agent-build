"""A change to the Termux runtime-lib pin table reaches the archive job and the build caches."""
import re
from pathlib import Path

from ruamel.yaml import YAML

from pm.termux_libs import table_path
from scripts.termux.wheelhouse_cache import build_identity

ROOT = Path(__file__).resolve().parents[2]
TABLE = table_path().relative_to(ROOT).as_posix()


def _load(name):
    return YAML(typ="base").load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _cache_keys(prefix):
    """The hashFiles() inputs of every cache step whose key starts with ``prefix``."""
    steps = [step for job in _load("desktop-bundled-release.yml")["jobs"].values() for step in job.get("steps", [])]
    keys = [step["with"]["key"] for step in steps if str(step.get("with", {}).get("key", "")).startswith(prefix)]
    assert keys, prefix
    return [set(re.findall(r"'([^']+)'", key)) for key in keys]


def test_archive_job_runs_when_the_pin_table_changes():
    paths = _load("archive-inputs.yml")["on"]["push"]["paths"]
    assert TABLE in paths
    assert [path for path in paths if not (ROOT / path).is_file()] == []


def test_wheelhouse_cache_key_covers_every_input_the_manifest_admits_on():
    inputs = set(build_identity(ROOT, "builder", "tag", "abi")) - {"builder", "platformTag", "pythonAbi"}
    assert TABLE in inputs
    for hashed in _cache_keys("termux-wheelhouse-"):
        assert inputs <= hashed


def test_payload_cache_key_hashes_files_that_exist():
    for hashed in _cache_keys("termux-payload-"):
        assert TABLE in hashed
        assert [path for path in hashed if not (ROOT / path).is_file()] == []
