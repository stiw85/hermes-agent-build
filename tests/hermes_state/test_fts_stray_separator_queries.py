"""A ``-`` or ``.`` that does not join two word parts must not empty a search.

FTS5 rejects a bare ``-``/``.`` outside a quoted phrase, and a rejected MATCH is
answered with zero rows — so ``.env``, ``--force`` or a sentence-final ``deploy.``
silently found nothing while the same words without the punctuation matched.
"""

import sqlite3

import pytest

from hermes_state import SessionDB
from hermes_state_search import SessionSearchMixin


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    d.create_session(session_id="s1", source="cli")
    d.append_message(
        "s1", role="user",
        content="put the key in the .env file and run with --force then deploy. wait for my-app.config",
    )
    yield d
    d.close()


@pytest.mark.parametrize(
    "query",
    [".env", "--force", "-force", "deploy.", "key - file", "env -", "config .env", "deploy* .env*", "and-gate"],
)
def test_query_with_stray_separator_stays_parsable(query):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
    sanitized = SessionSearchMixin._sanitize_fts5_query(query)
    assert sanitized
    conn.execute("SELECT count(*) FROM t WHERE t MATCH ?", (sanitized,)).fetchone()


@pytest.mark.parametrize("query", [".env", "--force", "deploy.", "key - file", "config .env"])
def test_search_finds_message_despite_stray_separator(db, query):
    assert len(db.search_messages(query)) == 1


def test_joined_terms_still_match_as_one_phrase(db):
    assert SessionSearchMixin._sanitize_fts5_query("my-app.config") == '"my-app.config"'
    assert len(db.search_messages("my-app.config")) == 1
    assert db.search_messages("app-my.config") == []
