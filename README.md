# Clearway

## Introduction

An accessibility evidence pipeline: it turns a raw accessibility signal into decision-ready, cited, confidence-scored conformance evidence for a human specialist, and measures the trustworthiness of its own AI-generated outputs. It never decides conformance — the specialist does. It starts with websites (where an automated checker gives near-free ground truth) and is designed to extend to physical audits.

## Motivation

Accessibility evaluation is expensive not because problems are hard to detect, but because **documenting defensible findings** is — mapping each issue to the correct citation, writing remediation an implementer can act on, and assembling a standards-shaped report. The costly unit is **expert-minutes-per-finding**, and that is what Clearway sets out to compress.

The design bet: the scarce, defensible thing is not the forward path (scan → retrieve → draft, which many tools already do) but **measuring how far the AI's own outputs can be trusted**. So Clearway hands a human specialist decision-ready evidence *together with* its own trust metrics, and never decides conformance itself. That is the thesis — **measured trust is the product**.

The full rationale — the regulatory backdrop (FTC v. accessiBe), the two-oracle-regime design, detailed scope, and an honest truth-ledger — lives in [`DESIGN_NOTE.md`](DESIGN_NOTE.md).

## Status

Early — **M0 (walking skeleton) is complete**: the thinnest end-to-end run that proves the measurement loop is real, with one trust metric moving on a live Grafana panel. See [`specs/M0-walking-skeleton.md`](specs/M0-walking-skeleton.md) and [Running the pipeline](#running-the-pipeline). Next up is **M1** (real retriever + drafter).

## Development

Requires [uv](https://docs.astral.sh/uv/), which manages the Python 3.13 toolchain and a project-local `.venv` — no system Python needed.

```bash
uv sync                 # create .venv + install deps (incl. dev tools)

uv run pytest           # tests
uv run ruff format .    # format
uv run ruff check .     # lint
uv run mypy clearway    # type-check
```

### Local stack & configuration

The observability stack (OTel Collector + Prometheus + Grafana) runs via Docker; see [`ARCHITECTURE.md`](ARCHITECTURE.md) §4 for the services and rationale.

```bash
cp env.example .env     # then edit .env; it is gitignored — never commit real secrets
docker compose up -d    # start the stack (Grafana → http://localhost:3000)
docker compose down     # stop it
```

**`env.example`** is the committed, non-secret **template** for your local `.env`. It documents the environment variables the stack and app read — the OTLP endpoint the app pushes metrics to, and the local Grafana credentials — with safe placeholder defaults. Copy it to `.env` and adjust; `.env` itself is gitignored, so real values never enter version control.

## Running the pipeline

`clearway run <fixture>` executes the M0 forward path over one page — scan (real Playwright + axe-core) → normalize → retrieve *(stub)* → draft *(stub)* → validate → eval — and reports `citation_hallucination_rate`, the M0 trust metric.

```bash
# compute + print the metric only — no stack needed:
uv run clearway run clearway/fixtures/pages/home.html --no-emit

# push the metric so the Grafana panel moves (needs `docker compose up -d` first):
uv run clearway run clearway/fixtures/pages/home.html            # planted faults  → 0.667
uv run clearway run clearway/fixtures/pages/home.html --clean    # correct citations → 0.000

uv run clearway run --help
```

The fixture carries three planted findings and two intentional citation faults, so the honest rate is **2/3**. `--clean` drafts the correct citations instead (rate **0.0**); alternating runs draw a moving line on the **Clearway — M0 Trust Metric** panel at <http://localhost:3000>. When the stack is down, use `--no-emit` — emitting otherwise fails to reach the collector at `localhost:4318`.

## Documentation

- [`DESIGN_NOTE.md`](DESIGN_NOTE.md) — full product scope, thesis, and rationale.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — decisions of record: stack, module boundaries, milestones.
- [`CONTRACTS.md`](CONTRACTS.md) — the shared data schemas (single source of truth).
- [`CLAUDE.md`](CLAUDE.md) — working conventions and rules of engagement for Claude Code and contributors.
- [`specs/`](specs/) — per-milestone task tickets.

## License & authorship

Licensed under the [Apache License 2.0](LICENSE). You may use and build on this work, but must retain the attribution in [`NOTICE`](NOTICE). Original author, architect, and designer: **FuYuan (Skinner) Cheng**. The public commit history is the authoritative record of authorship and precedence.
