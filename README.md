# Clearway

## Introduction

An accessibility evidence pipeline: it turns a raw accessibility signal into decision-ready, cited conformance evidence for a human specialist, and measures the trustworthiness of its own AI-generated outputs. It never decides conformance — the specialist does. It starts with websites (where an automated checker gives near-free ground truth) and is designed to extend to physical audits.

## Motivation

Accessibility evaluation is expensive not because problems are hard to detect, but because **documenting defensible findings** is — mapping each issue to the correct citation, writing remediation an implementer can act on, and assembling a standards-shaped report. The costly unit is **expert-minutes-per-finding**, and that is what Clearway sets out to compress.

The design bet: the scarce, defensible thing is not the forward path (scan → retrieve → draft, which many tools already do) but **measuring how far the AI's own outputs can be trusted**. So Clearway hands a human specialist decision-ready evidence *together with* its own trust metrics, and never decides conformance itself. That is the thesis — **measured trust is the product**.

The full rationale — the regulatory backdrop (FTC v. accessiBe), the two-oracle-regime design, detailed scope, and an honest truth-ledger — lives in [`DESIGN_NOTE.md`](DESIGN_NOTE.md).

## Status

Early, but the eval layer — Clearway's differentiator — has reached its sharpest point. The foundation is in place: a durable, checkpointed forward path (scan → retrieve → draft → validate → eval) with full OTel tracing, a human-in-the-loop review gate, per-run eval-report persistence, a Grafana trust dashboard where the stratified trust metric (a verifiable-subset rate plus the honest `unverifiable_share`) sits beside latency and cost, and retrieval exposed as a standalone MCP service ([below](#retrieval-as-an-mcp-service)). For the judgment items that have *no* automated oracle, an LLM judge grades the drafts and was checked against a self-built gold set before use — **Cohen's κ 0.79**, clearing a bar committed before the number was seen (a verdict the held-out benchmark below later overturned) — and the dashboard charts confidence against correctness.

The newest and most important result is a **held-out acceptance benchmark** on W3C ACT expert-authored gold: the first numbers scored on content the system never saw during development, with **nothing graded by an LLM**. It reports an honest negative. Against *external* gold the judge's agreement collapses from κ 0.79 to **≈ 0** (worse than chance in one of three runs), and the drafter flags **~43%** of genuinely-clean content — it "cries wolf." The two failures are largely one event: the judge co-signs the drafter's false positives, so the "verify" stage cannot catch the "draft" stage's mistakes. Self-reported confidence still carries no usable signal — held out, it confirms the earlier negative. The full trace-grounded diagnosis is the [acceptance-benchmark failure analysis](docs/acceptance-analysis.md); the benchmark is now the frozen regression baseline, and what comes next is chosen from its findings. Earlier notes: the [judge-calibration report](docs/M4-calibration-report.md), the [forward-path failure analysis](docs/M2-failure-analysis.md), and the [retrieval weak spots](docs/M1-weak-spots.md).

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

This section is the **single source for running and demoing Clearway** end to end. The pipeline runs the real forward path — scan (Playwright + axe-core) → normalize → **retrieve** (real embedder + pgvector) → **draft** (real LLM via Ollama) → validate → **assemble** — and prints, per finding, an **ACR/VPAT-shaped row** (conformance · severity · WCAG citation · remediation), then the stratified trust metrics (`citation_hallucination_rate`, the verifiable-subset rate, and the honest `unverifiable_share`). There is no offline/stub mode from the CLI (stubs are test-only), so each command hits the services it needs; `--no-emit` only skips the OTel push, not the model calls.

> **Before you start:** `uv sync` and `docker compose up -d` (above), with the Ollama models pulled. A live run drafts with a real LLM at **~35–50s per finding**, so begin with the bundled fixture page — it exercises the entire path in seconds-to-minutes, not hours.

### 1 · Ingest the WCAG corpus (once)

The retriever searches this corpus. Needs the Ollama **embedding** model + **pgvector** — but *not* the chat model.

```bash
uv run clearway corpus-ingest                                    # fetch WCAG 2.2 → chunk + embed → pgvector
uv run clearway corpus-query "images need a text alternative"    # sanity-check retrieval
```

### 2 · Scan a page and read the evidence

Point it at a bundled fixture (fast) or any live URL. It prints the ACR/VPAT rows to **stdout**, with live progress (which finding, which step) on **stderr**. `--run-id` names the run so you can resume it in step 4.

```bash
uv run clearway run clearway/fixtures/pages/home.html --run-id demo-1     # bundled fixture (fast)
uv run clearway run https://some-public-site.example/page --run-id demo-1 # any live page (single page; no crawl)
```

The output — one block per shipped finding, then the trust summary (values below are illustrative of the *shape*; the remediation prose and the rates are produced live):

```text
[2] <finding-id>
  Conformance : Does Not Support
  Severity    : critical
  WCAG        : 1.1.1 Non-text Content (Level A)
  Remediation : <the drafter's one-line fix>
...
m0-core@1  run demo-1  findings=N citations=N hallucinations=N
  citation_hallucination_rate=…  verifiable=…  unverifiable_share=… (n/n)
```

### 3 · See what was held back for a human

Not every finding ships: axe-`incomplete` and no-oracle *judgment* items are **withheld into a review queue** instead of sent out unvetted — so the printed rows can be fewer than the findings scanned, and that gap is the queue.

```bash
uv run clearway review list --status pending
uv run clearway review show <finding-id>        # the flagged draft + why it was held
```

### 4 · Resolve an item and finish the report

Approve / edit / reject, then **resume the same command** (same target + `--run-id`) so the approved rows assemble into the report.

```bash
uv run clearway review approve <finding-id>
uv run clearway run clearway/fixtures/pages/home.html --run-id demo-1   # resume: the approved row now assembles
```

> Two gotchas: resume with the **same target you first ran**, not `eval` (which always re-scans the fixture set); and to make an *edit* stick use `edit` **alone** — `edit` then `approve` ships the original draft. Both, plus how the durable interrupt/checkpointing works, are in [`clearway/orchestrator/README.md`](clearway/orchestrator/README.md).

### 5 · Watch the metrics move (optional)

Drop `--no-emit` and the run pushes to OTel; the **Clearway — Trust Dashboard** at <http://localhost:3000> updates — operational panels (LLM latency, tokens) during the run, the trust metric at the end. See [`stack/grafana/README.md`](stack/grafana/README.md) for how to read the panels.

```bash
uv run clearway run clearway/fixtures/pages/home.html    # no --no-emit → emits to OTel
uv run clearway eval                                     # or the whole m1-core@1 set (3 pages, 5 findings)
```

How the queue, checkpointing, and resume work under the hood — the **durable control loop** — is documented in [`clearway/orchestrator/README.md`](clearway/orchestrator/README.md).

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
- [`docs/acceptance-analysis.md`](docs/acceptance-analysis.md) — held-out benchmark failure analysis: where the drafter and judge fail, and why.
- [`specs/`](specs/) — per-milestone task tickets.
- [`docs/`](docs/) — milestone notes and analysis.

## License & authorship

Licensed under the [MIT License](LICENSE). Original author, architect, and designer: **FuYuan (Skinner) Cheng**. The public commit history is the authoritative record of authorship and precedence.
