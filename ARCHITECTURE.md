# Clearway — ARCHITECTURE

- **Status:** Draft
- **Date:** 2026-07-05
- **Author:** FuYuan (Skinner) Cheng
- **Version:** 0.1

**Status labels used below:**

- `DECIDED` — locked, build against it
- `OPEN` — deferred, do not assume
- `VERIFY` — believed true, confirm before relying
- `REJECTED` — considered and ruled out

## Table of Contents

1. [One-liner & positioning](#1-one-liner--positioning)
2. [Scope & non-goals](#2-scope--non-goals)
3. [Architecture invariants & variables](#3-architecture-invariants--variables)
4. [Decisions of Record](#4-decisions-of-record)
   - [4.1 Language, runtime, stores](#41-language-runtime-stores)
   - [4.2 Scanner (intake, Regime A)](#42-scanner-intake-regime-a)
   - [4.3 Cache policy](#43-cache-policy-deterministic-re-work-only)
   - [4.4 LLM stack — runtime, gateway, routing](#44-llm-stack--runtime-gateway-routing)
   - [4.5 Observability & Eval](#45-observability--eval-the-load-bearing-core)
   - [4.6 Orchestration & durability](#46-orchestration--durability-the-mini-harness)
   - [4.7 MCP](#47-mcp)
   - [4.8 Citation validation layering](#48-citation-validation-layering-verification-not-rag-layering)
   - [4.9 Judge (LLM-as-judge)](#49-judge-llm-as-judge)
5. [The Oracle interface](#5-the-oracle-interface)
6. [Module boundaries & repo layout](#6-module-boundaries--repo-layout)
7. [Build sequence & milestones](#7-build-sequence--milestones)
8. [Change log](#8-change-log)

---

## 1. One-liner & positioning

Clearway ingests a real accessibility signal (a URL, later photos/measurements), produces **decision-ready, cited, confidence-scored evidence** for a qualified human specialist, and **measures the trustworthiness of its own outputs**. It never renders the final conformance decision — the specialist does.

The intended trajectory (context, not current scope): Clearway accelerates the evaluation-and-report workflow of a real accessibility practice (the anchor described in [`DESIGN_NOTE.md`](DESIGN_NOTE.md) §9), and can later grow an Ops surface (quote generation, notifying the humans/engineers who do the physical remediation). **We are not building it as a demo of skills; we are building a system that would speed up real work if put in production.** Every architectural choice below is judged by that bar, not by showcase value.

---

## 2. Scope & non-goals

**In scope now:** Digital only — public website / web HTML, the sole digital subset with a free automated oracle (axe-core). Findings → ACR/VPAT-shaped output with correct citations, severity, remediation. The eval & observability layer is the load-bearing core.

**Deferred (not now, but the architecture must not block it):** Regime B (physical) via an `Oracle` swap; Ops surface (quoting/notification).

**Never:** Final conformance/legal decision. Automated overlays / auto-remediation of live sites. Construction cost estimation.

---

## 3. Architecture invariants & variables

The system is **one constant bench** (the product) with **two swappable domain ports**.

- **Invariant — the bench (must not drift):** forward path, control loop, human-review gate, trust-metric definitions. Domain-agnostic. This is the product.
- **Variable — two ports (swap per domain):**
  - **Intake port** — how raw signal enters (Regime A: URL/page scan; Regime B: photos/measurements/voice).
  - **Oracle port** — where ground truth comes from (Regime A: axe-core, near-free; Regime B: expert gold, costly). See §5 for the interface.

The single most important seam is the **`Oracle` interface** (§5). If the harness depends *only* on that interface, then proving the cross-regime transfer reduces to "swap the Oracle implementation, change nothing else."

---

## 4. Decisions of Record

### 4.1 Language, runtime, stores

| Area | Decision | Status | Note |
|---|---|---|---|
| Primary language | Python | DECIDED | Backend + AI/RAG ecosystem fit. |
| API surface | FastAPI | DECIDED | The eventual service/app host. The Walking Skeleton may be driven by a CLI/script — the FastAPI surface is not required to prove the spine. |
| Source of truth + vectors | PostgreSQL + `pgvector` | DECIDED | One store for structured findings *and* embeddings. Backend-narrative-consistent. |
| Cache | Redis | DECIDED | **Only for deterministic re-work** (see 4.3). No large-vector cache. |
| Dev/test host | Mac mini, 64 GB unified memory | DECIDED | Runs local LLMs + Postgres + Redis + headless Chromium. Resource contention is real (LLM is the big tenant, Chromium can eat 300 MB–1 GB+/page); staging scan vs LLM phases is an OPEN optimization. |

### 4.2 Scanner (intake, Regime A)

| Area | Decision | Status | Note |
|---|---|---|---|
| Browser automation | Playwright (Python) → headless Chromium | DECIDED | Self-hosted. No third-party scan API — buying a scanner would contradict the "axe-core is my free oracle" thesis. |
| Checker | axe-core, injected via `page.evaluate` (`axe.run()`) | DECIDED | Core oracle. Lighthouse deferred (heavier, Node). |
| Eval corpus | **Fixed, versioned fixture HTML set**; some pages with *planted* violations (= hard ground truth beyond axe-core) | DECIDED | Eval must be reproducible across time → cannot be random live pages. **Live scanning is a demo feature, not the eval backbone.** |
| Scraping ethics | robots.txt, rate-limit, explicit User-Agent; prefer owned/fixture pages | DECIDED | Applies to any non-fixture scanning. |

### 4.3 Cache policy (deterministic re-work only)

| Cache | Purpose | Status |
|---|---|---|
| Embedding cache | Don't re-embed identical text (same finding text recurs across pages) | DECIDED |
| Rule→SC retrieval cache | `axe rule-id → applicable SC set` is near-deterministic; huge hit rate; skips embed+retrieval | DECIDED |
| Semantic LLM cache | Cache LLM output keyed by prompt hash / semantic similarity; must **invalidate on corpus version bump** | DECIDED (later) |
| Large-vector / DB-vs-cache tiering | Corpus is too small (WCAG 2.2 ≈ 87 SC — **VERIFY** exact count (86 vs 87, after 4.1.1's removal); + Understanding/Techniques/APG ≈ a few thousand chunks); pgvector retrieves in single-digit ms. Adding this would be solution-first. | REJECTED |

`cache_hit_rate` is exported as a metric (see 4.5).

### 4.4 LLM stack — runtime, gateway, routing

These sit at **three different layers**; they are complementary, not alternatives.

| Layer | Choice | Role | Status |
|---|---|---|---|
| Inference runtime (runs the model locally) | **Ollama** | Serves GGUF models on the Mac via llama.cpp + Metal; exposes OpenAI-compatible API at `http://localhost:11434/v1`. Best single-user ergonomics on Apple Silicon. | DECIDED |
| Local models | Gemma 4, Qwen 3.5 (both multimodal, tool-calling) | Run under Ollama. Multimodal = free bridge to Regime B (photos) later. **VERIFY** the exact versions exist on Ollama and both support multimodal **and** tool-calling before pinning. | DECIDED |
| Embedding model (M1 default) | **`nomic-embed-text`** (768-dim, via LiteLLM→Ollama) | Grounds RAG retrieval; verified 768-dim. Local default because the eval corpus must be offline/key-free/cost-free/reproducible. The model+dim are baked into `corpus_version` — the embedder is *welded to the corpus* (swap = full re-embed under a new version), unlike the freely-swappable drafter model. LiteLLM keeps a cloud embedder a config flip. Needs `search_document:`/`search_query:` task prefixes. | DECIDED |
| Unified gateway (how the app calls **any** model) | **LiteLLM** | One OpenAI-compatible interface over local (Ollama) + cloud (OpenAI); does fallback, retries, cost tracking, OTel tracing. Sits **above** the runtime — it *calls* runtimes, it does not run models. | DECIDED |
| Cloud fallback | OpenAI (via LiteLLM) | Hard judgment items; reference judge. | DECIDED |
| Routing config | Frozen, versioned artifact (`config_id`); every eval run is tagged with it | Enables model/config-stratified eval: same fixed eval set, swap the frozen combo, re-compare. | DECIDED |
| Routing policy (which finding → which model, thresholds) | — | Must be justified by eval data, not vibes. | OPEN |
| High-throughput inference server (**vLLM**) | — | Not for local dev; production-only consideration. See note. | REJECTED (local) / OPEN (production) |

**On vLLM (recorded so it isn't re-litigated):** vLLM's value is high-*concurrency* throughput (continuous batching, PagedAttention) on NVIDIA GPU + Linux. It does **not** run natively on Apple Silicon — the CPU path is ~20–30× slower than llama.cpp/Metal, and the community `vllm-metal` / `vllm-mlx` plugins are experimental, pin old vLLM versions, and are currently **text-only** (which would break the multimodal Regime-B bridge). This project's dev workload is single-user and sequential, not high-concurrency, so vLLM's advantage doesn't apply. If Clearway ever serves many concurrent audits in production, the standard pattern is: develop locally on Apple Silicon (Ollama), keep the interface OpenAI-compatible (LiteLLM), deploy vLLM on Linux+GPU behind the same interface. LiteLLM makes that a `base_url` swap — so choosing Ollama now costs nothing later.

### 4.5 Observability & Eval (the load-bearing core)

| Area | Decision | Status | Note |
|---|---|---|---|
| Telemetry standard | OpenTelemetry **GenAI Semantic Conventions** (`gen_ai.*`) | DECIDED | Industry-standard vocabulary, not homemade. Covers LLM calls, agents, **MCP tool calls**, and (nascent) eval. |
| Pipeline | OTel Collector → **Prometheus** (metrics) + **Grafana** (dashboards) | DECIDED | Prometheus 3.0 natively supports OTel naming. Tempo (traces) / Loki (logs) optional later. |
| **Eval-as-metric** | Quality-eval results are **first-class Prometheus metrics**: `citation_hallucination_rate`, `judge_kappa`, `expert_edit_distance`, `loop_closure_rate`, `confidence_calibration_*` | DECIDED | This is how "measured trust is the product" becomes a concrete, visible object — eval scores sit on the same dashboard as latency/cost. |
| semconv maturity | Use `OTEL_SEMCONV_STABILITY_OPT_IN`; expect attribute-name churn | VERIFY | As of mid-2026 most GenAI semconv is experimental/development. OpenAI SDK instrumentation most mature; local-model (Ollama) auto-instrumentation may need custom spans. |

Two distinct things both called "eval": **(1) operational observability** (latency, tokens, cost, error rate, cache hit rate) — near-free via the standard; **(2) quality evaluation** (is the output trustworthy) — computed by us and emitted as metrics into the same Prometheus/Grafana. (2) is the actual product and the concrete form of the control loop.

### 4.6 Orchestration & durability (the "mini-harness")

| Area | Decision | Status | Note |
|---|---|---|---|
| Orchestrator | **Hand-rolled state machine** over the finding set | DECIDED | Not LangGraph, not Temporal — the point is to *understand* the primitives (and be able to speak to *why* those frameworks exist). |
| Durable primitives | retry + backoff (transient 429/timeout), idempotency (keyed by finding id), checkpoint table (resume mid-run), workflow-level observability | DECIDED | Reliability of the harness is a *precondition* for trustworthy eval: a flaky harness produces untrustworthy trust-measurements. |
| Positioning | These are **durable-workflow primitives**, i.e. a *mini-harness* — **not** a general autonomous-agent harness | DECIDED | The pipeline is a bounded, mostly-deterministic workflow, not an open-ended agent that chooses its own actions. |
| HITL gate | needs-review queue + approve/edit gate, implemented as a **durable interrupt** (pause → persist `needs_review` → resume from a separate entrypoint) | DECIDED | The hand-rolled equivalent of LangGraph's `interrupt`. |

### 4.7 MCP

| Area | Decision | Status | Note |
|---|---|---|---|
| One real MCP server = **the retrieval service** | Input: a `Finding`. Output: applicable SC + citation + fix technique. | DECIDED | Chosen for **real production reuse value** — other tools, agents, or the specialist's own software could call it. Part of Delivery/Demo, not built "for the sake of MCP." |
| Scanner as MCP | — | REJECTED | Low reuse value; kept as an in-process step. |
| MCP observability | Instrument via OTel MCP semconv | DECIDED | Ties MCP into the same trace/metric pipeline. |

### 4.8 Citation validation layering (verification, not RAG-layering)

The **trust of a citation is graded by which oracle can verify it** — cheapest/hardest first:

- **L0 — enum check (deterministic, free):** is the cited SC a real WCAG 2.2 SC? Catches hallucinated/nonexistent SCs.
- **L1 — axe-core tag cross-check (deterministic, free, uses checker ground truth):** does the cited SC match axe-core's own `wcagXXX` tags for that rule? Hard oracle for the checker-detectable subset. **VERIFY:** axe-core's actual tag schema/coverage must be confirmed against its current API before this is relied on (including non-WCAG `best-practice` tags mixed in).
- **L2 — RAG faithfulness (softer):** does the retrieved SC text actually support the finding? Needs judge or human.
- **L3 — expert gold (Regime B):** expert κ on judgment items with no checker.

This is citation *verification* layering, not RAG layering. For the axe-core-detectable subset, L0/L1 may not touch RAG at all — "which findings actually need RAG" is an OPEN question to settle with data.

### 4.9 Judge (LLM-as-judge)

| Decision | Status |
|---|---|
| Judge model ≠ drafter model (avoid self-preference bias) | DECIDED |
| Judge is calibrated against expert gold *first* (measure judge-vs-human κ) before trusting judge-vs-model κ | DECIDED |
| Prefer deterministic oracle wherever available; reserve LLM-judge for no-oracle judgment items only | DECIDED |
| Judge reproducibility: pin model + version + temperature (0/low) + fixed prompt, recorded in trace | DECIDED |
| Exact judge model (local vs cloud reference judge); "can a local model approximate the cloud judge?" experiment | OPEN |

---

## 5. The Oracle interface (the transfer seam)

The eval harness and the L1 citation check depend **only** on the `Oracle` interface — never on axe internals directly. Regime A implements it via axe-core (`AxeCoreOracle`); Regime B via gold labels (`GoldLabelOracle`). Swapping regimes = swapping this one implementation, with no change to `validator/` or `eval/`. That is the entire "flexibility without drift" proof reduced to a single seam.

Key behavioural contract: `verdict_for(finding)` returns ground truth, or `None` when the oracle can't judge that finding — in which case it falls through to the LLM-judge or human review. That single return value is what wires up the "prefer the hardest available oracle" layering (4.8).

**Authoritative schema (`Oracle`, `OracleVerdict`) lives in [`CONTRACTS.md`](CONTRACTS.md) §3 — the single source of truth. It is not duplicated here.**

---

## 6. Module boundaries & repo layout

Monorepo. Each top-level module is an **independently implementable unit** once the shared schemas in `CONTRACTS.md` are locked. All modules are flat sibling packages under `clearway/`.

The table lists each module's responsibility (with its I/O) and its build-order dependency. **`Depends on`** = *build*-order dependency — blank means independently implementable against `schemas/` alone — **not** runtime data-flow; everything imports `schemas/`.

| Module | Responsibility (I/O) | Depends on |
|---|---|---|
| `schemas/` | Shared cross-module data contracts (`CONTRACTS.md`) — everything imports these | — |
| `fixtures/` | Fixed, versioned eval corpus (planted-violation pages) | — |
| `scanner/` | Playwright + axe-core → raw `ScanResult` | — |
| `normalizer/` | Raw violations → deduped canonical `Finding[]` | — |
| `retriever/` | RAG grounding: `Finding` → `Citation[]` | `corpus` |
| `drafter/` | LLM structured output: `Finding` + `Citation[]` → `DraftRow` | — |
| `oracle/` | Ground truth: `AxeCoreOracle` now, `GoldLabelOracle` @ M6 | — |
| `validator/` | L0 (enum) + L1 (axe tag) citation checks → `CitationCheck[]` | — |
| `eval/` | Harness + trust-metric computation (`citation_hallucination_rate`, …) | `oracle` |
| `observability/` | OTel setup, exporters, Prometheus/Grafana wiring | — |
| `orchestrator/` | Hand-rolled state machine · checkpoint · retry · HITL gate | most |
| `cli/` | Drive the spine (`clearway run <fixture>`) | `orchestrator` |
| `corpus/` | WCAG/ARIA ingest → chunk → embed → pgvector | — |
| `llm/` | LiteLLM gateway + frozen routing (routing @ M4) | — |
| `mcp_server/` | Real MCP server wrapping `retriever` | `retriever` |
| `api/` | FastAPI surface | `orchestrator` |

Dependency direction: everything depends on `schemas/`; nothing depends on `orchestrator/` or `api/`. Keep it acyclic.

---

## 7. Build sequence & milestones

This refines the [Design Note](DESIGN_NOTE.md)'s coarser M1–M4 into finer, dependency-ordered milestones. Each is scoped to be independently implementable where possible (git-worktree-friendly). Numbers below are Clearway's own build sequence and can extend further if needed.

**The forward path (what M0–M1 build):**

```
intake(URL)
  -> scan (Playwright + axe-core)            -> ScanResult
  -> normalize / dedupe                       -> Finding[]
  -> for each Finding:
       retrieve (RAG)                         -> Citation candidates
       draft (LLM structured output)          -> DraftRow (conformance + remediation)
       validate citation (L0 enum, L1 tag)    -> trust flags
       flag low-confidence                    -> needs_review?
  -> (human) approve / edit  [HITL gate]
  -> assemble ACR/VPAT rows
```

Every step emits an OTel span; every LLM/tool/retrieval call is a child span; eval metrics are computed from the trace and exported to Prometheus.

| ID | Milestone | Scope | Depends on |
|---|---|---|---|
| **M0** | Walking Skeleton | Minimal spine proving the control loop is real and runs (detail below). | — |
| **M1** | Forward path, real | Replace the stubs: `scanner`, `normalizer`, `corpus`, `retriever`, `drafter`, `validator` (L0/L1). `scanner` / `corpus`+`retriever` / `drafter` / `validator` are largely parallel — one worktree each. | M0 |
| **M2** | Control loop + HITL + observability | `orchestrator` durable primitives (retry, idempotency, checkpoint); HITL durable-interrupt gate; full trust dashboard + honest failure analysis. | M1 |
| **M3** | MCP retrieval server | Wrap `retriever` as the real MCP server (§4.7); part of Delivery/Demo. | retriever (M1); ∥ M2 |
| **M4** | LLM routing | LiteLLM multi-model + frozen routing config; model/config-stratified eval. | M1; benefits from M2 |
| **M5** | Judge calibration | LLM-judge vs expert gold; κ; confidence-vs-correctness calibration. | eval + gold set |
| **M6** | Regime B transfer | Implement `GoldLabelOracle`; swap the Oracle port; two-regime comparison. Architecture unchanged — only a new `Oracle` implementation. | M5 + gold set |

**M0 — Walking Skeleton (the spine).** M0 runs the forward path above end-to-end but *thin*: one fixture page → real axe-core scan → normalize → L0+L1 citation check → compute `citation_hallucination_rate` → emit via OTel to a **real** Prometheus/Grafana. `retriever` and `drafter` are stubbed with canned output; routing (single model), cache, MCP, HITL, and physical are all absent.

Its only job is to prove the control loop is real. The detail exists to pin one hard **exit criterion**, so the spine can't quietly grow into the whole system: *one fixture page in → one trust metric visibly moves on a Grafana panel.*

---

## 8. Change log

| Date | Version | Change |
|---|---|---|
| 2026-07-05 | 0.1 | Initial Decisions of Record. |
