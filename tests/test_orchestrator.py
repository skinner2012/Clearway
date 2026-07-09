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

from datetime import UTC, datetime
from pathlib import Path

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.normalizer import normalize
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator import InMemoryOrchestratorStore, RunResult, execute, run, run_set
from clearway.scanner import scan
from clearway.schemas.models import EvalReport, OracleRegime, ReviewReason, ReviewStatus, Trace

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


def test_run_set_folds_the_verifiable_findings_and_queues_the_incomplete_ones() -> None:
    """T3: the HITL gate withholds the 2 incomplete-bucket findings for review, so a fresh run
    assembles only home's 3 verifiable violations and queues the rest — the run does not stall."""
    store = InMemoryOrchestratorStore()
    result = run_set(M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store)
    assert isinstance(result, RunResult)
    # 3 verifiable violations assemble; the 2 incomplete items are gated into the queue.
    assert len(result.traces) == 3
    assert len(store.load_reviews(status=ReviewStatus.PENDING)) == 2
    assert {r.reason for r in store.load_reviews()} == {ReviewReason.AXE_INCOMPLETE}
    # the whole set scores under ONE run so it aggregates into a single report.
    assert len({t.run_id for t in result.traces}) == 1
    assert result.report.run_id == result.traces[0].run_id
    assert result.report.eval_set_id == "m1-core@1"
    assert result.report.trace_ids == [t.finding_id for t in result.traces]


def test_run_set_gates_then_after_approval_restores_the_honest_unverifiable_share() -> None:
    """The M1 stratified headline (2/5 unverifiable) is now reached through the M2 HITL path: a
    fresh run withholds the 2 incomplete items (unverifiable_share drops to 0); once a human
    approves them, a resume folds them back in and the honest 2/5 share reappears."""
    store = InMemoryOrchestratorStore()
    run_id = "hitl-reflow"
    fresh = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
    ).report.metrics
    # Fresh run: only home's 3 verifiable violations are scored — the incomplete items are queued.
    assert fresh.findings_total == 3
    assert fresh.citations_unverifiable_total == 0
    assert fresh.unverifiable_share == pytest.approx(0.0)
    assert fresh.citation_hallucination_rate_verifiable == pytest.approx(2 / 3)

    # A human approves the 2 queued items, then the run resumes (same run_id).
    for review in store.load_reviews(status=ReviewStatus.PENDING):
        store.save_review(review.model_copy(update={"status": ReviewStatus.APPROVED}))
    m = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
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


# --- resume: proves the run_id/on_resume plumbing added to run()/run_set(), distinct from
# execute()'s own replay mechanics (already proven directly in test_machine.py) ------------------


def test_run_resumes_a_partially_completed_run_via_an_explicit_run_id() -> None:
    """Simulate a kill mid-run: `execute()` directly completes only the first finding (as if the
    process died before reaching the rest), then `run()` — called fresh, with the same run_id and
    store — must replay that finding instead of recomputing it and process only what's left."""
    findings = normalize(scan(FIXTURE))
    store = InMemoryOrchestratorStore()
    run_id = "partial-kill-test"
    calls: list[str] = []

    def counting_retrieve(finding):  # type: ignore[no-untyped-def]
        calls.append(finding.id)
        return canned_retrieve(finding)

    # "Prior process" completes only the first finding before being killed.
    execute(
        findings[:1],
        run_id=run_id,
        config_id="m1-single@1",
        model="gemma4:31b",
        created_at=datetime.now(UTC),
        do_retrieve=counting_retrieve,
        do_draft=canned_draft,
        oracle=AxeCoreOracle(),
        store=store,
    )
    assert calls == [findings[0].id]
    calls.clear()

    resume_notices = []
    result = run(
        FIXTURE,
        retrieve=counting_retrieve,
        draft=canned_draft,
        store=store,
        run_id=run_id,
        on_resume=lambda *a: resume_notices.append(a),
    )

    assert findings[0].id not in calls  # replayed, not recomputed
    assert len(result.traces) == 3  # all 3 findings present in the final result
    assert resume_notices == [(run_id, 1, 3, findings[1].id)]


def test_run_set_resumes_across_pages_without_recomputing_completed_pages() -> None:
    """A resumed run_set() must replay every page's findings, not just the first, and each page's
    resume notice must report counts scoped to that page — proving done_ids is scoped to the
    current batch rather than leaking counts across pages that share one run_id."""
    store = InMemoryOrchestratorStore()
    run_id = "set-resume-test"
    calls: list[str] = []

    def counting_retrieve(finding):  # type: ignore[no-untyped-def]
        calls.append(finding.id)
        return canned_retrieve(finding)

    run_set(M1_SET, eval_set_id="m1-core@1", retrieve=counting_retrieve, draft=canned_draft, store=store, run_id=run_id)
    assert len(calls) == 5
    calls.clear()

    resume_notices = []
    result = run_set(
        M1_SET,
        eval_set_id="m1-core@1",
        retrieve=counting_retrieve,
        draft=canned_draft,
        store=store,
        run_id=run_id,
        on_resume=lambda *a: resume_notices.append(a),
    )

    assert calls == []  # every finding replayed, nothing recomputed
    # 3 verifiable traces assemble; the 2 incomplete items stay gated in the queue. The resume
    # notices still count all findings — the gate is post-validate, so every VALIDATE step is DONE.
    assert len(result.traces) == 3
    assert [(done, total, next_id) for _, done, total, next_id in resume_notices] == [
        (3, 3, None),
        (1, 1, None),
        (1, 1, None),
    ]
