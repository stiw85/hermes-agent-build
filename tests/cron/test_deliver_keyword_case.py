"""``origin`` and ``local`` are keywords of the ``deliver`` grammar, matched like its other
keywords (``all``, ``bot-chat``, platform names): without regard to case.

``deliver="Origin"`` used to fall through to the bare-platform branch, resolve to nothing and
record "no delivery target resolved" on every run instead of replying to the creating chat.
"""

import pytest

from cron.scheduler_delivery import _resolve_delivery_targets, _unresolved_delivery_outcome

ORIGIN = {"platform": "telegram", "chat_id": "123", "thread_id": None}


def _job(deliver, origin=ORIGIN):
    return {"id": "job1", "name": "job", "deliver": deliver, "origin": origin}


@pytest.mark.parametrize("deliver", ["origin", "Origin", "ORIGIN", " Origin "])
def test_origin_keyword_resolves_to_the_creating_chat(deliver):
    targets = _resolve_delivery_targets(_job(deliver))

    assert [(t["platform"], t["chat_id"], t.get("_resolved_from")) for t in targets] == [
        ("telegram", "123", "origin")]


@pytest.mark.parametrize("deliver", ["local", "Local", "LOCAL"])
def test_local_keyword_is_a_silent_no_delivery(deliver):
    job = _job(deliver)

    assert _resolve_delivery_targets(job) == []
    assert _unresolved_delivery_outcome(job, False) is None


@pytest.mark.parametrize("deliver", ["origin", "Origin"])
def test_originless_origin_job_is_not_a_delivery_failure(deliver, monkeypatch):
    monkeypatch.setattr("cron.scheduler_delivery._iter_home_target_platforms", lambda: iter(()))
    job = _job(deliver, origin=None)

    assert _resolve_delivery_targets(job) == []
    assert _unresolved_delivery_outcome(job, False) is None


def test_local_keyword_beside_a_real_target_adds_nothing():
    targets = _resolve_delivery_targets(_job("Origin,Local"))

    assert [(t["platform"], t["chat_id"]) for t in targets] == [("telegram", "123")]
