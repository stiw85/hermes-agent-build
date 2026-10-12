"""Only ``<title> #<digits>`` is a numbered continuation of ``<title>``.

A title that merely starts with ``<title> #`` (an issue or PR reference such as
"Review PR #4521 feedback") is a different conversation: resuming "Review PR" by
name must not open it, and it must not reserve "Review PR" in the numbering.
"""

import time

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    yield d
    d.close()


def _titled(db, session_id, title):
    db.create_session(session_id=session_id, source="cli")
    db.append_message(session_id, role="user", content="hi")
    db.set_session_title(session_id, title)
    time.sleep(0.01)  # resolve orders continuations by started_at


def test_resolve_ignores_titles_that_only_share_a_hash_prefix(db):
    _titled(db, "wanted", "Review PR")
    _titled(db, "unrelated", "Review PR #4521 feedback")
    assert db.resolve_session_by_title("Review PR") == "wanted"

    _titled(db, "continued", "Review PR #2")
    assert db.resolve_session_by_title("Review PR") == "continued"


def test_next_title_is_the_base_when_only_a_hash_prefixed_title_exists(db):
    _titled(db, "solo", "Fix #12 crash")
    assert db.get_next_title_in_lineage("Fix") == "Fix"

    _titled(db, "base", "Fix")
    assert db.get_next_title_in_lineage("Fix") == "Fix #2"
