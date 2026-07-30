"""The benchmark snapshot projects the frozen scorecard onto the dashboard gauges. Two things must
hold or the dashboard silently lies: the projection covers EXACTLY the declared metric set (no gauge
left unset, no value with no gauge), and it refuses a scorecard that has no noise floor (a single run
passed in by mistake). Tested against the real committed baseline — no OTLP collector involved.
"""

from __future__ import annotations

import pytest

from clearway.eval.acceptance_snapshot import load_report
from clearway.eval.judge_score import CONFUSION_UNIT_CASE, CONFUSION_UNIT_FINDING
from clearway.observability.metrics import (
    _BENCH_METRICS,
    JUDGE_CONFUSION_UNIT,
    RESERVED_PER_CASE_BENCH_METRICS,
    benchmark_gauge_values,
)


def test_load_report_loads_the_frozen_baseline() -> None:
    report = load_report()
    assert report.eval_set_id == "act-acceptance@1"
    assert len(report.run_ids) == 3  # the frozen baseline aggregates the whole sweep
    assert report.scorecard.noise_floor is not None


def test_gauge_values_cover_exactly_the_declared_metrics() -> None:
    """Every declared gauge gets a value and every value has a declared gauge — the emit cannot drift
    from `_BENCH_METRICS` without this failing."""
    values = benchmark_gauge_values(load_report(), judge_confusion_unit=CONFUSION_UNIT_FINDING)
    assert set(values) == set(_BENCH_METRICS)


def test_headline_numbers_match_the_frozen_scorecard() -> None:
    values = benchmark_gauge_values(load_report(), judge_confusion_unit=CONFUSION_UNIT_FINDING)
    assert values["benchmark_drafter_false_positive_rate"] == pytest.approx(0.4333, abs=1e-3)
    assert values["benchmark_drafter_recall"] == pytest.approx(0.7391, abs=1e-3)
    # the judge instability the noise floor surfaced rides along as its own series
    assert values["benchmark_noise_floor_judge_kappa_sd"] > 0.1


def test_gauge_values_require_the_noise_floor() -> None:
    """A scorecard with no noise floor is a single run, not the frozen baseline — fail loud, don't push 0."""
    report = load_report()
    single = report.model_copy(update={"scorecard": report.scorecard.model_copy(update={"noise_floor": None})})
    with pytest.raises(ValueError, match="frozen baseline"):
        benchmark_gauge_values(single, judge_confusion_unit=CONFUSION_UNIT_FINDING)


def test_a_case_level_confusion_cannot_be_pushed_onto_the_per_finding_series() -> None:
    """The unit-free gauge name is the hazard, so the refusal is keyed to the family's declared unit.

    `JudgeConfusion` carries no unit field: a matrix tallied per case arrives here as the same shape
    with the same field names, and pushing it would re-scale three live series in place with no version
    marker and no gap in the data. The refusal names the reserved case-level series so the caller has
    somewhere to go rather than a reason to override.
    """
    assert JUDGE_CONFUSION_UNIT == CONFUSION_UNIT_FINDING
    with pytest.raises(ValueError, match="would silently redefine") as raised:
        benchmark_gauge_values(load_report(), judge_confusion_unit=CONFUSION_UNIT_CASE)
    for reserved in RESERVED_PER_CASE_BENCH_METRICS:
        assert reserved in str(raised.value)
        assert reserved not in _BENCH_METRICS  # reserved as names, never as gauges nothing feeds


def test_the_unit_has_no_default_so_a_publisher_must_declare_it() -> None:
    with pytest.raises(TypeError):
        benchmark_gauge_values(load_report())  # type: ignore[call-arg]
