"""Per-class drafter κ against ACT gold — chance-corrected agreement, stratified by fix unit.

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

**The fix unit is `axe_rule`, not the ACT rule.** The two link rules (*Link is descriptive*, *Link in
context is descriptive*) share one missing referent — the destination lies outside a single-page DOM —
and receive ONE M7 fix, and both already carry axe_rule `link-name`, so grouping by axe_rule pools
them automatically. The estimand must match the intervention: splitting one fix across two
underpowered samples would measure nothing twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clearway.eval.drafter_score import FAILED, DraftedCase, _flagged
from clearway.eval.kappa import cohen_kappa, raw_agreement
from clearway.eval.offline import _drafted_cases


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


def _rule_to_axe(artifact: dict[str, Any]) -> dict[str, str]:
    """`rule_name` → `axe_rule`, learned from the minting cases (which carry both). Honest-misses carry
    no `axe_rule`, so their class is recovered here by `rule_name`. Every honest-miss rule also has
    minting cases in the same artifact, so the map covers them; a rule that does not is raised on in
    `class_kappas`, never dropped silently."""
    return {c["rule_name"]: c["axe_rule"] for c in artifact["cases"]}


def class_kappas(artifact: dict[str, Any], *, partial_flags: bool = True) -> list[ClassKappa]:
    """Frozen offline-eval run artifact → per-fix-unit drafter κ vs ACT gold, sorted by `axe_rule`.

    Pure: no model, no network, no clock — a deterministic replay of the checked-in artifact. Reuses the
    scorer's own case stream (`_drafted_cases`, so honest-misses are carried in identically to recall/FP)
    and `_flagged` (flag-if-any), so κ inherits the exact scoring convention rather than inventing a
    second one. Groups by `axe_rule` (the fix unit; the two link rules pool into `link-name`). Reported
    under one `partial_flags` reading — call twice to get both, as every other rate does.
    """
    rule_to_axe = _rule_to_axe(artifact)
    by_class: dict[str, list[DraftedCase]] = {}
    for case in _drafted_cases(artifact):
        if case.rule_name not in rule_to_axe:
            raise KeyError(f"case rule {case.rule_name!r} has no axe_rule in the artifact — cannot classify it")
        by_class.setdefault(rule_to_axe[case.rule_name], []).append(case)

    results: list[ClassKappa] = []
    for axe_rule, group in sorted(by_class.items()):
        drafter = ["FLAG" if _flagged(c, partial_flags=partial_flags) else "CLEAN" for c in group]
        gold = ["FLAG" if c.expected == FAILED else "CLEAN" for c in group]
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
