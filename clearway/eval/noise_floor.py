"""The noise floor — run-to-run variance over repeat runs → the minimum detectable improvement.

The benchmark is the yardstick for every later change, so its smallest meaningful gradation must be
measured, not assumed: an LLM is not fully deterministic even at temperature 0, and a change smaller
than the run-to-run jitter is noise, not progress. This module replays N frozen run artifacts (the
non-deterministic models were called once each, in the builder) into a `NoiseFloor`. Pure — no LLM,
no network.

Two honesty refinements the spec demands are built in:
  - **Which source dominates.** At temperature 0 the run-to-run jitter may be near zero, leaving the
    finite-sample *binomial* noise as the real floor. So the dominant source is reported, not assumed:
    the larger of the observed cross-run SD and the binomial SD of the metric driving the floor.
  - **The paired floor is separate from the absolute CI.** The benchmark's primary change signal is a
    PAIRED comparison on the same cases (McNemar), and the two harms stay separate: TP→miss flips and
    TN→FP flips are counted PER STRATUM, never pooled (pooling lets a fix in one cancel a regression in
    the other). A real A/B change must exceed this same-config discordance, not zero.
"""

from __future__ import annotations

import statistics
from math import sqrt
from typing import Any

from clearway.eval.benchmark import build_report
from clearway.eval.stats import is_flag
from clearway.schemas.models import Conformance, NoiseFloor

# The drafter headline metrics the minimum detectable improvement is set on — recall and the
# cry-wolf rate. The judge metrics are tracked for variance too, but the MDI is the drafter's.
_HEADLINE = ("recall", "false_positive_rate")


def run_headline_metrics(run: dict[str, Any]) -> dict[str, float]:
    """The scalar metrics of one run, via the same scorer the report uses — so the variance is over the
    exact headline numbers, never a re-derivation that could drift from them."""
    sc = build_report(run).scorecard
    return {
        "recall": sc.drafter.recall.value,
        "false_positive_rate": sc.drafter.false_positive_rate.value,
        "judge_kappa": sc.judge.kappa,
        "judge_miss_rate": sc.judge.miss_rate.value,
    }


def case_outcomes(run: dict[str, Any]) -> dict[str, tuple[str, bool]]:
    """Per-case `(expected, flagged)` — flag-if-any over the case's drafts, honest-misses flagged=False.
    The unit the paired McNemar discordance is counted on."""
    outcomes: dict[str, tuple[str, bool]] = {}
    for c in run["cases"]:
        flagged = any(is_flag(Conformance(d["conformance"])) for d in c["drafts"])
        outcomes[c["act_testcase_id"]] = (c["expected"], flagged)
    for m in run["honest_misses"]:  # required — a silent [] default would skew the paired discordance
        outcomes[m["act_testcase_id"]] = (m["expected"], False)
    return outcomes


def stddev(values: list[float]) -> float:
    """Sample standard deviation; 0.0 for a single value (an SD needs at least two)."""
    return statistics.stdev(values) if len(values) > 1 else 0.0


def binomial_sd(p: float, n: int) -> float:
    """The finite-sample SD of a rate — the floor when run-to-run model jitter is near zero."""
    return sqrt(p * (1 - p) / n) if n else 0.0


def _stratum_n(run: dict[str, Any], expected: str) -> int:
    return sum(1 for c in (run["cases"] + run["honest_misses"]) if c["expected"] == expected)


def _discordance(runs: list[dict[str, Any]], expected: str) -> list[int]:
    """For every pair of runs, the number of cases IN THIS STRATUM whose flag verdict differs — the
    same-config jitter a real change must exceed. Per stratum, never pooled."""
    outs = [case_outcomes(r) for r in runs]
    ids = [cid for cid, (e, _) in outs[0].items() if e == expected]
    counts: list[int] = []
    for a in range(len(outs)):
        for b in range(a + 1, len(outs)):
            counts.append(sum(1 for cid in ids if outs[a][cid][1] != outs[b][cid][1]))
    return counts


def _paired_note(runs: list[dict[str, Any]]) -> str:
    tp, tn = _discordance(runs, "failed"), _discordance(runs, "passed")
    pairs = len(tp)
    return (
        f"Same-config paired discordance across {pairs} run-pair(s) — the floor a real A/B change must "
        f"EXCEED, per stratum, never pooled: TP→miss flips max {max(tp, default=0)}, TN→FP flips max "
        f"{max(tn, default=0)}. A change whose discordance is at or below this is jitter, not progress."
    )


def build_noise_floor(runs: list[dict[str, Any]]) -> NoiseFloor:
    """Variance over the repeat runs → `NoiseFloor`. The MDI is the noisier of the two drafter headline
    metrics' cross-run SD; the dominant source is whichever is larger, the observed jitter or the
    binomial floor of that metric. Raises on fewer than two runs — variance is undefined."""
    if len(runs) < 2:
        raise ValueError("the noise floor needs at least two runs to have a variance")
    metrics = [run_headline_metrics(r) for r in runs]
    per_sd = {k: stddev([m[k] for m in metrics]) for k in metrics[0]}

    driver = max(_HEADLINE, key=lambda k: per_sd[k])  # the headline metric setting the floor
    mdi = per_sd[driver]
    mean_p = statistics.fmean(m[driver] for m in metrics)
    n = _stratum_n(runs[0], "failed" if driver == "recall" else "passed")
    observed, binom = per_sd[driver], binomial_sd(mean_p, n)
    dominant = "binomial-sampling" if binom >= observed else "llm-jitter"

    return NoiseFloor(
        runs=len(runs),
        per_metric_sd=per_sd,
        min_detectable_improvement=mdi,
        dominant_source=dominant,
        paired_mdi_note=_paired_note(runs),
    )
