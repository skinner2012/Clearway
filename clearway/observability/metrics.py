"""Observability — emit the trust metrics via OTel (ARCHITECTURE §4.5).

M1 emits the overall `citation_hallucination_rate` plus its oracle-verifiability stratification —
`citation_hallucination_rate_verifiable` (~0 by construction) and `unverifiable_share` (the honest
headline) — pushed OTLP/HTTP → OTel Collector → Prometheus → Grafana. (Rich tracing / GenAI
semconv is deferred to M2, where the drafter is a real LLM and a trace backend exists.)

The app is a short-lived CLI, so we must force-flush before exit or the metric never
leaves the process — see `shutdown()`, which the orchestrator/CLI (T10) calls in a
`finally`. Metric labels are kept low-cardinality (no `run_id`) so a single time series'
*value moves* across runs instead of spawning a new series each run.
"""

from __future__ import annotations

import os

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import _Gauge as Gauge
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from clearway.schemas.models import BenchmarkReport, CalibrationReport, EvalMetrics, EvalReport

_DEFAULT_ENDPOINT = "http://localhost:4318"
_METRIC_NAME = "citation_hallucination_rate"
_METRIC_VERIFIABLE = "citation_hallucination_rate_verifiable"
_METRIC_UNVERIFIABLE_SHARE = "unverifiable_share"
_METRIC_EXPERT_EDIT_DISTANCE = "expert_edit_distance"

# M4 calibration series. Names are BARE (no `clearway_` prefix, no unit) to match the existing gauges
# above — a unit would make the Prometheus exporter suffix `..._ratio`, and a prefix would diverge from
# the dashboard's other queries. The scalars mirror the `EvalMetrics` judge/calibration fields; the
# curve is emitted per-bin as a labelled series so its data lives once (on `CalibrationReport`) and is
# never copied onto `EvalMetrics`. All are point-in-time milestone gauges, pushed by an explicit
# calibration emit, not by a per-run forward path.
_CAL_SCALAR_METRICS: dict[str, str] = {
    "judge_kappa": "Judge-vs-human Cohen's κ (the trust gate; [-1,1], negative = worse than chance).",
    "judge_agreement_rate": "Raw judge-vs-human agreement proportion, reported alongside κ.",
    "judge_trusted": "1 iff the judge cleared the pre-committed κ bar (else 0).",
    "judgment_correctness_rate": "Judge-scored correctness over judgment items (a κ-capped estimate).",
    "expected_calibration_error": "ECE — unsigned magnitude of confidence miscalibration.",
    "overconfidence_gap": "Signed confidence − correctness (positive = systematically over-confident).",
}
_CAL_CURVE_METRICS: dict[str, str] = {
    "confidence_correctness": "Correctness rate within a confidence bin (labelled by `bin`).",
    "confidence_mean_confidence": "Mean self-reported confidence within a bin (the calibration diagonal).",
    "confidence_bin_n": "Draft count in a bin — ships beside the rate so a single-bin curve cannot lie.",
}

# M5 held-out benchmark series. Same convention as above: bare names (no prefix would suffix `..._ratio`),
# point-in-time milestone gauges pushed by an explicit snapshot emit — the frozen scorecard is an
# artifact, not a per-run series, so a gauge holds the last freeze. The headline rates ship their Wilson
# bounds and n as sibling series so a panel shows the interval, never a bare point. Names mirror the
# `AcceptanceScorecard` fields; `benchmark_gauge_values` is the single source of what each one holds.
_BENCH_METRICS: dict[str, str] = {
    # Subject #1 — drafter, scored deterministically against ACT gold (never via the judge).
    "benchmark_drafter_recall": "Drafter recall on ACT failed cases — does it find the real problem (primary axis).",
    "benchmark_drafter_recall_ci_low": "Recall Wilson lower bound (asymmetric).",
    "benchmark_drafter_recall_ci_high": "Recall Wilson upper bound (asymmetric).",
    "benchmark_drafter_recall_n": "Recall denominator — the ACT-failed true positives.",
    "benchmark_drafter_false_positive_rate": "Drafter FP rate on ACT passed cases — does it cry wolf (THE headline).",
    "benchmark_drafter_false_positive_rate_ci_low": "FP-rate Wilson lower bound.",
    "benchmark_drafter_false_positive_rate_ci_high": "FP-rate Wilson upper bound.",
    "benchmark_drafter_false_positive_rate_n": "FP-rate denominator — the ACT-passed true negatives.",
    "benchmark_drafter_sc_citation_match": "Cited SC ∩ ACT gold on flagged fails — secondary; low by framing.",
    "benchmark_drafter_ece": "Expected calibration error — CI-exempt (single bin at this n); read with the gap.",
    "benchmark_drafter_overconfidence_gap": "Signed confidence − correctness; positive = over-confident.",
    # Subject #2 — judge, measured AGAINST ACT gold (a subject, not the ruler).
    "benchmark_judge_kappa": "Judge-vs-ACT-gold Cohen's κ on independent W3C gold (harder than M4's κ).",
    "benchmark_judge_miss_rate": "Judge passed a wrong draft — the DANGEROUS half; CI-exempt.",
    "benchmark_judge_false_alarm_rate": "Judge blocked a correct draft — the merely-annoying half.",
    "benchmark_judge_injected_flip_detection": "Detection on conformance-flipped drafts — an UPPER BOUND.",
    "benchmark_judge_injected_swap_detection": "Detection on SC-swapped drafts — upper bound, secondary.",
    # Overall — the noise floor, the regression yardstick's smallest gradation.
    "benchmark_min_detectable_improvement": "Smallest claimable improvement (pp) — below this is jitter.",
    "benchmark_noise_floor_judge_kappa_sd": "Judge κ SD across repeat runs — run-to-run unstable.",
}

_provider: MeterProvider | None = None
_rate_gauge: Gauge | None = None
_rate_verifiable_gauge: Gauge | None = None
_unverifiable_share_gauge: Gauge | None = None
_expert_edit_distance_gauge: Gauge | None = None
_cal_gauges: dict[str, Gauge] = {}
_bench_gauges: dict[str, Gauge] = {}


def setup_metrics(endpoint: str | None = None) -> None:
    """Wire an OTLP/HTTP MeterProvider and create the trust-metric gauge (idempotent)."""
    global _provider, _rate_gauge, _rate_verifiable_gauge, _unverifiable_share_gauge
    global _expert_edit_distance_gauge
    if _provider is not None:
        return
    base = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or _DEFAULT_ENDPOINT
    exporter = OTLPMetricExporter(endpoint=f"{base.rstrip('/')}/v1/metrics")
    # Long interval on purpose: we force-flush explicitly at shutdown rather than
    # relying on the periodic tick (the CLI may exit before a tick fires).
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    _provider = MeterProvider(
        metric_readers=[reader],
        # Fixed service.instance.id: otherwise the SDK/collector assigns a fresh id per
        # process, so every run would land in a NEW Prometheus series and the panel would
        # never show one line moving. A stable id keeps runs on the same series.
        resource=Resource.create({"service.name": "clearway", "service.instance.id": "clearway-cli"}),
    )
    # Also install as the global provider so operational.py's LLM/pipeline metrics (recorded from
    # the orchestrator during the run) export through this same OTLP reader.
    metrics.set_meter_provider(_provider)
    meter = _provider.get_meter("clearway.eval")
    # No unit on purpose: unit "1" makes the Prometheus exporter suffix the name
    # `..._ratio`, diverging from the documented metric name. The name + description
    # already convey it's a dimensionless fraction.
    _rate_gauge = meter.create_gauge(
        _METRIC_NAME,
        description="Fraction of drafted citations that fail L0/L1 validation.",
    )
    _rate_verifiable_gauge = meter.create_gauge(
        _METRIC_VERIFIABLE,
        description="Hallucination rate over the oracle-verifiable citation subset (~0 by construction).",
    )
    _unverifiable_share_gauge = meter.create_gauge(
        _METRIC_UNVERIFIABLE_SHARE,
        description="Fraction of citations with no automated oracle to check against (the honest headline).",
    )
    _expert_edit_distance_gauge = meter.create_gauge(
        _METRIC_EXPERT_EDIT_DISTANCE,
        description="Mean normalized text distance a human moved this run's edited drafts (0 = no edits).",
    )
    for name, description in {**_CAL_SCALAR_METRICS, **_CAL_CURVE_METRICS}.items():
        _cal_gauges[name] = meter.create_gauge(name, description=description)
    for name, description in _BENCH_METRICS.items():
        _bench_gauges[name] = meter.create_gauge(name, description=description)


def record_rate(rate: float, *, eval_set_id: str, config_id: str, oracle_regime: str) -> None:
    """Set the trust-metric gauge. Low-cardinality labels only (no run_id)."""
    if _rate_gauge is None:
        setup_metrics()
    assert _rate_gauge is not None  # set by setup_metrics
    _rate_gauge.set(
        rate,
        {"eval_set_id": eval_set_id, "config_id": config_id, "oracle_regime": oracle_regime},
    )


def record_eval_report(report: EvalReport) -> None:
    """Emit the trust metrics from a computed `EvalReport`: the overall hallucination rate plus its
    oracle-verifiability stratification (verifiable rate + unverifiable share), and the M2 HITL
    `expert_edit_distance` (run-mean human-edit distance). All share the same low-cardinality label
    set, so they move together on one panel per (eval_set, config)."""
    if _rate_gauge is None:
        setup_metrics()
    assert _rate_verifiable_gauge is not None and _unverifiable_share_gauge is not None  # set by setup_metrics
    assert _expert_edit_distance_gauge is not None  # set by setup_metrics
    labels = {
        "eval_set_id": report.eval_set_id,
        "config_id": report.config_id,
        "oracle_regime": report.oracle_regime.value,
    }
    m = report.metrics
    record_rate(
        m.citation_hallucination_rate,
        eval_set_id=report.eval_set_id,
        config_id=report.config_id,
        oracle_regime=report.oracle_regime.value,
    )
    _rate_verifiable_gauge.set(m.citation_hallucination_rate_verifiable, labels)
    _unverifiable_share_gauge.set(m.unverifiable_share, labels)
    _expert_edit_distance_gauge.set(m.expert_edit_distance, labels)


def record_calibration(metrics: EvalMetrics, report: CalibrationReport, *, judge_model: str, gold_version: str) -> None:
    """Push the M4 calibration snapshot: the judge/calibration SCALARS off `EvalMetrics`, and the
    confidence curve as a per-bin labelled series off `CalibrationReport.confidence_bins`.

    A milestone-triggered, point-in-time emit — the calibration is a milestone artifact, not a per-run
    metric, so its gauges hold the last snapshot rather than a per-run series. Labels are the pinned
    provenance (`judge_model`, `gold_version`): both are constants, so cardinality stays at one series
    per metric. The scalars are Optional on `EvalMetrics` but a calibration carrier always sets them —
    a missing one means the snapshot was mis-assembled, so we fail loudly rather than push a silent 0.
    """
    if not _cal_gauges:
        setup_metrics()
    labels = {"judge_model": judge_model, "gold_version": gold_version}
    scalars: dict[str, float | None] = {
        "judge_kappa": metrics.judge_kappa,
        "judge_agreement_rate": metrics.judge_agreement_rate,
        "judge_trusted": None if metrics.judge_trusted is None else float(metrics.judge_trusted),
        "judgment_correctness_rate": metrics.judgment_correctness_rate,
        "expected_calibration_error": metrics.expected_calibration_error,
        "overconfidence_gap": metrics.overconfidence_gap,
    }
    for name, value in scalars.items():
        if value is None:
            raise ValueError(f"calibration metric {name!r} is unset — the snapshot was mis-assembled")
        _cal_gauges[name].set(value, labels)

    for b in report.confidence_bins:
        bin_labels = {**labels, "bin": f"{b.lower}-{b.upper}"}
        _cal_gauges["confidence_correctness"].set(b.correctness_rate, bin_labels)
        _cal_gauges["confidence_mean_confidence"].set(b.mean_confidence, bin_labels)
        _cal_gauges["confidence_bin_n"].set(b.n, bin_labels)


def benchmark_gauge_values(report: BenchmarkReport) -> dict[str, float]:
    """The frozen scorecard → {gauge_name: value}: the single, pure source of what each benchmark gauge
    holds. Kept off the OTLP path so it can be tested against a frozen artifact with no collector, and
    so `record_benchmark` cannot silently skip a declared metric (the keys must equal `_BENCH_METRICS`).

    The snapshot is only meaningful for the FROZEN baseline, which carries the noise floor — a scorecard
    without one means a single run was passed in by mistake, so we fail loudly rather than push a 0.
    """
    sc = report.scorecard
    d, j, nf = sc.drafter, sc.judge, sc.noise_floor
    if nf is None:
        raise ValueError("benchmark snapshot needs the frozen baseline (with its noise floor) — freeze the sweep first")
    return {
        "benchmark_drafter_recall": d.recall.value,
        "benchmark_drafter_recall_ci_low": d.recall.ci_low,
        "benchmark_drafter_recall_ci_high": d.recall.ci_high,
        "benchmark_drafter_recall_n": float(d.recall.n),
        "benchmark_drafter_false_positive_rate": d.false_positive_rate.value,
        "benchmark_drafter_false_positive_rate_ci_low": d.false_positive_rate.ci_low,
        "benchmark_drafter_false_positive_rate_ci_high": d.false_positive_rate.ci_high,
        "benchmark_drafter_false_positive_rate_n": float(d.false_positive_rate.n),
        "benchmark_drafter_sc_citation_match": d.sc_citation_match.value,
        "benchmark_drafter_ece": d.expected_calibration_error.value,
        "benchmark_drafter_overconfidence_gap": d.overconfidence_gap,
        "benchmark_judge_kappa": j.kappa,
        "benchmark_judge_miss_rate": j.miss_rate.value,
        "benchmark_judge_false_alarm_rate": j.false_alarm_rate.value,
        "benchmark_judge_injected_flip_detection": j.injected_conformance_flip.value,
        "benchmark_judge_injected_swap_detection": j.injected_sc_swap.value,
        "benchmark_min_detectable_improvement": nf.min_detectable_improvement,
        "benchmark_noise_floor_judge_kappa_sd": nf.per_metric_sd.get("judge_kappa", 0.0),
    }


def record_benchmark(report: BenchmarkReport) -> None:
    """Push the frozen benchmark scorecard: the drafter's ACT-gold rates (with their Wilson bounds + n),
    the judge's two error rates and injected-detection upper bounds, and the noise floor. A point-in-time
    milestone emit like `record_calibration` — the frozen baseline is an artifact, not a per-run series,
    so its gauges hold the last snapshot. Labels are the pinned (eval_set_id, config_id): both constant,
    so cardinality stays at one series per metric."""
    if not _bench_gauges:
        setup_metrics()
    labels = {"eval_set_id": report.eval_set_id, "config_id": report.config_id}
    for name, value in benchmark_gauge_values(report).items():
        _bench_gauges[name].set(value, labels)


def shutdown() -> None:
    """Flush pending metrics and tear down. MUST run before a short-lived process exits."""
    global _provider, _rate_gauge, _rate_verifiable_gauge, _unverifiable_share_gauge
    global _expert_edit_distance_gauge
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
        _provider = None
        _rate_gauge = None
        _rate_verifiable_gauge = None
        _unverifiable_share_gauge = None
        _expert_edit_distance_gauge = None
        _cal_gauges.clear()
        _bench_gauges.clear()
