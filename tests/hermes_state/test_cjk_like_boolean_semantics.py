"""The CJK substring scan honours AND / NOT like every other search route.

One- and two-character CJK terms (most Chinese words) cannot use the trigram
index and are answered by a LIKE scan. That scan OR-ed every term, so
``部署 NOT 失败`` returned rows containing only the excluded word.
"""

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    d = SessionDB(db_path=tmp_path / "state.db")
    # Two-character terms take the LIKE scan only without the optional bigram index.
    monkeypatch.setattr(d, "_fts_cjk_available", False)
    d.create_session(session_id="s1", source="cli")
    for text in ("部署 成功", "部署 失败", "测试 失败"):
        d.append_message("s1", role="user", content=text)
    yield d
    d.close()


def _hits(db, query):
    return sorted(db.get_messages("s1")[r["id"] - 1]["content"] for r in db.search_messages(query))


def test_not_excludes_the_negated_term(db):
    assert _hits(db, "部署 NOT 失败") == ["部署 成功"]


@pytest.mark.parametrize("query", ["部署 AND 失败", "部署 失败"])
def test_and_requires_every_term(db, query):
    assert _hits(db, query) == ["部署 失败"]


def test_or_still_matches_any_term(db):
    assert _hits(db, "部署 OR 失败") == ["测试 失败", "部署 失败", "部署 成功"]
