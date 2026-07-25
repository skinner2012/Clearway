"""Pair frozen drafter verdict vectors case by case — the pre-registered sign tests, and run attribution.

The per-class κ scalar cannot be paired; the frozen `VerdictVector` can. This module sets one run's per-case
FLAG/CLEAN vector beside another's, keyed by `act_testcase_id`, and reads off the discordant pairs: `b` = a
case the earlier vector got wrong and the later got right (an improvement), `c` = the reverse (a regression).

**Two different questions are asked of those pairs, and they are kept apart.**

1. **`pair_verdicts` — the pre-registered hypothesis test**, against the frozen pre-change baseline. The
   one-sided exact sign test on `(b, c)` is the same `sign_test_p` the ceiling pre-registration uses —
   reused, not re-derived, so a run is measured against exactly the test that was fixed before it existed.
   **The primary endpoint is the POOLED test** across the classes the referent fix treats (`label` +
   `link-name`): the hypothesis is about referent PRESENCE, not about either class, so the estimand is the
   pooled reachable errors and the per-class tests are secondary. Both are computed; both are reported.
2. **`attribute_against_prior` — did this run give back what the run before it bought?** A later run
   carrying one further prompt change has to answer that separately, and it is NOT a hypothesis test: it
   carries no certified/failed vocabulary, because the remedy it feeds (roll the change back, or make it
   class-conditional) is a decision, not a result.

Pure — no LLM, no network, no clock. Every number is a deterministic function of the frozen vectors. ACT
gold is the oracle throughout (`gold_flag`), no judge field is read anywhere, and a case whose gold disagrees
between two vectors is a hard error, never silently scored: the whole point is that only the drafter's input
changed between them.

**Verdicts follow the pre-committed definitions, and the arithmetic self-enforces them.** A class is
`certified` only when its sign-test p clears α; `document-title` cannot reach that at any fix quality (3
reachable errors → best p = 0.125), so it lands `worked_but_uncertifiable` by construction, never by a
special case here. `failed` is no directional movement (b = 0) or regressions dominating (c ≥ b).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clearway.eval.drafter_kappa import _ALPHA, sign_test_p
from clearway.schemas.models import VerdictVector

# The classes the referent fix treats — the pool the primary endpoint runs over. `document-title` is
# measured (secondary, on mechanism) but is not in the pool: its ceiling cannot clear α, so pooling it in
# would only drag the primary endpoint it can never help.
_POOLED_AXE_RULES = ("label", "link-name")


@dataclass(frozen=True)
class ClassVerdict:
    """One fix-unit class paired run-vs-baseline: the discordant counts, the sign-test p, and the verdict.

    `improved` (b) and `regressed` (c) are the discordant pairs against ACT gold — baseline-wrong→right and
    baseline-right→wrong. `improved_ids` / `regressed_ids` name exactly which cases moved, so a reader can
    audit the wins and losses rather than trust the totals. `verdict` is one of the three pre-committed
    strings; `p_value` is the one-sided exact sign test on `(improved, regressed)`."""

    axe_rule: str
    n_paired: int
    improved: int
    regressed: int
    improved_ids: tuple[str, ...]
    regressed_ids: tuple[str, ...]
    p_value: float
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "axe_rule": self.axe_rule,
            "n_paired": self.n_paired,
            "improved": self.improved,
            "regressed": self.regressed,
            "improved_ids": list(self.improved_ids),
            "regressed_ids": list(self.regressed_ids),
            "p_value": self.p_value,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class PooledVerdict:
    """The primary endpoint: one hypothesis tested once over the pooled discordant pairs of the fixed classes.

    `thesis` is `supported` when the pooled p clears α, `not_supported` when improvements are `b ≤ 2` (the
    pre-committed failure line), and `directional_not_significant` in between — movement in the right
    direction that the gold set is too small to certify."""

    axe_rules: tuple[str, ...]
    improved: int
    regressed: int
    p_value: float
    alpha: float
    thesis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "axe_rules": list(self.axe_rules),
            "improved": self.improved,
            "regressed": self.regressed,
            "p_value": self.p_value,
            "alpha": self.alpha,
            "thesis": self.thesis,
        }


@dataclass(frozen=True)
class ClassAttribution:
    """One class compared against the PREVIOUS run rather than against the frozen baseline.

    `improved` / `regressed` are the discordant pairs prior-run → this run. `prior_gains_lost` is the
    stricter and more consequential quantity: the cases the baseline got wrong, the prior run fixed, and
    this run breaks again — the earlier fix, given back. A class can regress without losing a prior gain
    (it broke something the earlier run never fixed) and can net flat while losing one, so the two are
    reported separately and never collapsed."""

    axe_rule: str
    improved: int
    regressed: int
    improved_ids: tuple[str, ...]
    regressed_ids: tuple[str, ...]
    prior_gains_lost: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "axe_rule": self.axe_rule,
            "improved": self.improved,
            "regressed": self.regressed,
            "improved_ids": list(self.improved_ids),
            "regressed_ids": list(self.regressed_ids),
            "prior_gains_lost": list(self.prior_gains_lost),
        }


@dataclass(frozen=True)
class RunAttribution:
    """Whether this run's change consumed the previous run's fix, named to the class and the case.

    `eats_prior_run` is the decision input, not a verdict: when it is true the change is rolled back or
    made class-conditional, and the per-class `prior_gains_lost` says which class would have to be
    carved out. Deliberately carries no certified/failed string — this is an attribution check between
    two runs, not the pre-registered hypothesis test, and dressing it in the test's vocabulary would
    invite reading it as one."""

    classes: tuple[ClassAttribution, ...]
    eats_prior_run: bool
    prior_run_ids: tuple[str, ...]
    run_run_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "classes": [c.to_dict() for c in self.classes],
            "eats_prior_run": self.eats_prior_run,
            "prior_run_ids": list(self.prior_run_ids),
            "run_run_ids": list(self.run_run_ids),
        }


@dataclass(frozen=True)
class PairedThesis:
    """The full paired result: every class's discordant verdict plus the pooled primary endpoint."""

    classes: tuple[ClassVerdict, ...]
    pooled: PooledVerdict
    baseline_run_ids: tuple[str, ...]
    run_run_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "classes": [c.to_dict() for c in self.classes],
            "pooled": self.pooled.to_dict(),
            "baseline_run_ids": list(self.baseline_run_ids),
            "run_run_ids": list(self.run_run_ids),
        }


def _class_verdict(b: int, c: int, p: float, alpha: float) -> str:
    """The three pre-committed per-class strings, from the discordant counts and the sign-test p.

    `certified` requires the one-sided test to clear α; `failed` is no directional movement (b = 0) or
    regressions dominating (c ≥ b); everything else is `worked_but_uncertifiable` — the right direction the
    gold set is too small to certify (the expected, reportable outcome for `document-title`)."""
    if b == 0 or c >= b:
        return "failed"
    if p <= alpha:
        return "certified"
    return "worked_but_uncertifiable"


def _by_class(
    earlier_vec: VerdictVector, later_vec: VerdictVector, *, earlier: str, later: str
) -> dict[str, list[tuple[Any, Any]]]:
    """Two verdict vectors aligned by `act_testcase_id` and grouped by class.

    Both alignment failures are hard errors rather than silently-scored ones, because both mean the two
    vectors are no longer measuring the same thing: a differing case set would pair on the overlap and
    quietly drop the rest, and a drifted `gold_flag` would compare two different questions. Only the
    drafter's input may change between two runs."""
    earlier_by_id = {c.act_testcase_id: c for c in earlier_vec.cases}
    later_by_id = {c.act_testcase_id: c for c in later_vec.cases}
    if set(earlier_by_id) != set(later_by_id):
        only_earlier = sorted(set(earlier_by_id) - set(later_by_id))
        only_later = sorted(set(later_by_id) - set(earlier_by_id))
        raise ValueError(
            f"{earlier} and {later} case sets differ — cannot pair. "
            f"only in {earlier}: {only_earlier}; only in {later}: {only_later}"
        )

    by_class: dict[str, list[tuple[Any, Any]]] = {}
    for tid, ec in earlier_by_id.items():
        lc = later_by_id[tid]
        if ec.gold_flag != lc.gold_flag:
            raise ValueError(
                f"gold_flag drifted for case {tid} ({earlier} {ec.gold_flag}, {later} {lc.gold_flag}) — "
                "the gold oracle must be identical across the two runs; only the drafter's input may change"
            )
        by_class.setdefault(ec.axe_rule, []).append((ec, lc))
    return by_class


def _discordant(pairs: list[tuple[Any, Any]]) -> tuple[list[str], list[str]]:
    """The two discordant sets of one class: cases the earlier vector got wrong and the later got right,
    and the reverse. Correctness is against ACT gold on both sides."""
    improved_ids: list[str] = []
    regressed_ids: list[str] = []
    for ec, lc in pairs:
        earlier_right = ec.drafter_flag == ec.gold_flag
        later_right = lc.drafter_flag == lc.gold_flag
        if not earlier_right and later_right:
            improved_ids.append(ec.act_testcase_id)
        elif earlier_right and not later_right:
            regressed_ids.append(ec.act_testcase_id)
    return sorted(improved_ids), sorted(regressed_ids)


def attribute_against_prior(baseline: VerdictVector, prior: VerdictVector, run: VerdictVector) -> RunAttribution:
    """Three frozen vectors → whether this run's change consumed the previous run's fix.

    The pooled thesis asks whether a change helped, measured against the frozen pre-change baseline. This
    asks a different question that a run carrying one further prompt change has to answer separately: did
    that change give back what the run before it bought? A case counts as a lost gain only when all three
    line up — baseline **wrong**, prior run **right**, this run **wrong again** — which is why the
    baseline is needed here and a straight prior-vs-run pairing is not enough. A case this run breaks that
    the prior run never fixed is a regression but not a lost gain, and the two are never collapsed.

    Pure and deterministic. ACT gold is the oracle throughout; no judge field is read."""
    by_class = _by_class(prior, run, earlier="prior run", later="run")
    baseline_by_id = {c.act_testcase_id: c for c in baseline.cases}

    classes: list[ClassAttribution] = []
    for axe_rule in sorted(by_class):
        pairs = by_class[axe_rule]
        improved_ids, regressed_ids = _discordant(pairs)
        lost: list[str] = []
        for pc, rc in pairs:
            bc = baseline_by_id.get(pc.act_testcase_id)
            if bc is None:
                continue
            baseline_right = bc.drafter_flag == bc.gold_flag
            prior_right = pc.drafter_flag == pc.gold_flag
            run_right = rc.drafter_flag == rc.gold_flag
            if not baseline_right and prior_right and not run_right:
                lost.append(pc.act_testcase_id)
        classes.append(
            ClassAttribution(
                axe_rule=axe_rule,
                improved=len(improved_ids),
                regressed=len(regressed_ids),
                improved_ids=tuple(improved_ids),
                regressed_ids=tuple(regressed_ids),
                prior_gains_lost=tuple(sorted(lost)),
            )
        )

    return RunAttribution(
        classes=tuple(classes),
        eats_prior_run=any(c.prior_gains_lost for c in classes),
        prior_run_ids=tuple(prior.run_ids),
        run_run_ids=tuple(run.run_ids),
    )


def _pooled_thesis(b: int, c: int, p: float, alpha: float) -> str:
    if p <= alpha:
        return "supported"
    if b <= 2:
        return "not_supported"
    return "directional_not_significant"


def pair_verdicts(
    baseline: VerdictVector,
    run: VerdictVector,
    *,
    pooled_axe_rules: tuple[str, ...] = _POOLED_AXE_RULES,
    alpha: float = _ALPHA,
) -> PairedThesis:
    """Frozen baseline + a run's `VerdictVector` → the per-class and pooled discordant sign tests.

    Pairs by `act_testcase_id`: the two vectors must cover the identical case set (only the drafter's input
    changed between them), so a differing set or a per-case `gold_flag` drift is a hard error rather than a
    silently-scored one. For each class, `improved` = baseline wrong → run right, `regressed` = baseline
    right → run wrong, both against ACT gold; the per-class p is the one-sided exact sign test on those.
    The pooled endpoint sums the discordant pairs over `pooled_axe_rules` and tests once — the primary
    result. Pure and deterministic."""
    by_class = _by_class(baseline, run, earlier="baseline", later="run")

    classes: list[ClassVerdict] = []
    for axe_rule in sorted(by_class):
        improved_ids, regressed_ids = _discordant(by_class[axe_rule])
        b, c = len(improved_ids), len(regressed_ids)
        p = sign_test_p(b, c)
        classes.append(
            ClassVerdict(
                axe_rule=axe_rule,
                n_paired=len(by_class[axe_rule]),
                improved=b,
                regressed=c,
                improved_ids=tuple(improved_ids),
                regressed_ids=tuple(regressed_ids),
                p_value=p,
                verdict=_class_verdict(b, c, p, alpha),
            )
        )

    pooled_b = sum(c.improved for c in classes if c.axe_rule in pooled_axe_rules)
    pooled_c = sum(c.regressed for c in classes if c.axe_rule in pooled_axe_rules)
    pooled_p = sign_test_p(pooled_b, pooled_c)
    pooled = PooledVerdict(
        axe_rules=tuple(pooled_axe_rules),
        improved=pooled_b,
        regressed=pooled_c,
        p_value=pooled_p,
        alpha=alpha,
        thesis=_pooled_thesis(pooled_b, pooled_c, pooled_p, alpha),
    )
    return PairedThesis(
        classes=tuple(classes),
        pooled=pooled,
        baseline_run_ids=tuple(baseline.run_ids),
        run_run_ids=tuple(run.run_ids),
    )
