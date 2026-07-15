"""The deterministic scoring primitives: the asymmetric Wilson interval and the four-value → binary
conformance collapse. Pure, so these assert exact math against hand-computed reference values — the
whole scorecard rests on them, so a silent drift here would corrupt every headline number.
"""

from __future__ import annotations

import pytest

from clearway.eval.stats import (
    CLEAN,
    COLLAPSE_RULE,
    FLAGS,
    Z_95,
    is_flag,
    metric_ci,
    wilson_interval,
)
from clearway.schemas.models import Conformance

# ---- Wilson interval -------------------------------------------------------


def test_wilson_zero_successes_pins_low_at_zero() -> None:
    """0/10: the point estimate is 0, so the lower bound is 0 and only the upper bound carries width —
    the asymmetry a symmetric ± cannot express (it would dip below 0)."""
    low, high = wilson_interval(0, 10)
    assert low == pytest.approx(0.0, abs=1e-9)
    assert high == pytest.approx(0.2775, abs=1e-3)


def test_wilson_all_successes_is_mirror_of_zero() -> None:
    """10/10 mirrors 0/10: high pins at 1.0, low is 1 − (the 0/10 upper bound)."""
    low, high = wilson_interval(10, 10)
    assert high == pytest.approx(1.0, abs=1e-9)
    assert low == pytest.approx(1.0 - 0.2775, abs=1e-3)


def test_wilson_half_is_symmetric_about_point_estimate() -> None:
    """5/10: centred on 0.5 with the textbook 95% bounds (0.2366, 0.7634)."""
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-3)
    assert high == pytest.approx(0.7634, abs=1e-3)
    assert (low + high) / 2 == pytest.approx(0.5, abs=1e-9)


def test_wilson_bounds_always_inside_unit_interval() -> None:
    """Across the whole grid the clamp holds and the interval brackets the point estimate — the
    property that makes it safe to quote a rate near 0 or 1 without spilling past [0, 1]."""
    for n in (1, 3, 20, 53):
        for k in range(n + 1):
            low, high = wilson_interval(k, n)
            assert 0.0 <= low <= high <= 1.0
            assert low <= k / n <= high


def test_wilson_tighter_at_larger_n() -> None:
    """More observations → a narrower interval for the same rate (the CI's whole reason to exist)."""
    _, high_small = wilson_interval(0, 10)
    _, high_large = wilson_interval(0, 50)
    assert high_large < high_small


def test_wilson_rejects_empty_and_out_of_range() -> None:
    with pytest.raises(ValueError):
        wilson_interval(0, 0)  # no observations → undefined, must raise not fabricate (0, 1)
    with pytest.raises(ValueError):
        wilson_interval(4, 3)  # more successes than trials


def test_z_95_is_the_two_sided_quantile() -> None:
    assert Z_95 == pytest.approx(1.96, abs=1e-3)


# ---- metric_ci -------------------------------------------------------------


def test_metric_ci_carries_value_n_and_wilson_bounds() -> None:
    ci = metric_ci(2, 30, effective_n=5)
    assert ci.value == pytest.approx(2 / 30)
    assert ci.n == 30
    assert ci.effective_n == 5
    assert (ci.ci_low, ci.ci_high) == pytest.approx(wilson_interval(2, 30))
    assert ci.ci_method == "wilson"


def test_metric_ci_effective_n_defaults_none() -> None:
    ci = metric_ci(10, 20)
    assert ci.effective_n is None


def test_metric_ci_propagates_empty_stratum_error() -> None:
    with pytest.raises(ValueError):
        metric_ci(0, 0)


# ---- conformance collapse --------------------------------------------------


def test_flags_and_clean_partition_all_four_verdicts() -> None:
    """Every verdict lands in exactly one bucket — no verdict is unscored, none double-counted."""
    assert FLAGS | CLEAN == set(Conformance)
    assert FLAGS & CLEAN == set()


def test_is_flag_primary_rule_counts_partial_as_alarm() -> None:
    assert is_flag(Conformance.DOES_NOT_SUPPORT) is True
    assert is_flag(Conformance.PARTIALLY_SUPPORTS) is True
    assert is_flag(Conformance.SUPPORTS) is False
    assert is_flag(Conformance.NOT_APPLICABLE) is False


def test_is_flag_sensitivity_variant_moves_only_partial() -> None:
    """The one knob flips ONLY partially_supports; the other three verdicts are unambiguous and stay put."""
    assert is_flag(Conformance.PARTIALLY_SUPPORTS, partial_flags=False) is False
    assert is_flag(Conformance.DOES_NOT_SUPPORT, partial_flags=False) is True
    assert is_flag(Conformance.SUPPORTS, partial_flags=False) is False
    assert is_flag(Conformance.NOT_APPLICABLE, partial_flags=False) is False


def test_collapse_rule_text_is_generated_from_the_sets() -> None:
    """The audit string is derived from FLAGS/CLEAN, so it can never drift from the code that scores."""
    assert COLLAPSE_RULE == ("FLAGS={does_not_support, partially_supports}; CLEAN={not_applicable, supports}")
    for verdict in Conformance:
        assert verdict.value in COLLAPSE_RULE
