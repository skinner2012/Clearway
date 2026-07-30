"""The bar the paired routing comparison has to clear — fixed as arithmetic, before the floor exists.

The comparison is a one-sided exact sign test on discordant pairs at the pinned observation unit. What
is *not* settled by naming that test is how many discordant pairs, pointing which way, constitute a
result — and choosing that after seeing the pairs is how a test stops being a test. So the RULE is fixed
here, as a function of two quantities neither of which is known yet, and the stage that measures them
plugs them in.

**A result needs `b` to clear two bars, and the required `b` is the larger of them.**

1. **The statistical bar.** Given `n` realized discordant pairs, the fewest one-way wins whose one-sided
   exact p is at most α — `min{b ≤ n : sign_test_p(b, n − b) ≤ α}`. Closed form; the repo already owns
   `sign_test_p`. Below n = 5 no `b` exists at all.

2. **The floor bar.** Strictly more one-way wins than the largest a SAME-configuration pair produces
   when nothing has changed. This is the repo's existing convention for a paired floor — the noise-floor
   note reads its discordance as a `max` across run-pairs and calls anything at or below it jitter — and
   it is the reason bar 1 cannot stand alone: a judge that is not bit-reproducible scatters one-way wins
   of its own, and the cheapest passing configuration under bar 1 (five wins, no losses, p = 0.031) is a
   count the null has already been observed to reach. **"Five pairs certifies" is therefore not the
   rule.** Both bars use the same one-sided direction, because the hypothesis is directional.

**⚠️ Either bar can put the result out of reach, and that is a verdict rather than a failure.** `b` is
bounded by `n`, so a required count above the realized `n` cannot be met however the pairs fall — and
the floor bar, unlike the statistical one, is not chosen with `n` in view. `smallest_attainable_n` takes
the floor for exactly this reason: at a floor of 6 the statistical bar first admits a result at n = 5
and the combined rule not until n = 7. Below that the comparison is **uncertifiable at this n** — a
finding to record, never a reason to move α, drop the one-sided direction, or re-cut the unit — and it
must not be reported as a bar the evidence missed, which is a different pre-committed outcome.

Pure arithmetic — no model, no network, no artifact. The two inputs are measured elsewhere: `n` and `b`
come from the realized comparison, `null_wins` from the same-configuration repeat passes at the same
unit, taken after both collapses in their pinned order (majority across passes per finding, then
flag-if-any within the case). A floor counted per finding cannot govern a test scored per case.
"""

from __future__ import annotations

from dataclasses import dataclass

from clearway.eval.drafter_kappa import sign_test_p
from clearway.eval.judge_observation_unit import OBSERVATION_UNIT

ALPHA = 0.05

THRESHOLD_RULE = (
    "Pre-registered as arithmetic before the noise floor was measured, so no realized number could "
    "choose it. The paired routing comparison is a ONE-SIDED exact sign test on discordant pairs at the "
    f"pinned observation unit (the {OBSERVATION_UNIT}), alpha = 0.05, taken after both collapses in "
    "their pinned order. Let n be the realized discordant pairs and b the wins pointing the "
    "pre-registered way. A result requires b >= max(STATISTICAL BAR, FLOOR BAR + 1), where the "
    "STATISTICAL BAR is min{b <= n : sign_test_p(b, n - b) <= alpha} and the FLOOR BAR is the largest "
    "one-way win count any same-configuration pass-pair produces at the same unit when nothing has "
    "changed. Two bars and not one, because the judge is not bit-reproducible: at n = 5 the statistical "
    "bar alone is satisfied by five wins and no losses (p = 0.031), and the null has been observed to "
    "produce five one-way wins on its own, so that bar would certify jitter. The max across pass-pairs "
    "is used rather than the mean, matching the paired convention the noise floor already states — a "
    "change at or below the same-config discordance is jitter, not progress. Because b cannot exceed n, "
    "EITHER bar can sit above the realized n and put a result out of reach: below the smallest n at "
    "which both bars can be met — which is NOT the smallest n at which b clears alpha, since the floor "
    "bar is fixed without reference to n — the comparison is UNCERTIFIABLE at that n. That is a finding "
    "to record, and it is a different outcome from a bar the evidence missed; neither is a reason to "
    "loosen alpha, drop the one-sided direction, or re-cut the unit."
)


def minimum_wins_at(discordant: int, alpha: float = ALPHA) -> int | None:
    """The statistical bar: the fewest one-way wins clearing `alpha` at `discordant` pairs, or None.

    None means no split of this many pairs can clear alpha — the test is unattainable at that n, which
    is a property of the count and not of the effect.
    """
    for wins in range(discordant + 1):
        if sign_test_p(wins, discordant - wins) <= alpha:
            return wins
    return None


def smallest_attainable_n(*, null_wins: int, alpha: float = ALPHA) -> int:
    """The fewest discordant pairs at which any result is possible — the all-one-way case.

    ⚠️ `null_wins` is required, because BOTH bars gate attainability and the statistical one alone gives
    the wrong answer. `b` cannot exceed `n`, so a floor bar above `n` is unreachable however the pairs
    fall: at `null_wins = 6` the statistical bar first admits a result at n = 5, and the combined rule
    does not until n = 7. Defaulting this to 0 would answer a question nobody asks — the floor exists
    precisely because the statistical bar alone certifies jitter.
    """
    pairs = 0
    while True:
        statistical = minimum_wins_at(pairs, alpha)
        if statistical is not None and max(statistical, null_wins + 1) <= pairs:
            return pairs
        pairs += 1


@dataclass(frozen=True)
class Threshold:
    """The bar for one realized comparison, with both halves kept visible.

    `required_wins` is None when no result is reachable at this `discordant` count — either because no
    split of them clears alpha, or because the bar the two halves produce is larger than `n` and `b`
    cannot exceed `n`. `binding_bar` names which half decided, so a report can say whether a result was
    limited by the evidence, by the judge's own jitter, or by the count itself, rather than leaving that
    to be inferred from two numbers. **`statistical_bar` and `floor_bar` are reported even when
    `required_wins` is None**, because "the bar was 7 and only 6 pairs existed" is the finding.
    """

    discordant: int
    null_wins: int
    statistical_bar: int | None
    floor_bar: int
    required_wins: int | None
    binding_bar: str
    alpha: float

    def clears(self, wins: int) -> bool:
        """Does an observed one-way win count constitute a result under the pre-registered rule?"""
        return self.required_wins is not None and wins >= self.required_wins


def threshold(discordant: int, *, null_wins: int, alpha: float = ALPHA) -> Threshold:
    """The pre-registered bar, given the realized discordant count and the measured null's own wins.

    `null_wins` is the largest one-way win count a same-configuration pass-pair produced at the pinned
    unit. It is required rather than defaulted: a threshold computed without it is bar 1 alone, which is
    the bar this rule exists to say is insufficient, and a default of 0 would look like a measurement.
    """
    if discordant < 0:
        raise ValueError("a discordant count is not negative")
    if null_wins < 0:
        raise ValueError("a null win count is not negative")
    statistical = minimum_wins_at(discordant, alpha)
    floor = null_wins + 1
    required = None if statistical is None else max(statistical, floor)
    # ⚠️ `b` cannot exceed `n`. A bar above the realized discordant count is unreachable however the
    # pairs fall, so it is reported as UNATTAINABLE rather than as a bar that was missed: "required 7,
    # observed 6" reads as an effect that failed, and "uncertifiable at this n" is the honest verdict —
    # a different pre-committed outcome. The statistical bar can never trip this (it is chosen from
    # `range(discordant + 1)`); the floor bar can, and under a measured floor it is the common case at
    # small n.
    if required is not None and required > discordant:
        required = None
    if required is None and statistical is None:
        binding = "unattainable — no split of this many discordant pairs clears alpha"
    elif required is None:
        binding = "unattainable — the floor bar exceeds the discordant pairs available at this n"
    elif statistical is not None and floor > statistical:
        binding = "floor — the judge's own jitter, not the evidence, sets the bar"
    elif statistical is not None and floor < statistical:
        binding = "statistical — alpha at this discordant count sets the bar"
    else:
        binding = "both — the two bars coincide"
    return Threshold(
        discordant=discordant,
        null_wins=null_wins,
        statistical_bar=statistical,
        floor_bar=floor,
        required_wins=required,
        binding_bar=binding,
        alpha=alpha,
    )
