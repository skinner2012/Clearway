# Clearway — M1: Forward path, real

## Table of Contents

- [Preamble](#preamble)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)

---

## Preamble

M0 proved the loop with `retriever` and `drafter` stubbed. **M1 makes the forward path real:** a real WCAG corpus in pgvector, real RAG retrieval, and real LLM drafting — so the pipeline produces genuine cited `DraftRow`s instead of canned ones. Still **single model** (routing is M5), **no cache** (an optimization for later), **no judge** (M4).

M1 is also where the eval first gets something worth measuring, and the framing matters. Within digital there are two oracle conditions:

- **oracle-rich (axe-detectable):** the axe tag already implies the SC (`wcag111` → `1.1.1`), so a real citation here is near-deterministic — `citation_hallucination_rate` on this subset is ~0 *by construction*. Uninteresting on its own.
- **oracle-poor (judgment items):** no axe tag — the LLM must retrieve and cite on its own (meaningful alt text, heading structure, link-in-context…). This is where the model can genuinely fail, but we **cannot self-check it yet** (that needs the judge/gold in M4).

So M1's honest headline is not a flattering near-zero number. It is the **unverifiable share** — how much of the output falls into the judgment bucket that has no automated oracle. That number quantifies exactly what M4 must target, and it is the throughline to the project's actual highlight (P4 depth). Do not paper over it.

## Goal & exit criterion

Make the forward path real end-to-end — real corpus/RAG retrieval + real LLM drafting, single model — over the **fixture set only** (synthetic pages, incl. ones authored to trigger axe `incomplete`). Live/real-page scanning is **deferred to a later demo milestone** (§4.2: fixtures are the reproducible eval backbone; live scanning is a demo feature, not the backbone).

**Exit criterion:** `clearway run <target>` produces real RAG-grounded `Citation`s and LLM-drafted `DraftRow`s (conformance + remediation); the eval reports **two** figures — `citation_hallucination_rate` on the axe-verifiable subset (expected ~0) and the **unverifiable share** (judgment items with no automated oracle) — both on Grafana; plus a short written note of where retrieval/drafting look weak.

- **Real:** corpus, retriever (RAG), drafter (LLM via LiteLLM → Ollama), scanner / normalizer / validator (hardened), oracle, eval (stratified), observability, orchestrator.
- **Single model:** routing deferred to M5.
- **Absent:** routing (M5), cache (optimization, later), judge / gold / calibration and L2 faithfulness (M4), full dashboard + HITL (M2), MCP server (M3), physical / Regime B.

## How to use these tickets

Everything depends on **T0** (CONTRACTS additions). After T0, **T1 / T4 / T5 run in parallel**; T2 depends on T1; T3 and T6 depend on T0; T7 depends on T6; T8 integrates last.

## Tickets

### T0 — CONTRACTS additions  *(foundation)*
- **Produces:** two additions to `CONTRACTS.md` §3 — a `CorpusChunk` model (the shape shared between `corpus/` and `retriever/`) and stratified fields on `EvalMetrics` (verifiable-subset rate + unverifiable share + counts). Regenerate `clearway/schemas/models.py`; add a `CONTRACTS.md` §6 change-log row.
- **Detail:** `CorpusChunk` = `chunk_id`, `sc_ids: list[str]`, `text`, `source` (`WCAG-SC` | `Understanding` | `Technique` | `ARIA-APG`), `url`, `corpus_version`, `embedding`. `embedding` is **optional and excluded from serialization** — the vector lives in pgvector, not in the transported contract; the field exists only so ingestion can carry it in-process. Extend `EvalMetrics` with `citation_hallucination_rate_verifiable`, `unverifiable_share`, and their counts. Keep `extra="forbid"`.
- **Acceptance:** models import; JSON-schema smoke test passes; new change-log row present.
- **Out of scope:** `RoutingConfig`, `JudgeResult`, `GoldLabel`, L2 faithfulness fields on `CitationCheck` — all remain deferred (`CONTRACTS.md` §5).
- **Depends on:** —

### T1 — corpus ingestion → pgvector
- **Consumes:** WCAG 2.2 sources. **Produces:** `CorpusChunk`s in pgvector under a frozen `corpus_version`.
- **Detail:** fetch/parse WCAG 2.2 SC + Understanding + Techniques + ARIA APG → chunk → embed → upsert into pgvector. Chunking granularity is an OPEN choice — start by-SC and note it. **Embeddings go through LiteLLM** (provider-agnostic); the M1 default is local **`nomic-embed-text` (768-dim)** → pgvector column `vector(768)`. The embedding model + dimension are **baked into `corpus_version`** — switching to a cloud embedder later is a config change + a full re-embed under a new version, not a code change. **Verify** the model pulls and returns 768-dim before pinning. Respect the W3C document license: process for retrieval, do **not** commit verbatim corpus dumps to the repo.
- **Acceptance:** corpus loaded; a known query (e.g. "images need a text alternative") retrieves SC `1.1.1`'s chunk; `corpus_version` recorded and pinned.
- **Out of scope:** ADA / CBC (physical) corpus; multi-version corpus management.
- **Depends on:** T0

### T2 — retriever (real RAG)  *(replaces M0 stub)*
- **Consumes:** `Finding`. **Produces:** `Citation[]`.
- **Detail:** embed the finding's query (rule help + context) → vector search in pgvector at the frozen `corpus_version` → map top-k chunks to `Citation`s (`sc_id`, `title`, `level`, `source`, `url`, `technique_id`). Deterministic given a frozen corpus. No cache yet.
- **Acceptance:** for an axe-detectable finding, the retrieved SCs include the one the axe tag implies (sanity-check against the oracle); for a judgment finding, returns plausible SC candidates; identical results across runs on a frozen corpus.
- **Out of scope:** rule→SC / embedding cache (optimization, later); re-ranking beyond top-k.
- **Depends on:** T1

### T3 — drafter (real LLM)  *(replaces M0 stub)*
- **Consumes:** `Finding`, `Citation[]`. **Produces:** `DraftRow`.
- **Detail:** call the LLM via **LiteLLM → Ollama** (single pinned model, low temperature) using the `DraftRow` JSON schema as the structured-output contract; ground conformance + remediation in the retrieved citations. Record model + `config_id` on the `Trace`. Single model only — routing is M5. **Verify-first:** confirm the chat model (Gemma 4 / Qwen 3.5) pulls on Ollama **and** honors structured output before pinning.
- **Testing:** unit tests inject a **fake LLM client** (canned schema-valid `DraftRow`) for fast, offline, deterministic CI; **one integration test gated on Ollama** proves the real LiteLLM → Ollama path (skips when Ollama is down, mirroring `test_observability.py`).
- **Acceptance:** returns a schema-valid `DraftRow`; conformance + remediation reference the retrieved citations; model + `config_id` recorded; empty/weak retrieval degrades gracefully (low confidence, not a crash).
- **Out of scope:** multi-model routing (M5); the LLM-judge (M4).
- **Depends on:** T0

### T4 — scanner hardening
- **Consumes:** fixture path. **Produces:** `ScanResult`.
- **Detail:** extend M0's scanner from one fixture to the **full fixture set**; **author 1–2 synthetic fixtures that reliably trigger axe `incomplete` / needs-review** (e.g. color-contrast over a background image/gradient, links distinguished by color alone) — **empirically confirm** each actually lands in axe's `incomplete[]` (T2-style: scan and check, don't assume — cf. M0's `label`-in-`passes` surprise); capture `incomplete` items **distinctly** from violations in `ScanResult`.
- **Acceptance:** scans the full fixture set without crashing; ≥1 fixture produces axe `incomplete` items; incomplete items captured distinctly from violations.
- **Out of scope:** **live / real-page scanning (deferred to a later demo milestone)**; authenticated pages; multi-page crawling.
- **Depends on:** M0 scanner

### T5 — normalizer hardening
- **Consumes:** `ScanResult`. **Produces:** `Finding[]`.
- **Detail:** robust de-duplication across a fixture's many nodes; stable `Finding.id` under re-scan; carry `incomplete` items through as low-confidence findings (the oracle-poor / unverifiable bucket).
- **Acceptance:** fixture-set scan → stable, de-duplicated `Finding`s; re-run yields identical ids; incomplete-sourced findings flow through distinctly.
- **Depends on:** M0 normalizer

### T6 — validator (L0 + L1) on the real path
- **Consumes:** `DraftRow` (now LLM-produced), `Finding`, `Oracle`. **Produces:** `CitationCheck[]`.
- **Detail:** same L0 (enum) + L1 (axe-tag cross-check) as M0, now run against **real LLM citations**. Judgment items (no axe tag) → `l1_status = "no_oracle"` → `UNVERIFIABLE`. **L2 (retrieval faithfulness) stays deferred to M4** (needs a judge). Read ground truth only via the `Oracle` protocol.
- **Acceptance:** real drafts validate; axe items resolve `VERIFIED` / `HALLUCINATED`; judgment items resolve `UNVERIFIABLE` (correctly flagged as "can't self-check yet").
- **Out of scope:** L2 faithfulness; the judge.
- **Depends on:** T0, oracle (M0)

### T7 — eval, stratified
- **Consumes:** `CitationCheck[]`, `Trace[]`. **Produces:** `EvalReport` with stratified `EvalMetrics`.
- **Detail:** compute `citation_hallucination_rate` on the **axe-verifiable** subset (expected ~0) **and** the **unverifiable share** (judgment items with no automated oracle). Export both as Prometheus metrics. The unverifiable share is the honest headline — it is exactly what M4's judge/gold must target.
- **Acceptance:** `EvalReport` reports both figures with correct counts; on the fixture set the verifiable rate is ~0 and the unverifiable share is non-trivial (matches a hand count).
- **Out of scope:** judgment-item correctness (needs judge/gold — M4).
- **Depends on:** T6

### T8 — integration + first-pass failure read  *(exit criterion)*
- **Consumes:** all of the above. **Produces:** an M1 run over the **fixture set** → `EvalReport` + a short written note of where retrieval or drafting look weak.
- **Detail:** wire the real `retriever` + `drafter` into the M0 orchestrator/CLI; single model; emit traces + the stratified metrics.
- **Acceptance:** `clearway run <target>` produces real cited `DraftRow`s end-to-end; the two stratified metrics land on Grafana; the written note names ≥3 concrete weak spots (input to M2's deep dashboard and M4's calibration).
- **Depends on:** T1–T7
