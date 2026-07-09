# Clearway trust dashboard

Grafana is provisioned from this directory ([`provisioning/`](provisioning/) wires the Prometheus
datasource + the dashboards folder; [`dashboards/`](dashboards/) holds the JSON). One dashboard
today — **Clearway — M1 Trust Metric** (`dashboards/citation_hallucination.json`, uid
`clearway-m0-trust`). The uid is kept stable across milestones on purpose (renaming it orphans the
dashboard and breaks any saved link); only the **title** tracks the milestone.

## What it shows

The pipeline's headline is not "how good is the AI" — it's **how much of the AI's output we can
actually verify, and how honest we are about the rest**. The dashboard is that split, straight from
the emitted metrics ([`clearway/observability/metrics.py`](../../clearway/observability/metrics.py)):

| Panel | Metric | Reading |
|---|---|---|
| citation_hallucination_rate (overall) | `citation_hallucination_rate` | All drafted citations that fail L0/L1, verifiable + unverifiable pooled. The blended number; the row below un-blends it. |
| unverifiable_share (the honest headline) | `unverifiable_share` | Citations with **no automated oracle** (axe `incomplete` → `NO_ORACLE` → `UNVERIFIABLE`). **Not an error** — the coverage gap the pipeline is honest about, and what M5 calibration must shrink. Coloured neutrally (blue), not pass/fail. |
| current rate (verifiable subset) | `citation_hallucination_rate_verifiable` | Hallucination rate over **only** the oracle-verifiable citations (axe `violations`). ~0 by construction — anything above green is a real citation fault where an oracle exists to catch it. |

`hallucinations_total` is the numerator of **both** rates; `UNVERIFIABLE` is never counted as a
hallucination, so every hallucination lives in the verifiable subset. That is why the honest story
is two numbers, never one: a low overall rate can hide a large unverifiable share.

## Labels

All series carry the low-cardinality label set `eval_set_id` / `config_id` / `oracle_regime` (no
`run_id` — see the metrics module for why). A run's value therefore **moves the same line** rather
than spawning a new series. The M1 set run emits under `eval_set_id="m1-core@1"`.

## Seeing values

Bring the stack up (`docker compose up -d`), then emit a report:

```
uv run clearway eval          # runs the m1-core@1 set, emits all three metrics
uv run clearway run <page>    # single page (emits under its own eval_set_id)
```

Grafana scrapes Prometheus every 5s; the panels refresh at the same cadence.

> Location note: this doc lives beside the dashboard JSON it documents. If a top-level `docs/`
> directory lands later, move it there.
