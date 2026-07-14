"""The calibration dashboard panels and the emitted metrics cannot silently drift apart.

A Grafana panel queries a metric by NAME; rename the gauge in `metrics.py` (or fat-finger the panel
`expr`) and the panel goes blank with no error anywhere. This test pins the two together: every
calibration metric the emit publishes is referenced by a panel, and every calibration panel queries a
metric the emit actually publishes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from clearway.observability.metrics import _CAL_CURVE_METRICS, _CAL_SCALAR_METRICS

_DASHBOARD = Path(__file__).resolve().parent.parent / "stack" / "grafana" / "dashboards" / "citation_hallucination.json"

_CALIBRATION_METRICS = set(_CAL_SCALAR_METRICS) | set(_CAL_CURVE_METRICS)
# The reserved slots M2 left for the judge/calibration section, now wired to real metrics.
_CALIBRATION_PANEL_IDS = {15, 16, 19, 20, 21, 22, 23, 24}
_RESERVED_IDS = {15, 16, 103}  # the placeholders M2 committed; must still exist after wiring


def _panels() -> list[dict]:
    panels: list[dict] = json.loads(_DASHBOARD.read_text())["panels"]
    return panels


def _leading_metric(expr: str) -> str:
    """The metric name a Prometheus expr opens with (the exprs here are bare names, no functions)."""
    m = re.match(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)
    return m.group(0) if m else ""


def _exprs(panel: dict) -> list[str]:
    return [t["expr"] for t in panel.get("targets", []) if "expr" in t]


def test_reserved_placeholder_ids_are_still_present() -> None:
    ids = {p["id"] for p in _panels()}
    assert _RESERVED_IDS <= ids


def test_every_calibration_metric_is_shown_on_a_panel() -> None:
    referenced = {_leading_metric(e) for p in _panels() for e in _exprs(p)}
    missing = _CALIBRATION_METRICS - referenced
    assert not missing, f"emitted but never charted (dashboard would omit them): {sorted(missing)}"


def test_every_calibration_panel_queries_a_real_metric() -> None:
    by_id = {p["id"]: p for p in _panels()}
    for pid in _CALIBRATION_PANEL_IDS:
        panel = by_id[pid]
        for expr in _exprs(panel):
            metric = _leading_metric(expr)
            assert metric in _CALIBRATION_METRICS, f"panel {pid} queries unknown metric {metric!r}"


def test_placeholders_were_converted_to_real_panels() -> None:
    """The reserved slots were text placeholders; wiring them means they now carry Prometheus targets."""
    by_id = {p["id"]: p for p in _panels()}
    for pid in (15, 16):
        assert by_id[pid]["type"] != "text", f"panel {pid} is still a placeholder"
        assert _exprs(by_id[pid]), f"panel {pid} has no metric target"
