"""``hermes native …``: the operator surface for native learning memory.

Attached only while ``memory.provider`` is ``native`` (see ``plugins.memory.discover_plugin_cli_commands``).
Every command works on the active profile's store. ``explain`` shows the premises a conclusion was learned
from and what it replaced; ``correct`` and ``forget`` are the two ways a person edits what the agent has
learned. Nothing else deletes rows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .store import KIND_FACT, KIND_OUTCOME, NativeStore


def _store() -> NativeStore:
    from hermes_constants import get_hermes_home

    return NativeStore(Path(get_hermes_home()) / "memory_native.db")


def _line(row: dict[str, Any]) -> str:
    state = (
        f"superseded by {row['superseded_by']}"
        if row.get("superseded_by")
        else "active"
    )
    if row.get("kind") == KIND_OUTCOME:
        label = f"[outcome {row.get('status') or '?'} · {row.get('task_type') or 'general'}]"
    else:
        label = f"[{row.get('confidence', 0):.2f}]"
    return f"{row['id']:>5}  {label}  {state:<22}  {row['text']}"


def register_cli(subparser) -> None:
    sub = subparser.add_subparsers(dest="native_action", required=True)

    listing = sub.add_parser("list", help="List conclusions the agent has learned")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument(
        "--outcomes",
        action="store_true",
        help="Show task outcome records instead of facts",
    )

    explain = sub.add_parser(
        "explain", help="Show a conclusion with its premises and what it replaced"
    )
    explain.add_argument("id", type=int)

    correct = sub.add_parser(
        "correct", help="Replace a conclusion's text (premises are kept)"
    )
    correct.add_argument("id", type=int)
    correct.add_argument("text")

    forget = sub.add_parser("forget", help="Delete a conclusion")
    forget.add_argument("id", type=int)

    export = sub.add_parser(
        "export", help="Write every conclusion, active and superseded, as JSON"
    )
    export.add_argument("--file", default="-", help="Output path, or - for stdout")


def native_command(args) -> int:
    store = _store()
    try:
        action = args.native_action
        if action == "list":
            kind = KIND_OUTCOME if args.outcomes else KIND_FACT
            rows = store.active(kind=kind, limit=args.limit)
            if not rows:
                print("No learned conclusions yet.")
            for row in rows:
                print(_line(row))
            return 0
        if action == "explain":
            row = store.get(args.id)
            if row is None:
                print(f"No conclusion with id {args.id}.", file=sys.stderr)
                return 1
            print(_line(row))
            print(f"  learned from session: {row['source_session_id'] or '-'}")
            print(f"  corrected by hand: {'yes' if row['corrected'] else 'no'}")
            if row["premises"]:
                print("  premises:")
                for premise in row["premises"]:
                    print(f"    - {premise}")
            else:
                print("  premises: none recorded")
            return 0
        if action == "correct":
            if not args.text.strip():
                print("The corrected text is empty.", file=sys.stderr)
                return 1
            ok = store.correct(args.id, " ".join(args.text.split())[:300])
            print("Corrected." if ok else f"No conclusion with id {args.id}.")
            return 0 if ok else 1
        if action == "forget":
            ok = store.forget(args.id)
            print("Forgotten." if ok else f"No conclusion with id {args.id}.")
            return 0 if ok else 1
        if action == "export":
            rows = store.every_row()
            payload = json.dumps(rows, indent=2, ensure_ascii=False, default=str)
            if args.file == "-":
                print(payload)
            else:
                Path(args.file).write_text(payload + "\n", encoding="utf-8")
                print(
                    f"Wrote {len(rows)} conclusions (active and superseded) to {args.file}."
                )
            return 0
        print(f"Unknown action: {action}", file=sys.stderr)
        return 2
    finally:
        store.close()
