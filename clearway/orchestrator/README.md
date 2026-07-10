# Clearway orchestrator — durable control loop

The durable, checkpointed, resumable state machine that drives every finding through
retrieve → draft → validate (`ARCHITECTURE.md` §4.6). Not Temporal, not LangGraph — a hand-rolled
mini-harness over the same primitives, built to understand them and be able to say why those
frameworks exist.

## Layout

- [`store.py`](store.py) — the `OrchestratorStore` seam: dumb persistence only. `PgOrchestratorStore`
  (Postgres, the same `clearway` database `corpus/store.py` uses) and `InMemoryOrchestratorStore`
  (the offline stand-in tests inject) both implement it. Holds the `run_state` / `step_state` durable
  checkpoints, the `needs_review` HITL queue, and the `eval_report` run history.
- [`machine.py`](machine.py) — the actual state machine, `execute()`. Checkpoints every step
  (`RunState`/`StepState`, `CONTRACTS.md` §3) to the store, retries transient failures with backoff,
  replays a completed step from its cached result instead of recomputing it on resume, and runs the
  HITL gate that flags a finding for human review post-validation.
- [`run.py`](run.py) — thin wrappers, `run()`/`run_set()`: scan → normalize, then one call into
  `execute()`; aggregate the resulting traces into an `EvalReport` and persist it at completion.

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

## Run history (persisted reports)

At completion each run persists its `EvalReport` (`CONTRACTS.md` §3) to the `eval_report` table,
keyed by `run_id` (PK). The report is stored whole as JSON with `created_at` lifted into its own
column, so history is queryable by run and by time without exploding every metric into a column.

This is the **data-production half** of the trust dashboard's accuracy-over-time trend (T6): M1's
Prometheus gauges carry no `run_id`, so successive runs blur together on a time series; a persisted
per-run row gives a true history you can query and trend. Because the key is `run_id`, a resumed run
(e.g. a post-approval reflow) overwrites its own row rather than duplicating it — the reflowed
metrics win, and the history never double-counts one run.

## HITL review gate (the durable interrupt)

The hand-rolled equivalent of LangGraph's `interrupt` (`ARCHITECTURE.md` §4.6). Evaluated in
`machine.py` **after** validation, once a finding's `DraftRow` + `CitationCheck`s exist. A finding is
flagged when one trigger fires — a single `reason` is stored, by precedence:

| Reason | Fires when | M2 status |
|---|---|---|
| `low_confidence` | `draft.confidence < 0.5` | **dormant** — real confidence sits at 0.9–1.0 regardless of correctness, so this trigger is inert until M5 calibration |
| `axe_incomplete` | the finding came from axe's `incomplete` bucket (no oracle verdict) | effective |
| `unverifiable_judgment` | a citation is `UNVERIFIABLE` (valid SC, no oracle to check it) | effective |

On flag, a `NeedsReview(status=pending)` record (`CONTRACTS.md` §3) is persisted and **that finding is
withheld from the report** — the rest of the run continues. Because the record is durable, the queue
survives an orchestrator restart between flag and resolution.

A human resolves the queue from a **separate entrypoint**, `clearway review`:

```
uv run clearway review list [--status pending]        # the queue
uv run clearway review show <finding-id>              # draft + reason + context
uv run clearway review approve <finding-id>           # keep the draft as-is
uv run clearway review edit <finding-id>              # opens the DraftRow JSON in $EDITOR (re-validated on save)
uv run clearway review edit <finding-id> --remediation "…"   # quick single-field edit, no editor
uv run clearway review reject <finding-id>            # keep it out of the output
```

`review` commands mutate the record and print the exact resume command; they do **not** re-scan
themselves (resume needs the target re-supplied — `RunState` carries no `targets`). Resolving a
review then flowing it into the output is two steps:

```
uv run clearway review approve <finding-id>
uv run clearway eval --run-id <existing-id>           # resume: the approved/edited row now assembles
```

On resume the gate reads the `NeedsReview` status back: `approved` assembles the original draft,
`edited` re-validates the human's `edited_draft` and assembles that, `pending` / `rejected` stay
withheld.

An `edited` review is also the raw material for the **`expert_edit_distance`** metric
(`eval/edit_distance.py`): a normalized `[0, 1]` `difflib` ratio over how far the human moved the
draft's `remediation` text (`0` = an unedited approval). The run mean folds onto
`EvalMetrics.expert_edit_distance` (`CONTRACTS.md` §3) and exports as a Prometheus gauge alongside the
hallucination rates — the human-correction signal the trust dashboard tracks over time.
