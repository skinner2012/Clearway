"""T3: the orchestrator's opt-in MCP retrieval client (`clearway/orchestrator/mcp_retrieve.py`).

Offline throughout: drive the FastMCP app through the SDK's in-memory session (as test_mcp_server
does), so the map -> call -> parse -> raise logic and its interaction with the durable orchestrator
are proven without a socket. The real streamable-HTTP transport is exercised by production
(`build_mcp_retrieve`) and the T5 external-client demo; here the only real-transport assertion is
that a dead endpoint *raises* (so `_step()` retries and fails the step cleanly) rather than hanging
or returning garbage.

Three things this pins down, matching T3's acceptance:
- **parity**: over-MCP retrieval == in-process retrieval, enrichment (title/level) intact across the
  boundary — both at the unit level and end-to-end through `execute()`.
- **failure**: a tool error is *raised*, not silently returned, so the durable retry engages and the
  step fails cleanly without crashing the run.
- **resume**: a completed retrieve step replays from the checkpoint cache — the server is NOT
  re-called.
"""

from __future__ import annotations

from datetime import datetime, timezone

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import CallToolResult, TextContent

from clearway.corpus import FakeEmbedder, InMemoryCorpusStore, ScMeta, ingest
from clearway.mcp_server import build_server
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator.machine import execute
from clearway.orchestrator.mcp_retrieve import (
    _finding_to_query,
    _parse_citations,
    build_mcp_retrieve,
    retrieve_over_session,
)
from clearway.orchestrator.store import InMemoryOrchestratorStore
from clearway.retriever import Retriever
from clearway.schemas.models import (
    Citation,
    Conformance,
    ConformanceLevel,
    CorpusChunk,
    DraftRow,
    EvidenceQuery,
    Finding,
    PipelineStep,
    StepStatus,
)

_VERSION = "test@1"
_AT = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


# --- offline seam helpers (mirror test_mcp_server) -------------------------------


def _chunk(chunk_id: str, sc_ids: list[str], *, url: str = "") -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id,
        sc_ids=sc_ids,
        text=f"text for {chunk_id}",
        source="WCAG-SC",
        url=url,
        corpus_version=_VERSION,
    )


def _seeded_retriever(sc_meta: list[ScMeta] | None, *chunks: CorpusChunk) -> Retriever:
    embedder = FakeEmbedder()
    store = InMemoryCorpusStore()
    ingest(list(chunks), embedder, store)
    if sc_meta:
        store.upsert_sc_meta(_VERSION, sc_meta)
    return Retriever(embedder, store, _VERSION, k=len(chunks) or 1)


def _enriched_retriever() -> Retriever:
    return _seeded_retriever(
        [ScMeta(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A)],
        _chunk("sc:1.1.1", ["1.1.1"], url="https://www.w3.org/TR/WCAG22/#non-text-content"),
    )


def _finding(finding_id: str = "f1") -> Finding:
    # axe_tags carry the SC the oracle grounds against (wcag111 -> 1.1.1), so a clean image-alt
    # finding validates VERIFIED and is not HITL-gated — it produces a Trace to compare.
    return Finding(
        id=finding_id,
        source_url="file://x",
        rule_id="image-alt",
        axe_tags=["wcag2a", "wcag111"],
        target="img",
        help="Images must have alternate text",
    )


def _draft_ok(finding: Finding, citations: list[Citation]) -> DraftRow:
    return DraftRow(
        finding_id=finding.id, conformance=Conformance.DOES_NOT_SUPPORT, citations=citations, confidence=0.9
    )


def _mcp_session_retrieve(server, *, calls: dict[str, int] | None = None):  # type: ignore[no-untyped-def]
    """A sync `Retrieve` that, per finding, opens an in-memory MCP session to `server` and runs the
    real client mapping/parsing — the whole protocol boundary minus the socket. Drops into
    `execute()` exactly where the in-process retriever would. `calls` counts server round-trips (so
    a resume test can assert a replayed step makes none)."""

    def retrieve(finding: Finding) -> list[Citation]:
        if calls is not None:
            calls["n"] += 1

        async def _call() -> list[Citation]:
            async with connect(server._mcp_server) as session:
                return await retrieve_over_session(session, finding)

        return anyio.run(_call)

    return retrieve


def _execute(findings, store, *, retrieve, run_id="r1", max_attempts=3):  # type: ignore[no-untyped-def]
    return execute(
        findings,
        run_id=run_id,
        config_id="pytest-config@1",
        model="pytest-model",
        created_at=_AT,
        do_retrieve=retrieve,
        do_draft=_draft_ok,
        oracle=AxeCoreOracle(),
        store=store,
        max_attempts=max_attempts,
        backoff_seconds=0.0,  # no real sleeping in tests
    )


# --- unit: map / parse / raise ---------------------------------------------------


def test_finding_maps_to_a_lossless_evidence_query() -> None:
    # rule_id + help -> the reuse-shaped query; the server composes the same text the in-process
    # retriever does, which is what makes retrieval byte-identical across the boundary.
    assert _finding_to_query(_finding()) == EvidenceQuery(
        rule_id="image-alt", description="Images must have alternate text"
    )


def test_retrieve_over_session_matches_in_process_with_enrichment_intact() -> None:
    # The headline: over-MCP retrieval == in-process retrieval, and the enriched title/level survive
    # the JSON round-trip through the protocol boundary.
    retriever = _enriched_retriever()
    server = build_server(retriever)
    finding = _finding()

    async def _call() -> list[Citation]:
        async with connect(server._mcp_server) as session:
            return await retrieve_over_session(session, finding)

    over_mcp = anyio.run(_call)
    assert over_mcp == retriever.retrieve(finding)
    assert over_mcp[0].title == "Non-text Content"
    assert over_mcp[0].level is ConformanceLevel.A


def test_parse_citations_raises_on_a_tool_error() -> None:
    # A server-side failure comes back as a CallToolResult with isError=True — the SDK does NOT
    # raise on it. Our parser must, so the durable _step() retries instead of treating the failure
    # as an empty success. (The end-to-end raise-through-a-session path is covered by the
    # retries-then-fails test below; here we pin the pure decision precisely.)
    result = CallToolResult(isError=True, content=[TextContent(type="text", text="retrieval exploded")])
    with pytest.raises(RuntimeError, match="retrieval exploded"):
        _parse_citations(result)


def test_parse_citations_raises_on_a_missing_structured_payload() -> None:
    # A non-error result that somehow carries no structured content is still a failure, not an empty
    # success — raise so the step retries rather than silently dropping citations.
    result = CallToolResult(isError=False, content=[], structuredContent=None)
    with pytest.raises(RuntimeError, match="no structured content"):
        _parse_citations(result)


def test_build_mcp_retrieve_raises_on_a_dead_server() -> None:
    # Graceful degradation for the REAL transport: a dead endpoint surfaces as an exception on that
    # step (so the orchestrator retries, then fails it cleanly) rather than hanging or returning
    # garbage. Port 1 refuses immediately — no external network.
    retrieve = build_mcp_retrieve("http://127.0.0.1:1/mcp")
    with pytest.raises(Exception):
        retrieve(_finding())


# --- end-to-end through the durable orchestrator ---------------------------------


def test_execute_via_mcp_matches_in_process_retrieval() -> None:
    retriever = _enriched_retriever()
    server = build_server(retriever)
    findings = [_finding("f1")]

    via_mcp = _execute(findings, InMemoryOrchestratorStore(), retrieve=_mcp_session_retrieve(server), run_id="mcp")
    in_process = _execute(findings, InMemoryOrchestratorStore(), retrieve=retriever.retrieve, run_id="ip")

    assert via_mcp[0].retrieved_sc_ids == in_process[0].retrieved_sc_ids == ["1.1.1"]


def test_execute_via_mcp_retries_then_fails_the_step_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    # A dead/erroring server must not crash the run: the retrieve step exhausts its retries, is
    # marked FAILED, and the run still completes DONE (that finding is just withheld).
    retriever = _seeded_retriever(None, _chunk("sc:1.1.1", ["1.1.1"]))
    monkeypatch.setattr(retriever, "retrieve_query", lambda _q: (_ for _ in ()).throw(RuntimeError("server down")))
    server = build_server(retriever)
    store = InMemoryOrchestratorStore()

    traces = _execute([_finding("f1")], store, retrieve=_mcp_session_retrieve(server), max_attempts=2)

    assert traces == []  # the finding produced no trace, but the run did not crash
    steps = {(s.finding_id, s.step): s for s in store.load_steps("r1")}
    assert steps[("f1", PipelineStep.RETRIEVE)].status is StepStatus.FAILED
    assert steps[("f1", PipelineStep.RETRIEVE)].attempts == 2  # retried up to max_attempts
    assert ("f1", PipelineStep.DRAFT) not in steps  # halted at retrieve — draft never attempted
    run = store.load_run("r1")
    assert run is not None and run.status.value == "done"  # run completes; never crashes


def test_execute_via_mcp_replays_a_completed_step_without_recalling_the_server() -> None:
    # The resume guarantee: a completed retrieve step replays from result_json on the next pass —
    # the server is NOT called again (a dead server only affects not-yet-done steps).
    server = build_server(_enriched_retriever())
    store = InMemoryOrchestratorStore()
    calls = {"n": 0}
    seam = _mcp_session_retrieve(server, calls=calls)

    _execute([_finding("f1")], store, retrieve=seam)
    assert calls["n"] == 1  # first pass hit the server once

    _execute([_finding("f1")], store, retrieve=seam)  # resume
    assert calls["n"] == 1  # replayed from checkpoint — no second round-trip
