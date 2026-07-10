"""The real MCP retrieval server — the one component with genuine production reuse value.

Wraps the RAG `Retriever` behind a single read-only MCP tool, `retrieve_wcag_evidence`, that
takes a reuse-shaped `EvidenceQuery` (a described problem any caller already has) and returns
enriched `Citation`s. The RAG logic is unchanged (§4.7): the tool just composes the query text
and calls `Retriever.retrieve_query` — the same embed → pgvector-search → map path an in-process
run uses, so over-MCP and in-process retrieval are byte-identical (parity).

The tool schema is generated from the CONTRACTS Pydantic types (`EvidenceQuery` / `Citation`) — no
schema is redefined here (SSOT). The tool is read-only / side-effect-free (embed + vector search),
so page-derived input can't make it act (§4.10); that is asserted via `readOnlyHint`.

OTel instrumentation (cross-boundary trace propagation) is hand-wired separately, not taken from
FastMCP's built-in exporter — the same understand-the-primitives choice as the hand-rolled
orchestrator (§4.6).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from clearway.retriever import Retriever
from clearway.schemas.models import Citation, EvidenceQuery

SERVER_NAME = "clearway-retrieval"
TOOL_NAME = "retrieve_wcag_evidence"

_TOOL_DESCRIPTION = (
    "Retrieve the applicable WCAG 2.2 success criteria for a described accessibility problem. "
    "Given an EvidenceQuery (an optional axe rule id plus a human-readable description), returns "
    "the grounding success criteria as complete Citations (sc_id, title, level, source, url), "
    "nearest-first. Read-only: it embeds the query and vector-searches a frozen WCAG corpus; it "
    "has no side effects."
)


def build_server(retriever: Retriever, *, host: str = "127.0.0.1", port: int = 8848) -> FastMCP:
    """Build the FastMCP app exposing exactly one tool over the injected `retriever`.

    `host`/`port` configure the streamable-HTTP transport (mounted at `/mcp`). The retriever is
    injected so the server binds to a pinned `corpus_version` for its whole lifetime and so tests
    can drive the same tool with the offline seam (FakeEmbedder + InMemoryCorpusStore)."""
    mcp = FastMCP(SERVER_NAME, host=host, port=port, streamable_http_path="/mcp")

    @mcp.tool(
        name=TOOL_NAME,
        description=_TOOL_DESCRIPTION,
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def retrieve_wcag_evidence(query: EvidenceQuery) -> list[Citation]:
        return retriever.retrieve_query(query)

    return mcp
