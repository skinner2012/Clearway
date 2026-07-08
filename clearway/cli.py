"""`clearway` CLI — the M0 entrypoint that runs the forward path and moves the trust metric.

`clearway run <fixture>` scans one page end-to-end, prints the computed
`citation_hallucination_rate`, and (unless `--no-emit`) pushes it via OTel so the Grafana
panel updates — the M0 exit criterion. `--clean` drafts the correct citations (rate 0.0)
instead of the planted faults, so alternating runs draw a moving line on the panel.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from clearway.observability import record_eval_report, setup_metrics, shutdown
from clearway.orchestrator import run


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
    result = run(args.target, plant=not args.clean)
    report = result.report
    m = report.metrics
    mode = "clean" if args.clean else "inject"
    print(
        f"run {report.run_id} [{mode}]  "
        f"findings={m.findings_total} citations={m.citations_total} "
        f"hallucinations={m.hallucinations_total}  "
        f"citation_hallucination_rate={m.citation_hallucination_rate:.3f}"
    )
    if args.emit:
        setup_metrics()
        try:
            record_eval_report(report)
        finally:
            shutdown()  # force-flush before this short-lived process exits (T9)
        print("emitted → OTel (the Grafana panel will update)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clearway", description="Clearway accessibility evidence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the forward path over one page and emit the trust metric")
    run_p.add_argument("target", help="fixture path or URL to scan")
    run_p.add_argument(
        "--clean",
        action="store_true",
        help="draft the correct retrieved citations (rate 0.0) instead of the planted faults",
    )
    run_p.add_argument(
        "--no-emit",
        dest="emit",
        action="store_false",
        help="compute and print only; do not push the metric to OTel",
    )
    run_p.set_defaults(emit=True, func=_run_cmd)

    ingest_p = sub.add_parser("corpus-ingest", help="fetch WCAG 2.2, chunk + embed, upsert into pgvector")
    ingest_p.add_argument("--limit", type=int, default=0, help="ingest only the first N chunks (0 = all)")
    ingest_p.set_defaults(func=_corpus_ingest_cmd)

    query_p = sub.add_parser("corpus-query", help="embed a query and print the nearest corpus chunks")
    query_p.add_argument("text", help="query text, e.g. 'images need a text alternative'")
    query_p.add_argument("-k", type=int, default=5, help="how many results to return")
    query_p.set_defaults(func=_corpus_query_cmd)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
