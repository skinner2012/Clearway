"""The MCP retrieval server exposes the RAG retriever as one read-only tool.

Two layers, mirroring `test_retriever.py`:
- **offline** (default): drive the FastMCP app through the SDK's in-memory client (no HTTP, no
  network) over the offline retriever seam (`FakeEmbedder` + `InMemoryCorpusStore`). Proves the
  protocol surface: exactly one read-only tool, a schema generated from the CONTRACTS types (no
  redefinition), and — the headline — the tool returns the **same `Citation[]` as the in-process
  retriever** (parity: same query text → same embedding → same citations, incl. title/level).
- **gated** (`corpus_up`): the real path — `LiteLLMEmbedder` (Ollama) + `PgCorpusStore` — proves
  the tool grounds `image-alt` in SC 1.1.1 with the enriched title/level. Skips when the stack is
  down.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import anyio
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import CallToolResult, ListToolsResult

from clearway.corpus import (
    FakeEmbedder,
    InMemoryCorpusStore,
    LiteLLMEmbedder,
    PgCorpusStore,
    ScMeta,
    build_corpus_version,
    ingest,
    parse_sc_meta,
    parse_wcag_json,
)
from clearway.mcp_server import TOOL_NAME, build_server
from clearway.retriever import Retriever
from clearway.schemas.models import Citation, ConformanceLevel, CorpusChunk, EvidenceQuery, Finding

SAMPLE = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "corpus" / "wcag_sample.json"
_VERSION = "test@1"


def _chunk(chunk_id: str, sc_ids: list[str], *, source: str = "WCAG-SC", url: str = "") -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id, sc_ids=sc_ids, text=f"text for {chunk_id}", source=source, url=url, corpus_version=_VERSION
    )


def _seeded_retriever(sc_meta: list[ScMeta] | None = None, *chunks: CorpusChunk) -> Retriever:
    """A real `Retriever` over the offline seam: embed + upsert `chunks` (+ optional sc_meta) into
    an in-memory store under `_VERSION`."""
    embedder = FakeEmbedder()
    store = InMemoryCorpusStore()
    ingest(list(chunks), embedder, store)
    if sc_meta:
        store.upsert_sc_meta(_VERSION, sc_meta)
    return Retriever(embedder, store, _VERSION, k=len(chunks) or 1)


async def _list_tools(server: FastMCP) -> ListToolsResult:
    async with connect(server._mcp_server) as client:
        return await client.list_tools()


async def _call_tool(server: FastMCP, query: dict[str, str]) -> CallToolResult:
    async with connect(server._mcp_server) as client:
        return await client.call_tool(TOOL_NAME, {"query": query})


def _citations(result: CallToolResult) -> list[Citation]:
    """Parse the tool's structured output (`{"result": [...]}`) back into `Citation`s."""
    assert result.structuredContent is not None
    return [Citation.model_validate(c) for c in result.structuredContent["result"]]


# --- offline: FastMCP in-memory client over the fake seam --------------------


def test_exposes_exactly_one_readonly_tool() -> None:
    server = build_server(_seeded_retriever(None, _chunk("sc:1.1.1", ["1.1.1"])))
    tools = anyio.run(_list_tools, server).tools
    assert [t.name for t in tools] == [TOOL_NAME]
    (tool,) = tools
    assert tool.annotations is not None and tool.annotations.readOnlyHint is True


def test_tool_schema_is_generated_from_the_contract_types() -> None:
    # No schema is redefined in the server (SSOT): the input is EvidenceQuery, the output Citation,
    # both lifted straight from CONTRACTS Pydantic types.
    (tool,) = anyio.run(_list_tools, build_server(_seeded_retriever(None, _chunk("sc:1.1.1", ["1.1.1"])))).tools
    assert tool.inputSchema["required"] == ["query"]
    assert "EvidenceQuery" in tool.inputSchema["$defs"]
    assert set(tool.inputSchema["$defs"]["EvidenceQuery"]["properties"]) == {"rule_id", "description"}
    assert tool.outputSchema is not None
    assert "Citation" in tool.outputSchema["$defs"]


def test_tool_returns_same_citations_as_in_process_retriever() -> None:
    # The headline: over-MCP retrieval == in-process retrieval. Same retriever, so the only
    # variable is the protocol boundary; the enriched title/level must survive the round-trip.
    retriever = _seeded_retriever(
        [ScMeta(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A)],
        _chunk("sc:1.1.1", ["1.1.1"], url="https://www.w3.org/TR/WCAG22/#non-text-content"),
    )
    server = build_server(retriever)
    query = EvidenceQuery(rule_id="image-alt", description="Images must have alternate text")

    over_mcp = _citations(anyio.run(_call_tool, server, query.model_dump()))
    in_process = retriever.retrieve(
        Finding(id="h", source_url="file://x", rule_id="image-alt", target="x", help="Images must have alternate text")
    )
    assert over_mcp == in_process
    assert over_mcp[0].title == "Non-text Content"
    assert over_mcp[0].level == ConformanceLevel.A


# --- gated integration: real Ollama + real pgvector --------------------------


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def _postgres_up() -> bool:
    try:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", connect_timeout=1):
            return True
    except Exception:
        return False


corpus_up = pytest.mark.skipif(
    not (_ollama_up() and _postgres_up()),
    reason="corpus stack not running (need Ollama + `docker compose up -d postgres`)",
)


@corpus_up
def test_real_mcp_tool_grounds_image_alt_in_sc_1_1_1() -> None:
    """The acceptance sanity-check over the real retriever: the MCP tool returns SC 1.1.1 with its
    enriched title/level for an `image-alt` problem. Uses a throwaway corpus_version so it never
    disturbs a real ingested corpus."""
    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    version = build_corpus_version(embedder) + "-pytest-mcp"
    data = json.loads(SAMPLE.read_text())

    try:
        ingest(parse_wcag_json(data, corpus_version=version), embedder, store)
        store.upsert_sc_meta(version, parse_sc_meta(data))
        server = build_server(Retriever(embedder, store, version))
        citations = _citations(
            anyio.run(_call_tool, server, {"rule_id": "image-alt", "description": "Images must have an alternate text"})
        )
        non_text = next(c for c in citations if c.sc_id == "1.1.1")
        assert non_text.title == "Non-text Content"
        assert non_text.level == ConformanceLevel.A
    finally:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", autocommit=True) as conn:
            conn.execute("DELETE FROM corpus_chunk WHERE corpus_version = %s", (version,))
            conn.execute("DELETE FROM sc_meta WHERE corpus_version = %s", (version,))
