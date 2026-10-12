"""The shell tag picker follows tag chronology across CalVer and SemVer, like pick_tags.py."""
import json
import os
import subprocess
from pathlib import Path

import pytest

PICKER = Path(__file__).resolve().parents[2] / "scripts" / "sandbox" / "pick-release-tags.sh"


def _pick(repo: Path, count: int) -> list[str]:
    out = subprocess.run(["bash", str(PICKER), "--repo", str(repo), "--count", str(count)],
                         check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    return json.loads(out.stdout)


@pytest.mark.platforms("posix")
def test_sampling_spans_both_version_schemes_in_release_order(tmp_path):
    def git(*args, env=None):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=30)

    git("init", "-b", "main")
    git("config", "user.name", "fixture")
    git("config", "user.email", "fixture@example.invalid")
    for index, tag in enumerate(["v2026.7.20", "v2026.9.24", "v0.27.0", "v0.28.0", "backup/old"]):
        stamp = f"2026-08-{index + 1:02d}T00:00:00Z"
        git("commit", "--allow-empty", "-m", tag, env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        git("tag", tag)
    assert _pick(tmp_path, 1) == ["v0.28.0"]
    assert _pick(tmp_path, 2) == ["v2026.7.20", "v0.28.0"]
    assert _pick(tmp_path, 9) == ["v2026.7.20", "v2026.9.24", "v0.27.0", "v0.28.0"]
