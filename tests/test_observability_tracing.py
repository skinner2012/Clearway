"""T2: the durable machine emits a run → finding → step span tree, with retries/failures recorded
as span events + an ERROR status. Offline: an in-memory span exporter stands in for the collector,
and the machine picks it up through the global tracer provider (the same API path production uses).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from clearway.drafter import DraftResult, LLMUsage
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator.machine import execute
from clearway.orchestrator.store import InMemoryOrchestratorStore
from clearway.schemas.models import Citation, Conformance, DraftRow, Finding, PipelineStep, StepStatus

ORACLE = AxeCoreOracle()
_AT = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def _exporter() -> InMemorySpanExporter:
    """Install one in-memory span exporter for the module. `set_tracer_provider` is once-per-process,
    so if something already set a real provider we attach our processor to it instead of fighting it."""
    exporter = InMemorySpanExporter()
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        current.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(_exporter: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    _exporter.clear()
    yield _exporter
    _exporter.clear()


def _finding(finding_id: str) -> Finding:
    return Finding(
        id=finding_id, source_url="file://test.html", rule_id="image-alt", axe_tags=["wcag2a", "wcag111"], target="img"
    )


def _retrieve_ok(finding: Finding) -> list[Citation]:
    return [Citation(sc_id="1.1.1", source="WCAG-SC")]


def _draft_ok(finding: Finding, citations: list[Citation]) -> DraftRow:
    return DraftRow(
        finding_id=finding.id, conformance=Conformance.DOES_NOT_SUPPORT, citations=citations, confidence=0.9
    )


def _run(findings, store, *, run_id="r1", retrieve=_retrieve_ok, draft=_draft_ok, max_attempts=3):  # type: ignore[no-untyped-def]
    return execute(
        findings,
        run_id=run_id,
        config_id="pytest-config@1",
        model="pytest-model",
        created_at=_AT,
        do_retrieve=retrieve,
        do_draft=draft,
        oracle=ORACLE,
        store=store,
        max_attempts=max_attempts,
        backoff_seconds=0.0,
        on_resume=None,
    )


def test_emits_a_run_finding_step_span_tree(spans: InMemorySpanExporter) -> None:
    _run([_finding("f1")], InMemoryOrchestratorStore())
    finished = {s.name: s for s in spans.get_finished_spans()}

    assert "clearway.run" in finished
    assert "clearway.finding" in finished
    assert {"clearway.step.retrieve", "clearway.step.draft", "clearway.step.validate"} <= set(finished)

    run_span = finished["clearway.run"]
    assert run_span.attributes["clearway.run_id"] == "r1"
    assert run_span.attributes["clearway.model"] == "pytest-model"
    assert run_span.attributes["clearway.findings.count"] == 1

    # the finding span is a child of the run span (one trace, nested).
    finding_span = finished["clearway.finding"]
    assert finding_span.parent is not None
    assert finding_span.parent.span_id == run_span.context.span_id
    assert finding_span.attributes["clearway.finding_id"] == "f1"


def test_draft_span_carries_model_and_attempts(spans: InMemorySpanExporter) -> None:
    usage = LLMUsage(tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1.0)

    def draft(finding, citations):  # type: ignore[no-untyped-def]
        return DraftResult(_draft_ok(finding, citations), usage)

    _run([_finding("f1")], InMemoryOrchestratorStore(), draft=draft)
    draft_span = next(s for s in spans.get_finished_spans() if s.name == "clearway.step.draft")
    assert draft_span.attributes["clearway.step"] == "draft"
    assert draft_span.attributes["clearway.attempts"] == 1


def test_retry_is_recorded_as_a_span_event(spans: InMemorySpanExporter) -> None:
    calls = {"n": 0}

    def flaky_draft(finding, citations):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("boom")
        return _draft_ok(finding, citations)

    _run([_finding("f1")], InMemoryOrchestratorStore(), draft=flaky_draft)
    draft_span = next(s for s in spans.get_finished_spans() if s.name == "clearway.step.draft")
    events = {e.name: e for e in draft_span.events}
    assert "attempt_failed" in events
    assert events["attempt_failed"].attributes["exception.type"] == "TimeoutError"
    assert events["attempt_failed"].attributes["will_retry"] is True
    assert draft_span.status.status_code is not StatusCode.ERROR  # it recovered on retry


def test_exhausted_step_sets_error_status(spans: InMemorySpanExporter) -> None:
    def always_fails(finding):  # type: ignore[no-untyped-def]
        raise TimeoutError("permanent")

    _run([_finding("f1")], InMemoryOrchestratorStore(), retrieve=always_fails, max_attempts=2)
    retrieve_span = next(s for s in spans.get_finished_spans() if s.name == "clearway.step.retrieve")
    assert retrieve_span.status.status_code is StatusCode.ERROR
    assert retrieve_span.attributes["clearway.attempts"] == 2
    # both attempts recorded as events.
    assert len([e for e in retrieve_span.events if e.name == "attempt_failed"]) == 2


def test_replayed_step_is_marked_and_not_recomputed(spans: InMemorySpanExporter) -> None:
    store = InMemoryOrchestratorStore()
    _run([_finding("f1")], store)  # first pass
    spans.clear()  # only inspect the replay pass
    _run([_finding("f1")], store)  # second pass — fully replayed

    replayed = [s for s in spans.get_finished_spans() if s.name.startswith("clearway.step.")]
    assert replayed  # steps still spanned on replay
    assert all(s.attributes.get("clearway.replayed") is True for s in replayed)
    # sanity: the underlying checkpoint really is DONE (replay, not recompute).
    steps = {s.step: s for s in store.load_steps("r1")}
    assert steps[PipelineStep.VALIDATE].status is StepStatus.DONE
