"""The orchestrator runs the whole spine end-to-end — one page (`run`) or the M1 eval set (`run_set`).

Real-browser integration test — the runners scan fixtures with headless Chromium + axe-core, then
normalize → retrieve → draft → validate → eval. Requires `playwright install chromium`. `run` over
home.html asserts `citation_hallucination_rate == 2/3`; `run_set` over the m1-core@1 pages asserts
the honest stratified aggregate (`unverifiable_share == 2/5`, computed over CITATIONS). The
runners are pure — emission (OTel) lives in the CLI and is proven by the stack-gated
test_observability.py.

Note on the finding COUNTS below: the quality-review rule set is global and mints existence-only
judgment findings (document-title on every <title>, empty-heading on every non-empty <h1>), so
each fixture carries two more findings than its planted violations/incomplete. Those judgment
findings flow through the spine but carry NO canned citation offline (the stub returns [] for
rules it doesn't model) — they are measured properly against W3C ACT expert gold in the acceptance
benchmark, not scored here. So they lift the finding/trace/call COUNTS without touching any
citation-based metric: `citation_hallucination_rate == 2/3` and `unverifiable_share == 2/5` hold
unchanged.

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
from clearway.schemas.models import (
    Conformance,
    DraftRow,
    OnlineEvalReport,
    OracleRegime,
    ReviewReason,
    ReviewStatus,
    Trace,
)

PAGES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages"
FIXTURE = str(PAGES / "home.html")
# The m1-core@1 set: the 3 verifiable violations (home) + the 2 needs-review pages (incomplete).
M1_SET = [str(PAGES / p) for p in ("home.html", "contrast-gradient.html", "video-no-captions.html")]


def test_run_end_to_end_hits_the_exit_criterion() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore())
    assert isinstance(result, RunResult)
    assert isinstance(result.report, OnlineEvalReport)

    m = result.report.metrics
    # 3 planted violations + 2 quality-review judgment findings (document-title, empty-heading) = 5.
    # Only the 3 violations carry canned citations (3 total, 2 intentional faults html-has-lang→1.1.1,
    # label→9.9.9); the 2 judgment findings carry none offline, so the citation metrics are unmoved.
    assert m.findings_total == 5
    assert m.citations_total == 3
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == 2 / 3


def test_run_surfaces_assembled_drafts_aligned_with_traces() -> None:
    """`run` returns the assembled DraftRow for every non-withheld finding — the ACR/VPAT rows the
    CLI renders — one per trace, in the same order. The `on_assembled` sink fires exactly when a
    Trace is produced, so a finding withheld at the review gate appears in neither list (proven for
    the withheld incomplete pages by the run_set alignment below)."""
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore())
    assert all(isinstance(d, DraftRow) for d in result.drafts)
    assert [d.finding_id for d in result.drafts] == [t.finding_id for t in result.traces]
    # the canned drafter marks every fixture finding does_not_support
    assert {d.conformance for d in result.drafts} == {Conformance.DOES_NOT_SUPPORT}


def test_run_set_drafts_exclude_withheld_findings() -> None:
    """A fresh run_set over the m1 set withholds the two incomplete pages at the review gate. Since
    drafts track traces 1:1, the withheld findings are absent from `drafts` too — the report never
    ships a row it held back for review."""
    store = InMemoryOrchestratorStore()
    result = run_set(M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store)
    assert [d.finding_id for d in result.drafts] == [t.finding_id for t in result.traces]


def test_run_reports_progress_per_step() -> None:
    """`run` fires on_progress as it works — a 'scan' then 'normalize' page event carrying the
    finding count, then retrieve/draft/validate per finding — the live read a long real-LLM run
    shows so the console isn't silent for minutes."""
    events: list[tuple[str, int, int, str]] = []
    run(
        FIXTURE,
        retrieve=canned_retrieve,
        draft=canned_draft,
        store=InMemoryOrchestratorStore(),
        on_progress=lambda step, index, total, label: events.append((step, index, total, label)),
    )
    steps = [e[0] for e in events]
    assert "scan" in steps
    # normalize fires once and carries the finding count (5 = 3 violations + 2 judgment findings)
    normalize_events = [e for e in events if e[0] == "normalize"]
    assert len(normalize_events) == 1
    assert normalize_events[0][2] == 5
    # every finding is drafted; the index runs 1..5 with a stable total
    draft_events = [e for e in events if e[0] == "draft"]
    assert [e[1] for e in draft_events] == [1, 2, 3, 4, 5]
    assert all(e[2] == 5 for e in draft_events)


def test_run_produces_one_trace_per_finding_sharing_a_run() -> None:
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=InMemoryOrchestratorStore())
    assert len(result.traces) == 5  # 3 violations + 2 quality-review judgment findings
    assert all(isinstance(t, Trace) for t in result.traces)
    # all traces of one run share run_id / config_id, and each carries its checks.
    assert len({t.run_id for t in result.traces}) == 1
    assert {t.config_id for t in result.traces} == {"m1-single@1"}
    assert result.report.run_id == result.traces[0].run_id
    # the 3 violations carry validation checks; the 2 judgment findings have no citation offline
    # (stub returns []), so their traces have nothing to validate — no checks.
    assert sum(1 for t in result.traces if t.checks) == 3
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


# --- T5: the completed run persists its OnlineEvalReport (accuracy-over-time history) ---


def test_run_persists_its_report_to_the_store() -> None:
    """A completed run writes exactly one `OnlineEvalReport` row, keyed by its run_id and equal to the
    report it returns — the data-production half of the T6 accuracy-over-time trend."""
    store = InMemoryOrchestratorStore()
    result = run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store)
    persisted = store.load_report(result.report.run_id)
    assert persisted == result.report
    assert len(store.load_reports()) == 1


def test_two_runs_persist_two_report_rows() -> None:
    store = InMemoryOrchestratorStore()
    run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store)
    run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store)
    assert len(store.load_reports()) == 2


def test_a_resumed_run_overwrites_its_report_row_without_duplicating() -> None:
    """Resuming under the same run_id re-persists that run's row in place (PK on run_id), so the
    history never double-counts a resumed run — and the reflowed report replaces the earlier one."""
    store = InMemoryOrchestratorStore()
    run_id = "report-resume"
    run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id)
    run(FIXTURE, retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id)
    assert len(store.load_reports()) == 1
    assert store.load_report(run_id) is not None


# --- run_set: the M1 exit-criterion set runner -------------------------------


def test_run_set_folds_the_verifiable_findings_and_queues_the_incomplete_ones() -> None:
    """T3: the HITL gate withholds the 2 incomplete-bucket findings for review, so a fresh run
    assembles the ungated findings and queues the incomplete rest — the run does not stall.
    Ungated = home's 3 violations + the 6 quality-review judgment findings (2 per page) = 9 traces;
    only the 2 incomplete items are gated (the judgment findings are not gated)."""
    store = InMemoryOrchestratorStore()
    result = run_set(M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store)
    assert isinstance(result, RunResult)
    # 3 violations + 6 judgment findings assemble; the 2 incomplete items are gated into the queue.
    assert len(result.traces) == 9
    assert len(store.load_reviews(status=ReviewStatus.PENDING)) == 2
    assert {r.reason for r in store.load_reviews()} == {ReviewReason.AXE_INCOMPLETE}
    # the whole set scores under ONE run so it aggregates into a single report.
    assert len({t.run_id for t in result.traces}) == 1
    assert result.report.run_id == result.traces[0].run_id
    assert result.report.eval_set_id == "m1-core@1"
    assert result.report.trace_ids == [t.finding_id for t in result.traces]


def test_run_set_gates_then_after_approval_restores_the_honest_unverifiable_share() -> None:
    """The M1 stratified headline (2/5 unverifiable, over CITATIONS) is reached through the M2 HITL
    path: a fresh run withholds the 2 incomplete items (their unverifiable citations drop out →
    unverifiable_share 0); once a human approves them, a resume folds them back in and the honest
    2/5 share reappears. The 6 quality-review judgment findings ride along in findings_total but carry no
    citation offline, so they never touch the citation-based headline."""
    store = InMemoryOrchestratorStore()
    run_id = "hitl-reflow"
    fresh = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
    ).report.metrics
    # Fresh run: home's 3 violations + 6 judgment findings are scored; the 2 incomplete items are queued.
    assert fresh.findings_total == 9
    assert fresh.citations_unverifiable_total == 0
    assert fresh.unverifiable_share == pytest.approx(0.0)
    assert fresh.citation_hallucination_rate_verifiable == pytest.approx(2 / 3)

    # A human approves the 2 queued items, then the run resumes (same run_id).
    for review in store.load_reviews(status=ReviewStatus.PENDING):
        store.save_review(review.model_copy(update={"status": ReviewStatus.APPROVED}))
    m = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
    ).report.metrics

    # 3 violations + 6 judgment findings + 2 approved-incomplete = 11 findings; but only the 5
    # oracle-relevant findings carry citations (the 6 judgment findings carry none offline).
    assert m.findings_total == 11
    assert m.citations_total == 5
    # the 2 incomplete-bucket citations (1.4.3, 1.2.2) have no oracle → UNVERIFIABLE.
    assert m.citations_unverifiable_total == 2
    assert m.citations_verifiable_total == 3
    assert m.unverifiable_share == pytest.approx(2 / 5)
    # hallucinations only live in the verifiable subset (home's 2 planted faults).
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == pytest.approx(2 / 5)
    assert m.citation_hallucination_rate_verifiable == pytest.approx(2 / 3)


def test_run_set_edit_reflow_populates_expert_edit_distance() -> None:
    """A human edit to a queued draft flows into the report's `expert_edit_distance` (M2 T4): a
    fresh run has no edits (distance 0); after one queued item is edited and the run resumes, the
    report's run-mean distance is the SequenceMatcher complement over that item's remediation."""
    from clearway.eval import expert_edit_distance

    store = InMemoryOrchestratorStore()
    run_id = "hitl-edit"
    fresh = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
    ).report.metrics
    assert fresh.expert_edit_distance == 0.0  # nothing edited yet

    # A human edits one queued item's remediation and approves the other unchanged.
    pending = store.load_reviews(status=ReviewStatus.PENDING)
    assert len(pending) == 2
    edited, approved = pending
    edited_draft = edited.draft.model_copy(
        update={"remediation": edited.draft.remediation + " Provide a visible text alternative."}
    )
    store.save_review(edited.model_copy(update={"status": ReviewStatus.EDITED, "edited_draft": edited_draft}))
    store.save_review(approved.model_copy(update={"status": ReviewStatus.APPROVED}))

    m = run_set(
        M1_SET, eval_set_id="m1-core@1", retrieve=canned_retrieve, draft=canned_draft, store=store, run_id=run_id
    ).report.metrics
    # mean over the single EDITED review (the APPROVED one contributes nothing).
    expected = expert_edit_distance(edited.draft, edited_draft)
    assert expected > 0.0
    assert m.expert_edit_distance == pytest.approx(expected)


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
    assert len(result.traces) == 5  # all 5 findings present in the final result
    assert resume_notices == [(run_id, 1, 5, findings[1].id)]


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
    assert len(calls) == 11  # every finding retrieved once: (3+2) home + (1+2) contrast + (1+2) video
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
    # 9 ungated traces assemble (3 violations + 6 judgment findings); the 2 incomplete items stay
    # gated in the queue. The resume notices still count all findings — the gate is post-validate,
    # so every VALIDATE step is DONE.
    assert len(result.traces) == 9
    # per-page counts (scoped to each page's own batch): home 3 violations + 2 judgment = 5;
    # contrast/video 1 incomplete + 2 judgment = 3 each.
    assert [(done, total, next_id) for _, done, total, next_id in resume_notices] == [
        (5, 5, None),
        (3, 3, None),
        (3, 3, None),
    ]
