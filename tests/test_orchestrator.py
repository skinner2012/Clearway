"""The orchestrator runs the whole spine end-to-end — one page (`run`) or the M1 eval set (`run_set`).

Real-browser integration test — the runners scan fixtures with headless Chromium + axe-core, then
normalize → retrieve → draft → validate → eval. Requires `playwright install chromium`. `run` over
home.html asserts `citation_hallucination_rate == 2/3`; `run_set` over the m1-core@1 pages asserts
the honest stratified aggregate (5 findings, 2 UNVERIFIABLE → `unverifiable_share == 2/5`). The
runners are pure — emission (OTel) lives in the CLI and is proven by the stack-gated
test_observability.py.

Both model-facing steps are injected with canned stubs, and the durable checkpoint store is an
in-memory stand-in, so the spine runs offline (no corpus stack, no Ollama, no Postgres):
`canned_retrieve` returns the correct SC per fixture rule, and the drafter stub plants known
citation faults — together they make the exit-criterion metric deterministic and assertable. The
real retriever/drafter/store are proven in their own modules' gated tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.orchestrator import InMemoryOrchestratorStore, RunResult, run, run_set
from clearway.schemas.models import EvalReport, OracleRegime, Trace

PAGES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages"
FIXTURE = str(PAGES / "home.html")
# The m1-core@1 set: the 3 verifiable violations (home) + the 2 needs-review pages (incomplete).
M1_SET = [str(PAGES / p) for p in ("home.html", "contrast-gradient.html", "video-no-captions.html")]


def test_run_end_to_end_hits_the_exit_criterion() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore())
    assert isinstance(result, RunResult)
    assert isinstance(result.report, EvalReport)

    m = result.report.metrics
    # 3 planted findings, 3 citations, 2 intentional faults (html-has-lang→1.1.1, label→9.9.9).
    assert m.findings_total == 3
    assert m.citations_total == 3
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == 2 / 3


def test_run_produces_one_trace_per_finding_sharing_a_run() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore())
    assert len(result.traces) == 3
    assert all(isinstance(t, Trace) for t in result.traces)
    # all traces of one run share run_id / config_id, and each carries its checks.
    assert len({t.run_id for t in result.traces}) == 1
    assert {t.config_id for t in result.traces} == {"m1-single@1"}
    assert result.report.run_id == result.traces[0].run_id
    assert all(t.checks for t in result.traces)
    # report labels are read off the oracle, not hardcoded.
    assert result.report.oracle_regime == OracleRegime.A_DIGITAL
    assert result.report.eval_set_id == "m0-core@1"
    assert result.report.trace_ids == [t.finding_id for t in result.traces]


def test_run_is_idempotent_on_finding_ids_and_rate() -> None:
    store = InMemoryOrchestratorStore()
    a = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store)
    b = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store)
    # finding ids are a deterministic hash (T3) → identical across runs; only run_id differs.
    assert [t.finding_id for t in a.traces] == [t.finding_id for t in b.traces]
    assert a.report.metrics.citation_hallucination_rate == b.report.metrics.citation_hallucination_rate
    assert a.report.run_id != b.report.run_id


# --- run_set: the M1 exit-criterion set runner -------------------------------


def test_run_set_folds_the_m1_page_set_into_one_report() -> None:
    result = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore()
    )
    assert isinstance(result, RunResult)
    # 5 findings across 3 pages: home's 3 verifiable violations + 2 incomplete needs-review items.
    assert len(result.traces) == 5
    # the whole set scores under ONE run so it aggregates into a single report.
    assert len({t.run_id for t in result.traces}) == 1
    assert result.report.run_id == result.traces[0].run_id
    assert result.report.eval_set_id == "m1-core@1"
    assert result.report.trace_ids == [t.finding_id for t in result.traces]


def test_run_set_stratifies_the_honest_unverifiable_share() -> None:
    m = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore()
    ).report.metrics
    assert m.findings_total == 5
    assert m.citations_total == 5
    # the 2 incomplete-bucket citations (1.4.3, 1.2.2) have no oracle → UNVERIFIABLE.
    assert m.citations_unverifiable_total == 2
    assert m.citations_verifiable_total == 3
    assert m.unverifiable_share == pytest.approx(2 / 5)
    # hallucinations only live in the verifiable subset (home's 2 planted faults).
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == pytest.approx(2 / 5)
    assert m.citation_hallucination_rate_verifiable == pytest.approx(2 / 3)


def test_run_set_rejects_empty_targets() -> None:
    with pytest.raises(ValueError, match="at least one target"):
        run_set(
            [], eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore()
        )
