# Clearway — M0: Walking Skeleton

## Table of Contents

- [Preamble](#preamble)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)

---

## Preamble

M0 is the **walking skeleton**: the thinnest possible end-to-end run of the forward path. Its only job is to prove the measurement loop is real — one trust metric visibly moving on a real Grafana panel — before any breadth (routing, cache, MCP, HITL) is added.

M0 does **not** produce a real audit report. The scan is real (Playwright + axe-core → real `Finding`s), but **retrieval and drafting are stubbed** with canned content, so the report body is not real yet — that arrives in M1, when `retriever` and `drafter` become real. The drafter stub deliberately cites a wrong/nonexistent SC in at least one case, so `eval` has a known hallucination to measure and the metric moves off zero. This framing is what keeps M0 from quietly growing into the whole system.

## Goal & exit criterion

Run the forward path end-to-end but *thin*, on one fixture page, and see one trust metric move on a real Grafana panel.

**Exit criterion:** `clearway run <fixture>` scans → normalizes → (stub) retrieves + drafts → validates (L0+L1) → computes `citation_hallucination_rate` → emits it via OTel to a real Prometheus/Grafana, where the panel updates.

- **Real:** scanner, normalizer, oracle (`AxeCoreOracle`), validator, eval, observability, orchestrator.
- **Stubbed:** retriever, drafter — real output *shape*, canned content.
- **Absent:** routing (single model), cache, MCP, HITL, physical.

## How to use these tickets

Everything depends on **T0** (schemas). After T0, **T1 / T2 / T4 / T5 / T6 / T9 run in parallel**. `Depends on` lists a ticket's **hard** dependencies (what it needs to be written); a ticket may separately name another as a *test target* (e.g. T2 scans T1) without that being a hard dependency.

## Tickets

### T0 — schemas package  *(foundation)*
- **Produces:** `clearway/schemas/models.py` — the Pydantic v2 models from `CONTRACTS.md` §3, verbatim.
- **Acceptance:** every model imports; a JSON-schema smoke test passes; `extra="forbid"` and frozen `OracleVerdict` are covered by tests.
- **Out of scope:** any schema not in `CONTRACTS.md`.
- **Depends on:** —

### T1 — fixtures + expected findings  *(ground truth)*
- **Produces:** `fixtures/` with ≥1 HTML page carrying *planted* violations (e.g. `<img>` with no alt → rule `image-alt`, tag `wcag111`), plus `fixtures/README.md` listing each page's expected findings (rule_id, SC, target).
- **Acceptance:** planted violations are documented and stable (a versioned set).
- **Depends on:** —

### T2 — scanner
- **Consumes:** a URL / fixture path. **Produces:** `ScanResult`.
- **Detail:** Playwright + headless Chromium; inject axe-core `axe.min.js`; call `axe.run()`; map output to `ScanResult` (pin the axe-core version in `tool_version`).
- **Acceptance:** scanning a T1 fixture returns the planted violations with correct `rule_id` and `tags`.
- **Out of scope:** Lighthouse; live-site crawling.
- **Depends on:** T0 (uses T1 as a real test target)

### T3 — normalizer
- **Consumes:** `ScanResult`. **Produces:** `Finding[]`.
- **Detail:** de-duplicate; `Finding.id` = deterministic hash of (source_url, rule_id, target); carry `axe_tags`.
- **Acceptance:** T1 fixture → expected `Finding` ids; re-running yields identical ids (idempotency).
- **Depends on:** T0, T2 (consumes its `ScanResult`)

### T4 — retriever  *(STUB)*
- **Consumes:** `Finding`. **Produces:** `Citation[]` (canned).
- **Detail:** hardcode a `rule_id → Citation` map; real `Citation` objects, fake content. No RAG.
- **Acceptance:** returns valid `Citation` objects for known findings.
- **Depends on:** T0

### T5 — drafter  *(STUB)*
- **Consumes:** `Finding`, `Citation[]`. **Produces:** `DraftRow` (canned).
- **Detail:** return a valid `DraftRow` (conformance + the stub citations + a fixed confidence). No LLM call.
- **Acceptance:** returns a valid `DraftRow`. Include at least one fixture case whose stub cites a deliberately wrong/nonexistent SC, so eval has a non-zero hallucination to measure.
- **Depends on:** T0

### T6 — oracle: `AxeCoreOracle` + WCAG SC reference
- **Consumes:** `Finding`. **Produces:** `OracleVerdict` (or `None`).
- **Detail:** derive SC ids from `finding.axe_tags` (e.g. `wcag111` → `1.1.1`, `wcag1410` → `1.4.10`); filter out non-SC tags (`wcag2a`, `best-practice`, `cat.*`, …). Also ship the valid WCAG 2.2 SC set used by T7. Implements the `Oracle` protocol. **VERIFY** the axe tag schema against axe-core's current API (ARCHITECTURE §4.8), and **VERIFY** the exact WCAG 2.2 SC set/count (86 vs 87, after 4.1.1's removal) — this set is load-bearing for T7's L0 check.
- **Acceptance:** known finding → verdict with correct SC(s); finding with no `wcag` SC tag → `None`; `isinstance(o, Oracle)` holds.
- **Depends on:** T0

### T7 — validator (L0 + L1)
- **Consumes:** `DraftRow`, `Finding`, `Oracle`. **Produces:** `CitationCheck[]`.
- **Detail:** L0 = cited `sc_id` is in the valid SC set (from T6); L1 = `sc_id` is in the oracle verdict's SCs. Emit `verdict` per `CONTRACTS.md` (`VERIFIED` / `HALLUCINATED` / `UNVERIFIABLE`). Read ground truth **only** via the `Oracle` protocol, never axe internals.
- **Acceptance:** nonexistent SC → `HALLUCINATED`; correct SC matching oracle → `VERIFIED`; valid SC with no oracle verdict → `UNVERIFIABLE`.
- **Depends on:** T0, T6

### T8 — eval
- **Consumes:** `Trace[]` (each carries its `CitationCheck[]`). **Produces:** `EvalReport`.
- **Detail:** compute `citation_hallucination_rate` and counts into `EvalMetrics`.
- **Acceptance:** on the T1 + T5 fixture with a known injected hallucination, the computed rate equals the hand-computed value.
- **Depends on:** T0, T7

### T9 — observability
- **Produces:** OTel setup in `observability/`; a Grafana panel for `citation_hallucination_rate`.
- **Detail:** OTel GenAI semconv spans per step; export metrics via OTel Collector → Prometheus; Grafana panel. Set `OTEL_SEMCONV_STABILITY_OPT_IN`.
- **Acceptance:** the metric is visible and updates on a Grafana panel after a run.
- **Depends on:** T0 (local stack running)

### T10 — orchestrator + CLI  *(integration / exit criterion)*
- **Consumes:** all of the above. **Produces:** a `Trace` per finding; a `clearway run <fixture>` entrypoint.
- **Detail:** wire T2 → T8 for one fixture; single model; emit trace + metric (T9). Minimal retry only — full durable primitives are M2.
- **Acceptance:** the exit criterion above holds end-to-end.
- **Depends on:** T2–T9
