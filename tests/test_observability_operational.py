"""T2: operational metrics — GenAI-semconv LLM metrics + custom pipeline_* metrics — emitted from
the durable machine during a run. Offline: a local MeterProvider with an in-memory reader stands in
for the OTLP→Collector→Prometheus path, so we can read the recorded points back and assert on them.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from clearway.drafter import DraftResult, LLMUsage
from clearway.observability.operational import (
    mcp_span_attributes,
    record_mcp_call,
    setup_operational_metrics,
    shutdown_operational_metrics,
)
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator.machine import execute
from clearway.orchestrator.store import InMemoryOrchestratorStore
from clearway.schemas.models import Citation, Conformance, DraftRow, Finding

ORACLE = AxeCoreOracle()
_AT = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    """A private MeterProvider + in-memory reader wired straight into the operational instruments —
    avoids the once-per-process global-provider guard so this test is order-independent."""
    rdr = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[rdr])
    setup_operational_metrics(provider)
    yield rdr
    shutdown_operational_metrics()  # reset the singletons so a later setup rebuilds them
    provider.shutdown()


def _points(reader: InMemoryMetricReader) -> dict[str, Any]:
    """Flatten the collected metrics to {name: metric.data} for easy assertions."""
    out: dict[str, Any] = {}
    data = reader.get_metrics_data()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                out[metric.name] = metric.data
    return out


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


def _run(findings, store, *, retrieve=_retrieve_ok, draft=_draft_ok, max_attempts=3):  # type: ignore[no-untyped-def]
    return execute(
        findings,
        run_id="r1",
        config_id="pytest-config@1",
        model="gemma4:31b",
        created_at=_AT,
        do_retrieve=retrieve,
        do_draft=draft,
        oracle=ORACLE,
        store=store,
        max_attempts=max_attempts,
        backoff_seconds=0.0,
        on_resume=None,
    )


def _draft_with_usage(usage: LLMUsage):  # type: ignore[no-untyped-def]
    def draft(finding, citations):  # type: ignore[no-untyped-def]
        return DraftResult(_draft_ok(finding, citations), usage)

    return draft


def test_llm_metrics_recorded_under_genai_semconv_names(reader: InMemoryMetricReader) -> None:
    usage = LLMUsage(tokens_in=120, tokens_out=30, cost_usd=0.0, latency_ms=850.0)
    _run([_finding("f1")], InMemoryOrchestratorStore(), draft=_draft_with_usage(usage))
    points = _points(reader)

    assert "gen_ai.client.operation.duration" in points
    assert "gen_ai.client.token.usage" in points

    dur = points["gen_ai.client.operation.duration"].data_points
    assert dur[0].sum == pytest.approx(0.85)  # 850ms → 0.85s
    assert dur[0].attributes["gen_ai.request.model"] == "gemma4:31b"

    # token histogram split by gen_ai.token.type into input/output.
    by_type = {dp.attributes["gen_ai.token.type"]: dp.sum for dp in points["gen_ai.client.token.usage"].data_points}
    assert by_type == {"input": 120, "output": 30}


def test_bare_row_stub_emits_no_llm_metrics(reader: InMemoryMetricReader) -> None:
    # a draft seam with no LLM call (bare DraftRow) → no gen_ai points, only pipeline metrics.
    _run([_finding("f1")], InMemoryOrchestratorStore())
    points = _points(reader)
    assert "gen_ai.client.operation.duration" not in points
    assert "pipeline_step_duration" in points  # steps still timed


def test_pipeline_step_duration_recorded_per_step(reader: InMemoryMetricReader) -> None:
    _run([_finding("f1")], InMemoryOrchestratorStore())
    points = _points(reader)
    steps = {dp.attributes["step"] for dp in points["pipeline_step_duration"].data_points}
    assert steps == {"retrieve", "draft", "validate"}


def test_retries_and_failures_counters(reader: InMemoryMetricReader) -> None:
    calls = {"n": 0}

    def flaky_draft(finding, citations):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("transient")
        return _draft_ok(finding, citations)

    def retrieve_fails(finding):  # type: ignore[no-untyped-def]
        raise TimeoutError("permanent")

    # finding A: draft retries once then succeeds → 1 retry, no failure.
    _run([_finding("A")], InMemoryOrchestratorStore(), draft=flaky_draft)
    # finding B: retrieve exhausts 2 attempts → 1 retry + 1 failure on the retrieve step.
    _run([_finding("B")], InMemoryOrchestratorStore(), retrieve=retrieve_fails, max_attempts=2)

    points = _points(reader)
    retries = {dp.attributes["step"]: dp.value for dp in points["pipeline_step_retries"].data_points}
    failures = {dp.attributes["step"]: dp.value for dp in points["pipeline_failures"].data_points}
    assert retries.get("draft") == 1  # flaky draft: one retry
    assert retries.get("retrieve") == 1  # exhausted retrieve: one retry (attempt 2)
    assert failures.get("retrieve") == 1  # and it ultimately failed
    assert "draft" not in failures  # draft recovered, no failure counted


def test_mcp_call_duration_recorded_under_semconv_name(reader: InMemoryMetricReader) -> None:
    record_mcp_call(tool="retrieve_wcag_evidence", duration_s=0.25)
    points = _points(reader)
    assert "mcp.client.operation.duration" in points
    dp = points["mcp.client.operation.duration"].data_points[0]
    assert dp.sum == pytest.approx(0.25)
    assert dp.attributes["mcp.method.name"] == "tools/call"
    assert dp.attributes["gen_ai.tool.name"] == "retrieve_wcag_evidence"
    assert "error.type" not in dp.attributes  # success path → no error tag


def test_mcp_call_failure_tags_error_type(reader: InMemoryMetricReader) -> None:
    record_mcp_call(tool="retrieve_wcag_evidence", duration_s=0.1, error_type="TimeoutError")
    dp = _points(reader)["mcp.client.operation.duration"].data_points[0]
    assert dp.attributes["error.type"] == "TimeoutError"  # error rate derives from this


def test_record_mcp_call_is_noop_before_setup() -> None:
    # No MeterProvider installed → the recorder must be a silent no-op, never raising (offline path).
    shutdown_operational_metrics()  # force the singletons to None, independent of test order
    record_mcp_call(tool="retrieve_wcag_evidence", duration_s=0.1)


def test_mcp_span_attributes_carry_semconv_names() -> None:
    attrs = mcp_span_attributes(tool="retrieve_wcag_evidence", session_id="sess-123")
    assert attrs == {
        "mcp.method.name": "tools/call",
        "gen_ai.tool.name": "retrieve_wcag_evidence",
        "network.transport": "tcp",
        "network.protocol.name": "http",
        "mcp.session.id": "sess-123",
    }


def test_mcp_span_attributes_omit_session_when_unknown() -> None:
    assert "mcp.session.id" not in mcp_span_attributes(tool="retrieve_wcag_evidence")
