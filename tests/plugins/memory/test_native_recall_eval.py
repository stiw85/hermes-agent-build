"""The native-vs-builtin recall eval (evals/native_memory) as a regression guard.

Native recall is scored with gold extraction, so these assertions pin storage and retrieval, not model
quality. The built-in side assumes oldest-first eviction; see evals/native_memory/README.md.
"""

from __future__ import annotations

from pathlib import Path

from evals.native_memory.run_recall import evaluate, load_dataset


def test_native_recalls_every_answerable_question_on_the_seed_set_and_with_filler(
    tmp_path: Path,
):
    dataset = load_dataset()
    for with_filler in (False, True):
        results = evaluate(dataset, with_filler=with_filler, work=tmp_path)
        assert results["native"].misses == [], (with_filler, results["native"].misses)


def test_native_keeps_what_a_bounded_builtin_store_loses_over_time(tmp_path: Path):
    dataset = load_dataset()
    results = evaluate(dataset, with_filler=True, work=tmp_path)
    assert results["native"].recall > results["builtin"].recall
