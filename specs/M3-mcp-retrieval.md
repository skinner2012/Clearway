# Clearway — M3: MCP retrieval server

## Table of Contents

- [Preamble](#preamble)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)

---

## Preamble

M3 is the smallest, most self-contained milestone: it takes something that already works — the M1 real RAG retriever — and exposes it as a real, standalone **MCP server**, then routes the orchestrator's retrieval step through it. The RAG logic does not change; M3 is a protocol boundary + observability + a reuse demo, not new retrieval work.

Why this piece, and why it matters for Clearway:

- **It is the one component with genuine production reuse value.** A retrieval service — "given a described accessibility problem, return the applicable SC + citation + fix technique" — is something other tools, other agents, or the specialist's own software could call. That is exactly why `ARCHITECTURE.md` §4.7 chose the retriever (and rejected the scanner) as the one real MCP server.
- **It demonstrates real MCP competence on a real problem and real data**, not a toy `add(a, b)` server.
- **Honest framing:** MCP adds a protocol boundary (a separate server process) that a single-machine pipeline does not strictly need. We add it for the reuse value and the signal, **not** because the architecture demands it — and we say so plainly. A staff engineer names when complexity is for signal versus necessity.

**The interface is reuse-shaped, not pipeline-shaped.** The tool takes an **`EvidenceQuery`** — a described problem (`{rule_id?, description}`) that any caller already has in hand — never Clearway's internal axe `Finding` (which carries a hashed id, a `source_url`, and a CSS `target` that an external caller does not possess). And the returned `Citation`s are **enriched** (`title` + `level` populated, not just `sc_id`/`url`) so the response is self-contained evidence. Delivering that reuse surface is why M3 also adds one small contract (T0) and touches `corpus/` for citation enrichment (T1) — deliberately, because reuse is the thesis, not an afterthought.

**The headline engineering artifact is distributed tracing across the protocol boundary.** Instrumented with the MCP semantic conventions and W3C `traceparent` propagation, a single `trace_id` links the whole chain — orchestrator → MCP server → retrieval — so the tool call shows up as a *child span* of the same run trace on the M2 dashboard, not a flattened, disconnected RPC span.

Still **single model** (routing deferred); still **no judge** (M4). MCP wraps retrieval only.

## Goal & exit criterion

Turn retrieval from an in-process function into a **reusable, observable MCP service**: expose the M1 retriever as a standalone MCP server with one read-only tool over a reuse-shaped input, switch the orchestrator to call it over MCP (opt-in), instrument it with the MCP semantic conventions and cross-boundary trace propagation, and prove reuse with an external client.

**Exit criterion:**
- A standalone MCP server exposes `retrieve_wcag_evidence(query: EvidenceQuery) -> list[Citation]`, wrapping the M1 retriever unchanged; its tool schema is generated from the CONTRACTS Pydantic types (no redefinition). The input is the slim `EvidenceQuery`, not the internal `Finding`.
- Retrieved `Citation`s are **complete** — `sc_id` + `title` + `level` + `source` + `url` — enriched at corpus ingest.
- `clearway run` / `eval` produce the **same output** whether retrieval is in-process (the default) or via the MCP server (a transport toggle); MCP-call failures retry via the M2 durable orchestrator, and a completed retrieve step replays from the checkpoint cache on resume.
- The MCP call appears as a **child span under the run trace** — one `trace_id` via W3C `traceparent` propagation, carrying MCP-semconv attributes — and its latency lands on the M2 dashboard.
- An **external client** (not the Clearway pipeline) connects to the server and retrieves cited evidence for a sample problem sent as an `EvidenceQuery`.

- **Real:** `EvidenceQuery` contract, citation enrichment (corpus), MCP server (one read-only tool), MCP client in the orchestrator + transport toggle, MCP observability (cross-boundary trace propagation), reuse demo.
- **Unchanged:** the RAG retrieval logic (M1 — embed + vector search); single model.
- **Absent:** scanner-as-MCP (rejected, §4.7), multi-tool server, OAuth/multi-tenant auth, routing (deferred), judge (M4).

## How to use these tickets

**T0** (the contract) and **T1** (citation enrichment) are independent of each other and of MCP — do them first. **T2** (the server) needs both. After T2, **T3 / T4 / T5 run in parallel** (T3 also uses the M2 orchestrator; T4 also uses the M2 observability pipeline — both already exist). We build sequentially — `T0 → T1 → T2 → T3 → T4 → T5` — reviewing each ticket, per the project's build discipline.

## Tickets

### T0 — `EvidenceQuery` contract (the slim MCP input)
- **Consumes / Produces:** a new CONTRACTS type; no runtime behavior.
- **Detail:** add `EvidenceQuery` to `CONTRACTS.md` §3 — the reuse-shaped input the MCP retrieval tool accepts: `rule_id: str = ""` (optional axe rule id, if the caller has one) + `description: str` (the human-readable problem). This is the real domain object — an "evidence request" — that a production caller already has; it is deliberately **not** the internal `Finding` (whose hashed `id` / `source_url` / `target` an external caller does not possess). Strict (`extra="forbid"`) like every contract. The retriever's query text stays `f"{rule_id} {description}".strip()` — identical in form to today's `f"{rule_id} {help}"` — so a `Finding` maps to an `EvidenceQuery` losslessly for retrieval (T3). Update §5 (module I/O) + §6 (change log) in the **same change** (CLAUDE.md rule); regenerate `schemas/models.py` + exports. **No change to `Citation`** — its `title`/`level` fields already exist and are populated in T1.
- **Acceptance:** `EvidenceQuery` present in `schemas/` + `models.py` + exports; round-trips; §5/§6 updated; ruff/mypy green.
- **Out of scope:** any retrieval or MCP behavior; changing the `Finding` or `Citation` shapes.
- **Depends on:** —

### T1 — citation enrichment (ingest path)
- **Consumes:** the WCAG source already fetched at M1 ingest. **Produces:** the retriever returns complete `Citation`s (`title` + `level` populated).
- **Detail:** M1 left `Citation.title`/`level` empty (retriever "option A" — the corpus persisted neither as a structured field). Enrich at **ingest**: `corpus-ingest` captures each SC's `title` and conformance `level` from the WCAG JSON into a small **`sc_meta(sc_id, title, level)` reference table** in the corpus store (86 rows; same source as `oracle/wcag.py`). The retriever joins it in `_chunks_to_citations`, stamping `title` + `level` onto each `Citation`. `CorpusChunk` is **unchanged** (no contract change — a chunk's `sc_ids` is a list, so per-SC metadata does not belong on the chunk). **No re-embed** — the `corpus_version` is unchanged (metadata is not part of the embedding identity); a re-ingest just adds the reference rows. This updates the M1 parity expectations — retrieved `Citation`s now carry `title`/`level`.
- **Acceptance:** after `corpus-ingest`, retrieving for a known finding returns `Citation`s with correct `title` + `level` (e.g. `1.1.1` → "Non-text Content", level A); existing retriever tests updated for the richer output; `corpus_version` unchanged, no re-embed.
- **Out of scope:** `technique_id` (Techniques corpus, later); MCP; any embedding change.
- **Depends on:** corpus + retriever (M1)

### T2 — MCP retrieval server (wrap the retriever)  *(core)*
- **Consumes:** an `EvidenceQuery` (over MCP). **Produces:** `Citation[]` (over MCP); a standalone MCP server process.
- **Detail:** build with the **official `mcp` SDK** (which bundles FastMCP) — the canonical, stable choice, and we hand-wire OTel in T4 rather than lean on `fastmcp` 3.x's built-in exporter (fits §4.6's understand-the-primitives ethos — the same reason the orchestrator is hand-rolled over Temporal/LangGraph). Note the choice and pin the version. Expose exactly one tool, `retrieve_wcag_evidence(query: EvidenceQuery) -> list[Citation]`, that composes the query text and calls the existing M1 `Retriever.retrieve` — **do not change the RAG logic**. The tool schema is auto-generated from the CONTRACTS Pydantic types (`EvidenceQuery` / `Citation`) → **no schema redefinition** (SSOT). Transport: **streamable HTTP** (mount `/mcp`) for the reuse story; stdio is acceptable for local-only. Launch via a new **`clearway mcp-serve`** subcommand — a long-lived host process (reaches host-Ollama + compose-Postgres exactly as the CLI does today); the server URL comes from `.env`. The tool is **read-only / side-effect-free** (it embeds + vector-searches; page-derived input can't make it act — per §4.10). Pin the `corpus_version` the server serves. New dependency (`mcp`) — approved.
- **Acceptance:** `clearway mcp-serve` starts; the MCP Inspector (or any client) lists `retrieve_wcag_evidence` with a schema matching `EvidenceQuery` / `Citation`; for a known problem it returns the **same `Citation[]` as the in-process retriever** — a parity test (same query text → same embedding → same citations, now including `title`/`level`).
- **Out of scope:** scanner-as-MCP (REJECTED, §4.7); more than one tool; OAuth / multi-tenant auth; any change to retrieval logic.
- **Depends on:** T0 (`EvidenceQuery`), T1 (enriched citations)

### T3 — orchestrator calls retrieval via the MCP client (+ transport toggle)
- **Consumes / Produces:** the same pipeline I/O; the retrieve step optionally goes over MCP.
- **Detail:** add an MCP-client `do_retrieve` that maps the finding to an `EvidenceQuery` (`{rule_id: finding.rule_id, description: finding.help}`) and calls the T2 server. Wire a **transport toggle**: in-process retrieval stays the **default** (normal runs need no server), MCP is opt-in via env/flag (e.g. `CLEARWAY_RETRIEVE_TRANSPORT=mcp` or `--retrieve-via-mcp`). The seam already exists (`retrieve: Retrieve | None`), so this is CLI/config wiring, not new architecture. Keep it inside the M2 durable primitives: an MCP-call failure retries/backs off like any step and fails that step **cleanly** (does not crash the run); a completed retrieve step **replays from the checkpoint cache** on resume (the `list[Citation]` is stored as `result_json`), so a dead server only affects not-yet-done steps.
- **Acceptance:** `clearway run` / `eval` produce the **same output** in-process (default) vs via MCP (toggle); an MCP-call failure retries via the M2 orchestrator; a stopped server degrades gracefully; a resumed run does **not** re-call the server for already-completed retrieve steps.
- **Out of scope:** routing (deferred).
- **Depends on:** T2, M2 orchestrator

### T4 — MCP observability  *(headline)*
- **Produces:** OTel instrumentation on the MCP server + client with **cross-boundary trace propagation**; an MCP panel on the M2 dashboard.
- **Detail:** the core deliverable is **one `trace_id` spanning orchestrator → MCP server → retrieval** across the HTTP boundary — the client injects the W3C `traceparent` into the MCP request, the server extracts it and starts its span as a **child** of the run trace (not a flattened, disconnected RPC span). **VERIFY the OTel MCP semantic conventions first** (as M2 did for GenAI semconv — MCP semconv is newer/Development-stage, names may churn): `mcp.method.name`, `mcp.session.id`, `gen_ai.tool.name`, transport metadata (`network.transport`, `network.protocol.name`); confirm the exact attribute names in the pinned semconv version before relying on them, else hand-roll spans carrying those names. Export via the M2 Collector → Prometheus. Add MCP-call latency + error rate to the dashboard.
- **Acceptance:** an MCP retrieval call appears as a **child span of the run trace** (verified: same `trace_id` as the orchestrator run) carrying MCP-semconv attributes; MCP-call latency/errors are visible on the dashboard.
- **Out of scope:** capturing tool args/results content stays opt-in and redacted (untrusted page content, §4.10).
- **Depends on:** T2, M2 observability

### T5 — reuse / delivery demo  *(the point of building a real MCP server)*
- **Produces:** a standalone external client (a small script and/or the MCP Inspector) that calls the retrieval server **independently of the Clearway pipeline**.
- **Detail:** show that another tool/agent — not the Clearway orchestrator — can connect to `retrieve_wcag_evidence` over streamable HTTP and get **complete cited WCAG evidence** (`sc_id` + `title` + `level` + `url`) for a sample problem, sending only an `EvidenceQuery` (a described problem), never an internal `Finding`. This is the "real production reuse value" that justified building a real MCP server (§4.7). Document the connection (URL, transport, sample request/response) so a reviewer can reproduce it.
- **Acceptance:** an external client (not the orchestrator) connects and successfully retrieves enriched evidence for a sample problem sent as an `EvidenceQuery`; the steps are documented.
- **Out of scope:** publishing to a public MCP registry; remote/cloud hosting.
- **Depends on:** T2
