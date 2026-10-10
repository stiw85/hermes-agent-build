"""Every built-in Automation Blueprint must be schedulable with nothing but its own defaults.

The dashboard pre-fills a blueprint's form with the slot defaults and the catalog publishes a
ready-to-paste ``/blueprint`` command built from them, so a default the fill step rejects breaks
the blueprint on first use. Plugin blueprints are held to this at registration
(``cron.blueprint_plugins._validate``); the in-repo catalog is held to it here.
"""

import shlex

import pytest

from cron.blueprint_catalog import CATALOG, blueprint_slash_command, fill_blueprint
from cron.jobs import parse_schedule

pytest.importorskip("croniter")


@pytest.mark.parametrize("blueprint", CATALOG, ids=lambda b: b.key)
def test_builtin_blueprint_fills_with_its_own_defaults(blueprint):
    spec = fill_blueprint(blueprint, {})

    assert parse_schedule(spec["schedule"])["kind"] in {"cron", "interval"}


@pytest.mark.parametrize("blueprint", CATALOG, ids=lambda b: b.key)
def test_ready_to_paste_command_is_accepted_by_fill(blueprint):
    tokens = shlex.split(blueprint_slash_command(blueprint))[2:]  # drop "/blueprint <key>"
    values = dict(token.split("=", 1) for token in tokens)

    assert fill_blueprint(blueprint, values)["schedule"]


@pytest.mark.parametrize("blueprint", CATALOG, ids=lambda b: b.key)
def test_strict_enum_default_is_one_of_its_options(blueprint):
    for slot in blueprint.slots:
        if slot.options and slot.strict and slot.default not in (None, ""):
            assert str(slot.default) in {str(o) for o in slot.options}, slot.name
