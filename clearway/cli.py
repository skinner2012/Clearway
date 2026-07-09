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
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from clearway.observability import (
    record_eval_report,
    setup_metrics,
    setup_tracing,
    shutdown,
    shutdown_tracing,
)
from clearway.orchestrator import run, run_set
from clearway.schemas.models import EvalReport

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
def _tracing(emit: bool) -> Iterator[None]:
    """Bracket the run with OTel tracing when emitting: spans are produced *during* `execute()`, so
    unlike metrics (recorded from the finished report) tracing must be set up before the run and
    flushed after. `--no-emit` skips it entirely — spans then fall back to inert no-op API calls."""
    if emit:
        setup_tracing()
    try:
        yield
    finally:
        if emit:
            shutdown_tracing()  # force-flush spans before this short-lived process exits


def _emit(report: EvalReport) -> None:
    """Push the report's metrics via OTel, force-flushing before this short-lived process exits."""
    setup_metrics()
    try:
        record_eval_report(report)
    finally:
        shutdown()  # force-flush before this short-lived process exits (T9)
    print("emitted → OTel (the Grafana panel will update)")


def _print_resume_notice(run_id: str, done_count: int, total_count: int, next_finding_id: str | None) -> None:
    """`execute()`'s `on_resume` hook, wired to a real print — fires before the run proceeds, so a
    resumed `run`/`eval` confirms it's actually skipping finished work before real drafts take
    35-50s each."""
    where = f"continuing from {next_finding_id}" if next_finding_id is not None else "nothing left to do"
    print(f"resuming run {run_id}: {done_count}/{total_count} findings already complete, {where}")


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
    with _tracing(args.emit):
        report = run(args.target, run_id=args.run_id, on_resume=_print_resume_notice).report
    _print_metrics(report)
    if args.emit:
        _emit(report)
    return 0


def _eval_cmd(args: argparse.Namespace) -> int:
    """Run the whole `m1-core@1` fixture set (the manifest's pages) and report the stratified
    trust metrics. This is the M1 exit-criterion command — the set is where the two incomplete
    fixtures make `unverifiable_share` non-trivial. Needs the real corpus stack + Ollama."""
    manifest = json.loads((_FIXTURES / "expected_m1.json").read_text())
    targets = [str(_FIXTURES / page["path"]) for page in manifest["pages"]]
    with _tracing(args.emit):
        report = run_set(
            targets, eval_set_id=manifest["eval_set_id"], run_id=args.run_id, on_resume=_print_resume_notice
        ).report
    _print_metrics(report)
    if args.emit:
        _emit(report)
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
