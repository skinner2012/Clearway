"""The calibration push emits the right named series — offline, via an in-memory metric reader.

`record_calibration` normally exports over OTLP to the collector (integration-tested in
`test_observability.py` when the stack is up). Here we swap in an `InMemoryMetricReader` so the
gauge names, labels, and values are asserted WITHOUT a running stack — this is the drift guard the
dashboard depends on: if a metric is renamed, the panel that queries the old name goes blank.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from clearway.eval.calibration_snapshot import assemble, calibration_metrics
from clearway.observability import metrics
from clearway.schemas.models import OnlineEvalMetrics

_FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
_CALIBRATION = _FIXTURES / "calibration_set.json"
_CONFIDENCE = _FIXTURES / "confidence_calibration.json"

pytestmark = pytest.mark.skipif(
    not (_CALIBRATION.exists() and _CONFIDENCE.exists()),
    reason="calibration artifacts not built yet — run the calibration_build / confidence_build modules",
)

_AT = datetime(2026, 7, 13, tzinfo=timezone.utc)


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    """Point the module's calibration gauges at an in-memory reader, restoring the real ones after."""
    saved = dict(metrics._cal_gauges)
    mem = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[mem])
    meter = provider.get_meter("test.calibration")
    metrics._cal_gauges.clear()
    for name in {**metrics._CAL_SCALAR_METRICS, **metrics._CAL_CURVE_METRICS}:
        metrics._cal_gauges[name] = meter.create_gauge(name)
    try:
        yield mem
    finally:
        provider.shutdown()
        metrics._cal_gauges.clear()
        metrics._cal_gauges.update(saved)


def _emitted(mem: InMemoryMetricReader) -> dict[str, list[Any]]:
    """Collect {metric_name: [data points]} from the in-memory reader."""
    data = mem.get_metrics_data()
    out: dict[str, list[Any]] = {}
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                out[m.name] = list(m.data.data_points)
    return out


def _snapshot() -> tuple[OnlineEvalMetrics, Any]:
    cal = json.loads(_CALIBRATION.read_text())
    conf = json.loads(_CONFIDENCE.read_text())
    report, curve = assemble(created_at=_AT, calibration=cal, confidence=conf)
    return calibration_metrics(report, curve), report


def test_push_emits_every_scalar_series(reader: InMemoryMetricReader) -> None:
    m, report = _snapshot()
    metrics.record_calibration(m, report, judge_model="gpt-5.6-luna", gold_version="quality-gold@1")
    emitted = _emitted(reader)
    assert set(metrics._CAL_SCALAR_METRICS) <= set(emitted)
    (kappa_pt,) = emitted["judge_kappa"]
    assert kappa_pt.value == pytest.approx(0.7909, abs=1e-4)
    assert kappa_pt.attributes["judge_model"] == "gpt-5.6-luna"
    (trusted_pt,) = emitted["judge_trusted"]
    assert trusted_pt.value == 1.0  # κ 0.79 cleared the bar → trusted encodes as 1
    (ece_pt,) = emitted["expected_calibration_error"]
    assert ece_pt.value == pytest.approx(0.3917, abs=1e-4)


def test_push_emits_the_curve_as_labelled_bins_with_counts(reader: InMemoryMetricReader) -> None:
    m, report = _snapshot()
    metrics.record_calibration(m, report, judge_model="gpt-5.6-luna", gold_version="quality-gold@1")
    emitted = _emitted(reader)
    # The degenerate curve: a single bin, so a single labelled point per curve metric.
    (corr,) = emitted["confidence_correctness"]
    assert corr.attributes["bin"] == "0.8-1.0"
    assert corr.value == pytest.approx(0.5667, abs=1e-4)
    (count,) = emitted["confidence_bin_n"]
    assert count.value == 30  # the count ships beside the rate so the flat curve cannot lie


def test_push_fails_loudly_on_an_unset_scalar(reader: InMemoryMetricReader) -> None:
    """A calibration carrier must set every scalar; a None means mis-assembly, not a real 0 to publish."""
    _, report = _snapshot()
    incomplete = OnlineEvalMetrics(citation_hallucination_rate=0.0)  # judge_kappa etc. left None
    with pytest.raises(ValueError, match="mis-assembled"):
        metrics.record_calibration(incomplete, report, judge_model="x", gold_version="y")
