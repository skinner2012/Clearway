"""T1: the durable state machine — checkpointed retry, resumable replay (not recompute),
the resume-notice hook. ARCHITECTURE §4.6.

Offline throughout: InMemoryOrchestratorStore + canned retrieve/draft, no DB/LLM needed — proves
the machine's own mechanics. The real path (real retriever/drafter/Postgres) is proven by
run()/run_set()'s own tests once the refactor lands them onto execute()."""

from __future__ import annotations

from datetime import datetime, timezone

from clearway.drafter import DraftResult
from clearway.llm import LLMUsage
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator.machine import _review_reason, execute
from clearway.orchestrator.store import InMemoryOrchestratorStore
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    CitationCheck,
    CitationVerdict,
    Conformance,
    DraftRow,
    Finding,
    L1Status,
    PipelineStep,
    ReviewReason,
    ReviewStatus,
    StepStatus,
)

ORACLE = AxeCoreOracle()
_AT = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
_CONFIG = "pytest-config@1"
_MODEL = "pytest-model"


def _finding(finding_id: str) -> Finding:
    return Finding(
        id=finding_id, source_url="file://test.html", rule_id="image-alt", axe_tags=["wcag2a", "wcag111"], target="img"
    )


def _incomplete_finding(finding_id: str) -> Finding:
    """A finding from axe's INCOMPLETE bucket — the oracle grounds only VIOLATIONS, so its citation
    comes back UNVERIFIABLE and the HITL gate flags it `axe_incomplete`."""
    return Finding(
        id=finding_id,
        source_url="file://test.html",
        rule_id="color-contrast",
        axe_tags=["wcag2aa", "wcag143"],
        target="p",
        source_bucket=AxeBucket.INCOMPLETE,
    )


def _retrieve_ok(finding: Finding) -> list[Citation]:
    return [Citation(sc_id="1.1.1", source="WCAG-SC")]


def _draft_ok(finding: Finding, citations: list[Citation]) -> DraftRow:
    return DraftRow(
        finding_id=finding.id, conformance=Conformance.DOES_NOT_SUPPORT, citations=citations, confidence=0.9
    )


def _run(findings, store, *, run_id="r1", retrieve=_retrieve_ok, draft=_draft_ok, on_resume=None, max_attempts=3):  # type: ignore[no-untyped-def]
    return execute(
        findings,
        run_id=run_id,
        config_id=_CONFIG,
        model=_MODEL,
        created_at=_AT,
        do_retrieve=retrieve,
        do_draft=draft,
        oracle=ORACLE,
        store=store,
        max_attempts=max_attempts,
        backoff_seconds=0.0,  # no real sleeping in tests
        on_resume=on_resume,
    )


# --- happy path ----------------------------------------------------------------


def test_execute_produces_one_trace_per_finding_and_checkpoints_every_step() -> None:
    store = InMemoryOrchestratorStore()
    traces = _run([_finding("f1"), _finding("f2")], store)

    assert len(traces) == 2
    assert {t.finding_id for t in traces} == {"f1", "f2"}
    assert all(t.checks for t in traces)

    steps = store.load_steps("r1")
    assert len(steps) == 6  # 2 findings x 3 steps
    assert all(s.status is StepStatus.DONE for s in steps)

    run = store.load_run("r1")
    assert run is not None and run.status.value == "done"


def test_execute_handles_empty_findings() -> None:
    store = InMemoryOrchestratorStore()
    assert _run([], store) == []
    run = store.load_run("r1")
    assert run is not None and run.status.value == "done"


# --- usage quartet (T2: draft usage threads into the Trace) ----------------------


def _draft_with_usage(usage: LLMUsage):  # type: ignore[no-untyped-def]
    def draft(finding, citations):  # type: ignore[no-untyped-def]
        return DraftResult(_draft_ok(finding, citations), usage)

    return draft


def test_draftresult_usage_populates_the_trace_operational_quartet() -> None:
    store = InMemoryOrchestratorStore()
    usage = LLMUsage(tokens_in=200, tokens_out=50, cost_usd=0.0, latency_ms=87.5)
    (trace,) = _run([_finding("f1")], store, draft=_draft_with_usage(usage))
    assert trace.tokens_in == 200
    assert trace.tokens_out == 50
    assert trace.cost_usd == 0.0
    assert trace.latency_ms == 87.5


def test_bare_draftrow_stub_leaves_the_quartet_none() -> None:
    # a draft seam that returns a plain DraftRow (no LLM call) has no usage — honestly None.
    (trace,) = _run([_finding("f1")], InMemoryOrchestratorStore())  # default _draft_ok returns DraftRow
    assert (trace.tokens_in, trace.tokens_out, trace.cost_usd, trace.latency_ms) == (None, None, None, None)


def test_replayed_draft_reports_no_fresh_usage() -> None:
    # first pass records usage; a replay makes no fresh LLM call, so the replayed Trace's quartet
    # is None — the honest value (we didn't pay for it again).
    store = InMemoryOrchestratorStore()
    usage = LLMUsage(tokens_in=200, tokens_out=50, cost_usd=0.0, latency_ms=87.5)
    _run([_finding("f1")], store, draft=_draft_with_usage(usage))
    (replayed,) = _run([_finding("f1")], store, draft=_draft_with_usage(usage))
    assert replayed.tokens_in is None and replayed.latency_ms is None


# --- retry / backoff -------------------------------------------------------------


def test_execute_retries_a_transient_failure_then_succeeds() -> None:
    store = InMemoryOrchestratorStore()
    calls = {"n": 0}

    def flaky_draft(finding, citations):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated transient failure")
        return _draft_ok(finding, citations)

    traces = _run([_finding("f1")], store, draft=flaky_draft)
    assert len(traces) == 1
    assert calls["n"] == 2  # failed once, succeeded on retry

    steps = {s.step: s for s in store.load_steps("r1")}
    assert steps[PipelineStep.DRAFT].status is StepStatus.DONE
    assert steps[PipelineStep.DRAFT].attempts == 2


def test_execute_exhausts_retries_marks_step_failed_but_run_continues() -> None:
    def retrieve_fails_only_for_f1(finding):  # type: ignore[no-untyped-def]
        if finding.id == "f1":
            raise TimeoutError("simulated permanent-for-this-run failure")
        return _retrieve_ok(finding)

    store = InMemoryOrchestratorStore()
    traces = _run([_finding("f1"), _finding("f2")], store, retrieve=retrieve_fails_only_for_f1, max_attempts=2)

    assert [t.finding_id for t in traces] == ["f2"]  # f1 produced no trace; f2 still ran fine

    steps = {(s.finding_id, s.step): s for s in store.load_steps("r1")}
    assert steps[("f1", PipelineStep.RETRIEVE)].status is StepStatus.FAILED
    assert steps[("f1", PipelineStep.RETRIEVE)].attempts == 2  # exhausted max_attempts
    assert ("f1", PipelineStep.DRAFT) not in steps  # draft never attempted — pipeline halted at retrieve
    assert steps[("f2", PipelineStep.VALIDATE)].status is StepStatus.DONE


# --- resume: replay, not recompute ------------------------------------------------


def test_execute_replays_a_completed_step_without_recomputing() -> None:
    """A second execute() call for a fully-completed finding must reuse its cached results —
    retrieve/draft must NOT be called again."""
    store = InMemoryOrchestratorStore()
    first_pass = _run([_finding("f1")], store)
    assert len(first_pass) == 1

    calls = {"retrieve": 0, "draft": 0}

    def counting_retrieve(finding):  # type: ignore[no-untyped-def]
        calls["retrieve"] += 1
        return _retrieve_ok(finding)

    def counting_draft(finding, citations):  # type: ignore[no-untyped-def]
        calls["draft"] += 1
        return _draft_ok(finding, citations)

    second_pass = _run([_finding("f1")], store, retrieve=counting_retrieve, draft=counting_draft)

    assert calls == {"retrieve": 0, "draft": 0}  # fully replayed, nothing recomputed
    assert len(second_pass) == 1
    assert second_pass[0].retrieved_sc_ids == first_pass[0].retrieved_sc_ids
    assert second_pass[0].checks == first_pass[0].checks


def test_execute_resumes_a_partially_completed_run_and_processes_only_what_remains() -> None:
    """Kill-and-resume: f1 completed in the first pass. A resumed call with f1+f2 must replay
    f1 (no recompute) and process f2 fresh."""
    store = InMemoryOrchestratorStore()
    _run([_finding("f1")], store)  # first pass: only f1

    calls = {"n": 0}

    def counting_retrieve(finding):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return _retrieve_ok(finding)

    resumed = _run([_finding("f1"), _finding("f2")], store, retrieve=counting_retrieve)

    assert calls["n"] == 1  # only f2 was actually retrieved; f1 was replayed
    assert {t.finding_id for t in resumed} == {"f1", "f2"}


def test_on_resume_hook_reports_progress_and_next_finding() -> None:
    store = InMemoryOrchestratorStore()
    _run([_finding("f1")], store)

    seen = []
    _run([_finding("f1"), _finding("f2")], store, on_resume=lambda *args: seen.append(args))

    assert seen == [("r1", 1, 2, "f2")]  # 1 of 2 already done, continuing from f2


def test_on_resume_hook_is_not_called_for_a_fresh_run() -> None:
    store = InMemoryOrchestratorStore()
    seen = []
    _run([_finding("f1")], store, on_resume=lambda *args: seen.append(args))
    assert seen == []


def test_on_resume_hook_scopes_counts_to_the_current_batch_not_the_whole_run() -> None:
    """execute() may be called more than once under one run_id — run_set() does this, once per
    page. A later call's on_resume count must reflect only its OWN findings, not every finding
    ever checkpointed under this run_id (a page-2 call must not see page-1's done-count)."""
    store = InMemoryOrchestratorStore()
    _run([_finding("a1"), _finding("a2")], store, run_id="r1")  # "page 1" completes fully

    seen = []
    _run([_finding("b1")], store, run_id="r1", on_resume=lambda *args: seen.append(args))

    assert seen == [("r1", 0, 1, "b1")]  # scoped to b1 alone, not inflated by a1/a2's done count


# --- HITL gate: reason precedence (pure function) --------------------------------


def _check(verdict: CitationVerdict) -> CitationCheck:
    l1 = L1Status.NO_ORACLE if verdict is CitationVerdict.UNVERIFIABLE else L1Status.MATCH
    return CitationCheck(sc_id="1.1.1", l0_valid=True, l1_status=l1, verdict=verdict)


def test_review_reason_axe_incomplete_wins_over_unverifiable_judgment() -> None:
    # incomplete bucket, unverifiable citation → axe_incomplete (the broader cause).
    reason = _review_reason(_incomplete_finding("f1"), [_check(CitationVerdict.UNVERIFIABLE)])
    assert reason is ReviewReason.AXE_INCOMPLETE


def test_review_reason_unverifiable_judgment_for_a_violations_finding() -> None:
    # VIOLATIONS bucket, but a citation with no oracle verdict → unverifiable_judgment.
    reason = _review_reason(_finding("f1"), [_check(CitationVerdict.UNVERIFIABLE)])
    assert reason is ReviewReason.UNVERIFIABLE_JUDGMENT


def test_review_reason_is_none_for_a_clean_verified_finding() -> None:
    assert _review_reason(_finding("f1"), [_check(CitationVerdict.VERIFIED)]) is None


# --- HITL gate: interrupt + durable queue + resume-reflow ------------------------


def test_execute_gates_a_flagged_finding_queues_it_and_continues_the_run() -> None:
    """The flagged (incomplete) finding is withheld from the traces but persisted as a pending
    NeedsReview; the clean sibling finding still produces its trace — the run continues."""
    store = InMemoryOrchestratorStore()
    traces = _run([_incomplete_finding("gated"), _finding("clean")], store)

    assert [t.finding_id for t in traces] == ["clean"]  # gated finding withheld from the report

    review = store.load_review("r1", "gated")
    assert review is not None
    assert review.status is ReviewStatus.PENDING
    assert review.reason is ReviewReason.AXE_INCOMPLETE
    assert review.draft.finding_id == "gated"  # the record carries the drafted row
    assert store.load_review("r1", "clean") is None  # the clean finding was never queued


def test_a_pending_review_stays_withheld_and_is_not_re_queued_on_resume() -> None:
    store = InMemoryOrchestratorStore()
    _run([_incomplete_finding("gated")], store)
    first = store.load_review("r1", "gated")

    resumed = _run([_incomplete_finding("gated")], store)  # resume with no human action yet
    assert resumed == []  # still withheld
    assert store.load_review("r1", "gated") == first  # untouched — not re-saved / re-timestamped


def test_approving_a_review_reflows_the_original_draft_on_resume() -> None:
    store = InMemoryOrchestratorStore()
    _run([_incomplete_finding("gated")], store)
    review = store.load_review("r1", "gated")
    assert review is not None
    store.save_review(review.model_copy(update={"status": ReviewStatus.APPROVED}))

    (trace,) = _run([_incomplete_finding("gated")], store)  # resume after approval
    assert trace.finding_id == "gated"  # the approved finding now assembles into the report
    assert trace.confidence == review.draft.confidence


def test_editing_a_review_reflows_the_edited_draft_with_revalidated_checks() -> None:
    store = InMemoryOrchestratorStore()
    _run([_incomplete_finding("gated")], store)
    review = store.load_review("r1", "gated")
    assert review is not None
    # the human rewrites the remediation and drops confidence — the edit is what must ship.
    edited = review.draft.model_copy(update={"remediation": "human-reviewed fix", "confidence": 0.6})
    store.save_review(review.model_copy(update={"status": ReviewStatus.EDITED, "edited_draft": edited}))

    (trace,) = _run([_incomplete_finding("gated")], store)  # resume after edit
    assert trace.finding_id == "gated"
    assert trace.confidence == 0.6  # the Trace reflects the EDITED draft, not the original


def test_rejecting_a_review_keeps_the_finding_out_of_the_report() -> None:
    store = InMemoryOrchestratorStore()
    _run([_incomplete_finding("gated")], store)
    review = store.load_review("r1", "gated")
    assert review is not None
    store.save_review(review.model_copy(update={"status": ReviewStatus.REJECTED}))

    assert _run([_incomplete_finding("gated")], store) == []  # rejected → never enters the output
