# Clearway retrieval MCP service — interface reference

Retrieval is exposed as a standalone **MCP server** so tools *other than* the Clearway pipeline
can reuse it: given a described accessibility problem, it returns the applicable WCAG 2.2 success
criteria as complete, cited evidence. This is the one component with genuine production reuse
value — the rationale (and why the scanner was *not* exposed) is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) §4.7.

This document is the integration reference for an external caller: endpoint, transport, the one
tool, its input/output schemas, error semantics, and observability. You do **not** strictly need
it to integrate — the server is self-describing (`tools/list` returns a JSON Schema generated from
the Clearway contract types) — but it lets a reviewer or integrator understand the surface without
connecting.

## Endpoint & transport

- **Transport:** streamable HTTP (MCP), mounted at `/mcp`.
- **URL:** `http://{CLEARWAY_MCP_HOST}:{CLEARWAY_MCP_PORT}/mcp` — default `http://127.0.0.1:8848/mcp`.
  The Clearway reference client reads it from `CLEARWAY_MCP_URL`.
- **Auth:** none. The server is a local, single-tenant host process; OAuth / multi-tenant auth is
  deliberately out of scope.
- **SDK:** built on the official `mcp` SDK (FastMCP), pinned `mcp>=1.28.1,<2`. Any spec-compliant
  MCP client works — the [MCP Inspector](https://github.com/modelcontextprotocol/inspector), an
  agent framework's MCP client, or a hand-written one.

### Starting the server

The server needs the same services as in-process retrieval — the host-Ollama embedder and
pgvector — so ingest the corpus once first, then launch:

```bash
uv run clearway corpus-ingest          # one-time: fetch WCAG 2.2 → chunk + embed → pgvector
uv run clearway mcp-serve              # long-lived host process; binds CLEARWAY_MCP_HOST:PORT, mounts /mcp
```

On start it prints the tool, URL, and the `corpus_version` it will serve for the whole process
lifetime, e.g.:

```text
clearway mcp-serve: retrieve_wcag_evidence on http://127.0.0.1:8848/mcp  corpus_version=...
```

## The tool

Exactly one tool is exposed:

```
retrieve_wcag_evidence(query: EvidenceQuery) -> list[Citation]
```

Retrieve the applicable WCAG 2.2 success criteria for a described accessibility problem. The tool
embeds the query text and vector-searches a frozen WCAG corpus, returning the grounding success
criteria as complete `Citation`s, **nearest-first**.

It is **read-only / side-effect-free** (`readOnlyHint=true`, `idempotentHint=true`,
`openWorldHint=false`): it only embeds + searches a frozen corpus, so page-derived input cannot make
it act. The same query text always maps to the same embedding and the same citations for a given
`corpus_version` (see [Determinism](#determinism--corpus_version)).

## Input — `EvidenceQuery`

The **reuse-shaped** input: a *described problem*, which any caller already holds. It is
deliberately **not** Clearway's internal `Finding` — it omits the hashed `id`, `source_url`, and CSS
`target` an external caller does not possess. Strict (`extra="forbid"`): unknown fields are rejected.

| field         | type  | required | description |
| ------------- | ----- | -------- | ----------- |
| `rule_id`     | `str` | no (`""`) | Optional axe rule id, if the caller has one (e.g. `"image-alt"`). |
| `description` | `str` | **yes**  | The human-readable problem. |

The retriever composes its query text as `f"{rule_id} {description}".strip()`, so `rule_id` is
purely additive context — `description` alone is a valid query. The canonical definition lives in
[`CONTRACTS.md`](../CONTRACTS.md) §3 (`EvidenceQuery`).

## Output — `list[Citation]`

Each `Citation` is **self-contained evidence** — enough to cite a criterion without a second
lookup. Nearest-first.

| field          | type                   | description |
| -------------- | ---------------------- | ----------- |
| `sc_id`        | `str`                  | Canonical WCAG 2.2 SC id, dotted form, e.g. `"1.1.1"` (never `"wcag111"`). |
| `title`        | `str`                  | SC title, e.g. `"Non-text Content"`. |
| `level`        | `"A" \| "AA" \| "AAA" \| null` | Conformance level. |
| `source`       | `str`                  | Corpus origin, e.g. `"WCAG-SC"` / `"Understanding"`. |
| `url`          | `str`                  | Link to the SC's Understanding page. |
| `technique_id` | `str \| null`          | Fix technique id — reserved; currently `null`. |

Canonical definition: [`CONTRACTS.md`](../CONTRACTS.md) §3 (`Citation`).

### Wire shape

The tool call carries the query as its single `query` argument. FastMCP returns a `list[Citation]`
as MCP **structured content** under `result`:

```jsonc
// request  — tools/call retrieve_wcag_evidence
{
  "query": {
    "rule_id": "image-alt",
    "description": "an image on the page has no text alternative for screen reader users"
  }
}
```

```jsonc
// response — structuredContent
{
  "result": [
    {
      "sc_id": "1.1.1",
      "title": "Non-text Content",
      "level": "A",
      "source": "WCAG-SC",
      "url": "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
      "technique_id": null
    }
  ]
}
```

## Error semantics

The tool signals failure via the MCP tool-result **`isError`** flag, not a JSON-RPC protocol error.
The `mcp` SDK's `call_tool` does **not** raise on `isError` — so a client must check it (and the
presence of `structuredContent.result`) itself, or a failed retrieval will look like an empty
success. The Clearway reference client and orchestrator both do this and raise. A well-behaved
client should:

1. Treat `isError == true` as a failure and read the human-readable reason from the result's text
   content.
2. Treat a missing `structuredContent` / absent `result` key as a failure.
3. Otherwise parse `structuredContent.result` as `list[Citation]`.

An empty list (`[]`) is a **valid, successful** response — it means no criterion matched, not an
error.

## Determinism & `corpus_version`

A running server pins one `corpus_version` for its whole lifetime (printed at startup). Retrieval
is deterministic for a fixed `corpus_version`: identical query text → identical embedding →
identical citations. The `corpus_version` encodes the embedding model and dimension, so results are
only comparable across servers that report the same value. This is also what makes over-MCP and
in-process retrieval byte-identical (parity).

## Observability (optional, for trace-aware clients)

The tool is instrumented with the MCP semantic conventions and **W3C `traceparent` propagation**. A
client that injects a `traceparent` into the call's `_meta` gets the server's tool span parented on
its own span — one `trace_id` across the HTTP boundary — so the retrieval appears as a child of the
caller's trace rather than a disconnected RPC span. A client that does **not** propagate degrades
cleanly to a normal root span; propagation is never required for a successful call.

## Quickstart — reference client

[`scripts/mcp_retrieval_client.py`](../scripts/mcp_retrieval_client.py) is a standalone external
client (no orchestrator, retriever, or corpus code — it imports only the shared contract types). It
connects over streamable HTTP, sends an `EvidenceQuery`, and prints the returned citations:

```bash
uv run python scripts/mcp_retrieval_client.py
uv run python scripts/mcp_retrieval_client.py \
  --rule-id color-contrast \
  --description "body text is light grey on a white background"
```

```text
← 1 WCAG citation(s), nearest-first:
  • 1.1.1 (A)  Non-text Content
    https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html
```

The server URL comes from `CLEARWAY_MCP_URL` (default `http://127.0.0.1:8848/mcp`); pass `--url` to
point elsewhere. For interactive exploration, point the MCP Inspector at the same `/mcp` endpoint —
it lists `retrieve_wcag_evidence` with the `EvidenceQuery` / `Citation` schema.

## Stability

The interface is generated from the Clearway contract types (single source of truth,
[`CONTRACTS.md`](../CONTRACTS.md) §3) — the tool schema is never hand-redefined, so it cannot drift
from the pipeline's own types. Schema changes follow the CONTRACTS change process. Not yet in scope:
publishing to a public MCP registry, remote/cloud hosting, a `technique_id`-bearing corpus.
