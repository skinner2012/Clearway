"""Push the frozen benchmark scorecard onto the dashboard — a point-in-time milestone emit, the twin
of `calibration_snapshot`. It loads the frozen `benchmark/reports/scorecard.json` and projects it onto
the benchmark gauges; it never re-runs a model, so the pushed numbers are exactly the checked-in ones.

Run it when the frozen baseline changes (after a re-freeze): `uv run python -m clearway.eval.acceptance_snapshot`.
The push side is imported locally so the load/summary above stays free of the observability stack.
"""

from __future__ import annotations

import json
from pathlib import Path

from clearway.schemas.models import BenchmarkReport

_SCORECARD = Path(__file__).resolve().parents[2] / "benchmark" / "reports" / "scorecard.json"


def load_report(path: Path = _SCORECARD) -> BenchmarkReport:
    """The frozen scorecard artifact → a validated `BenchmarkReport` (the baseline, noise floor and all)."""
    return BenchmarkReport.model_validate(json.loads(path.read_text()))


def _print_summary(report: BenchmarkReport) -> None:
    sc = report.scorecard
    d, j = sc.drafter, sc.judge
    recall, fp = d.recall, d.false_positive_rate
    print(f"benchmark {report.eval_set_id} / {report.config_id} (runs={len(report.run_ids)})")
    print(
        f"  drafter: recall {recall.value:.3f} [{recall.ci_low:.2f},{recall.ci_high:.2f}] (n={recall.n}), "
        f"FP {fp.value:.3f} [{fp.ci_low:.2f},{fp.ci_high:.2f}] (n={fp.n})"
    )
    print(
        f"  judge:   κ {j.kappa:.3f}, miss {j.miss_rate.value:.3f} (n={j.miss_rate.n}), "
        f"false-alarm {j.false_alarm_rate.value:.3f}"
    )
    if sc.noise_floor is not None:
        nf = sc.noise_floor
        print(
            f"  noise:   MDI {nf.min_detectable_improvement:.3f} pp ({nf.dominant_source}), "
            f"judge κ SD {nf.per_metric_sd.get('judge_kappa', 0.0):.3f}"
        )


def main() -> None:
    from clearway.observability import metrics

    report = load_report()
    _print_summary(report)

    metrics.setup_metrics()
    try:
        metrics.record_benchmark(report)
    finally:
        metrics.shutdown()
    print("pushed benchmark scorecard to the OTLP collector")


if __name__ == "__main__":
    main()
