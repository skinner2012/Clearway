"""Observability: emit the M0 trust metric via OTel → Collector → Prometheus (ARCHITECTURE §4.5)."""

from clearway.observability.metrics import record_eval_report, record_rate, setup_metrics, shutdown

__all__ = ["setup_metrics", "record_rate", "record_eval_report", "shutdown"]
