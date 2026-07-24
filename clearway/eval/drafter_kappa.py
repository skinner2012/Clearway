"""Per-class drafter κ against ACT gold — chance-corrected agreement + its bootstrap CI, by fix unit.

The acceptance layer scores the drafter with recall / false-positive / SC-match / ECE, all pooled
across rules and none chance-corrected. That hides a structural failure mode: a CONSTANT classifier
(one verdict stamped on every case in a class) earns a flattering recall while carrying no
discriminative signal at all. Cohen's κ exposes it — a rater with no variance scores 0 however the
marginals fall. This module points the EXISTING κ math at a NEW subject: the drafter's per-case
flag/clean stream. New subject, not new math.

Pure — no LLM, no network, no clock. Every number replays from the frozen offline-eval run artifact,
the same discipline `offline.py` and the judge-κ replay follow.

**The unit is one ACT case, not one finding**, and the case stream is the scorer's own
(`_drafted_cases` + `_flagged`): honest-misses are carried in as drafts-less cases exactly as recall
counts them, so κ cannot inflate the way a miss-dropping recall would, and the drafter FLAG/CLEAN
collapse is identical to the one every other rate uses.

**The fix unit is `axe_rule`, and each one carries exactly one scored ACT rule.** The class definition
is the gold's own scope (`act_gold.RULE_TO_AXE`), so a rule scoped out of the gold leaves the classes
here too — a frozen run artifact still holds its cases, and scoring them would measure something the
gold no longer claims. `_grouped(..., scoped=False)` recovers the unscoped reading, which is what the
superseded row on the baseline is built from.

**The interval is a seeded case-level bootstrap** (`class_kappa_cis`), never Wilson: Wilson is the
contract for proportions and κ is not one, so κ is never routed through `metric_ci`. The bounds are
percentile — resample cases within a class, recompute κ, read the 2.5/97.5 percentiles — with the seed
recorded so they reproduce bit-for-bit. Two honesty guards ship with every interval: the
degenerate-resample share (resamples where a stream came out constant, so κ was undefined and returned
0.0 by convention), and a constant-classifier flag on any ZERO-WIDTH interval — document-title's
`[0.0, 0.0]` is no variance because no signal, and must never read as precision.

**The ceiling** (`class_ceilings`) is what a class could prove even under a PERFECT future fix: the
one-sided exact sign-test p if a fix corrected every error it can reach and introduced none. Its
direction and α are pre-registered before any fixed run exists (`CEILING_PREREGISTRATION`), so they
cannot be chosen after the fact. A class that cannot clear α at any fix quality is limited by the gold
set's SIZE — the per-class analogue of the run-to-run noise floor, not a verdict on the drafter.

**Two ceilings, and only one of them is honest about a prompt-input fix.** `errors` counts every
discordant case; some of those are STRUCTURALLY out of reach of anything the drafter is given — the case
minted no finding so the drafter was never invoked, or two byte-identical fixtures carry opposite ACT
outcomes so one of them is permanently wrong. Subtracting exactly those named cases gives
`reachable_errors`, and the ceiling over them is what a fix is measured against. A *predicted* failure is
never subtracted: it is a claim about model behaviour, and removing it would make the ceiling
unfalsifiable. `tolerated_regressions` states the margin plainly — 0 means only a perfect run passes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import comb
from typing import Any

from clearway.eval.act_gold import RULE_TO_AXE, contradictory_gold_twins
from clearway.eval.drafter_score import FAILED, DraftedCase, _flagged
from clearway.eval.kappa import cohen_kappa, raw_agreement
from clearway.eval.offline import _drafted_cases

# Seeded and recorded on every interval so the percentile bounds are bit-reproducible — a CI you
# cannot reproduce is not a measurement. Case-level, 10k resamples.
_BOOTSTRAP_SEED = 0
_RESAMPLES = 10_000

# PRE-REGISTERED, here in code, before any fixed run exists: the ceiling test is ONE-SIDED (the
# hypothesis is directional — a fix should improve, not merely change) at α = 0.05. Fixing the direction
# and the level now — the same discipline as the pre-committed KAPPA_THRESHOLD — is what separates the
# ceiling from choosing a test after seeing the result.
_ALPHA = 0.05
ONE_SIDED = True

CEILING_PREREGISTRATION = (
    "Pre-registered before any fixed run exists: the detectable-improvement test is ONE-SIDED (the "
    "hypothesis is directional — a fix should improve, not merely change) at alpha = 0.05, scored on "
    "DISCORDANT PAIRS against the frozen per-case verdict vector, keyed by act_testcase_id, with ACT "
    "gold as the oracle and the judge absent from every number. The ceiling is the MOST GENEROUS outcome "
    "available — a hypothetical fix that corrects every error it can reach and introduces none. Only "
    "STRUCTURALLY unreachable errors are subtracted (a case that minted no finding, so the drafter was "
    "never invoked; a case whose fixture is byte-identical to one carrying the opposite ACT outcome, so "
    "one of the pair is permanently wrong): a PREDICTED failure stays in the count, because subtracting "
    "predictions is how a ceiling stops being falsifiable. Fixing the direction, alpha and the "
    "subtraction rule here, before any fixed run, is what separates this from p-hacking. A class marked "
    "NOT certifiable is limited by the GOLD SET'S SIZE, never by the drafter or any future fix: at n this "
    "small even a perfect fix cannot clear alpha. Per-class certification carries zero margin at these n, "
    "so the PRIMARY endpoint is the pooled test across the classes a fix treats and the per-class results "
    "are secondary — both are computed and both are reported. One yardstick: you cannot detect an "
    "improvement the class lacks the statistical room to show."
)


def sign_test_p(b: int, c: int) -> float:
    """The one-sided exact sign-test p on discordant pairs: `b` improved, `c` regressed.

    P(X >= b) under Bin(b + c, 1/2) — the probability of at least this many improvements if the change
    were a coin flip. Exact, never normal-approximated: at these n the approximation is not usable. With
    c = 0 it reduces to 0.5^b, which is the ceiling form."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(b, n + 1))
    return tail / 2.0**n


def minimum_wins(alpha: float = _ALPHA) -> int:
    """The fewest fixed cases that clear `alpha` at zero regressions — the bar a perfect run must reach."""
    b = 0
    while sign_test_p(b, 0) > alpha:
        b += 1
    return b


def tolerated_regressions(reachable_errors: int, alpha: float = _ALPHA) -> int:
    """How many newly-broken cases a ceiling absorbs and still clears `alpha`, given every reachable error
    is fixed. 0 means a perfect run is the only passing run — the margin stated, rather than assumed.
    `sign_test_p` is monotone in `c`, so the first failure ends the search."""
    if sign_test_p(reachable_errors, 0) > alpha:
        return 0
    c = 0
    while sign_test_p(reachable_errors, c + 1) <= alpha:
        c += 1
    return c


@dataclass(frozen=True)
class ClassKappa:
    """The drafter's per-case κ over one fix-unit class (an `axe_rule`), against ACT gold.

    `tp/fp/fn/tn` is the 2×2 of the drafter FLAG/CLEAN stream against the gold FLAG/CLEAN stream, where
    gold FLAG == ACT `failed`: `fp` is a cry-wolf, `fn` a miss. `raw_agreement` rides beside `kappa`
    because κ can be low at high agreement when one class dominates — that gap is the constant-classifier
    tell (κ ≈ 0 at high agreement means "stamped one verdict", not "judged well"). `rule_names` records
    which ACT rule(s) the class pools. Computed under a single `partial_flags` reading.
    """

    axe_rule: str
    rule_names: tuple[str, ...]
    n: int
    failed: int
    passed: int
    tp: int
    fp: int
    fn: int
    tn: int
    kappa: float
    raw_agreement: float
    partial_flags: bool


@dataclass(frozen=True)
class ClassKappaCI:
    """A class's κ with a seeded case-level bootstrap percentile CI.

    NOT a Wilson interval — Wilson is the contract for PROPORTIONS, and κ is not one (it lives in
    `[-1, 1]` and its sampling distribution is not binomial), so κ is never routed through `metric_ci`.
    `constant_classifier` is set when the interval is ZERO-WIDTH: the fingerprint of a rater with no
    variance (document-title stamps one verdict on every case), which must read as "no signal", never as
    perfect precision. `degenerate_share` is the fraction of resamples in which a stream came out
    single-valued — κ undefined, returned 0.0 by convention — disclosed because, unreported, it silently
    drags the lower bound toward zero. `seed` + `resamples` are recorded so the bounds reproduce exactly.
    """

    axe_rule: str
    kappa: float
    ci_low: float
    ci_high: float
    degenerate_share: float
    resamples: int
    seed: int
    constant_classifier: bool
    partial_flags: bool


@dataclass(frozen=True)
class UnreachableErrorRow:
    """One current error a change to the drafter's INPUT provably cannot fix, named to its ACT case and
    to the structural reason. These, and only these, are subtracted from a ceiling."""

    act_testcase_id: str
    kind: str
    reason: str


@dataclass(frozen=True)
class ClassCeiling:
    """The most generous detectable improvement for a class, in both readings.

    `errors` = FP + miss is every current discordant case, and `p_value` / `certifiable` are the ceiling
    over all of them — the arithmetic a class would reach if a fix corrected literally everything. That
    ceiling is OPTIMISTIC: `unreachable` names the errors no drafter-input change can touch, and
    `reachable_errors` is what remains. `reachable_p_value` / `reachable_certifiable` are the ceiling a
    fix is actually measured against, and `tolerated_regressions` is its margin — 0 means only a perfect
    run clears alpha. A NOT-certifiable class is limited by the GOLD SET'S SIZE, never by the drafter or
    any future fix. See `CEILING_PREREGISTRATION` for the standing pre-registration."""

    axe_rule: str
    n: int
    errors: int
    fp: int
    fn: int
    p_value: float
    alpha: float
    certifiable: bool
    reachable_errors: int
    reachable_error_ids: tuple[str, ...]
    reachable_p_value: float
    reachable_certifiable: bool
    tolerated_regressions: int
    unreachable: tuple[UnreachableErrorRow, ...] = field(default_factory=tuple)


def _rule_to_axe(artifact: dict[str, Any]) -> dict[str, str]:
    """`rule_name` → `axe_rule`, learned from the minting cases (which carry both). Honest-misses carry
    no `axe_rule`, so their class is recovered here by `rule_name`. Every honest-miss rule also has
    minting cases in the same artifact, so the map covers them; a rule that does not is raised on in
    `_grouped`, never dropped silently."""
    return {c["rule_name"]: c["axe_rule"] for c in artifact["cases"]}


def _grouped(artifact: dict[str, Any], *, scoped: bool = True) -> dict[str, list[DraftedCase]]:
    """The scorer's own case stream (honest-misses carried in) grouped by fix unit (`axe_rule`).

    `scoped=True` keeps only the ACT rules the gold currently scores (`act_gold.RULE_TO_AXE`) — a frozen
    artifact predating a scope correction still holds the dropped rule's cases, and scoring them would
    measure something the gold no longer claims. `scoped=False` recovers the unscoped reading, which is
    what the superseded row on the baseline is built from. Raises on a case whose rule has no axe_rule
    rather than dropping it."""
    rule_to_axe = _rule_to_axe(artifact)
    by_class: dict[str, list[DraftedCase]] = {}
    for case in _drafted_cases(artifact):
        if scoped and case.rule_name not in RULE_TO_AXE:
            continue
        if case.rule_name not in rule_to_axe:
            raise KeyError(f"case rule {case.rule_name!r} has no axe_rule in the artifact — cannot classify it")
        by_class.setdefault(rule_to_axe[case.rule_name], []).append(case)
    return by_class


def _streams(group: list[DraftedCase], *, partial_flags: bool) -> tuple[list[str], list[str]]:
    """The paired (drafter, gold) FLAG/CLEAN streams for one class: the drafter flags iff any finding on
    the case alarms (`_flagged`, flag-if-any), gold flags iff the ACT outcome is `failed`."""
    drafter = ["FLAG" if _flagged(c, partial_flags=partial_flags) else "CLEAN" for c in group]
    gold = ["FLAG" if c.expected == FAILED else "CLEAN" for c in group]
    return drafter, gold


def class_kappas(artifact: dict[str, Any], *, partial_flags: bool = True, scoped: bool = True) -> list[ClassKappa]:
    """Frozen offline-eval run artifact → per-fix-unit drafter κ vs ACT gold, sorted by `axe_rule`.

    Pure: no model, no network, no clock — a deterministic replay of the checked-in artifact. Reuses the
    scorer's own case stream (`_drafted_cases`, so honest-misses are carried in identically to recall/FP)
    and `_flagged` (flag-if-any), so κ inherits the exact scoring convention rather than inventing a
    second one. Groups by `axe_rule` (the fix unit), over the rules the gold currently scores unless
    `scoped=False`. Reported under one `partial_flags` reading — call twice to get both, as every other
    rate does.
    """
    results: list[ClassKappa] = []
    for axe_rule, group in sorted(_grouped(artifact, scoped=scoped).items()):
        drafter, gold = _streams(group, partial_flags=partial_flags)
        tp = sum(1 for d, g in zip(drafter, gold) if d == "FLAG" and g == "FLAG")
        fp = sum(1 for d, g in zip(drafter, gold) if d == "FLAG" and g == "CLEAN")
        fn = sum(1 for d, g in zip(drafter, gold) if d == "CLEAN" and g == "FLAG")
        tn = sum(1 for d, g in zip(drafter, gold) if d == "CLEAN" and g == "CLEAN")
        failed = sum(1 for c in group if c.expected == FAILED)
        results.append(
            ClassKappa(
                axe_rule=axe_rule,
                rule_names=tuple(sorted({c.rule_name for c in group})),
                n=len(group),
                failed=failed,
                passed=len(group) - failed,
                tp=tp,
                fp=fp,
                fn=fn,
                tn=tn,
                kappa=cohen_kappa(drafter, gold),
                raw_agreement=raw_agreement(drafter, gold),
                partial_flags=partial_flags,
            )
        )
    return results


def _bootstrap_ci(drafter: list[str], gold: list[str], *, seed: int, resamples: int) -> tuple[float, float, float]:
    """Case-level percentile bootstrap of κ → (ci_low, ci_high, degenerate_share).

    Resample the PAIRED (drafter, gold) cases with replacement, recompute κ, and read the 2.5/97.5
    percentiles off the sorted estimates. A fresh `random.Random(seed)` per call makes the bounds
    independent of call order and bit-reproducible. A resample whose drafter OR gold stream comes out
    single-valued is counted degenerate (κ undefined → 0.0 by convention); for a constant classifier
    like document-title the drafter stream is constant on EVERY resample, so the share is 1.0.
    """
    n = len(drafter)
    rng = random.Random(seed)
    estimates: list[float] = []
    degenerate = 0
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        d = [drafter[i] for i in idx]
        g = [gold[i] for i in idx]
        if len(set(d)) < 2 or len(set(g)) < 2:
            degenerate += 1
        estimates.append(cohen_kappa(d, g))
    estimates.sort()
    return estimates[int(0.025 * resamples)], estimates[int(0.975 * resamples)], degenerate / resamples


def class_kappa_cis(
    artifact: dict[str, Any],
    *,
    partial_flags: bool = True,
    seed: int = _BOOTSTRAP_SEED,
    resamples: int = _RESAMPLES,
    scoped: bool = True,
) -> list[ClassKappaCI]:
    """Per-class κ with a seeded case-level bootstrap percentile CI, sorted by `axe_rule`.

    Pure — no model, no network, no clock. `seed` and `resamples` are recorded on every interval so the
    bounds reproduce exactly. A zero-width interval is flagged `constant_classifier` (document-title
    yields `[0.0, 0.0]`) — read it as "no variance, no signal", never as precision. Percentile bootstrap,
    NOT Wilson: κ is not a proportion, so it never travels through `metric_ci`.
    """
    results: list[ClassKappaCI] = []
    for axe_rule, group in sorted(_grouped(artifact, scoped=scoped).items()):
        drafter, gold = _streams(group, partial_flags=partial_flags)
        ci_low, ci_high, degenerate = _bootstrap_ci(drafter, gold, seed=seed, resamples=resamples)
        results.append(
            ClassKappaCI(
                axe_rule=axe_rule,
                kappa=cohen_kappa(drafter, gold),
                ci_low=ci_low,
                ci_high=ci_high,
                degenerate_share=degenerate,
                resamples=resamples,
                seed=seed,
                constant_classifier=(ci_high == ci_low),
                partial_flags=partial_flags,
            )
        )
    return results


def _error_cases(group: list[DraftedCase], *, partial_flags: bool) -> list[DraftedCase]:
    """The class's current errors — cases where the drafter's FLAG/CLEAN disagrees with ACT gold."""
    return [c for c in group if _flagged(c, partial_flags=partial_flags) != (c.expected == FAILED)]


def _unreachable(group: list[DraftedCase], *, partial_flags: bool) -> tuple[UnreachableErrorRow, ...]:
    """The structurally unreachable errors in a class, named to their ACT cases.

    Two kinds, both provable from the artifacts and neither a judgement call: a case that minted no
    finding was never put to the drafter, and a case whose fixture is byte-identical to one carrying the
    opposite ACT outcome receives the same input as its twin, so exactly one of them is permanently
    wrong. Nothing else is subtracted — a predicted failure is a claim about the model and stays in."""
    twins = contradictory_gold_twins()
    rows: list[UnreachableErrorRow] = []
    for case in _error_cases(group, partial_flags=partial_flags):
        if not case.drafts:
            rows.append(
                UnreachableErrorRow(
                    act_testcase_id=case.act_testcase_id,
                    kind="honest_miss",
                    reason=(
                        "the case minted no finding, so the drafter was never invoked — "
                        "no change to its input reaches it"
                    ),
                )
            )
        elif case.act_testcase_id in twins:
            counterparts = ", ".join(twins[case.act_testcase_id])
            rows.append(
                UnreachableErrorRow(
                    act_testcase_id=case.act_testcase_id,
                    kind="contradictory_gold",
                    reason=(
                        f"byte-identical fixture to {counterparts}, which carries the opposite ACT outcome — "
                        "same input, so exactly one of the pair is permanently wrong"
                    ),
                )
            )
    return tuple(rows)


def class_ceilings(
    artifact: dict[str, Any], *, partial_flags: bool = True, alpha: float = _ALPHA, scoped: bool = True
) -> list[ClassCeiling]:
    """Per-class detectable-improvement ceiling, sorted by `axe_rule`, in both readings.

    Deterministic and offline: arithmetic on the frozen artifact's error counts plus a sha256 over the
    vendored fixture bytes — no model, no network, no clock. `errors` = current FP + miss and `p_value` =
    0.5^errors is the ceiling over ALL of them; `reachable_errors` subtracts the named structural
    exclusions and `reachable_p_value` is the ceiling a drafter-input fix is measured against.
    `tolerated_regressions` states the margin. The one-sided direction, alpha and the subtraction rule are
    PRE-REGISTERED (`CEILING_PREREGISTRATION`) before any fixed run exists; 'not certifiable' is a
    property of the gold set's size, not of the drafter or any fix."""
    groups = _grouped(artifact, scoped=scoped)
    ceilings: list[ClassCeiling] = []
    for c in class_kappas(artifact, partial_flags=partial_flags, scoped=scoped):
        errors = c.fp + c.fn
        p_value = sign_test_p(errors, 0)
        unreachable = _unreachable(groups[c.axe_rule], partial_flags=partial_flags)
        excluded = {row.act_testcase_id for row in unreachable}
        reachable_ids = tuple(
            case.act_testcase_id
            for case in _error_cases(groups[c.axe_rule], partial_flags=partial_flags)
            if case.act_testcase_id not in excluded
        )
        reachable_p = sign_test_p(len(reachable_ids), 0)
        ceilings.append(
            ClassCeiling(
                axe_rule=c.axe_rule,
                n=c.n,
                errors=errors,
                fp=c.fp,
                fn=c.fn,
                p_value=p_value,
                alpha=alpha,
                certifiable=p_value <= alpha,
                reachable_errors=len(reachable_ids),
                reachable_error_ids=reachable_ids,
                reachable_p_value=reachable_p,
                reachable_certifiable=reachable_p <= alpha,
                tolerated_regressions=tolerated_regressions(len(reachable_ids), alpha),
                unreachable=unreachable,
            )
        )
    return ceilings
