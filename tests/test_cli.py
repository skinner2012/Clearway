"""`clearway` CLI smoke tests — the user-facing entrypoint over the orchestrator.

The `run` and `eval` tests inject the canned spine (`offline_spine`) and pass `--no-emit`, so they
exercise argument parsing and the printed stratified summary without the corpus stack, Ollama, or
OTel (emission is proven end-to-end by the stack-gated test_observability.py). `eval` still scans
the real fixture pages with headless Chromium. The `corpus-*` test is stack-gated (real Ollama +
pgvector), since those subcommands construct the real embedder/store.
"""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.cli import _render_drafts, main
from clearway.schemas.models import (
    Citation,
    Conformance,
    ConformanceLevel,
    DraftRow,
    NeedsReview,
    ReviewReason,
    ReviewStatus,
    Severity,
)

FIXTURE = str(Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages" / "home.html")


def _draft_row(**overrides: object) -> DraftRow:
    """A representative assembled DraftRow for the renderer tests; override any field per case."""
    fields: dict[str, object] = {
        "finding_id": "img-1",
        "conformance": Conformance.DOES_NOT_SUPPORT,
        "citations": [
            Citation(
                sc_id="1.1.1",
                title="Non-text Content",
                level=ConformanceLevel.A,
                url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
            )
        ],
        "remediation": "Add an alt attribute to the image.",
        "severity": Severity.SERIOUS,
        "confidence": 0.9,
    }
    fields.update(overrides)
    return DraftRow(**fields)  # type: ignore[arg-type]


def _review(reason: ReviewReason) -> NeedsReview:
    """A minimal pending NeedsReview for the withheld-summary tests — only `reason` varies."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return NeedsReview(
        run_id="r1",
        finding_id="f",
        draft=_draft_row(),
        reason=reason,
        status=ReviewStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


def test_render_drafts_shows_an_acr_shaped_row() -> None:
    out = _render_drafts("https://example.gov", [_draft_row()], [])
    assert "ACR / VPAT evidence -- https://example.gov" in out
    assert "Does Not Support" in out  # standard VPAT wording, not the raw enum value
    assert "does_not_support" not in out
    assert "serious" in out
    assert "1.1.1 Non-text Content (Level A)" in out
    assert "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html" in out
    assert "Add an alt attribute to the image." in out


def test_render_drafts_omits_decorative_confidence() -> None:
    out = _render_drafts("t", [_draft_row(confidence=0.9)], [])
    assert "0.9" not in out
    assert "onfidence" not in out


def test_render_drafts_marks_a_row_with_no_citations() -> None:
    out = _render_drafts("t", [_draft_row(citations=[])], [])
    assert "(none cited)" in out


def test_render_drafts_lists_every_citation() -> None:
    rows = [
        _draft_row(
            citations=[
                Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A),
                Citation(sc_id="2.4.4", title="Link Purpose (In Context)", level=ConformanceLevel.A),
            ]
        )
    ]
    out = _render_drafts("t", rows, [])
    assert "1.1.1 Non-text Content (Level A)" in out
    assert "2.4.4 Link Purpose (In Context) (Level A)" in out


def test_render_drafts_empty_is_explicit() -> None:
    out = _render_drafts("https://example.gov", [], [])
    assert "No rows assembled" in out


def test_render_drafts_summarises_withheld_by_reason() -> None:
    withheld = [_review(ReviewReason.UNVERIFIABLE_JUDGMENT)] * 3 + [_review(ReviewReason.AXE_INCOMPLETE)] * 2
    out = _render_drafts("t", [_draft_row()], withheld)
    assert "5 withheld for specialist review" in out
    assert "3 no automated oracle" in out
    assert "2 axe could not decide" in out
    assert "clearway review list --status pending" in out


def test_render_drafts_empty_still_names_the_withheld_gap() -> None:
    out = _render_drafts("t", [], [_review(ReviewReason.UNVERIFIABLE_JUDGMENT)])
    assert "No rows assembled" in out
    assert "1 withheld for specialist review" in out


@pytest.fixture
def offline_spine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `clearway run`/`clearway eval` use the canned retriever + drafter stubs and an
    in-memory checkpoint store instead of building the real RAG retriever, LLM drafter, and
    Postgres store, so the CLI tests exercise the CLI glue without needing the corpus stack,
    Ollama, or Postgres (see run._default_retrieve / _default_draft / _default_store). Patched via
    importlib because the re-exported `run` *function* shadows the submodule under plain attribute
    access."""
    import importlib

    from clearway.orchestrator import InMemoryOrchestratorStore

    run_module = importlib.import_module("clearway.orchestrator.run")
    monkeypatch.setattr(run_module, "_default_retrieve", lambda: canned_retrieve)
    monkeypatch.setattr(run_module, "_default_draft", lambda: canned_draft)
    monkeypatch.setattr(run_module, "_default_store", lambda: InMemoryOrchestratorStore())


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


def test_cli_run_no_emit_exits_zero(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["run", FIXTURE, "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "citation_hallucination_rate=0.667" in out
    assert "emitted" not in out  # --no-emit must not touch OTel


def test_cli_eval_no_emit_reports_the_stratified_set(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """`clearway eval` runs the whole m1-core@1 set. With the T3 HITL gate, the two incomplete
    fixtures are withheld for review, so a fresh eval scores only home's 3 verifiable citations →
    unverifiable_share = 0.000; they rejoin the score once a reviewer approves them (proven in
    test_orchestrator.py's reflow test)."""
    code = main(["eval", "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "m1-core@1" in out
    assert "unverifiable_share=0.000" in out
    assert "emitted" not in out  # --no-emit must not touch OTel


def test_cli_run_prints_the_acr_evidence_block(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """`clearway run <url>` prints the assembled ACR/VPAT rows, then the trust-metric summary — the
    drafter output a reader sees, not just the aggregate metrics."""
    code = main(["run", FIXTURE, "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "ACR / VPAT evidence" in out
    assert "Conformance" in out
    assert "Does Not Support" in out  # the canned drafter marks every fixture finding does_not_support
    assert "citation_hallucination_rate" in out  # metrics still print after the rows


def test_cli_run_prints_progress_to_stderr(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """`clearway run` shows live progress — the finding count and per-step lines — on stderr, so
    redirecting stdout to a file still captures only the report, not the progress log."""
    assert main(["run", FIXTURE, "--no-emit"]) == 0
    captured = capsys.readouterr()
    assert "5 finding(s) found" in captured.err
    assert "[1/5] draft" in captured.err
    assert "finding(s) found" not in captured.out  # progress stays out of the report on stdout


def test_cli_run_with_run_id_resumes_and_prints_a_notice(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """--run-id resumes a prior run: the second invocation must print a resume notice before its
    metrics, proving the CLI wires on_resume through to a real print (run()/run_set() accepting the
    parameter is proven directly in test_orchestrator.py). Needs one store shared across both
    `main()` calls, unlike `offline_spine`, which hands out a fresh store per call."""
    import importlib

    from clearway.orchestrator import InMemoryOrchestratorStore

    run_module = importlib.import_module("clearway.orchestrator.run")
    shared_store = InMemoryOrchestratorStore()
    monkeypatch.setattr(run_module, "_default_retrieve", lambda: canned_retrieve)
    monkeypatch.setattr(run_module, "_default_draft", lambda: canned_draft)
    monkeypatch.setattr(run_module, "_default_store", lambda: shared_store)

    assert main(["run", FIXTURE, "--no-emit", "--run-id", "cli-resume-test"]) == 0
    capsys.readouterr()  # discard the first call's output

    assert main(["run", FIXTURE, "--no-emit", "--run-id", "cli-resume-test"]) == 0
    out = capsys.readouterr().out
    assert "resuming run cli-resume-test: 5/5 findings already complete, nothing left to do" in out


# --- HITL review queue (T3) ---------------------------------------------------


@pytest.fixture
def shared_spine(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Like `offline_spine`, but hands out ONE shared in-memory store across every `main()` call so
    a `review` command sees the queue a prior `eval` populated (and a resume sees the review's
    outcome). Yields the store so tests can read the queue directly."""
    import importlib

    from clearway.orchestrator import InMemoryOrchestratorStore

    run_module = importlib.import_module("clearway.orchestrator.run")
    store = InMemoryOrchestratorStore()
    monkeypatch.setattr(run_module, "_default_retrieve", lambda: canned_retrieve)
    monkeypatch.setattr(run_module, "_default_draft", lambda: canned_draft)
    monkeypatch.setattr(run_module, "_default_store", lambda: store)
    return store


def test_cli_review_list_and_show_surface_the_queue(shared_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """A fresh eval gates the 2 incomplete fixtures; `review list` shows them pending and `review
    show` prints the flagged draft + reason."""
    assert main(["eval", "--no-emit", "--run-id", "cli-review"]) == 0
    capsys.readouterr()

    assert main(["review", "list", "--status", "pending"]) == 0
    listed = capsys.readouterr().out
    assert listed.count("axe_incomplete") == 2

    finding_id = shared_spine.load_reviews()[0].finding_id
    assert main(["review", "show", finding_id]) == 0
    shown = capsys.readouterr().out
    assert finding_id in shown
    assert "reason=axe_incomplete" in shown
    assert '"remediation"' in shown  # the DraftRow JSON is printed


def test_cli_review_approve_then_resume_restores_the_unverifiable_share(shared_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """Approving the 2 gated items and resuming the run folds them back into the report — the honest
    2/5 unverifiable share returns."""
    assert main(["eval", "--no-emit", "--run-id", "cli-approve"]) == 0
    capsys.readouterr()

    for review in shared_spine.load_reviews():
        assert main(["review", "approve", review.finding_id]) == 0
    capsys.readouterr()

    assert main(["eval", "--no-emit", "--run-id", "cli-approve"]) == 0
    out = capsys.readouterr().out
    assert "unverifiable_share=0.400" in out


def test_cli_review_edit_with_remediation_persists_and_flows_into_the_report(shared_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """`review edit --remediation` re-drafts a queued row without the editor; it persists as an
    edit and, on resume, the finding assembles into the report (findings_total climbs back to 11:
    3 violations + 6 quality-review judgment findings + the 2 edited-and-folded incomplete items)."""
    assert main(["eval", "--no-emit", "--run-id", "cli-edit"]) == 0
    capsys.readouterr()

    for review in shared_spine.load_reviews():
        assert main(["review", "edit", review.finding_id, "--remediation", "human-reviewed fix"]) == 0
    capsys.readouterr()

    # the edit is persisted on the record...
    edited = shared_spine.load_reviews()[0]
    assert edited.status.value == "edited"
    assert edited.edited_draft is not None
    assert edited.edited_draft.remediation == "human-reviewed fix"

    # ...and flows into the assembled output on resume (all 11 findings scored again).
    assert main(["eval", "--no-emit", "--run-id", "cli-edit"]) == 0
    assert "findings=11" in capsys.readouterr().out


def test_cli_review_reject_keeps_the_finding_out_of_the_report(shared_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["eval", "--no-emit", "--run-id", "cli-reject"]) == 0
    capsys.readouterr()

    for review in shared_spine.load_reviews():
        assert main(["review", "reject", review.finding_id]) == 0
    capsys.readouterr()

    assert main(["eval", "--no-emit", "--run-id", "cli-reject"]) == 0
    # 3 violations + 6 quality-review judgment findings stay; the 2 rejected incomplete never rejoin.
    assert "findings=9" in capsys.readouterr().out


def test_cli_review_show_unknown_finding_errors(shared_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["review", "show", "does-not-exist"]) == 1
    assert "no review found" in capsys.readouterr().err


@corpus_up
def test_cli_corpus_ingest_then_query_smoke(capsys) -> None:  # type: ignore[no-untyped-def]
    """Both corpus subcommands run end-to-end through the real embedder/store. `--limit`
    keeps it to a few real SCs (an idempotent re-upsert — SC 1.1.1 is first, so the query
    finds it); this exercises the CLI glue that the module-level tests don't touch."""
    assert main(["corpus-ingest", "--limit", "3"]) == 0
    ingest_out = capsys.readouterr().out
    assert "ingested" in ingest_out and "corpus_version=" in ingest_out

    assert main(["corpus-query", "images need a text alternative"]) == 0
    assert "1.1.1" in capsys.readouterr().out
