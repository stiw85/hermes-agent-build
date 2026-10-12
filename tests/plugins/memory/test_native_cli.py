"""``hermes native …`` operator commands: parsing, each action's output, and discovery gating."""

from __future__ import annotations

import argparse
import json

import pytest

from hermes_constants import get_hermes_home
from plugins.memory import discover_plugin_cli_commands
from plugins.memory.native.cli import native_command, register_cli
from plugins.memory.native.store import KIND_OUTCOME, NativeStore


def _parse(*argv: str):
    root = argparse.ArgumentParser(prog="hermes")
    top = root.add_subparsers(dest="cmd")
    register_cli(top.add_parser("native"))
    return root.parse_args(["native", *argv])


def _store() -> NativeStore:
    return NativeStore(get_hermes_home() / "memory_native.db")


def test_list_explain_correct_forget_and_export_round_trip(capsys, tmp_path):
    store = _store()
    old = store.add(text="The user lives in Sydney.", session_id="s1", confidence=0.7)
    new = store.add(
        text="The user moved to Perth.",
        premises=["I moved to Perth in June."],
        session_id="s2",
        confidence=0.9,
    )
    store.supersede(old, new)
    store.close()

    assert native_command(_parse("list")) == 0
    out = capsys.readouterr().out
    assert (
        "Perth" in out and "Sydney" not in out
    )  # superseded rows are not listed as active

    assert native_command(_parse("explain", str(new))) == 0
    out = capsys.readouterr().out
    assert "I moved to Perth in June." in out and "learned from session: s2" in out

    assert (
        native_command(
            _parse("correct", str(new), "The user lives in Perth, Western Australia.")
        )
        == 0
    )
    assert "Corrected." in capsys.readouterr().out
    assert native_command(_parse("explain", str(new))) == 0
    assert "corrected by hand: yes" in capsys.readouterr().out

    target = tmp_path / "dump.json"
    assert native_command(_parse("export", "--file", str(target))) == 0
    dumped = json.loads(target.read_text(encoding="utf-8"))
    assert {row["id"] for row in dumped} == {old, new}  # export keeps superseded rows

    assert native_command(_parse("forget", str(old))) == 0
    assert "Forgotten." in capsys.readouterr().out
    assert native_command(_parse("explain", str(old))) == 1
    assert "No conclusion with id" in capsys.readouterr().err


def test_correct_refuses_empty_text_and_unknown_ids(capsys):
    assert native_command(_parse("correct", "9999", "anything")) == 1
    assert "No conclusion with id 9999." in capsys.readouterr().out
    store = _store()
    row = store.add(text="A fact.")
    store.close()
    assert native_command(_parse("correct", str(row), "   ")) == 1
    assert "empty" in capsys.readouterr().err


def test_outcomes_are_listed_separately(capsys):
    store = _store()
    store.add(
        text="Fixed the flaky test.",
        kind=KIND_OUTCOME,
        task_type="debug",
        status="success",
    )
    store.close()
    assert native_command(_parse("list")) == 0
    assert "No learned conclusions yet." in capsys.readouterr().out
    assert native_command(_parse("list", "--outcomes")) == 0
    assert "[outcome success · debug]" in capsys.readouterr().out


def test_commands_attach_only_while_native_is_the_active_provider(monkeypatch):
    import plugins.memory as memory

    monkeypatch.setattr(memory, "_get_active_memory_provider", lambda: "builtin-none")
    assert discover_plugin_cli_commands() == []

    monkeypatch.setattr(memory, "_get_active_memory_provider", lambda: "native")
    commands = discover_plugin_cli_commands()
    assert [c["name"] for c in commands] == ["native"]
    assert (
        callable(commands[0]["setup_fn"])
        and commands[0]["handler_fn"] is native_command
    )
