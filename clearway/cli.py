"""`clearway` CLI — the entrypoint that runs the forward path and moves the trust metric.

`clearway run <fixture>` scans one page end-to-end; `clearway eval` runs the whole `m1-core@1`
fixture set. Both print the stratified trust metrics — the overall `citation_hallucination_rate`,
the verifiable-subset rate, and the honest `unverifiable_share` — and (unless `--no-emit`) push
them via OTel so the Grafana panel updates. The rates are the real drafter's *emergent* values —
the M0 planting demo lever was retired at T3, so the honest measurement is what the panel shows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clearway.observability import (
    record_eval_report,
    setup_metrics,
    setup_operational_metrics,
    setup_tracing,
    shutdown,
    shutdown_operational_metrics,
    shutdown_tracing,
)
from clearway.orchestrator import run, run_set
from clearway.orchestrator.store import OrchestratorStore
from clearway.schemas.models import DraftRow, EvalReport, NeedsReview, ReviewStatus

_FIXTURES = Path(__file__).parent / "fixtures"


def _print_metrics(report: EvalReport) -> None:
    """Print the stratified trust metrics for one report: the overall hallucination rate plus its
    split by oracle-verifiability (verifiable-subset rate + the honest `unverifiable_share`)."""
    m = report.metrics
    print(
        f"{report.eval_set_id}  run {report.run_id}  "
        f"findings={m.findings_total} citations={m.citations_total} hallucinations={m.hallucinations_total}"
    )
    print(
        f"  citation_hallucination_rate={m.citation_hallucination_rate:.3f}  "
        f"verifiable={m.citation_hallucination_rate_verifiable:.3f}  "
        f"unverifiable_share={m.unverifiable_share:.3f} "
        f"({m.citations_unverifiable_total}/{m.citations_total})"
    )


@contextmanager
def _telemetry(emit: bool) -> Iterator[None]:
    """Bracket the whole run with OTel telemetry when emitting. Spans AND the operational LLM/
    pipeline metrics are produced *during* `execute()`, so — unlike the trust gauges, set from the
    finished report — they must be set up before the run and flushed after. `--no-emit` skips all of
    it; spans/metrics then fall back to inert no-op API calls, so an offline run needs no stack."""
    if emit:
        setup_metrics()  # installs the global MeterProvider the operational metrics export through
        setup_operational_metrics()
        setup_tracing()
    try:
        yield
    finally:
        if emit:
            # force-flush before this short-lived process exits (T9)
            shutdown_tracing()
            shutdown_operational_metrics()
            shutdown()


def _print_resume_notice(run_id: str, done_count: int, total_count: int, next_finding_id: str | None) -> None:
    """`execute()`'s `on_resume` hook, wired to a real print — fires before the run proceeds, so a
    resumed `run`/`eval` confirms it's actually skipping finished work before real drafts take
    35-50s each."""
    where = f"continuing from {next_finding_id}" if next_finding_id is not None else "nothing left to do"
    print(f"resuming run {run_id}: {done_count}/{total_count} findings already complete, {where}")


# --- HITL review queue (T3) --------------------------------------------------


def _open_store() -> OrchestratorStore:
    """The durable store the review commands read/write. Reuses `run._default_store` (real Postgres
    + ensure_schema) so tests patch a single seam; imported lazily so `clearway review` never builds
    a DB connection when another subcommand is invoked."""
    from clearway.orchestrator.run import _default_store

    return _default_store()


def _resolve_review(store: OrchestratorStore, finding_id: str, run_id: str | None) -> NeedsReview | None:
    """Find one queued review by `finding_id` (+ optional `--run-id` to disambiguate). Prints why
    and returns None when it's unknown or queued under more than one run."""
    if run_id is not None:
        review = store.load_review(run_id, finding_id)
        if review is None:
            print(f"no review for finding {finding_id} in run {run_id}", file=sys.stderr)
        return review
    matches = [r for r in store.load_reviews() if r.finding_id == finding_id]
    if not matches:
        print(f"no review found for finding {finding_id}", file=sys.stderr)
        return None
    if len(matches) > 1:
        runs = ", ".join(sorted(r.run_id for r in matches))
        print(f"finding {finding_id} is queued in multiple runs ({runs}); pass --run-id", file=sys.stderr)
        return None
    return matches[0]


def _resume_hint(review: NeedsReview) -> str:
    return f"resume to assemble: clearway eval --run-id {review.run_id}"


def _review_list_cmd(args: argparse.Namespace) -> int:
    status = ReviewStatus(args.status) if args.status else None
    reviews = _open_store().load_reviews(status=status)
    if not reviews:
        print("review queue is empty")
        return 0
    for r in reviews:
        print(f"{r.finding_id}  run={r.run_id}  {r.status.value:<8}  {r.reason.value:<20}  {r.draft.conformance.value}")
    return 0


def _review_show_cmd(args: argparse.Namespace) -> int:
    review = _resolve_review(_open_store(), args.finding_id, args.run_id)
    if review is None:
        return 1
    print(f"finding {review.finding_id}  run {review.run_id}")
    print(f"  status={review.status.value}  reason={review.reason.value}")
    print("  draft:")
    print(json.dumps(review.draft.model_dump(mode="json"), indent=2))
    if review.edited_draft is not None:
        print("  edited_draft:")
        print(json.dumps(review.edited_draft.model_dump(mode="json"), indent=2))
    return 0


def _edit_draft_in_editor(draft: DraftRow) -> DraftRow | None:
    """Open the DraftRow as JSON in `$EDITOR`, re-validating on save. Returns the edited row, or
    None if the buffer no longer parses as a valid DraftRow."""
    editor = os.getenv("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tf.write(json.dumps(draft.model_dump(mode="json"), indent=2))
        path = tf.name
    try:
        subprocess.run([editor, path], check=True)
        edited_text = Path(path).read_text()
    finally:
        os.unlink(path)
    try:
        return DraftRow.model_validate_json(edited_text)  # re-validate on save
    except ValidationError as exc:
        print(f"edited draft is not a valid DraftRow:\n{exc}", file=sys.stderr)
        return None


def _apply_review_outcome(
    store: OrchestratorStore, review: NeedsReview, status: ReviewStatus, edited: DraftRow | None
) -> None:
    store.save_review(
        review.model_copy(update={"status": status, "edited_draft": edited, "updated_at": datetime.now(UTC)})
    )


def _review_approve_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    _apply_review_outcome(store, review, ReviewStatus.APPROVED, review.edited_draft)
    print(f"approved {review.finding_id} — {_resume_hint(review)}")
    return 0


def _review_edit_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    base = review.edited_draft or review.draft
    if args.remediation is not None:
        edited: DraftRow | None = base.model_copy(update={"remediation": args.remediation})
    else:
        edited = _edit_draft_in_editor(base)
        if edited is None:
            return 1
    _apply_review_outcome(store, review, ReviewStatus.EDITED, edited)
    print(f"edited {review.finding_id} — {_resume_hint(review)}")
    return 0


def _review_reject_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    _apply_review_outcome(store, review, ReviewStatus.REJECTED, review.edited_draft)
    print(f"rejected {review.finding_id} — it will stay out of the assembled output")
    return 0


def _corpus_ingest_cmd(args: argparse.Namespace) -> int:
    from clearway.corpus import (
        LiteLLMEmbedder,
        PgCorpusStore,
        build_corpus_version,
        fetch_wcag_json,
        ingest,
        parse_wcag_json,
    )

    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    corpus_version = build_corpus_version(embedder)
    chunks = parse_wcag_json(fetch_wcag_json(), corpus_version=corpus_version)
    if args.limit:
        chunks = chunks[: args.limit]
    stored = ingest(chunks, embedder, store)
    print(f"ingested {stored} chunks  corpus_version={corpus_version}  total={store.count(corpus_version)}")
    return 0


def _corpus_query_cmd(args: argparse.Namespace) -> int:
    from clearway.corpus import LiteLLMEmbedder, PgCorpusStore, build_corpus_version

    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    corpus_version = build_corpus_version(embedder)
    hits = store.query(embedder.embed_query(args.text), k=args.k, corpus_version=corpus_version)
    for hit in hits:
        print(f"{','.join(hit.sc_ids):8} {hit.text[:90]}")
    return 0


def _run_cmd(args: argparse.Namespace) -> int:
    with _telemetry(args.emit):
        report = run(args.target, run_id=args.run_id, on_resume=_print_resume_notice).report
        if args.emit:
            record_eval_report(report)
    _print_metrics(report)
    if args.emit:
        print("emitted → OTel (the Grafana panel will update)")
    return 0


def _eval_cmd(args: argparse.Namespace) -> int:
    """Run the whole `m1-core@1` fixture set (the manifest's pages) and report the stratified
    trust metrics. This is the M1 exit-criterion command — the set is where the two incomplete
    fixtures make `unverifiable_share` non-trivial. Needs the real corpus stack + Ollama."""
    manifest = json.loads((_FIXTURES / "expected_m1.json").read_text())
    targets = [str(_FIXTURES / page["path"]) for page in manifest["pages"]]
    with _telemetry(args.emit):
        report = run_set(
            targets, eval_set_id=manifest["eval_set_id"], run_id=args.run_id, on_resume=_print_resume_notice
        ).report
        if args.emit:
            record_eval_report(report)
    _print_metrics(report)
    if args.emit:
        print("emitted → OTel (the Grafana panel will update)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clearway", description="Clearway accessibility evidence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the forward path over one page and emit the trust metric")
    run_p.add_argument("target", help="fixture path or URL to scan")
    run_p.add_argument(
        "--no-emit",
        dest="emit",
        action="store_false",
        help="compute and print only; do not push the metric to OTel",
    )
    run_p.add_argument(
        "--run-id",
        default=None,
        help="resume an existing run id instead of starting a fresh one (target must be the same page)",
    )
    run_p.set_defaults(emit=True, func=_run_cmd)

    eval_p = sub.add_parser("eval", help="run the m1-core@1 fixture set and emit the stratified trust metrics")
    eval_p.add_argument(
        "--no-emit",
        dest="emit",
        action="store_false",
        help="compute and print only; do not push the metrics to OTel",
    )
    eval_p.add_argument(
        "--run-id",
        default=None,
        help="resume an existing run id instead of starting a fresh one",
    )
    eval_p.set_defaults(emit=True, func=_eval_cmd)

    review_p = sub.add_parser("review", help="triage the HITL needs-review queue (list/show/approve/edit/reject)")
    review_sub = review_p.add_subparsers(dest="review_command", required=True)

    list_p = review_sub.add_parser("list", help="list queued reviews")
    list_p.add_argument(
        "--status", choices=[s.value for s in ReviewStatus], default=None, help="filter by review status"
    )
    list_p.set_defaults(func=_review_list_cmd)

    show_p = review_sub.add_parser("show", help="show a queued review's draft + context")
    show_p.add_argument("finding_id", help="the flagged finding's id (from `review list`)")
    show_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    show_p.set_defaults(func=_review_show_cmd)

    approve_p = review_sub.add_parser("approve", help="approve a queued draft as-is")
    approve_p.add_argument("finding_id")
    approve_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    approve_p.set_defaults(func=_review_approve_cmd)

    edit_p = review_sub.add_parser("edit", help="edit a queued draft (opens $EDITOR unless --remediation)")
    edit_p.add_argument("finding_id")
    edit_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    edit_p.add_argument("--remediation", default=None, help="quick single-field edit without opening the editor")
    edit_p.set_defaults(func=_review_edit_cmd)

    reject_p = review_sub.add_parser("reject", help="reject a queued draft (kept out of the assembled output)")
    reject_p.add_argument("finding_id")
    reject_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    reject_p.set_defaults(func=_review_reject_cmd)

    ingest_p = sub.add_parser("corpus-ingest", help="fetch WCAG 2.2, chunk + embed, upsert into pgvector")
    ingest_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="ingest only the first N chunks (0 = all)",
    )
    ingest_p.set_defaults(func=_corpus_ingest_cmd)

    query_p = sub.add_parser("corpus-query", help="embed a query and print the nearest corpus chunks")
    query_p.add_argument("text", help="query text, e.g. 'images need a text alternative'")
    query_p.add_argument(
        "-k",
        type=int,
        default=5,
        help="how many results to return",
    )
    query_p.set_defaults(func=_corpus_query_cmd)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
