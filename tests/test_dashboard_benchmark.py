"""The benchmark panels and the emitted benchmark gauges cannot silently drift apart — a renamed gauge
or a fat-fingered panel `expr` blanks the panel with no error anywhere. This pins the two together:
every benchmark metric the emit publishes is charted, and every benchmark-panel target queries a metric
the emit actually publishes. The twin of `test_dashboard_calibration.py`, for the M5 scorecard section.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from clearway.observability.metrics import _BENCH_METRICS

_DASHBOARD = Path(__file__).resolve().parent.parent / "stack" / "grafana" / "dashboards" / "citation_hallucination.json"

_BENCH_ROW_ID = 104
_READING_NOTE_ID = 45  # the methodology / not-measured text panel — no metric target, by design
_HEADLINE_FP_PANEL_ID = 30


def _panels() -> list[dict]:
    return json.loads(_DASHBOARD.read_text())["panels"]


def _leading_metric(expr: str) -> str:
    """The metric name a Prometheus expr opens with (the benchmark exprs are bare names, no functions)."""
    m = re.match(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)
    return m.group(0) if m else ""


def _exprs(panel: dict) -> list[str]:
    return [t["expr"] for t in panel.get("targets", []) if "expr" in t]


def _benchmark_panels() -> list[dict]:
    return [p for p in _panels() if any(_leading_metric(e).startswith("benchmark_") for e in _exprs(p))]


def test_every_benchmark_metric_is_shown_on_a_panel() -> None:
    referenced = {_leading_metric(e) for p in _panels() for e in _exprs(p)}
    missing = set(_BENCH_METRICS) - referenced
    assert not missing, f"emitted but never charted (dashboard would omit them): {sorted(missing)}"


def test_every_benchmark_panel_queries_a_declared_metric() -> None:
    for panel in _benchmark_panels():
        for expr in _exprs(panel):
            metric = _leading_metric(expr)
            if metric.startswith("benchmark_"):
                assert metric in _BENCH_METRICS, f"panel {panel['id']} queries unknown metric {metric!r}"


def test_benchmark_row_and_reading_note_are_present() -> None:
    by_id = {p["id"]: p for p in _panels()}
    assert by_id[_BENCH_ROW_ID]["type"] == "row"
    assert by_id[_READING_NOTE_ID]["type"] == "text"  # the honest "how to read this" note ships with the numbers


def test_headline_fp_panel_charts_the_false_positive_rate() -> None:
    """The FP-rate is the scorecard's most important number — pin that its panel exists and queries it,
    so the headline can never be silently dropped from the dashboard."""
    by_id = {p["id"]: p for p in _panels()}
    assert "benchmark_drafter_false_positive_rate" in _exprs(by_id[_HEADLINE_FP_PANEL_ID])
