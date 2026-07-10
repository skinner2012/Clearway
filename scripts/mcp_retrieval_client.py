#!/usr/bin/env python
"""External client for the Clearway retrieval MCP service.

A standalone client that connects to `retrieve_wcag_evidence` over streamable HTTP and
retrieves complete, cited WCAG evidence for a *described problem* — **independently of the
Clearway orchestrator**. This is the reuse story that justified building a real MCP server
(ARCHITECTURE §4.7): any other tool or agent already holds a described accessibility problem,
so it sends only an `EvidenceQuery` (`{rule_id?, description}`) — never Clearway's internal
`Finding` (whose hashed id / source_url / CSS target an external caller does not possess) — and
gets back self-contained `Citation`s (sc_id + title + level + source + url).

This script is deliberately *not* part of the pipeline: it imports the shared CONTRACTS types
(`EvidenceQuery` / `Citation`) — reuse means sharing the contract — but touches no orchestrator,
retriever, or corpus code. It is the same connect → send-query → parse path an external caller
would write.

Prerequisites (see README → "Retrieval as an MCP service"): the server must be running, and the
corpus ingested.

    uv run clearway mcp-serve                        # in another terminal
    uv run python scripts/mcp_retrieval_client.py          # this client
    uv run python scripts/mcp_retrieval_client.py --rule-id image-alt --description "image has no alt text"

The server URL comes from `CLEARWAY_MCP_URL` (default `http://127.0.0.1:8848/mcp`), or `--url`.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from clearway.schemas.models import Citation, EvidenceQuery

DEFAULT_URL = os.environ.get("CLEARWAY_MCP_URL", "http://127.0.0.1:8848/mcp")
TOOL_NAME = "retrieve_wcag_evidence"


async def retrieve_evidence(url: str, query: EvidenceQuery) -> list[Citation]:
    """Open a fresh streamable-HTTP session, call the one tool with an `EvidenceQuery`, and parse
    the structured result back into `Citation`s. FastMCP wraps a `list[Citation]` return as
    `structuredContent["result"]`; the SDK does not raise on a tool-level error, so we do."""
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            if TOOL_NAME not in names:
                raise RuntimeError(f"server at {url} exposes {names}, not {TOOL_NAME!r}")

            result = await session.call_tool(TOOL_NAME, {"query": query.model_dump()})
            if result.isError:
                text = "; ".join(getattr(b, "text", "") for b in result.content) or "unknown error"
                raise RuntimeError(f"tool {TOOL_NAME!r} returned an error: {text}")
            if result.structuredContent is None or "result" not in result.structuredContent:
                raise RuntimeError(f"tool {TOOL_NAME!r} returned no structured content")
            return [Citation.model_validate(c) for c in result.structuredContent["result"]]


def _format(citation: Citation) -> str:
    level = citation.level.value if citation.level is not None else "?"
    return f"  • {citation.sc_id} ({level})  {citation.title}\n    {citation.url}"


def main() -> None:
    parser = argparse.ArgumentParser(description="External client for the Clearway retrieval MCP service.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"MCP server URL (default: {DEFAULT_URL})")
    parser.add_argument("--rule-id", default="image-alt", help="optional axe rule id, if the caller has one")
    parser.add_argument(
        "--description",
        default="an image on the page has no text alternative for screen reader users",
        help="the human-readable accessibility problem",
    )
    args = parser.parse_args()

    query = EvidenceQuery(rule_id=args.rule_id, description=args.description)
    print(f"→ connecting to {args.url}")
    print(f"→ EvidenceQuery: rule_id={query.rule_id!r}  description={query.description!r}\n")

    citations = asyncio.run(retrieve_evidence(args.url, query))

    if not citations:
        print("← no citations returned")
        return
    print(f"← {len(citations)} WCAG citation(s), nearest-first:")
    for citation in citations:
        print(_format(citation))


if __name__ == "__main__":
    main()
