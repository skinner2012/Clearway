# Clearway — M2: Control loop + HITL + observability

## Table of Contents

- [Preamble](#preamble)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)

---

## Preamble

M2 is where the straight pipeline of M0/M1 becomes a real **control loop**, and where the eval & observability layer — Clearway's actual differentiator, the reason the project exists — goes deep. Three pieces:

1. **A durable, hand-rolled orchestrator.** A hand-rolled state machine over the finding set with configurable retry + backoff, idempotency (keyed by `(run_id, finding_id, step)`), a checkpoint table, and resume. Per `ARCHITECTURE.md` §4.6 this is **not** Temporal and **not** LangGraph as *libraries* — but resume honors the same semantic those systems do: it **replays each completed step's cached result rather than recomputing it** (Temporal's event-sourcing replay and LangGraph's state-checkpointing both persist output, not just a status flag — a status-only checkpoint would be a weaker primitive than either). This is load-bearing, not gold-plating: *a flaky harness produces untrustworthy trust-measurements*, so durability is a precondition for the eval to mean anything. The durable machine becomes the **one** execution path — the M1 `run` / `run_set` / `eval` entrypoints refactor to drive findings through it.

2. **The HITL durable-interrupt gate.** The hand-rolled equivalent of LangGraph's `interrupt`: flag a finding → persist a `NeedsReview` record → return; a human approves/edits from a separate entrypoint → the run resumes from checkpoint. This is where **expert edit-distance** becomes measurable (the human edits a draft, we measure the change), and where the co-pilot framing — *speeds up the specialist, never replaces the decision* — becomes concrete.

3. **The full trust dashboard + an honest failure analysis.** The eval scores become first-class metrics on the same Grafana as latency and cost — that is the "control loop is the point" thesis made into a concrete object. One honest boundary drives the whole design: the OTel GenAI semantic conventions give operational telemetry (model, tokens, latency) nearly for free, but they **cannot tell you whether the output was correct** — a span can record "1,200 tokens in 850 ms", not "those citations contradicted ground truth." That quality layer is exactly what Clearway builds, and it is the product. Each run's `EvalReport` is **persisted**, so the accuracy-over-time trend is a true per-run history — not a blur of overwritten gauge values.

Still **single model** (routing deferred) and **no judge yet** (M4) — so κ and confidence-calibration appear on the dashboard as reserved placeholders, not computed numbers. The honest headline from M1 stands: the **unverifiable share** (judgment items with no automated oracle) is the number that matters; M2 makes it observable over time and routes those items to the human.

## Goal & exit criterion

Wrap the M1 forward path in a durable, resumable, observable control loop with a human-in-the-loop gate, and stand up the full trust dashboard plus a written honest failure analysis.

**Exit criterion:**
- A run killed mid-way **resumes from checkpoint** without re-doing completed findings or double-producing.
- Low-confidence / unverifiable-judgment / axe-incomplete findings land in a **needs-review queue**; a human approves or edits them from a separate entrypoint; the run resumes and assembles the final output including the human-approved rows.
- A **Grafana dashboard, provisioned as code**, shows the quality metrics (`citation_hallucination_rate_verifiable`, `unverifiable_share`, `expert_edit_distance`) next to operational metrics (latency, tokens, cost, retries, failures) with an accuracy-over-time trend read from **persisted `EvalReport`s**.
- A written **honest failure analysis** ships, grounded in real traces from a real run **over the fixture set**.

- **Real:** durable orchestrator (retry, idempotency, checkpoint, resume), HITL gate (needs-review queue + approve/edit + durable interrupt), workflow + LLM observability, persisted eval-report history, full trust dashboard (as code), accuracy-over-time, honest failure analysis.
- **Single model:** routing deferred (a later milestone).
- **Absent:** routing (deferred), judge / κ / confidence-calibration (M4 — dashboard placeholders only), MCP server (M3), cache (optimization, later), physical / Regime B, full ACR/VPAT document assembly (later), **live-page scanning + its robots.txt / rate-limit compliance (a Delivery/Demo concern near M3/the FastAPI surface — see `ARCHITECTURE.md` §4.2 "live scanning is a demo feature")**.

## How to use these tickets

Everything depends on **T0** (CONTRACTS additions). **T1** (durable orchestrator) is the spine — the M1 `run` / `run_set` / `eval` entrypoints refactor onto it. The dependency graph would allow some parallelism (T2, T3, and T5 each depend only on T1), but **M2 is built strictly sequentially — `T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7`, one reviewable ticket at a time** (a deliberate review-and-understand choice, see `dev-workflow-prefs`). **T4** depends on T3; **T6** (dashboard) depends on T2 + T4 + T5; **T7** (failure analysis) is written last against a real run. **T1 is the heavy ticket** and will land as 3 commits on one branch (see T1's own `Depends on` line for the breakdown). Persistence for both the durable run (T1) and the eval history (T5) follows the `corpus/store.py` precedent: raw psycopg, `CREATE TABLE IF NOT EXISTS`, no ORM, no migration framework.

## Tickets

### T0 — CONTRACTS additions  *(foundation)*
- **Produces:** additions to `CONTRACTS.md` §3 — `NeedsReview` (HITL record), `RunState` + `StepState` (durable run/step checkpoint), and an `expert_edit_distance` field on `EvalMetrics`. Regenerate `clearway/schemas/models.py`; remove `NeedsReview` from `CONTRACTS.md` §5; add a §6 change-log row.
- **Detail:**
  - `NeedsReview` = `finding_id`, `run_id`, `draft: DraftRow`, `reason` (`low_confidence` | `axe_incomplete` | `unverifiable_judgment`), `status` (`pending` | `approved` | `edited` | `rejected`), `edited_draft: DraftRow | None`, timestamps. **`reason` is a single value; when more than one trigger applies, precedence is `low_confidence` > `axe_incomplete` > `unverifiable_judgment` (decided in T3).**
  - `RunState` = `run_id`, `config_id`, `status` (`running` | `paused` | `done` | `failed`), `created_at`.
  - `StepState` = `run_id`, `finding_id`, `step`, `status` (`pending` | `done` | `failed` | `needs_review`), `attempts`, `updated_at` (the checkpoint unit).
  - `expert_edit_distance` on `EvalMetrics`: type **`float = Field(0.0, ge=0.0)` — unbounded above on purpose**, so T4 can choose normalized-vs-raw distance later without a schema change.
  - Keep `extra="forbid"`.
- **Acceptance:** models import; JSON-schema smoke test passes; `NeedsReview` no longer in §5; new §6 row present.
- **Out of scope:** `RoutingConfig`, `JudgeResult`, `GoldLabel`, L2 faithfulness fields — all remain deferred. **No table/DDL here** — persistence shapes live in the store modules (`corpus/store.py` precedent), and the persisted `EvalReport` (T5) reuses the existing model, so it needs no §3 change.
- **Depends on:** —

### T1 — durable orchestrator (hand-rolled state machine)  *(spine)*
- **Consumes:** `Finding[]` (from the M1 forward path). **Produces:** persisted `RunState` + `StepState` rows; a completed/paused run; new `clearway/orchestrator/store.py` + `clearway/orchestrator/machine.py`; a brief `clearway/orchestrator/README.md`.
- **Detail:** two files with a clean split — **`store.py` is dumb persistence** (`OrchestratorStore` protocol + `PgOrchestratorStore` + `InMemoryOrchestratorStore`, mirroring `corpus/store.py`'s three-part seam exactly — required so the offline test suite never needs a real Postgres connection): rows in, rows out, no domain logic. **`machine.py` is the actual state machine** — `execute(findings, *, run_id, config_id, created_at, do_retrieve, do_draft, oracle, store, max_attempts=3, backoff_seconds=1.0, on_resume=None) -> list[Trace]`, replacing the per-finding loop currently inline in `orchestrator/run.py`'s `_trace_page` (which becomes: scan, normalize, then one call into `execute(...)`).
  - **Retry + backoff**, on transient failures (LLM 429/timeout, browser crash): capped at `max_attempts` (configurable, default 3), exponential backoff (`backoff_seconds * 2**attempt`, configurable base) — parameters, not module constants, so tests can pass `max_attempts=1, backoff_seconds=0` for speed (mirrors the existing `Drafter(client, retries=1)` precedent). Catches bare `Exception` (no transient-vs-permanent classification — matches the existing `_scan_with_retry` precedent). On exhaustion: mark that step `FAILED`, halt *that finding's* pipeline (don't cascade into `draft` with no citations), the run continues to the next finding — do not crash the whole run.
  - **Idempotency + true replay, not recompute.** Keyed by `(run_id, finding_id, step)`. A completed step is **replayed from its cached result**, never recomputed — this is what makes it a durable-execution primitive rather than a task tracker (Temporal's event-sourcing replay and LangGraph's state-checkpointing both persist step *output*, not just a status flag; a hand-rolled equivalent that only recorded status would be materially weaker). The cached result (`list[Citation]` / `DraftRow` / `list[CitationCheck]`, depending on `step` — all already-defined contract types) lives as a `result_json` column on the underlying `step_state` **table** — **store-internal, not a new `CONTRACTS.md` field**, since nothing outside `orchestrator/` ever reads it directly; `machine.py` deserializes it using the type implied by `step`. *(Distinct from `Finding.id`'s cross-run content-hash dedup: resuming a killed run replays completed steps; a fresh run of the same page still re-processes everything.)*
  - **Checkpoint** every step transition (status + attempts + result) to Postgres via `store.py` (raw psycopg + `CREATE TABLE IF NOT EXISTS`, no ORM, no migration framework).
  - **Resume — no new subcommand.** `run()` / `run_set()` gain an optional `run_id: str | None = None`: `None` generates a fresh id (today's behavior); a caller-supplied id resumes that run (the CLI exposes this as `--run-id <existing-id>` on `run` / `eval`). The caller re-supplies the same target(s) — `RunState` carries no `targets` field, so resume relies on `Finding.id`'s determinism to line back up with persisted `step_state` rows, not on re-deriving what to scan.
  - **Resume notice.** `execute()` takes an optional `on_resume` hook (default no-op — keeps it pure/silent in tests, same pattern as the `retrieve`/`draft` seams), called once at the top when resuming with `(run_id, done_count, total_count, next_finding_id)`. The CLI wires it to a real `print(...)` **before** the run proceeds (not just in the final summary) — e.g. `resuming run 6d5e2ba7: 7/10 findings already complete, continuing from h:label`.
  - **The durable machine becomes the one execution path: the existing `run()` / `run_set()` / `eval` refactor to drive findings through it** (they stop running their own ad-hoc loop) — their external signatures/return shape (`RunResult`) stay stable.
  - **`orchestrator/README.md`:** a short orientation to the durable primitives (retry / idempotency / checkpoint / resume / replay) that points to `ARCHITECTURE.md` §4.6 and the `RunState` / `StepState` contracts — orientation, not duplication.
- **Acceptance:** a run killed after N findings resumes and completes **without recomputing** the first N (replayed from cached results) or double-producing; an injected transient error retries then fails that one step while the rest of the run proceeds; identical inputs → identical persisted state; `run` / `run_set` / `eval` still pass their M1 tests through the new path (offline, via `InMemoryOrchestratorStore`); a resumed run prints what it's resuming from before continuing.
- **Out of scope:** distributed/multi-worker execution; a workflow framework; CLI flags for retry tuning (`max_attempts`/`backoff_seconds` are code-configurable in M2; expose as CLI flags later if needed).
- **Depends on:** T0, M1 forward path. *(3 commits: store.py + machine.py with their own tests → refactor `run`/`run_set` onto `execute()`, M1 tests passing unchanged → `run_id`/resume wiring + the kill/resume test + the resume-notice hook.)*

### T2 — workflow + LLM observability
- **Produces:** OTel instrumentation in `observability/`; operational metrics in Prometheus; the dormant `Trace` operational fields populated; a brief `clearway/observability/README.md`.
- **Detail:** model the run/finding/step as OTel **spans** (one trace per run, child spans per finding/step); record retries and failures as span events. Instrument LLM calls with the **GenAI semantic conventions** — `gen_ai.client.operation.duration`, `gen_ai.client.token.usage`, attributes `gen_ai.request.model` / `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` — and set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`. **VERIFY:** the GenAI semconv is still in *Development* and the exact attribute/metric names may churn — confirm against the installed OTel SDK before relying on them (`ARCHITECTURE.md` §4.5). **Capture LLM usage once at the call site and fill BOTH the OTel spans AND the (until-now dormant) `Trace` fields `cost_usd` / `tokens_in` / `tokens_out` / `latency_ms`** — this requires `LLMClient.complete_json` to return content **+ usage** instead of a bare `str`. **Tag telemetry by model** (span attribute + a low-cardinality `model` metric label) so the future cloud-vs-local / multi-model comparison (a later routing milestone) is data-ready; capture `cost_usd` even though local Ollama reports ~0. Add custom pipeline metrics: `pipeline_step_retries_total`, `pipeline_failures_total`, `pipeline_step_duration`. Export via OTel Collector → Prometheus (native OTel naming). **Content capture (prompts/outputs) stays opt-in and redacted** — page-derived content is untrusted (`ARCHITECTURE.md` §4.5). **`observability/README.md`:** what the module emits (spans, GenAI-semconv LLM metrics, custom pipeline metrics) + pointers to `ARCHITECTURE.md` §4.5 and `stack/grafana/README.md`.
- **Acceptance:** a run produces one trace with per-finding child spans; LLM latency + token metrics appear in Prometheus under GenAI-semconv names; the `Trace` quartet is populated (not `None`); retries/failures are visible per run.
- **Out of scope:** MCP-span instrumentation (M3); the **quality/eval** metrics — those are computed by `eval/` (the hallucination rates, since M1) and by T4 (`expert_edit_distance`), and displayed in T6, not emitted by this OTel instrumentation.
- **Depends on:** T1

### T3 — HITL needs-review queue + durable-interrupt gate
- **Consumes:** validated `DraftRow`s + `CitationCheck`s. **Produces:** `NeedsReview` records; a resumed, human-approved run.
- **Detail:** flag a finding for review — **evaluated post-validation, once the `DraftRow` + `CitationCheck`s exist (the record carries the `DraftRow`)** — when the drafter confidence is low, the item is axe-incomplete, or the citation is `UNVERIFIABLE` (judgment item). **When more than one applies, store a single `reason` by precedence `low_confidence` > `axe_incomplete` > `unverifiable_judgment`.** **`low_confidence` uses a conservative placeholder threshold (e.g. `< 0.5`); note that per the M1 weak-spots read, real confidence sits at 0.9–1.0 regardless of correctness, so this trigger is largely dormant until M4 calibration — `axe_incomplete` / `unverifiable_judgment` are the effective M2 triggers.** On flag: persist `NeedsReview(status=pending)` and interrupt that finding's path (the rest of the run continues). Provide a **separate entrypoint** (`clearway review …`) to list the queue, view the draft + finding context, and **approve / edit / reject**. **Edit UX:** `clearway review edit <id>` opens the `DraftRow` as JSON in `$EDITOR` and re-validates on save; a `--remediation "…"` flag supports a quick single-field edit without the editor. **CLI only** — no web UI, no FastAPI surface in M2. On approve/edit: persist the outcome and **resume** the run to assemble the final output including the human-approved rows. This is a durable interrupt — the run survives a restart between flag and resume.
- **Acceptance:** flagged findings appear in the queue and block only their own assembly, not the whole run; an edit is persisted and flows into the assembled output; the queue survives an orchestrator restart (durable).
- **Out of scope:** a web UI (CLI entrypoint is enough for M2); auto-approval heuristics.
- **Depends on:** T0, T1

### T4 — expert edit-distance metric
- **Consumes:** `NeedsReview` records with an `edited_draft`. **Produces:** the `expert_edit_distance` metric.
- **Detail:** compute a **normalized distance in `[0, 1]`** between the original `DraftRow` and the human `edited_draft` — a **`difflib.SequenceMatcher` ratio over the `remediation` text** (the primary human-edited free-text field), plus a categorical **"conformance changed" flag**. **Stdlib only — no new dependency** (`rapidfuzz` / semantic scoring is M4 judge territory). Emit as a Prometheus metric tagged by finding class (axe vs judgment), and aggregate onto `EvalMetrics.expert_edit_distance` (run mean). The trend should fall over time as retrieval/drafting improve.
- **Acceptance:** an unedited approval → distance 0; a known edit → the expected distance; the metric is queryable per run and over time.
- **Out of scope:** semantic-similarity scoring via an LLM (judge territory — M4); a per-field / multi-dimensional distance breakdown (M4) — M2 keeps it a single aggregate scalar.
- **Depends on:** T3

### T5 — eval-report persistence
- **Consumes:** the `EvalReport` produced at run completion. **Produces:** persisted `EvalReport` rows in Postgres — the accuracy-over-time history.
- **Detail:** persist each run's `EvalReport` to a new `eval_report` table in `orchestrator/store.py` (keyed by `run_id`; metrics stored as columns or JSONB — choice noted in the ticket). The durable run writes its report at completion, alongside its `RunState`. This is the **data-production half** of the dashboard's accuracy-over-time trend (T6): M1 only pushed gauge values to Prometheus with **no `run_id`**, which blurs runs together; persisted reports give a true per-run history you can query and analyse. Raw psycopg + `CREATE TABLE IF NOT EXISTS`, no ORM (`corpus/store.py` precedent). The `EvalReport` model already exists in `CONTRACTS.md` §3 — this is **persistence, not a new contract shape** (no T0 change).
- **Acceptance:** a completed run persists exactly one `EvalReport` row (`run_id` PK); a second run adds a second row; rows are queryable by run and by `created_at`; a resumed run does **not** duplicate the row (idempotent on `run_id`).
- **Out of scope:** a query API / reporting endpoint (analysis reads the table directly for now).
- **Depends on:** T1

### T6 — trust dashboard (dashboard-as-code)  *(the control loop, made visible)*
- **Produces:** the **extended** version-controlled Grafana dashboard + a Grafana Postgres datasource, both provisioned from repo config.
- **Detail:** **extend the existing dashboard** `stack/grafana/dashboards/citation_hallucination.json` (**uid `clearway-m0-trust` — keep the uid stable**; retitle to a milestone-neutral **"Clearway — Trust Dashboard"**) — do **not** create a second, competing dashboard. Panels for **quality metrics** (`citation_hallucination_rate_verifiable`, `unverifiable_share`, `expert_edit_distance`) computed by `eval/` + T4 and exported as Prometheus metrics; **operational** panels (LLM latency, token usage, cost, retries, failures) from T2; an **accuracy-over-time** trend read from the persisted `EvalReport` rows (T5) via a **new Grafana Postgres datasource** (today only Prometheus is provisioned — add a `postgres` datasource under `stack/grafana/provisioning/datasources/`). Reserve labelled placeholder panels for **judge κ** and **confidence-calibration** — they light up in M4. The dashboard's whole point: eval scores sit on the same board as latency/cost, because the measurement is the product.
- **Acceptance:** the dashboard loads from repo provisioning on a fresh Grafana; quality + operational panels populate from a real run; the accuracy-over-time panel shows ≥2 runs (from persisted `EvalReport`s via the Postgres datasource); κ/calibration panels are present but marked "M4".
- **Out of scope:** alerting rules; the κ/calibration computations (M4).
- **Depends on:** T2, T4, T5

### T7 — honest failure analysis  *(written deliverable / exit)*
- **Produces:** a short written report in `docs/` (continuing `docs/M1-weak-spots.md` — e.g. `docs/M2-failure-analysis.md`) analysing where retrieval, drafting, or validation failed and **why**, grounded in real traces from a real run **over the fixture set (`m1-core@1`) — fixture-only** (live-page scanning is deferred; see the *Absent* list).
- **Detail:** name concrete failure modes (which finding types retrieve the wrong SC; where drafts read thin; how much of the output is unverifiable and lands on the human); tie each claim to a trace. State the current unverifiable share and edit-distance. This is the honest audit that distinguishes a real eval story from a metrics wall — the senior/staff signal, and the direct input to M4's judge calibration.
- **Acceptance:** the report cites ≥3 concrete, trace-grounded failure modes and states the current unverifiable share and edit-distance; no flattering hand-waving.
- **Depends on:** T1–T6 + a real run
