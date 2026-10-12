#!/usr/bin/env python3
"""Diff ruff + ty diagnostic reports between two git refs.

Produces a Markdown summary suitable for `$GITHUB_STEP_SUMMARY` and for PR
comments. Compares issues by a stable key (file, rule, message) so line-only
shifts from unrelated edits are treated as the same issue.

Usage:
    lint_diff.py \\
        --base-ruff base/ruff.json --head-ruff head/ruff.json \\
        --base-ty   base/ty.json   --head-ty   head/ty.json \\
        [--base-root /tmp/lint-base] [--base-ref origin/main] [--head-ref HEAD]

``--base-root`` is the directory the base reports were produced in when that is
not the current one (CI scans the base revision in a separate worktree): ruff
reports absolute paths, and both sides must name a file the same way.

Any of the four --{base,head}-{ruff,ty} files may be missing or empty; in that
case the tool treats it as "0 diagnostics" (e.g. if base/main doesn't have the
config yet, or a tool crashed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _load_json(path: Path | None) -> list[dict]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
        return []
    if not isinstance(data, list):
        return []
    return data


def _normalize_ruff(entries: list[dict], root: Path | None = None) -> list[dict]:
    """Ruff JSON: {code, filename, location.row, message}; ``root`` is where ruff ran."""
    out: list[dict] = []
    for e in entries:
        code = e.get("code") or "unknown"
        # ruff emits absolute paths; relativize to the scanned tree if possible
        filename = e.get("filename", "")
        try:
            filename = os.path.relpath(filename, root)
        except ValueError:
            pass
        line = (e.get("location") or {}).get("row", 0)
        out.append(
            {
                "tool": "ruff",
                "rule": code,
                "path": filename,
                "line": line,
                "message": e.get("message", ""),
            }
        )
    return out


def _normalize_ty(entries: list[dict]) -> list[dict]:
    """ty gitlab JSON: {check_name, location.path, location.positions.begin.line, description}."""
    out: list[dict] = []
    for e in entries:
        loc = e.get("location") or {}
        begin = (loc.get("positions") or {}).get("begin") or {}
        out.append(
            {
                "tool": "ty",
                "rule": e.get("check_name", "unknown"),
                "path": loc.get("path", ""),
                "line": begin.get("line", 0),
                "message": e.get("description", ""),
            }
        )
    return out


def _key(d: dict) -> tuple[str, str, str]:
    """Stable diagnostic identity across commits: (path, rule, message)."""
    # Intentionally omit line so unrelated edits above an issue don't flag it
    # as "new". Same file + same rule + same message = same issue.
    return (d["path"], d["rule"], d["message"])


def _by_key(entries: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for d in entries:
        groups[_key(d)].append(d)
    return groups


def _diff(base: list[dict], head: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    # Counted per key: a file may hold the same rule and message more than once, and one
    # more occurrence on head is a new issue even though its key already existed on base.
    base_groups, head_groups = _by_key(base), _by_key(head)
    new: list[dict] = []
    fixed: list[dict] = []
    unchanged: list[dict] = []
    # Head entries for new and unchanged (current line numbers), base entries for fixed
    for key, entries in head_groups.items():
        kept = len(base_groups.get(key, ()))
        unchanged += entries[:kept]
        new += entries[kept:]
    for key, entries in base_groups.items():
        fixed += entries[len(head_groups.get(key, ())):]
    return new, fixed, unchanged


def _rule_counts(entries: list[dict]) -> list[tuple[str, int]]:
    return Counter(e["rule"] for e in entries).most_common()


def _section(title: str, entries: list[dict], limit: int = 25) -> str:
    if not entries:
        return f"**{title}:** none\n"
    lines = [f"**{title} ({len(entries)}):**\n"]
    # Group by rule for readability
    counts = _rule_counts(entries)
    lines.append("| Rule | Count |")
    lines.append("| --- | ---: |")
    for rule, count in counts[:15]:
        lines.append(f"| `{rule}` | {count} |")
    if len(counts) > 15:
        lines.append(f"| _+{len(counts) - 15} more rules_ | |")
    lines.append("")
    lines.append("<details><summary>First entries</summary>\n")
    lines.append("```")
    for e in entries[:limit]:
        lines.append(f"{e['path']}:{e['line']}: [{e['rule']}] {e['message']}")
    if len(entries) > limit:
        lines.append(f"... and {len(entries) - limit} more")
    lines.append("```")
    lines.append("</details>\n")
    return "\n".join(lines)


def _tool_report(
    tool_name: str,
    base: list[dict],
    head: list[dict],
    base_available: bool,
) -> str:
    new, fixed, unchanged = _diff(base, head)
    delta = len(head) - len(base)
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    emoji = "🆕" if delta > 0 else ("✅" if delta < 0 else "➖")

    lines = [f"## {tool_name}\n"]
    if not base_available:
        lines.append(
            "_Base report unavailable (likely main has no config for this tool yet); "
            "treating all head diagnostics as new._\n"
        )
    lines.append(
        f"**Total:** {len(head)} on HEAD, {len(base)} on base "
        f"({emoji} {delta_str})\n"
    )
    lines.append(_section("🆕 New issues", new))
    lines.append(_section("✅ Fixed issues", fixed))
    lines.append(
        f"**Unchanged:** {len(unchanged)} pre-existing issues carried over.\n"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ruff", type=Path, required=True)
    ap.add_argument("--head-ruff", type=Path, required=True)
    ap.add_argument("--base-ty", type=Path, required=True)
    ap.add_argument("--head-ty", type=Path, required=True)
    ap.add_argument("--base-root", type=Path, help="Directory the base reports were produced in")
    ap.add_argument("--base-ref", default="base")
    ap.add_argument("--head-ref", default="HEAD")
    ap.add_argument(
        "--output", type=Path, help="Write summary to this file instead of stdout"
    )
    args = ap.parse_args()

    base_ruff_raw = _load_json(args.base_ruff)
    head_ruff_raw = _load_json(args.head_ruff)
    base_ty_raw = _load_json(args.base_ty)
    head_ty_raw = _load_json(args.head_ty)

    base_ruff = _normalize_ruff(base_ruff_raw, args.base_root)
    head_ruff = _normalize_ruff(head_ruff_raw)
    base_ty = _normalize_ty(base_ty_raw)
    head_ty = _normalize_ty(head_ty_raw)

    base_ruff_avail = args.base_ruff.exists() and args.base_ruff.stat().st_size > 0
    base_ty_avail = args.base_ty.exists() and args.base_ty.stat().st_size > 0

    buf: list[str] = []
    buf.append(f"# 🔎 Lint report: `{args.head_ref}` vs `{args.base_ref}`\n")
    buf.append(_tool_report("ruff", base_ruff, head_ruff, base_ruff_avail))
    buf.append(_tool_report("ty (type checker)", base_ty, head_ty, base_ty_avail))
    buf.append(
        "_Diagnostics are surfaced as warnings — this check never fails the build._\n"
    )

    summary = "\n".join(buf)
    if args.output:
        args.output.write_text(summary, encoding="utf-8")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
