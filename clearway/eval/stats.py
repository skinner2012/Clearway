"""The deterministic scoring primitives every acceptance number rests on — no LLM, no network.

Two things live here, kept together because the whole benchmark is built from them:

- **The Wilson score interval.** Every headline rate ships as `(value, n, CI)`. The interval is the
  *asymmetric* Wilson score interval, never a symmetric `p ± z·se`: near 0 or 1 the normal
  approximation spills past `[0, 1]` and badly understates the true bound, exactly where a
  cry-wolf / recall rate sits. Wilson is a closed form, so it is hand-rolled — no scipy dependency
  to pin. It does NOT undo the deeper problem that the cases cluster in a handful of rules; that is
  what `effective_n` on `MetricCI` records, and the caller sets it.

- **The four-value → binary conformance collapse.** ACT's ground truth is binary (does the content
  fail the rule or not?), while Clearway drafts one of four verdicts. `FLAGS` = the two that raise
  an alarm, `CLEAN` = the two that don't. `partially_supports` sits in `FLAGS` by design: on clean
  content it *is* crying wolf; on a real problem it did catch that something is off. The one knob,
  `partial_flags`, exists so the report can show the sensitivity of every number to scoring
  `partially_supports` the other way — the collapse is a judgement call, so its cost is measured,
  not hidden.

Kept pure so the scorecard replays from a frozen artifact, never re-derived by a non-deterministic
model — the same discipline the κ replay follows.
"""

from __future__ import annotations

from math import sqrt

from clearway.schemas.models import Conformance, MetricCI

# 95% two-sided normal quantile — the CI level every headline rate is quoted at.
Z_95 = 1.959963984540054

# The binary collapse of Clearway's four-value verdict onto ACT's pass/fail axis. `partially_supports`
# raises an alarm (∈ FLAGS); `not_applicable` is an abstention that does not (∈ CLEAN) — but the
# scorer still surfaces the NA count separately, never folding it silently into "clean".
FLAGS: frozenset[Conformance] = frozenset({Conformance.DOES_NOT_SUPPORT, Conformance.PARTIALLY_SUPPORTS})
CLEAN: frozenset[Conformance] = frozenset({Conformance.SUPPORTS, Conformance.NOT_APPLICABLE})


def _collapse_rule_text() -> str:
    """The human-readable collapse rule, generated FROM the sets so the audit string can never drift
    from the code that actually scores. Matches the `conformance_collapse_rule` scorecard field."""
    flags = ", ".join(sorted(c.value for c in FLAGS))
    clean = ", ".join(sorted(c.value for c in CLEAN))
    return f"FLAGS={{{flags}}}; CLEAN={{{clean}}}"


COLLAPSE_RULE: str = _collapse_rule_text()


def is_flag(conformance: Conformance, *, partial_flags: bool = True) -> bool:
    """Does this verdict raise an alarm under the binary collapse?

    `partial_flags=True` (the primary rule) counts `partially_supports` as a flag. `partial_flags=False`
    is the sensitivity variant — score `partially_supports` as clean instead — so the report can state
    how much each rate moves under the other reading of that one ambiguous verdict.
    """
    if conformance is Conformance.PARTIALLY_SUPPORTS:
        return partial_flags
    return conformance in FLAGS


def wilson_interval(k: int, n: int, *, z: float = Z_95) -> tuple[float, float]:
    """The asymmetric Wilson score interval for `k` successes out of `n`, clamped to `[0, 1]`.

    center = (p̂ + z²/2n) / (1 + z²/n);  half = z/(1 + z²/n) · √( p̂(1−p̂)/n + z²/4n² ).
    Asymmetric and tighter near 0/1 than a normal `p ± z·se`, which is why it — not the Wald interval —
    is the contract for every rate. Raises on `n == 0`: an interval over no observations is undefined,
    and fabricating `(0, 1)` would read as a real (maximally-wide) measurement rather than "no data".
    """
    if n <= 0:
        raise ValueError("wilson_interval needs at least one observation (n >= 1)")
    if not (0 <= k <= n):
        raise ValueError(f"successes {k} out of range for n={n}")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    # The point estimate always lies inside the Wilson interval; snap the bounds to bracket it so
    # floating-point rounding at the k=0 / k=n boundaries can't leave it a hair outside (which would
    # otherwise report ci_high=0.9999… on a 100%-clean stratum instead of a clean 1.0).
    return (min(low, p), max(high, p))


def metric_ci(k: int, n: int, *, effective_n: int | None = None, z: float = Z_95) -> MetricCI:
    """Assemble a `(value, n, Wilson CI)` triple — the standard shape every headline rate carries.

    `value` is the raw rate `k/n`; the interval is Wilson. `effective_n` (≈ the rule count) is passed
    straight through: when set it flags that the iid Wilson bound assumes an independence the clustered
    data lacks, and is the honest precision to read instead of `n`. Raises on `n == 0` via `wilson_interval`.
    """
    low, high = wilson_interval(k, n, z=z)
    return MetricCI(value=k / n, n=n, ci_low=low, ci_high=high, effective_n=effective_n)


def metric_ci_or_empty(k: int, n: int, *, effective_n: int | None = None) -> MetricCI:
    """`metric_ci` for a real stratum; a transparent empty triple (value 0, n 0, CI [0, 1]) when the
    stratum has no cases. n=0 is visible on the metric, so an absent stratum reads as 'no data', not a
    measured 0 — the same honesty as raising, but total, so a scorer never crashes on an empty subset."""
    if n == 0:
        return MetricCI(value=0.0, n=0, ci_low=0.0, ci_high=1.0, effective_n=0)
    return metric_ci(k, n, effective_n=effective_n)
