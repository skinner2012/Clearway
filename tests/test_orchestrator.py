"""T10 acceptance: the orchestrator runs the whole spine end-to-end (the exit criterion).

Real-browser integration test — `run()` scans the fixture with headless Chromium + axe-core,
then normalizes → retrieves → drafts → validates → evals. Requires `playwright install chromium`.
Asserts the exit-criterion value: one fixture in → `citation_hallucination_rate == 2/3`, and
that the `plant=False` lever drives it to 0.0 (the moving line on the panel). `run()` is pure —
emission (OTel) lives in the CLI and is proven by the stack-gated test_observability.py.

The retrieve step is injected with the canned stub (`tests/stubs.py`), so the spine runs
without the corpus stack: it returns the correct SC per fixture rule deterministically, which
is exactly what these exit-criterion metrics assert. Real RAG retrieval is proven separately
in test_retriever.py's gated test.
"""

from __future__ import annotations

from pathlib import Path

from stubs import canned_retrieve

from clearway.orchestrator import RunResult, run
from clearway.schemas.models import EvalReport, OracleRegime, Trace

FIXTURE = str(Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages" / "home.html")


def test_run_end_to_end_hits_the_exit_criterion() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve)
    assert isinstance(result, RunResult)
    assert isinstance(result.report, EvalReport)

    m = result.report.metrics
    # 3 planted findings, 3 citations, 2 intentional faults (html-has-lang→1.1.1, label→9.9.9).
    assert m.findings_total == 3
    assert m.citations_total == 3
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == 2 / 3


def test_run_produces_one_trace_per_finding_sharing_a_run() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve)
    assert len(result.traces) == 3
    assert all(isinstance(t, Trace) for t in result.traces)
    # all traces of one run share run_id / config_id, and each carries its checks.
    assert len({t.run_id for t in result.traces}) == 1
    assert {t.config_id for t in result.traces} == {"m0-single@1"}
    assert result.report.run_id == result.traces[0].run_id
    assert all(t.checks for t in result.traces)
    # report labels are read off the oracle, not hardcoded.
    assert result.report.oracle_regime == OracleRegime.A_DIGITAL
    assert result.report.eval_set_id == "m0-core@1"
    assert result.report.trace_ids == [t.finding_id for t in result.traces]


def test_clean_run_scores_zero() -> None:
    result = run(FIXTURE, plant=False, retrieve=canned_retrieve)
    m = result.report.metrics
    assert m.findings_total == 3
    assert m.hallucinations_total == 0
    assert m.citation_hallucination_rate == 0.0


def test_run_is_idempotent_on_finding_ids_and_rate() -> None:
    a = run(FIXTURE, retrieve=canned_retrieve)
    b = run(FIXTURE, retrieve=canned_retrieve)
    # finding ids are a deterministic hash (T3) → identical across runs; only run_id differs.
    assert [t.finding_id for t in a.traces] == [t.finding_id for t in b.traces]
    assert a.report.metrics.citation_hallucination_rate == b.report.metrics.citation_hallucination_rate
    assert a.report.run_id != b.report.run_id
