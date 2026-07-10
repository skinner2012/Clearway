# Clearway

## Introduction

An accessibility evidence pipeline: it turns a raw accessibility signal into decision-ready, cited, confidence-scored conformance evidence for a human specialist, and measures the trustworthiness of its own AI-generated outputs. It never decides conformance — the specialist does. It starts with websites (where an automated checker gives near-free ground truth) and is designed to extend to physical audits.

## Motivation

Accessibility evaluation is expensive not because problems are hard to detect, but because **documenting defensible findings** is — mapping each issue to the correct citation, writing remediation an implementer can act on, and assembling a standards-shaped report. The costly unit is **expert-minutes-per-finding**, and that is what Clearway sets out to compress.

The design bet: the scarce, defensible thing is not the forward path (scan → retrieve → draft, which many tools already do) but **measuring how far the AI's own outputs can be trusted**. So Clearway hands a human specialist decision-ready evidence *together with* its own trust metrics, and never decides conformance itself. That is the thesis — **measured trust is the product**.

The full rationale — the regulatory backdrop (FTC v. accessiBe), the two-oracle-regime design, detailed scope, and an honest truth-ledger — lives in [`DESIGN_NOTE.md`](DESIGN_NOTE.md).

## Status

Early — **M2 (control loop + observability) is complete**: the forward path now runs on a durable, checkpointed orchestrator with full OTel tracing and LLM/pipeline metrics, a human-in-the-loop review gate that routes unverifiable findings to a specialist queue, an `expert_edit_distance` correction metric, per-run eval-report persistence, and a Grafana trust dashboard that puts the quality metrics on the same board as latency and cost. The trust metric remains stratified into a verifiable-subset rate and the honest `unverifiable_share` — the fraction of citations no automated oracle can check. See [`specs/M2-control-loop.md`](specs/M2-control-loop.md), the [M2 failure analysis](docs/M2-failure-analysis.md) (which continues the [M1 weak spots](docs/M1-weak-spots.md)), and [Running the pipeline](#running-the-pipeline). Next up is **M3**.

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

The pipeline runs the real forward path — scan (Playwright + axe-core) → normalize → **retrieve** (real embedder + pgvector) → **draft** (real LLM via Ollama) → validate → eval — and reports the stratified trust metrics: the overall `citation_hallucination_rate`, the verifiable-subset rate, and the honest `unverifiable_share`. There is no offline/stub mode from the CLI (stubs are test-only), so each command hits the services it needs; `--no-emit` only skips the OTel push, not the model calls.

First, ingest the WCAG corpus once so the retriever has something to search. This needs the Ollama **embedding** model + **pgvector** (started by `docker compose up -d`) — but *not* the chat model:

```bash
uv run clearway corpus-ingest                                    # fetch WCAG 2.2 → chunk + embed → upsert into pgvector
uv run clearway corpus-query "images need a text alternative"    # sanity-check retrieval
```

Then run the forward path — over one page, or the whole eval set. This needs the **full stack**: the Ollama **chat** *and* **embedding** models, **pgvector**, and a headless browser to scan:

```bash
uv run clearway run clearway/fixtures/pages/home.html   # one page
uv run clearway eval                                     # the m1-core@1 fixture set (3 pages, 5 findings)

# --no-emit computes + prints only; without it, the metrics push to OTel and the Grafana panel moves:
uv run clearway eval --no-emit
```

Emitted metrics land on the **Clearway — Trust Dashboard** at <http://localhost:3000> — see [`stack/grafana/README.md`](stack/grafana/README.md) for how to read its panels.

## Retrieval as an MCP service

Retrieval is also exposed as a standalone **MCP server** so tools *other than* the Clearway pipeline can reuse it: given a described accessibility problem, it returns the applicable WCAG success criteria as complete, cited evidence. This is the one component with genuine production reuse value — see [`ARCHITECTURE.md`](ARCHITECTURE.md) §4.7.

Ingest the corpus first (`uv run clearway corpus-ingest`, above), then start the server and, in another terminal, run the external reference client:

```bash
uv run clearway mcp-serve                        # long-lived host process; mounts /mcp
uv run python scripts/mcp_retrieval_client.py    # external client: sends an EvidenceQuery, prints cited evidence
```

The full interface — endpoint, transport, the `EvidenceQuery` / `Citation` schemas, error semantics, and a sample request/response — is documented in [`docs/mcp-retrieval-interface.md`](docs/mcp-retrieval-interface.md).

## Documentation

- [`DESIGN_NOTE.md`](DESIGN_NOTE.md) — full product scope, thesis, and rationale.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — decisions of record: stack, module boundaries, milestones.
- [`CONTRACTS.md`](CONTRACTS.md) — the shared data schemas (single source of truth).
- [`CLAUDE.md`](CLAUDE.md) — working conventions and rules of engagement for Claude Code and contributors.
- [`docs/mcp-retrieval-interface.md`](docs/mcp-retrieval-interface.md) — integration reference for the retrieval MCP service.
- [`specs/`](specs/) — per-milestone task tickets.
- [`docs/`](docs/) — milestone notes and analysis.

## License & authorship

Licensed under the [Apache License 2.0](LICENSE). You may use and build on this work, but must retain the attribution in [`NOTICE`](NOTICE). Original author, architect, and designer: **FuYuan (Skinner) Cheng**. The public commit history is the authoritative record of authorship and precedence.
