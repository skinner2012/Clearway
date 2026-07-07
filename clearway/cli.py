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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
