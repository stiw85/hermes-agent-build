"""Root-ward lineage walks reach the root of a long compression lineage.

Real conversations compress well past 100 times. The tip-to-root walkers stopped
after 100 segments, so a resume showed only the newest hundred segments and the
"stable" conversation root changed with every further compression.
"""

import pytest

from hermes_state import SessionDB

SEGMENTS = 130


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    parent = None
    for i in range(SEGMENTS):
        sid = f"seg{i:03d}"
        d.create_session(sid, source="cli", parent_session_id=parent)
        d.append_message(sid, role="user", content=f"turn {i}")
        if i < SEGMENTS - 1:
            d.end_session(sid, "compression")
        parent = sid
    yield d
    d.close()


def test_resume_materializes_every_segment(db):
    tip = f"seg{SEGMENTS - 1:03d}"
    messages = db.get_messages(tip, include_ancestors=True)
    assert len(messages) == SEGMENTS
    assert messages[0]["content"] == "turn 0"
    assert db.get_resume_message_count(tip) == SEGMENTS


def test_conversation_root_is_the_same_from_every_segment(db):
    assert {db.get_conversation_root(f"seg{i:03d}") for i in (0, 50, 110, SEGMENTS - 1)} == {"seg000"}
