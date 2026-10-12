"""Enabling or disabling ``<category>/<name>`` leaves a different plugin called ``<name>`` alone.

The bare leaf is purged from the opposing list as a legacy spelling of the category plugin;
when it is another plugin's own key, that plugin's state is not ours to change.
"""

from hermes_cli.plugins_cmd import _apply_activation, _plugin_aliases

# (name, version, description, source, dir_path, key) rows, as _discover_all_plugins() returns them.
BUNDLED = ("web-tavily", "1.0", "", "bundled", "/bundled/web/tavily", "web/tavily")
USER_FLAT = ("tavily", "1.0", "", "user", "/home/plugins/tavily", "tavily")


def test_disabling_the_category_plugin_keeps_the_flat_plugin_enabled():
    entries = [BUNDLED, USER_FLAT]
    enabled, disabled = {"tavily"}, set()

    _apply_activation(enabled, disabled, "web/tavily", _plugin_aliases("web/tavily", entries), enable=False)

    assert enabled == {"tavily"}
    assert disabled == {"web/tavily"}


def test_enabling_the_category_plugin_keeps_the_flat_plugin_disabled():
    entries = [BUNDLED, USER_FLAT]
    enabled, disabled = set(), {"tavily"}

    _apply_activation(enabled, disabled, "web/tavily", _plugin_aliases("web/tavily", entries), enable=True)

    assert enabled == {"web/tavily"}
    assert disabled == {"tavily"}


def test_a_stale_bare_leaf_is_still_purged_when_no_plugin_owns_it():
    enabled, disabled = set(), {"tavily", "web-tavily"}

    _apply_activation(enabled, disabled, "web/tavily", _plugin_aliases("web/tavily", [BUNDLED]), enable=True)

    assert enabled == {"web/tavily"}
    assert disabled == set()
