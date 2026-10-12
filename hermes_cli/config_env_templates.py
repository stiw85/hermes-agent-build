"""Keep ``${VAR}`` templates when a loaded (expanded) config is saved back.

Split out of :mod:`hermes_cli.config` (code-health size ratchet); ``save_config`` late-imports it.
"""

from __future__ import annotations


def _items_by_unique_name(items):
    """Return a name-indexed dict only when all items have unique string names."""
    if not isinstance(items, list):
        return None
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        name = item["name"]
        if name in indexed:
            return None
        indexed[name] = item
    return indexed


def _raw_position(index: int, item, expanded_raw: list) -> int:
    """Index of the raw list item that *item* was loaded from: its own slot while the list is
    unshifted, else the raw item whose expansion equals it. A removal or insertion earlier in the
    list must not line an untouched item up with a neighbour's template."""
    if index < len(expanded_raw) and expanded_raw[index] == item:
        return index
    return next((i for i, expanded in enumerate(expanded_raw) if expanded == item), index)


def _preserve_env_ref_templates(current, raw, loaded_expanded=None):
    """Restore raw ``${VAR}`` templates where the value is otherwise unchanged, so persisting a
    loaded (expanded) config never writes the plaintext secret back to ``config.yaml``."""
    from hermes_cli.config import _ENV_REF_RE, _expand_env_vars

    if isinstance(current, str) and isinstance(raw, str) and _ENV_REF_RE.search(raw):
        if current in (raw, loaded_expanded) or _expand_env_vars(raw) == current:
            return raw
        return current

    if isinstance(current, dict) and isinstance(raw, dict):
        return {
            key: _preserve_env_ref_templates(
                value, raw.get(key),
                loaded_expanded.get(key) if isinstance(loaded_expanded, dict) else None)
            for key, value in current.items()}

    if isinstance(current, list) and isinstance(raw, list):
        # Match named objects (e.g. custom_providers) by name so reordering keeps templates;
        # with duplicate names fall back to positional matching rather than shadowing an entry.
        current_by_name = _items_by_unique_name(current)
        raw_by_name = _items_by_unique_name(raw)
        loaded_by_name = _items_by_unique_name(loaded_expanded)
        if current_by_name is not None and raw_by_name is not None:
            return [
                _preserve_env_ref_templates(
                    item, raw_by_name.get(item.get("name")),
                    loaded_by_name.get(item.get("name")) if loaded_by_name is not None else None)
                for item in current]
        expanded_raw = [_expand_env_vars(item) for item in raw]
        loaded = loaded_expanded if isinstance(loaded_expanded, list) else []
        return [
            _preserve_env_ref_templates(
                item,
                raw[source] if source < len(raw) else None,
                loaded[source] if source < len(loaded) else None)
            for index, item in enumerate(current)
            for source in (_raw_position(index, item, expanded_raw),)]

    return current
