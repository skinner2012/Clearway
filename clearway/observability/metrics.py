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

from clearway.schemas.models import EvalReport

_DEFAULT_ENDPOINT = "http://localhost:4318"
_METRIC_NAME = "citation_hallucination_rate"
_METRIC_VERIFIABLE = "citation_hallucination_rate_verifiable"
_METRIC_UNVERIFIABLE_SHARE = "unverifiable_share"
_METRIC_EXPERT_EDIT_DISTANCE = "expert_edit_distance"

_provider: MeterProvider | None = None
_rate_gauge: Gauge | None = None
_rate_verifiable_gauge: Gauge | None = None
_unverifiable_share_gauge: Gauge | None = None
_expert_edit_distance_gauge: Gauge | None = None


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
