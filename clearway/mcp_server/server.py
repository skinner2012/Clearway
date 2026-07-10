"""The real MCP retrieval server — the one component with genuine production reuse value.

Wraps the RAG `Retriever` behind a single read-only MCP tool, `retrieve_wcag_evidence`, that
takes a reuse-shaped `EvidenceQuery` (a described problem any caller already has) and returns
enriched `Citation`s. The RAG logic is unchanged (§4.7): the tool just composes the query text
and calls `Retriever.retrieve_query` — the same embed → pgvector-search → map path an in-process
run uses, so over-MCP and in-process retrieval are byte-identical (parity).

The tool schema is generated from the CONTRACTS Pydantic types (`EvidenceQuery` / `Citation`) — no
schema is redefined here (SSOT). The tool is read-only / side-effect-free (embed + vector search),
so page-derived input can't make it act (§4.10); that is asserted via `readOnlyHint`.

OTel instrumentation is hand-wired here (not FastMCP's built-in exporter — the same
understand-the-primitives choice as the hand-rolled orchestrator, §4.6): the tool starts a SERVER
span parented on the caller's `traceparent` (extracted from the request `_meta`), so the retrieval
lands as a child of the run trace across the HTTP boundary rather than a disconnected RPC span. The
process installs its own tracer provider via `clearway mcp-serve` (`setup_tracing`); in-process
tests drive the tool with a no-op tracer, so span wiring stays offline-safe.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from opentelemetry import trace
from opentelemetry.context import Context as OtelContext
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind

from clearway.observability.operational import mcp_span_attributes
from clearway.retriever import Retriever
from clearway.schemas.models import Citation, EvidenceQuery

SERVER_NAME = "clearway-retrieval"
TOOL_NAME = "retrieve_wcag_evidence"

_tracer = trace.get_tracer("clearway.mcp.server")

_TOOL_DESCRIPTION = (
    "Retrieve the applicable WCAG 2.2 success criteria for a described accessibility problem. "
    "Given an EvidenceQuery (an optional axe rule id plus a human-readable description), returns "
    "the grounding success criteria as complete Citations (sc_id, title, level, source, url), "
    "nearest-first. Read-only: it embeds the query and vector-searches a frozen WCAG corpus; it "
    "has no side effects."
)


def _parent_context(ctx: Context) -> OtelContext:
    """Rebuild the caller's trace context from the request `_meta` so the tool span attaches as a
    child of the client's CLIENT span (one `trace_id` across the boundary). An absent/empty
    `traceparent` yields an empty context, and the span is then a normal root — a client that does
    not propagate degrades to a disconnected span, never an error."""
    carrier: dict[str, str] = {}
    meta = ctx.request_context.meta
    if meta is not None:
        traceparent = getattr(meta, "traceparent", None)
        if traceparent:
            carrier["traceparent"] = traceparent
        tracestate = getattr(meta, "tracestate", None)
        if tracestate:
            carrier["tracestate"] = tracestate
    return extract(carrier)


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
    def retrieve_wcag_evidence(query: EvidenceQuery, ctx: Context) -> list[Citation]:
        # Parent the tool span on the caller's client span (extracted from the request _meta), so the
        # retrieval shows up as a child under the run trace, not a disconnected RPC span. `ctx` is
        # injected by FastMCP and excluded from the tool's input schema (still just `query`).
        with _tracer.start_as_current_span(
            f"tools/call {TOOL_NAME}",
            context=_parent_context(ctx),
            kind=SpanKind.SERVER,
            attributes=mcp_span_attributes(tool=TOOL_NAME),
        ):
            return retriever.retrieve_query(query)

    return mcp
