"""A skill's credential-file registration outlives the tool call that made it.

Every tool call runs in a copy of the turn's context (``propagate_context_to_thread``), so a
registration made by ``skill_view`` must still be there when the next tool (``terminal`` on a
remote backend) asks which files to mount. Registrations stay per profile home.
"""

import concurrent.futures
import contextvars

import pytest

import tools.credential_files as credential_files
from tools.credential_files import clear_credential_files, get_credential_file_mounts, register_credential_files
from tools.thread_context import propagate_context_to_thread


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "google_token.json").write_text("{}")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(credential_files, "_config_files", {})
    clear_credential_files()
    yield home
    clear_credential_files()


def _next_tool_call(fn):
    """Run *fn* the way the tool executor does: on a worker, in a copy of the submitting context."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(propagate_context_to_thread(fn)).result()


def test_registration_is_visible_to_the_next_tool_call(hermes_home):
    def turn():
        missing = _next_tool_call(lambda: register_credential_files(["google_token.json"]))
        return missing, _next_tool_call(get_credential_file_mounts)

    # A fresh turn: the submitting context has never touched the registry.
    missing, mounts = contextvars.Context().run(turn)

    assert missing == []
    assert [m["container_path"] for m in mounts] == ["/root/.hermes/google_token.json"]
    assert mounts[0]["host_path"] == str(hermes_home / "google_token.json")


def test_clear_from_another_context_drops_the_registration(hermes_home):
    def turn():
        _next_tool_call(lambda: register_credential_files(["google_token.json"]))
        _next_tool_call(clear_credential_files)
        return _next_tool_call(get_credential_file_mounts)

    assert contextvars.Context().run(turn) == []


def test_registration_does_not_reach_another_profile_home(hermes_home, tmp_path, monkeypatch):
    register_credential_files(["google_token.json"])
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))

    assert get_credential_file_mounts() == []
