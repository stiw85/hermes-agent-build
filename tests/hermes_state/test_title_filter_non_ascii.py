"""Title filters must find a title typed exactly, whatever script it is written in.

SQLite folds case for ASCII only, so a needle lowercased in Python ("привет") can
never equal the stored "Привет": every capitalised Cyrillic, Greek or accented
title was unreachable through the session search and the prune ``--title`` filter.
"""

import pytest

from hermes_state import SessionDB

TITLES = {"ru": "Привет Мир", "fr": "École normale", "de": "Über uns", "en": "Hello World"}


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    for sid, title in TITLES.items():
        d.create_session(session_id=sid, source="cli")
        d.append_message(sid, role="user", content="hi")
        d.set_session_title(sid, title)
        d.end_session(sid, "user_exit")
    yield d
    d.close()


@pytest.mark.parametrize("sid", sorted(TITLES))
def test_session_search_finds_the_exact_title(db, sid):
    rows = db.list_sessions_rich(search_query=TITLES[sid], order_by_last_active=True)
    assert [r["id"] for r in rows] == [sid]


@pytest.mark.parametrize("sid", sorted(TITLES))
def test_prune_title_filter_finds_the_exact_title(db, sid):
    assert [r["id"] for r in db.list_prune_candidates(title_like=TITLES[sid])] == [sid]


def test_ascii_titles_still_match_case_insensitively(db):
    assert [r["id"] for r in db.list_sessions_rich(search_query="hELLO", order_by_last_active=True)] == ["en"]
    assert [r["id"] for r in db.list_prune_candidates(title_like="hELLO")] == ["en"]
