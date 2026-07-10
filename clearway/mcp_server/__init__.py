"""MCP retrieval server: the real MCP server wrapping `retriever` (§4.7).

Exposes exactly one read-only tool, `retrieve_wcag_evidence(query: EvidenceQuery) -> list[Citation]`,
over streamable HTTP. Launched via `clearway mcp-serve`. Depends only on `retriever`.
"""

from clearway.mcp_server.server import SERVER_NAME, TOOL_NAME, build_server

__all__ = ["SERVER_NAME", "TOOL_NAME", "build_server"]
