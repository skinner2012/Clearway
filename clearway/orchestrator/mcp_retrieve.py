"""The orchestrator's opt-in MCP retrieval client — the same `retrieve` seam, over the wire.

`build_mcp_retrieve(url)` returns a `Retrieve` (`Finding -> list[Citation]`) that calls the T2
server's one tool instead of retrieving in-process. In-process retrieval stays the default (a
normal run needs no server); this is opt-in via the transport toggle (`--retrieve-via-mcp` /
`CLEARWAY_RETRIEVE_TRANSPORT=mcp`, wired in the CLI). Parity is by construction: the finding maps
to a **lossless** `EvidenceQuery` (`{rule_id, description=finding.help}`), whose query text the
server composes identically to `Retriever.retrieve(finding)` — same text -> same embedding -> same
citations (ARCHITECTURE §4.7).

Two layers, so the mapping/parsing logic is testable offline (against the SDK's in-memory session,
as the T2 tests are) without a real socket:

- `retrieve_over_session` — transport-agnostic: given any connected `ClientSession`, map the
  finding, call the tool, and parse the result back into `Citation`s. A tool-level error
  (`isError`) or a missing structured payload is **raised**, not returned — so a server-side
  failure propagates as an exception and the durable `_step()` retries/fails it cleanly rather than
  silently yielding garbage (the SDK's `call_tool` does *not* raise on `isError` itself). It also
  opens the CLIENT span, injects the W3C `traceparent` into the call's `_meta` so the server's tool
  span is a child of it, and records `mcp.client.operation.duration`.
- `build_mcp_retrieve` — the production factory: a **connect-per-call** closure (fresh
  streamable-HTTP session per retrieve, run via `asyncio.run`). Retrieve is once-per-finding, so
  the connection cost is minor; and keeping each call self-contained and synchronous avoids
  entangling a long-lived async session with `_step()`'s synchronous retry backoff (`time.sleep`).
  Each retry is therefore a clean fresh connect.

The tool is read-only (§4.10), so nothing here mutates server state; failures are purely transport
or retrieval errors, which the M2 orchestrator already knows how to retry and checkpoint.
"""

from __future__ import annotations

import asyncio
from time import perf_counter

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind, Status, StatusCode

from clearway.mcp_server import TOOL_NAME
from clearway.observability.operational import mcp_span_attributes, record_mcp_call
from clearway.orchestrator.machine import Retrieve
from clearway.schemas.models import Citation, EvidenceQuery, Finding

_tracer = trace.get_tracer("clearway.mcp.client")


def _finding_to_query(finding: Finding) -> EvidenceQuery:
    """Map a `Finding` to the reuse-shaped `EvidenceQuery` the tool accepts — lossless for
    retrieval: the server composes `f"{rule_id} {description}"`, identical to the in-process
    `f"{rule_id} {help}"`, so a finding and its query retrieve the same citations."""
    return EvidenceQuery(rule_id=finding.rule_id, description=finding.help)


def _parse_citations(result: CallToolResult) -> list[Citation]:
    """Parse the tool's structured output back into `Citation`s, raising on a tool-level error or a
    missing payload. FastMCP wraps a `list[Citation]` return as `structuredContent["result"]`; the
    SDK does not raise on `isError`, so we do — otherwise a failed retrieval would look like an
    empty (or malformed) success and bypass the durable retry."""
    if result.isError:
        text = "; ".join(getattr(block, "text", "") for block in result.content) or "unknown error"
        raise RuntimeError(f"MCP tool {TOOL_NAME!r} returned an error: {text}")
    if result.structuredContent is None or "result" not in result.structuredContent:
        raise RuntimeError(f"MCP tool {TOOL_NAME!r} returned no structured content")
    return [Citation.model_validate(c) for c in result.structuredContent["result"]]


async def retrieve_over_session(session: ClientSession, finding: Finding) -> list[Citation]:
    """Map -> call -> parse over an already-connected session. Transport-agnostic, so the same
    logic runs against the SDK's in-memory session (tests) and a real streamable-HTTP session
    (production).

    Wrapped in a CLIENT span whose W3C `traceparent` is injected into the tool call's `_meta`, so the
    server starts its tool span as a child (one `trace_id` across the boundary). Latency and outcome
    land on `mcp.client.operation.duration`, tagged `error.type` on failure."""
    with _tracer.start_as_current_span(
        f"tools/call {TOOL_NAME}", kind=SpanKind.CLIENT, attributes=mcp_span_attributes(tool=TOOL_NAME)
    ) as span:
        carrier: dict[str, str] = {}
        inject(carrier)  # W3C traceparent for this span -> rides in _meta to the server
        started = perf_counter()
        error_type: str | None = None
        try:
            result = await session.call_tool(
                TOOL_NAME, {"query": _finding_to_query(finding).model_dump()}, meta=carrier
            )
            return _parse_citations(result)
        except Exception as exc:
            error_type = type(exc).__name__
            span.set_status(Status(StatusCode.ERROR, error_type))
            span.record_exception(exc)
            raise
        finally:
            record_mcp_call(tool=TOOL_NAME, duration_s=perf_counter() - started, error_type=error_type)


def build_mcp_retrieve(url: str) -> Retrieve:
    """Build a `Retrieve` seam that calls the MCP retrieval server at `url` (streamable HTTP,
    e.g. `http://127.0.0.1:8848/mcp`). Connect-per-call: each retrieve opens a fresh session, so a
    dead server surfaces as an exception on that step (the orchestrator retries, then fails the step
    cleanly) and never wedges the run."""

    async def _call(finding: Finding) -> list[Citation]:
        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await retrieve_over_session(session, finding)

    def retrieve(finding: Finding) -> list[Citation]:
        return asyncio.run(_call(finding))

    return retrieve
