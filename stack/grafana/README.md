# Clearway trust dashboard

Grafana is provisioned from this directory ([`provisioning/`](provisioning/) wires the **Prometheus**
+ **Postgres** datasources and the dashboards folder; [`dashboards/`](dashboards/) holds the JSON).
One dashboard — **Clearway — Trust Dashboard** (`dashboards/citation_hallucination.json`, uid
`clearway-m0-trust`). The uid is kept stable across milestones on purpose (renaming it orphans the
dashboard and breaks any saved link); the **title** is milestone-neutral.

## What it shows

The pipeline's headline is not "how good is the AI" — it's **how much of the AI's output we can
actually verify, how honest we are about the rest, and what it costs to produce that measurement**.
The dashboard puts all three on one board, in stacked rows.

### Quality — trust metrics

Straight from the emitted metrics ([`clearway/observability/metrics.py`](../../clearway/observability/metrics.py)):

| Panel | Metric | Reading |
|---|---|---|
| citation_hallucination_rate (overall) | `citation_hallucination_rate` | All drafted citations that fail L0/L1, verifiable + unverifiable pooled. The blended number; the row below un-blends it. |
| unverifiable_share (the honest headline) | `unverifiable_share` | Citations with **no automated oracle** (axe `incomplete` → `NO_ORACLE` → `UNVERIFIABLE`). **Not an error** — the coverage gap the pipeline is honest about, and what judge calibration must shrink. Coloured neutrally (blue), not pass/fail. |
| current rate (verifiable subset) | `citation_hallucination_rate_verifiable` | Hallucination rate over **only** the oracle-verifiable citations (axe `violations`). ~0 by construction — anything above green is a real citation fault where an oracle exists to catch it. |
| expert_edit_distance | `expert_edit_distance` | Mean normalized text-edit distance between drafted and human-edited remediations, over drafts a reviewer edited through the HITL gate. 0 = shipped unedited; higher = model judgment drifted from the expert. |

`hallucinations_total` is the numerator of **both** rates; `UNVERIFIABLE` is never counted as a
hallucination, so every hallucination lives in the verifiable subset. That is why the honest story
is two numbers, never one: a low overall rate can hide a large unverifiable share.

### Accuracy over time — persisted `eval_report` history (Postgres)

The quality gauges above carry no `run_id`, so successive runs **move the same line** rather than
building a history (a deliberate low-cardinality choice — see the metrics module). The true per-run
trend comes instead from the **persisted `eval_report` rows** (one row per completed run), read
through the **Postgres datasource** via a small `jsonb` query over `report_json`. This is the panel
that shows accuracy *across* runs, not just the latest value.

### Operational — the cost of producing the measurement

From the OTel instrumentation in [`clearway/observability/operational.py`](../../clearway/observability/operational.py),
so eval scores sit next to what they cost: LLM call latency (`gen_ai_client_operation_duration_seconds`),
token usage split by input/output (`gen_ai_client_token_usage`), pipeline step retries/failures
(`pipeline_step_retries_total` / `pipeline_failures_total` — "no data" until a retry actually
happens) and per-step duration (`pipeline_step_duration`). Cost is captured per-trace (`Trace.cost_usd`)
but ≈ 0 for local Ollama, so it has no live series yet — it lights up when cloud LLMs enter the
comparison.

### Judge calibration & confidence

The judge-reliability and confidence panels (`judge_kappa`, `judge_agreement_rate`, the
confidence→correctness curve, `expected_calibration_error`, `overconfidence_gap`) — pushed
point-in-time by the calibration snapshot, not by a per-run tick. They show the judge cleared its
self-built-gold bar (κ 0.79) and that the drafter's self-reported confidence is systematically
over-confident.

### Benchmark — held-out acceptance (ACT gold)

The frozen acceptance scorecard (`benchmark_*` series), pushed point-in-time by the acceptance
snapshot from [`benchmark/reports/scorecard.json`](../../benchmark/reports/scorecard.json): the
drafter's recall and false-positive rate (with Wilson bounds + n), the judge's confusion against
**external** expert gold (κ, the dangerous miss-rate, false-alarm, injected-detection upper bounds),
and the noise floor. Nothing on this row is scored by an LLM. The honest headline lives here — the
full diagnosis is the [acceptance-benchmark failure analysis](../../docs/acceptance-analysis.md).

## Labels

Quality series carry the low-cardinality label set `eval_set_id` / `config_id` / `oracle_regime`
(no `run_id` — the Postgres history above is the run-keyed view instead). Operational series are
tagged by `gen_ai.request.model` and `step`. The core forward-path run emits under `eval_set_id="m1-core@1"`.

## Seeing values

Bring the stack up (`docker compose up -d`), then emit a report:

```
uv run clearway eval          # runs the m1-core@1 set: emits the metrics + persists an eval_report row
uv run clearway run <page>    # single page (emits under its own eval_set_id)
```

Prometheus panels refresh at Grafana's 5s scrape cadence; the accuracy-over-time panel gains a point
each time a run persists its `eval_report` (run `eval` twice to see the trend). Operational metrics
appear only on a **real** run (a stub/fixture run emits no `gen_ai.*`).

> Location note: this doc lives beside the dashboard JSON it documents. If a top-level `docs/`
> directory lands later, move it there.
