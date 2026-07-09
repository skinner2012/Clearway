# Clearway observability — telemetry & eval-as-metric

OTel instrumentation for the durable control loop (`ARCHITECTURE.md` §4.5). Two families, mirroring
the split §4.5 draws — **(1) operational observability** (latency, tokens, cost, retries) and
**(2) quality evaluation** (is the output trustworthy). (2) is the actual product: eval scores sit on
the *same* Grafana as latency and cost.

Everything is emitted through the OTel **API**, which is inert until the CLI installs a provider —
so an offline / `--no-emit` run (and the whole test suite) needs no collector.

## Layout

- [`metrics.py`](metrics.py) — the **quality** trust gauges, set from a finished `EvalReport`:
  `citation_hallucination_rate`, `citation_hallucination_rate_verifiable`, `unverifiable_share`.
  Low-cardinality labels only (no `run_id`), so one series *moves* across runs. Owns the
  `MeterProvider` (and installs it globally so `operational.py` exports through the same reader).
- [`operational.py`](operational.py) — the **operational** metrics, recorded from
  `orchestrator/machine.py` *during* the run: GenAI-semconv LLM metrics + custom `pipeline_*` metrics.
- [`tracing.py`](tracing.py) — run/finding/step **spans**.
- [`smoke.py`](smoke.py) — `python -m clearway.observability.smoke` validates the metric pipeline
  hop-by-hop, independent of a real run.

## What it emits

### Spans (tracing.py + machine.py)

One trace per run: `clearway.run` → `clearway.finding` → `clearway.step.<retrieve|draft|validate>`.
Retries are `attempt_failed` span events; an exhausted step records the exception and an ERROR
status; a replayed step is tagged `clearway.replayed=true`. Model is a span attribute.

### Metrics

| Metric (Prometheus name) | Type | Source | Notes |
|---|---|---|---|
| `citation_hallucination_rate` | gauge | `metrics.py` | overall quality (M1) |
| `citation_hallucination_rate_verifiable` | gauge | `metrics.py` | oracle-verifiable subset |
| `unverifiable_share` | gauge | `metrics.py` | the honest headline |
| `gen_ai_client_operation_duration_seconds` | histogram | `operational.py` | LLM latency, GenAI semconv |
| `gen_ai_client_token_usage` | histogram | `operational.py` | tokens, split by `gen_ai_token_type=input\|output` |
| `pipeline_step_retries_total` | counter | `operational.py` | retries beyond the first, by `step` |
| `pipeline_failures_total` | counter | `operational.py` | steps that exhausted retries, by `step` |
| `pipeline_step_duration` | histogram | `operational.py` | wall-clock seconds per step, by `step` |

LLM metrics are tagged by `gen_ai_request_model` so the M4 cloud-vs-local comparison is data-ready;
`cost_usd` is captured even though local Ollama reports ~0. The same usage — captured once at the
call site (`drafter/llm.py`) — also fills the `Trace` operational quartet (`cost_usd` / `tokens_in`
/ `tokens_out` / `latency_ms`). Counters carry no `_total` in the instrument name — the Prometheus
exporter appends it.

## GenAI semconv is Development-stage

The `gen_ai.*` metric and attribute names may churn (`ARCHITECTURE.md` §4.5). They were **verified
against the installed OTel SDK** (`opentelemetry-semantic-conventions 0.64b0`) before use, sourced
from `opentelemetry.semconv._incubating`, and `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
is set. Re-verify on an SDK bump.

## Seeing it

Bring the stack up and do a **real** run (operational + LLM metrics come from real Ollama calls —
fixture/stub runs emit no `gen_ai.*` points):

```
docker compose up -d
uv run clearway eval          # --no-emit to skip all telemetry
```

Metrics reach Prometheus via the Collector; query them ad-hoc in **Grafana → Explore** now, e.g.
`rate(pipeline_step_retries_total[5m])` or `gen_ai_client_token_usage_sum`. Provisioned **dashboard
panels** for these land in **T6** (the trust dashboard extends
[`stack/grafana`](../../stack/grafana/README.md), uid `clearway-m0-trust`, kept stable).

**Traces have no viewer yet:** the collector's `traces` pipeline echoes spans to its own log
(`docker compose logs otel-collector`). A real trace backend (**Grafana Tempo**) is deferred —
`ARCHITECTURE.md` §4.5 marks it optional-later; because spans are standard OTel, adding Tempo later
is a compose service + a Grafana datasource, no application-code change.
