"""Observability: emit trust metrics + run/finding/step traces via OTel → Collector → Prometheus
(metrics) and the collector's traces pipeline (spans) — ARCHITECTURE §4.5."""

from clearway.observability.metrics import record_eval_report, record_rate, setup_metrics, shutdown
from clearway.observability.operational import (
    record_llm_call,
    record_step,
    setup_operational_metrics,
    shutdown_operational_metrics,
)
from clearway.observability.tracing import setup_tracing, shutdown_tracing

__all__ = [
    "record_eval_report",
    "record_llm_call",
    "record_rate",
    "record_step",
    "setup_metrics",
    "setup_operational_metrics",
    "setup_tracing",
    "shutdown",
    "shutdown_operational_metrics",
    "shutdown_tracing",
]
