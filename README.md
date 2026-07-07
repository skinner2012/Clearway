# Clearway

## Introduction

An accessibility evidence pipeline: it turns a raw accessibility signal into decision-ready, cited, confidence-scored conformance evidence for a human specialist, and measures the trustworthiness of its own AI-generated outputs. It never decides conformance — the specialist does. It starts with websites (where an automated checker gives near-free ground truth) and is designed to extend to physical audits.

## Motivation

Accessibility evaluation is expensive not because problems are hard to detect, but because **documenting defensible findings** is — mapping each issue to the correct citation, writing remediation an implementer can act on, and assembling a standards-shaped report. The costly unit is **expert-minutes-per-finding**, and that is what Clearway sets out to compress.

The design bet: the scarce, defensible thing is not the forward path (scan → retrieve → draft, which many tools already do) but **measuring how far the AI's own outputs can be trusted**. So Clearway hands a human specialist decision-ready evidence *together with* its own trust metrics, and never decides conformance itself. That is the thesis — **measured trust is the product**.

The full rationale — the regulatory backdrop (FTC v. accessiBe), the two-oracle-regime design, detailed scope, and an honest truth-ledger — lives in [`DESIGN_NOTE.md`](DESIGN_NOTE.md).

## Status

Early — currently building **M0 (walking skeleton)**, the thinnest end-to-end run that proves the measurement loop is real. See [`specs/M0-walking-skeleton.md`](specs/M0-walking-skeleton.md).

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

## Documentation

- [`DESIGN_NOTE.md`](DESIGN_NOTE.md) — full product scope, thesis, and rationale.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — decisions of record: stack, module boundaries, milestones.
- [`CONTRACTS.md`](CONTRACTS.md) — the shared data schemas (single source of truth).
- [`CLAUDE.md`](CLAUDE.md) — working conventions and rules of engagement for Claude Code and contributors.
- [`specs/`](specs/) — per-milestone task tickets.

## License & authorship

Licensed under the [Apache License 2.0](LICENSE). You may use and build on this work, but must retain the attribution in [`NOTICE`](NOTICE). Original author, architect, and designer: **FuYuan (Skinner) Cheng**. The public commit history is the authoritative record of authorship and precedence.
