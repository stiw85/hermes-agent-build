"""Tab-completable subcommands match what each handler actually accepts.

Completions derived from an ``args_hint`` stop at the first character that is not ``[a-z|]``, so
``restore <id>|prune`` lost ``prune``, ``session-id`` (a placeholder) became ``session`` and
``codex_app_server`` became ``codex``. These three declare their subcommands explicitly.
"""

from hermes_cli.codex_runtime_switch import parse_args
from hermes_cli.commands import SUBCOMMANDS


def test_snapshot_offers_every_verb_including_prune():
    assert SUBCOMMANDS["/snapshot"] == ["list", "create", "restore", "prune"]


def test_topic_offers_only_real_keywords():
    assert SUBCOMMANDS["/topic"] == ["off", "help"]


def test_codex_runtime_offers_values_the_parser_accepts():
    offered = SUBCOMMANDS["/codex-runtime"]

    assert "codex_app_server" in offered and "auto" in offered
    for value in offered:
        assert parse_args(value)[1] == []
