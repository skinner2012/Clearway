"""The calibration snapshot: prove the two frozen artifacts assemble into the κ report + confidence
curve, and that the `OnlineEvalMetrics` projection carries every calibration scalar (and nothing else).

Skips until both artifacts exist — they are built offline by the calibration_build / confidence_build
modules; once committed this runs on every suite, guarding the numbers the dashboard gauges read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.calibration_snapshot import assemble, calibration_metrics

_FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
_CALIBRATION = _FIXTURES / "calibration_set.json"
_CONFIDENCE = _FIXTURES / "confidence_calibration.json"

pytestmark = pytest.mark.skipif(
    not (_CALIBRATION.exists() and _CONFIDENCE.exists()),
    reason="calibration artifacts not built yet — run the calibration_build / confidence_build modules",
)

_AT = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _cal() -> dict[str, Any]:
    return json.loads(_CALIBRATION.read_text())


def _conf() -> dict[str, Any]:
    return json.loads(_CONFIDENCE.read_text())


def test_assemble_reproduces_the_frozen_trust_gate_and_curve() -> None:
    """The snapshot replays offline to the same κ (the trust gate) and the same single over-confident
    bin — the two numbers the whole milestone turns on."""
    report, curve = assemble(created_at=_AT, calibration=_cal(), confidence=_conf())
    assert report.judge_kappa == pytest.approx(0.7909, abs=1e-4)
    assert report.judge_trusted is True  # κ 0.79 clears the pre-committed 0.6 bar
    assert report.kappa_threshold == 0.6
    assert report.n == 43  # the balanced set the κ gate is computed over
    # The curve is degenerate by design: one populated bin in [0.8, 1.0], never a low-confidence bin.
    (only_bin,) = curve.bins
    assert (only_bin.lower, only_bin.upper, only_bin.n, only_bin.correct_n) == (0.8, 1.0, 30, 17)
    assert curve.ece == pytest.approx(0.3917, abs=1e-4)
    assert curve.overconfidence_gap == pytest.approx(0.3917, abs=1e-4)


def test_report_owns_the_curve_the_metrics_never_copy_it() -> None:
    """The curve lives on the report; the OnlineEvalMetrics projection has no field to copy it into."""
    report, curve = assemble(created_at=_AT, calibration=_cal(), confidence=_conf())
    assert report.confidence_bins  # the curve's only home
    assert not hasattr(calibration_metrics(report, curve), "confidence_bins")


def test_projection_carries_every_calibration_scalar() -> None:
    report, curve = assemble(created_at=_AT, calibration=_cal(), confidence=_conf())
    m = calibration_metrics(report, curve)
    assert m.judge_kappa == pytest.approx(0.7909, abs=1e-4)
    assert m.judge_agreement_rate == pytest.approx(0.8605, abs=1e-4)
    assert m.judge_gold_n == 43
    assert m.judge_trusted is True
    assert (m.judgment_correct_total, m.judgment_items_total) == (15, 27)
    assert m.judgment_correctness_rate == pytest.approx(15 / 27)
    assert m.expected_calibration_error == pytest.approx(0.3917, abs=1e-4)
    assert m.overconfidence_gap == pytest.approx(0.3917, abs=1e-4)


def test_projection_leaves_forward_path_fields_at_defaults() -> None:
    """A calibration-only carrier: the M0–M3 rate fields are untouched defaults, so the emit that reads
    it can push the judge/calibration series without disturbing the citation-hallucination gauges."""
    report, curve = assemble(created_at=_AT, calibration=_cal(), confidence=_conf())
    m = calibration_metrics(report, curve)
    assert m.citation_hallucination_rate == 0.0
    assert m.unverifiable_share == 0.0
    assert m.expert_edit_distance == 0.0
    assert m.hallucinations_total == 0
