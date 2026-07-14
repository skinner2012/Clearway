"""Assemble the calibration snapshot the dashboard reads — κ (judge reliability) + the confidence
curve — from the two frozen artifacts, and project its scalars onto `EvalMetrics`.

This is the one place the two calibration halves meet: `calibration_set.json` (the balanced κ set,
judge-scored) and `confidence_calibration.json` (the verifiable oracle-scored half). Both are frozen
by their build scripts and replayed OFFLINE here — no LLM, no oracle, no network — so the snapshot is
reproducible from checked-in data, never re-derived by calling a non-deterministic model.

Two shapes come out, each with a single home for its data (the milestone's "data lives once" rule):
- `CalibrationReport` — carries κ, the trust gate, and the confidence curve (`confidence_bins`).
- `EvalMetrics` — carries the calibration SCALARS only (κ, ECE, over-confidence gap, judgment
  correctness); the curve is never copied here.

The gauge push that puts these on the dashboard is a milestone-triggered, point-in-time emit (the
calibration is a milestone artifact, not a per-run metric), wired in `observability/metrics.py`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from clearway.eval.confidence import CalibrationCurve, build_curve, judgment_points, verifiable_points
from clearway.eval.kappa import agreements_from_artifact, build_report
from clearway.schemas.models import CalibrationReport, EvalMetrics

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_CALIBRATION = _FIXTURES / "calibration_set.json"
_CONFIDENCE = _FIXTURES / "confidence_calibration.json"


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def assemble(
    *,
    created_at: datetime,
    calibration: dict[str, Any] | None = None,
    confidence: dict[str, Any] | None = None,
) -> tuple[CalibrationReport, CalibrationCurve]:
    """Compose the κ report and the confidence curve from the two frozen artifacts.

    The balanced-set κ is the trust gate; the natural-pass κ rides along in `bias_notes` for the
    real-workload honesty check. The curve combines the judge-scored judgment half (natural drafts
    only) with the oracle-scored verifiable half. `created_at` is passed in — this module stays
    deterministic, stamping is the caller's job.
    """
    cal = calibration if calibration is not None else _load(_CALIBRATION)
    conf = confidence if confidence is not None else _load(_CONFIDENCE)
    balanced, natural = agreements_from_artifact(cal)
    curve = build_curve(judgment_points(cal), verifiable_points(conf))
    report = build_report(balanced, natural, created_at=created_at, confidence_bins=curve.bins)
    return report, curve


def calibration_metrics(report: CalibrationReport, curve: CalibrationCurve) -> EvalMetrics:
    """Project the snapshot onto the `EvalMetrics` calibration SCALARS — the fields the dashboard
    gauges read. The M0–M3 forward-path fields stay at their schema defaults: this is a
    calibration-only carrier, and the emit pushes ONLY these judge/calibration series (never the
    default rate fields). The confidence curve is deliberately absent — it lives on `CalibrationReport`.

    `judge_gold_n` mirrors `CalibrationReport.n` (the balanced set the judge was calibrated on);
    judgment correctness ships as numerator + denominator, never a bare rate.
    """
    return EvalMetrics(
        citation_hallucination_rate=0.0,  # unused: not emitted by the calibration push (see metrics.record_calibration)
        judge_kappa=report.judge_kappa,
        judge_agreement_rate=report.judge_agreement,
        judge_gold_n=report.n,
        judge_trusted=report.judge_trusted,
        judgment_correctness_rate=curve.judgment_correctness_rate,
        judgment_items_total=curve.judgment_total,
        judgment_correct_total=curve.judgment_correct,
        expected_calibration_error=curve.ece,
        overconfidence_gap=curve.overconfidence_gap,
    )


def _print_summary(report: CalibrationReport, curve: CalibrationCurve) -> None:
    trusted = "TRUSTED" if report.judge_trusted else "NOT TRUSTED"
    print(
        f"judge κ {report.judge_kappa:.4f} (raw agreement {report.judge_agreement:.4f}, n={report.n}) "
        f"vs bar {report.kappa_threshold} → {trusted}"
    )
    print(
        f"confidence: ECE {curve.ece:.4f}, over-confidence gap {curve.overconfidence_gap:+.4f}, "
        f"judgment correctness {curve.judgment_correct}/{curve.judgment_total}"
    )
    for b in curve.bins:
        print(
            f"  bin [{b.lower}-{b.upper}]  n={b.n}  mean_conf={b.mean_confidence:.4f}  correct={b.correctness_rate:.4f}"
        )


def main() -> None:
    """Assemble the snapshot from the frozen artifacts and push it to the OTLP collector.

    The push side is imported locally so the pure assembly above stays free of the observability stack.
    Run explicitly when the calibration changes: `uv run python -m clearway.eval.calibration_snapshot`.
    """
    from datetime import timezone

    from clearway.observability import metrics

    calibration = _load(_CALIBRATION)
    report, curve = assemble(
        created_at=datetime.now(timezone.utc), calibration=calibration, confidence=_load(_CONFIDENCE)
    )
    _print_summary(report, curve)

    metrics.setup_metrics()
    try:
        metrics.record_calibration(
            calibration_metrics(report, curve),
            report,
            judge_model=calibration["judge_model"],
            gold_version=calibration["gold_version"],
        )
    finally:
        metrics.shutdown()
    print("pushed calibration snapshot to the OTLP collector")


if __name__ == "__main__":
    main()
