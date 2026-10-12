# Native learning memory

A local memory provider that stores conclusions with the premises they were learned from, recalls them
each turn, and learns from each finished session. No hosted service is involved.

## Turn it on

```yaml
memory:
  provider: native
plugins:
  native-memory:
    learning: true            # one auxiliary LLM call per finished session (default true)
    task_learning: false      # also record task outcomes for the curator (default false)
    max_new_per_session: 10
    recall_limit: 5
    recall_char_budget: 1200
```

The model for the learning pass is `auxiliary.memory_learning` (defaults to the auxiliary model
resolution used by other background tasks).

## What happens

- **Recall, each turn.** One local FTS5 query over active conclusions, ranked by BM25 weighted by age
  (half-life 180 days). The block is capped in characters and goes through `prefetch()`. The system
  prompt does not change within a session.
- **Learning, at session end.** A background thread asks the model for conclusions with premises. Each
  conclusion passes a threat scan, is deduplicated against active rows, and may supersede rows the model
  was shown. Superseded rows stop being recalled but are kept. A session is marked learned only after its
  reply is processed, so a failed call is retried and a re-run is a no-op.
- **Caps.** At most `max_new_per_session` conclusions per session, a bounded transcript, and at most five
  premises of 200 characters each.

## Operator commands

Available as `hermes native` while `memory.provider` is `native`:

| Command | Does |
|---|---|
| `hermes native list [--outcomes]` | Active conclusions (or task outcome records) |
| `hermes native explain ID` | The conclusion, its premises, the session it came from, whether it was corrected |
| `hermes native correct ID TEXT` | Replace the text; premises are kept |
| `hermes native forget ID` | Delete. The only operation that deletes a row |
| `hermes native export [--file PATH]` | Every row, active and superseded, as JSON |

## Files

- `$HERMES_HOME/memory_native.db`: SQLite, WAL. Separate from the core session state DB.
- Profile isolation follows `get_hermes_home()` at initialise time.

## Status

Phases 0–2 and the operator surface are built. Phase 3 (task outcomes) records outcomes behind
`task_learning`, but the curator does not read them yet. That needs a change in `agent/curator.py`
and is not done. Phase 4 (default on) is not done. The defaults keep it opt-in until a live
evaluation shows the recall and cost gates pass; see `evals/native_memory/README.md`.
