"""Confidence-calibration math — pure, offline, fully deterministic.

Hand-computed bins (half-open with a closed top), ECE as a count-weighted gap, the signed
over-confidence direction, and the degenerate all-high case the earlier reads predict: every draft in
one bin, so the curve is a single point whose gap is the whole story.
"""

from __future__ import annotations

import pytest

from clearway.eval.confidence import (
    ConfidencePoint,
    bin_points,
    expected_calibration_error,
    overconfidence_gap,
)


def _pt(confidence: float, correct: bool) -> ConfidencePoint:
    return ConfidencePoint(confidence=confidence, correct=correct)


def test_points_group_into_half_open_bins_with_a_closed_top() -> None:
    # 0.1 → [0,0.2); 0.6 → [0.6,0.8) (interior edge opens the upper bin); 1.0 → closed top [0.8,1.0].
    curve = bin_points([_pt(0.1, True), _pt(0.6, False), _pt(1.0, True)])
    assert [(b.lower, b.upper, b.n) for b in curve] == [(0.0, 0.2, 1), (0.6, 0.8, 1), (0.8, 1.0, 1)]


def test_only_populated_bins_are_emitted_in_ascending_order() -> None:
    curve = bin_points([_pt(0.95, True), _pt(0.9, False), _pt(0.85, True)])
    assert len(curve) == 1  # all three land in the single top bin — the degenerate shape
    (b,) = curve
    assert (b.lower, b.upper, b.n, b.correct_n) == (0.8, 1.0, 3, 2)
    assert b.correctness_rate == pytest.approx(2 / 3)
    assert b.mean_confidence == pytest.approx(0.9)


def test_bin_counts_and_rates_are_exact() -> None:
    curve = bin_points([_pt(0.3, True), _pt(0.3, False), _pt(0.3, False), _pt(0.7, True)])
    low, high = curve
    assert (low.lower, low.n, low.correct_n) == (0.2, 3, 1)
    assert low.correctness_rate == pytest.approx(1 / 3)
    assert (high.lower, high.n, high.correct_n) == (0.6, 1, 1)
    assert high.correctness_rate == 1.0


def test_confidence_outside_the_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        bin_points([_pt(1.5, True)])


def test_ece_is_the_count_weighted_confidence_correctness_gap() -> None:
    # Bin A: 3 pts, mean conf 0.3, correctness 1/3 → gap |0.3-0.333| = 0.0333.
    # Bin B: 1 pt, conf 0.7, correctness 1.0     → gap |0.7-1.0|   = 0.30.
    # ECE = 3/4·0.0333 + 1/4·0.30 = 0.025 + 0.075 = 0.10.
    curve = bin_points([_pt(0.3, True), _pt(0.3, False), _pt(0.3, False), _pt(0.7, True)])
    assert expected_calibration_error(curve) == pytest.approx(0.1, abs=1e-9)


def test_ece_is_zero_only_when_confidence_equals_correctness() -> None:
    # A well-calibrated toy set: 0.0-confidence wrongs and 1.0-confidence rights.
    curve = bin_points([_pt(0.0, False), _pt(1.0, True), _pt(1.0, True)])
    assert expected_calibration_error(curve) == pytest.approx(0.0)


def test_ece_rejects_an_empty_curve_rather_than_lie_zero() -> None:
    with pytest.raises(ValueError):
        expected_calibration_error([])


def test_overconfidence_gap_is_signed() -> None:
    # mean confidence 0.9, mean correctness 0.5 → +0.4: over-confident (the predicted failure mode).
    over = [_pt(0.9, True), _pt(0.9, False), _pt(0.9, True), _pt(0.9, False)]
    assert overconfidence_gap(over) == pytest.approx(0.4)
    # Flip correctness high, confidence low → negative: under-confident.
    under = [_pt(0.1, True), _pt(0.1, True), _pt(0.1, False), _pt(0.1, True)]
    assert overconfidence_gap(under) == pytest.approx(0.1 - 0.75)


def test_overconfidence_gap_rejects_no_points() -> None:
    with pytest.raises(ValueError):
        overconfidence_gap([])
