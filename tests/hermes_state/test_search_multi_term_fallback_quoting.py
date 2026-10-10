"""A dotted / hyphenated term must not break the substring routes for the rest of the query.

The sanitizer quotes ``config.yaml`` and ``my-app`` so FTS5 reads them as phrases.
The substring routes re-quote each token themselves; with more than one term a
quote stayed glued to a token and was searched for literally, so two terms that
each matched alone matched nothing together.
"""

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    d.create_session(session_id="s1", source="cli")
    d.append_message("s1", role="user", content="数据库配置写在config.yaml里面")
    d.append_message("s1", role="user", content="修改my-app服务端和youer组件")
    yield d
    d.close()


@pytest.mark.parametrize("query", ["数据库配置 config.yaml", "config.yaml 数据库配置"])
def test_cjk_term_with_a_dotted_term(db, query):
    assert [r["id"] for r in db.search_messages(query)] == [1]


@pytest.mark.parametrize("query", ["my-app youer", "youer my-app"])
def test_latin_terms_embedded_in_cjk_text(db, query):
    assert [r["id"] for r in db.search_messages(query)] == [2]


@pytest.mark.parametrize("query", ["数据库配置", "config.yaml", "my-app", "youer", '"my-app"'])
def test_single_terms_keep_matching(db, query):
    assert len(db.search_messages(query)) == 1
