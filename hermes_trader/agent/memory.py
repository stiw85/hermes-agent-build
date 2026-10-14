"""Hermes-style memory, trimmed for trading.

- LESSONS.md: short declarative memory ("BTC mean-reversion fails in strong trends").
  Entries separated by '§', hard character budget so it stays prompt-sized.
- playbooks/<name>/SKILL.md: procedural memory ("how to handle a volatility spike"),
  agentskills.io-style frontmatter (name, description). Only the index goes in the
  system prompt; bodies are loaded on demand.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SEP = "\n§\n"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class Lessons:
    def __init__(self, path: str | Path, char_limit: int = 2500) -> None:
        self.path = Path(path)
        self.limit = char_limit

    def entries(self) -> list[str]:
        if not self.path.is_file():
            return []
        return [e.strip() for e in self.path.read_text().split("§") if e.strip()]

    def _write(self, entries: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(SEP.join(entries) + "\n")

    def render(self) -> str:
        return "\n".join(f"- {e}" for e in self.entries()) or "(no lessons yet)"

    def add(self, text: str) -> str:
        text = text.strip()
        if not text:
            return "error: empty lesson"
        ents = self.entries()
        if text in ents:
            return "already recorded"
        new = [*ents, text]
        size = len(SEP.join(new))
        if size > self.limit:
            return (f"error: lessons would be {size}/{self.limit} chars. Merge or remove older entries "
                    "with action=replace/remove first.")
        self._write(new)
        return f"added ({size}/{self.limit} chars)"

    def replace(self, old: str, new: str) -> str:
        ents = self.entries()
        hits = [i for i, e in enumerate(ents) if old.strip() and old.strip() in e]
        if len(hits) != 1:
            return f"error: '{old[:40]}' matched {len(hits)} entries; need exactly 1"
        ents[hits[0]] = new.strip()
        if len(SEP.join(ents)) > self.limit:
            return "error: over character budget"
        self._write(ents)
        return "replaced"

    def remove(self, old: str) -> str:
        ents = self.entries()
        keep = [e for e in ents if old.strip() not in e]
        if len(keep) != len(ents) - 1:
            return f"error: '{old[:40]}' matched {len(ents) - len(keep)} entries; need exactly 1"
        self._write(keep)
        return "removed"


class Playbooks:
    def __init__(self, root: str | Path, extra_roots: list[Path] | None = None) -> None:
        self.root = Path(root)
        self.roots = [self.root, *(extra_roots or [])]

    def _find(self, name: str) -> Path | None:
        for r in self.roots:
            p = r / name / "SKILL.md"
            if p.is_file():
                return p
        return None

    @staticmethod
    def _meta(p: Path) -> dict[str, Any]:
        txt = p.read_text()
        if txt.startswith("---"):
            parts = txt.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1]) or {}
        return {}

    def index(self) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for r in self.roots:
            if not r.is_dir():
                continue
            for p in sorted(r.glob("*/SKILL.md")):
                m = self._meta(p)
                name = m.get("name") or p.parent.name
                seen.setdefault(name, {"name": name, "description": str(m.get("description", ""))[:200]})
        return list(seen.values())

    def view(self, name: str) -> str:
        p = self._find(name)
        return p.read_text() if p else f"error: no playbook {name!r}"

    def create(self, name: str, description: str, body: str) -> str:
        if not _NAME.match(name):
            return "error: name must be lowercase letters, digits and dashes"
        if self._find(name):
            return f"error: {name} exists; use patch"
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        fm = yaml.safe_dump({"name": name, "description": description.strip()}, sort_keys=False)
        (d / "SKILL.md").write_text(f"---\n{fm}---\n\n{body.strip()}\n")
        return f"created playbook {name}"

    def patch(self, name: str, old: str, new: str) -> str:
        p = self._find(name)
        if not p:
            return f"error: no playbook {name!r}"
        if p.parent.parent != self.root:  # bundled playbook: copy into writable root first
            dst = self.root / name / "SKILL.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(p.read_text())
            p = dst
        txt = p.read_text()
        if txt.count(old) != 1:
            return f"error: old text matched {txt.count(old)} times; need exactly 1"
        p.write_text(txt.replace(old, new))
        return f"patched {name}"
