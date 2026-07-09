# Clearway orchestrator — durable control loop

The durable, checkpointed, resumable state machine that drives every finding through
retrieve → draft → validate (`ARCHITECTURE.md` §4.6). Not Temporal, not LangGraph — a hand-rolled
mini-harness over the same primitives, built to understand them and be able to say why those
frameworks exist.

## Layout

- [`store.py`](store.py) — the `OrchestratorStore` seam: dumb persistence only. `PgOrchestratorStore`
  (Postgres, the same `clearway` database `corpus/store.py` uses) and `InMemoryOrchestratorStore`
  (the offline stand-in tests inject) both implement it.
- [`machine.py`](machine.py) — the actual state machine, `execute()`. Checkpoints every step
  (`RunState`/`StepState`, `CONTRACTS.md` §3) to the store, retries transient failures with backoff,
  and replays a completed step from its cached result instead of recomputing it on resume.
- [`run.py`](run.py) — thin wrappers, `run()`/`run_set()`: scan → normalize, then one call into
  `execute()`; aggregate the resulting traces into an `EvalReport`.

## Durable primitives

| Primitive | How |
|---|---|
| Retry + backoff | `max_attempts` / `backoff_seconds` params on `execute()` (default 3, exponential) — function parameters, not module constants, so tests can zero them out. |
| Idempotency | Keyed by `(run_id, finding_id, step)` — distinct from `Finding.id`'s cross-run content-hash dedup. Resuming a `run_id` skips/replays its completed steps; a fresh run of the same page reprocesses everything. |
| Checkpoint | Every step transition (status + attempts + result) is persisted before moving on to the next step. |
| Resume | `run()` / `run_set()` take an optional `run_id`: `None` starts fresh, an existing id resumes. The caller re-supplies the same target(s) — `RunState` carries no `targets` field, so resume relies on `Finding.id` being a deterministic hash to line back up with persisted rows. |
| Replay, not recompute | A step already checkpointed DONE is deserialized from its cached `result_json` and returned as-is — never re-run. This is what makes it a durable-execution primitive rather than a task tracker: Temporal's event-sourcing replay and LangGraph's state-checkpointing both persist step *output*, not just a status flag; a status-only checkpoint would be materially weaker. |

`result_json` lives on the `step_state` table but is store-internal, not a `CONTRACTS.md` field —
nothing outside this module reads it directly.

## Resuming a run

```
uv run clearway run <page> --run-id <existing-id>
uv run clearway eval --run-id <existing-id>
```

Prints a notice — `resuming run <id>: N/M findings already complete, continuing from <finding_id>`
— before the run proceeds, not just in a final summary.
