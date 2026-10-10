"""Importing a session whose title is already taken must not abort the import.

Titles are unique per store. A backup restored into a store that already holds a
session with the same title (or a payload carrying the same title twice) used to
die on the unique index with ``sqlite3.IntegrityError``; the imported row now takes
the next free ``<title> #N`` instead, exactly like a manual duplicate would.
"""

import json

import pytest

from hermes_state import SessionDB


@pytest.fixture
def stores(tmp_path):
    source = SessionDB(db_path=tmp_path / "source.db")
    target = SessionDB(db_path=tmp_path / "target.db")
    yield source, target
    source.close()
    target.close()


def test_import_renumbers_a_title_the_store_already_holds(stores):
    source, target = stores
    source.create_session("laptop", source="cli")
    source.append_message("laptop", role="user", content="hello")
    source.set_session_title("laptop", "Debugging Import Error")
    target.create_session("desktop", source="cli")
    target.append_message("desktop", role="user", content="x")
    target.set_session_title("desktop", "Debugging Import Error")

    result = target.import_sessions(json.loads(json.dumps(source.export_all(include_inactive=True))))

    assert result["ok"] and result["imported"] == 1
    assert target.get_session_title("desktop") == "Debugging Import Error"
    assert target.get_session_title("laptop") == "Debugging Import Error #2"
    assert [m["content"] for m in target.get_messages("laptop")] == ["hello"]


def test_import_accepts_a_payload_repeating_one_title(stores):
    _, target = stores
    payload = [{"id": sid, "title": title, "messages": [{"role": "user", "content": sid}]}
               for sid, title in (("a", "Shared"), ("b", "Shared"), ("c", ""), ("d", ""))]

    result = target.import_sessions(payload)

    assert result["ok"] and result["imported"] == 4
    assert {target.get_session_title(sid) for sid in ("a", "b")} == {"Shared", "Shared #2"}
    assert target.get_session_title("c") is None and target.get_session_title("d") is None


def test_adopting_a_stranded_bot_chat_keeps_the_stores_own_canonical_chat(stores):
    donor, profile = stores
    title = SessionDB.CANONICAL_BOT_CHAT_TITLE
    for db, sid, text in ((donor, "stranded", "old turn"), (profile, "fresh", "new turn")):
        db.create_session(sid, source="tui")
        db.set_session_title(sid, title)
        db.set_session_hidden(sid, True)
        db.append_message(sid, role="user", content=text)

    assert profile.adopt_session_lineage_from(donor, "stranded")["adopted"]

    # The name IS the canonical chat's identity: the store's own chat keeps it.
    assert profile.resolve_session_by_title(title) == "fresh"
    adopted = profile.get_session("stranded")
    assert adopted["hidden"] and adopted["title"] != title
    assert [m["content"] for m in profile.get_messages("stranded")] == ["old turn"]
