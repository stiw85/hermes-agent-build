"""Test discovery: which suites a root selects does not depend on where the checkout lives."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "rtp_discovery", Path(__file__).resolve().parents[2] / "scripts" / "run_tests_parallel.py")
rtp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtp)


def _checkout(parent: Path) -> Path:
    repo = parent / "hermes-agent"
    for suite in ("agent", "docker", "e2e", "integration"):
        (repo / "tests" / suite).mkdir(parents=True)
        (repo / "tests" / suite / f"test_{suite}.py").write_text("def test_x(): pass\n", encoding="utf-8")
    return repo


def _found(repo: Path, root: str) -> list[str]:
    return [p.relative_to(repo).as_posix() for p in rtp._discover_files([repo / root])]


@pytest.mark.parametrize("ancestor", ["work", "docker", "e2e", "integration"])
def test_default_root_skips_the_service_suites_wherever_the_checkout_lives(tmp_path, ancestor):
    assert _found(_checkout(tmp_path / ancestor), "tests") == ["tests/agent/test_agent.py"]


def test_naming_a_skipped_suite_as_the_root_runs_it(tmp_path):
    assert _found(_checkout(tmp_path), "tests/docker") == ["tests/docker/test_docker.py"]
