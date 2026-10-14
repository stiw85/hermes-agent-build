"""Strategy registry. Add your own by subclassing Strategy and calling register()."""

from __future__ import annotations

from typing import Any

from .base import Strategy
from .builtin import BUILTINS

REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    REGISTRY[cls.name] = cls
    return cls


for _c in BUILTINS:
    register(_c)


def make(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; available: {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))


def describe() -> list[dict[str, Any]]:
    return [
        {"name": c.name, "description": c.description, "defaults": c.defaults, "grid": c.grid}
        for c in REGISTRY.values()
    ]


__all__ = ["Strategy", "REGISTRY", "register", "make", "describe"]
