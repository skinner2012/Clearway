"""The pre-registered bar for the paired routing comparison.

The sign-test tail is re-derived here by **enumerating every outcome of a fair coin**, not by importing
the repo's closed form — a test that calls the same function cannot tell a wrong formula from a right
one. The floor half is exercised against the null the frozen observation-unit record actually measured,
read out of the artifact rather than quoted, so the claim "five pairs is not a safe bar" rests on a file.
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import pytest

from clearway.eval.judge_threshold import (
    ALPHA,
    THRESHOLD_RULE,
    minimum_wins_at,
    smallest_attainable_n,
    threshold,
)

_OBSERVATION_UNIT = Path(__file__).resolve().parent.parent / "benchmark" / "reports" / "judge_observation_unit.json"


def _one_sided_tail(wins: int, losses: int) -> float:
    """P(at least `wins` heads in `wins + losses` fair flips), by enumeration.

    Brute force on purpose: at these n the whole outcome space is small, and enumerating it is the one
    statement of the sign test that shares no arithmetic with the implementation under test.
    """
    pairs = wins + losses
    if pairs == 0:
        return 1.0
    outcomes = list(product((0, 1), repeat=pairs))
    return sum(1 for o in outcomes if sum(o) >= wins) / len(outcomes)


def test_the_statistical_bar_is_the_exact_one_sided_tail() -> None:
    for discordant in range(0, 13):
        bar = minimum_wins_at(discordant)
        if bar is None:
            assert all(_one_sided_tail(w, discordant - w) > ALPHA for w in range(discordant + 1))
            continue
        assert _one_sided_tail(bar, discordant - bar) <= ALPHA
        assert all(_one_sided_tail(w, discordant - w) > ALPHA for w in range(bar))


def test_no_result_is_available_below_five_discordant_pairs() -> None:
    """A property of the count, never of the effect — and the reason an n this small is a finding."""
    assert smallest_attainable_n(null_wins=0) == 5
    assert all(minimum_wins_at(n) is None for n in range(5))
    assert minimum_wins_at(5) == 5
    assert _one_sided_tail(5, 0) == pytest.approx(0.03125)


def test_the_floor_bar_also_gates_attainability_and_the_statistical_one_cannot_see_it() -> None:
    """`b` is bounded by `n`, so a floor above `n` is unreachable however the pairs fall.

    The statistical bar is chosen from `range(n + 1)` and so can never exceed `n`; the floor bar is
    fixed from the same-configuration passes with no reference to `n` at all, and under a measured floor
    it sits above the cheapest statistically-attainable counts. Reporting those as a bar the evidence
    missed would file an uncertifiable comparison as a failed effect — two different pre-committed
    verdicts.
    """
    assert smallest_attainable_n(null_wins=6) == 7
    for pairs in (5, 6):
        bar = threshold(pairs, null_wins=6)
        assert bar.statistical_bar is not None, "the statistical bar alone admits a result at this n"
        assert bar.required_wins is None, "a bar above n is unattainable, not merely unmet"
        assert "floor bar exceeds" in bar.binding_bar
        assert not bar.clears(pairs), "a clean sweep of every pair still cannot reach a bar above n"
        assert bar.floor_bar == 7, "both halves stay visible — 'the bar was 7 and only n existed'"


def test_the_two_reasons_a_result_is_unreachable_are_reported_apart() -> None:
    """Too few pairs to clear alpha, and a floor above the pairs there are, are different findings."""
    assert "clears alpha" in threshold(4, null_wins=6).binding_bar
    assert "floor bar exceeds" in threshold(5, null_wins=6).binding_bar


def test_the_null_this_judge_already_produces_makes_five_wins_an_unsafe_bar() -> None:
    """The justification for the second bar, taken off the frozen record rather than restated.

    The same-configuration pass-pairs are a null by construction — nothing changed between them — so the
    largest one-way win count they produce is jitter with a number on it. If that number reaches the
    statistical bar at the cheapest attainable n, the statistical bar alone certifies noise.
    """
    directional = json.loads(_OBSERVATION_UNIT.read_text())["discordant_pairs_under_the_null"]["directional"]
    null_wins = max(max(pair["improved"], pair["regressed"]) for pair in directional)
    assert null_wins >= minimum_wins_at(smallest_attainable_n(null_wins=0)), (
        "the null no longer reaches the cheapest certifying win count — re-read whether the second bar "
        "is still justified rather than deleting it"
    )
    cheapest = smallest_attainable_n(null_wins=0)
    bar = threshold(cheapest, null_wins=null_wins)
    assert bar.statistical_bar == 5, "the statistical bar alone would certify five wins here"
    assert bar.floor_bar == null_wins + 1 > 5, "the measured null already reaches that count"
    # And the consequence the first bar cannot express: at the count where alpha is cheapest to clear,
    # the measured floor is not merely higher — it is out of reach, because b cannot exceed n.
    assert bar.required_wins is None
    assert not bar.clears(cheapest)
    assert threshold(smallest_attainable_n(null_wins=null_wins), null_wins=null_wins).required_wins == null_wins + 1


def test_the_binding_bar_is_named_so_a_report_can_say_which_limited_it() -> None:
    quiet_null = threshold(20, null_wins=2)
    assert quiet_null.required_wins == quiet_null.statistical_bar
    assert quiet_null.binding_bar.startswith("statistical")

    unattainable = threshold(3, null_wins=1)
    assert (unattainable.statistical_bar, unattainable.required_wins) == (None, None)
    assert unattainable.binding_bar.startswith("unattainable")
    assert not unattainable.clears(3)

    coincide = threshold(5, null_wins=4)
    assert (coincide.statistical_bar, coincide.floor_bar, coincide.required_wins) == (5, 5, 5)
    assert coincide.binding_bar.startswith("both")


def test_the_measured_null_is_required_rather_than_defaulted() -> None:
    """A default would make bar 1 alone look like the whole rule — the exact reading this forbids."""
    with pytest.raises(TypeError):
        threshold(9)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        threshold(9, null_wins=-1)


def test_the_rule_is_pre_registered_as_text_beside_the_arithmetic() -> None:
    assert "ONE-SIDED" in THRESHOLD_RULE and "alpha = 0.05" in THRESHOLD_RULE
    assert "UNCERTIFIABLE" in THRESHOLD_RULE
    assert "case" in THRESHOLD_RULE  # the pinned unit is named, not implied
