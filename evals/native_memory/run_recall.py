"""Recall eval for native learning memory against a built-in baseline.

What this measures, and what it does not:

- Native: the real learning pass (``learn_from_session``: dedupe, supersession, caps, the threat
  scan) and the real recall (``recall_block``). The model is replaced by a scripted extractor that
  returns the gold conclusions, so the score isolates storage and retrieval. It says nothing about how
  well a live model extracts conclusions.
- Built-in baseline: the same gold conclusions written into a bounded MEMORY.md-style store
  (``builtin_char_limit`` characters, oldest entries dropped when full, superseded entries replaced).
  The built-in store is injected whole, so "recall" here means the answer survives in that store.

The filler sessions add unrelated facts so the stored volume passes the built-in cap. On the seed set
alone the built-in store fits, and the two systems are not expected to differ.

Run: ``python -m evals.native_memory.run_recall``
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plugins.memory.native.learn import learn_from_session
from plugins.memory.native.recall import recall_block
from plugins.memory.native.store import NativeStore

DATASET = Path(__file__).with_name("recall_set.json")
K = 5
_BUILTIN_DELIMITER = "\n§\n"


@dataclass
class Result:
    system: str
    condition: str
    hits: list[bool] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return sum(self.hits) / len(self.hits) if self.hits else 0.0


def load_dataset(path: Path = DATASET) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _filler(spec: dict[str, Any]) -> list[dict[str, Any]]:
    sessions = []
    for i in range(int(spec["sessions"])):
        gold = [
            {
                "key": f"f{i}-{j}",
                "text": f"Filler person {i} keeps a {['red', 'blue', 'green'][j % 3]} notebook number {j}.",
            }
            for j in range(int(spec["per_session"]))
        ]
        sessions.append({"id": f"filler-{i}", "gold": gold})
    return sessions


def _sessions(
    item: dict[str, Any], filler: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    # The item's facts are learned first; the filler sessions that follow are the months of later use that
    # push early facts out of a bounded store. The questions are asked after all of them.
    return item["sessions"] + filler


def _gold_extractor(key_text: dict[str, str], gold: list[dict[str, Any]]):
    """A scripted extractor: returns this session's gold conclusions, mapping ``supersedes`` keys to ids."""

    def call(messages: list[dict[str, str]]) -> str:
        existing = json.loads(
            messages[1]["content"]
            .split("EXISTING (current conclusions, JSON data):\n", 1)[1]
            .split("\n\nTRANSCRIPT", 1)[0]
        )
        by_text = {row["text"]: row["id"] for row in existing}
        conclusions = []
        for entry in gold:
            supersedes = []
            for old_key in entry.get("supersedes", []):
                if key_text[old_key] in by_text:
                    supersedes.append(by_text[key_text[old_key]])
            conclusions.append({
                "text": entry["text"],
                "premises": [entry["text"]],
                "confidence": 0.9,
                "supersedes": supersedes,
            })
        return json.dumps({"summary": "scripted", "conclusions": conclusions})

    return call


def run_native(
    item: dict[str, Any],
    filler: list[dict[str, Any]],
    key_text: dict[str, str],
    work: Path,
    *,
    k: int = K,
) -> Result:
    store = NativeStore(work / f"native-{item['id']}.db")
    try:
        for session in _sessions(item, filler):
            transcript = [{"role": "user", "content": f"(session {session['id']})"}]
            learn_from_session(
                store,
                transcript,
                session_id=session["id"],
                call=_gold_extractor(key_text, session["gold"]),
            )
        result = Result(system="native", condition="")
        for question in item["questions"]:
            block, _ids = recall_block(store, question["question"], limit=k)
            found = any(answer in block.lower() for answer in question["answers"])
            result.hits.append(found)
            if not found:
                result.misses.append(question["question"])
        return result
    finally:
        store.close()


def run_builtin(
    item: dict[str, Any], filler: list[dict[str, Any]], char_limit: int
) -> Result:
    entries: list[tuple[str, str]] = []  # (key, text), oldest first
    for session in _sessions(item, filler):
        for entry in session["gold"]:
            superseded = set(entry.get("supersedes", []))
            entries = [(key, text) for key, text in entries if key not in superseded]
            entries.append((entry["key"], entry["text"]))
    while (
        entries
        and len(_BUILTIN_DELIMITER.join(text for _, text in entries)) > char_limit
    ):
        entries.pop(0)  # the built-in store is full: the oldest entries go first
    store_text = _BUILTIN_DELIMITER.join(text for _, text in entries).lower()
    result = Result(system="builtin", condition="")
    for question in item["questions"]:
        found = any(answer in store_text for answer in question["answers"])
        result.hits.append(found)
        if not found:
            result.misses.append(question["question"])
    return result


def evaluate(
    dataset: dict[str, Any], *, with_filler: bool, work: Path
) -> dict[str, Result]:
    filler = _filler(dataset["filler"]) if with_filler else []
    key_text = {
        entry["key"]: entry["text"]
        for item in dataset["items"]
        for session in item["sessions"]
        for entry in session["gold"]
    }
    key_text.update({
        entry["key"]: entry["text"] for session in filler for entry in session["gold"]
    })
    native_hits: list[bool] = []
    native_misses: list[str] = []
    builtin_hits: list[bool] = []
    builtin_misses: list[str] = []
    for item in dataset["items"]:
        native = run_native(item, filler, key_text, work)
        builtin = run_builtin(item, filler, dataset["builtin_char_limit"])
        native_hits += native.hits
        native_misses += native.misses
        builtin_hits += builtin.hits
        builtin_misses += builtin.misses
    condition = "with filler" if with_filler else "seed set"
    return {
        "native": Result("native", condition, native_hits, native_misses),
        "builtin": Result("builtin", condition, builtin_hits, builtin_misses),
    }


def main() -> None:
    dataset = load_dataset()
    with tempfile.TemporaryDirectory(prefix="native-recall-") as tmp:
        for with_filler in (False, True):
            results = evaluate(dataset, with_filler=with_filler, work=Path(tmp))
            label = "with filler" if with_filler else "seed set"
            print(f"\n{label}  (questions: {len(results['native'].hits)}, recall@{K})")
            for name in ("native", "builtin"):
                result = results[name]
                print(
                    f"  {name:8s} {result.recall:6.2%}  misses: {result.misses or 'none'}"
                )


if __name__ == "__main__":
    main()
