# Native learning memory: recall eval

`python -m evals.native_memory.run_recall` compares native recall with a built-in-style baseline on a
seed set of fictional personas (`recall_set.json`), with and without 30 filler sessions.

## Results (Phase 0 baseline, 12 Oct 2026)

Recall@5 over 9 answerable questions:

| Condition | Native | Built-in baseline |
|---|---|---|
| Seed set (4 personas, 9 questions) | 100% | 100% |
| With 30 filler sessions (about 60 unrelated facts) | 100% | 0% |

## What these numbers do and do not show

- **Native assumes perfect extraction.** The learning pass runs for real (dedupe, supersession, caps,
  threat scan), but the model is replaced by a scripted extractor that returns the gold conclusions.
  Live numbers will be lower by whatever a real model misses or gets wrong. This eval cannot show that.
- **The built-in baseline assumes oldest-first eviction.** A model that curates a full MEMORY.md could
  keep the important entries and do better than 0%. This run does not measure that curation.
- **The seed set does not separate the two.** Both fit under the 2,200-character cap, so the filler
  condition is the one that tests keeping facts over time.
- **Nine questions is a seed, not a benchmark.** The gate for default-on needs a larger labelled set and
  live runs, with a cost measurement per session.

The regression tests in `tests/plugins/memory/test_native_recall_eval.py` pin the native side at 100% and
require it to beat the baseline with filler.
