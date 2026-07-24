"""Pair a Run A drafter verdict vector against the frozen baseline, case by case → the pre-registered sign tests.

The per-class κ scalar cannot be paired; the frozen `VerdictVector` can. This module sets Run A's per-case
FLAG/CLEAN vector beside the baseline's, keyed by `act_testcase_id`, and reads off the discordant pairs the
pre-registration is scored on: `b` = a case the baseline got wrong and Run A got right (an improvement),
`c` = a case the baseline got right and Run A got wrong (a regression). The one-sided exact sign test on
`(b, c)` is the same `sign_test_p` the ceiling pre-registration uses — reused, not re-derived, so the run is
measured against exactly the test that was fixed before it existed.

**The primary endpoint is the POOLED test** across the classes the referent fix treats (`label` + `link-name`): the
hypothesis is about referent PRESENCE, not about either class, so the estimand is the pooled reachable
errors and the per-class tests are secondary. Both are computed; both are reported.

Pure — no LLM, no network, no clock. Every number is a deterministic function of the two frozen vectors.
ACT gold is the oracle in both (`gold_flag`), and a case whose gold disagrees between the two vectors is a
hard error, never silently scored: the whole point is that only the drafter's input changed between them.

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
    """One fix-unit class paired Run-A-vs-baseline: the discordant counts, the sign-test p, and the verdict.

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
    """Frozen baseline + Run A `VerdictVector` → the per-class and pooled discordant sign tests.

    Pairs by `act_testcase_id`: the two vectors must cover the identical case set (only the drafter's input
    changed between them), so a differing set or a per-case `gold_flag` drift is a hard error rather than a
    silently-scored one. For each class, `improved` = baseline wrong → Run A right, `regressed` = baseline
    right → Run A wrong, both against ACT gold; the per-class p is the one-sided exact sign test on those.
    The pooled endpoint sums the discordant pairs over `pooled_axe_rules` and tests once — the primary
    result. Pure and deterministic."""
    base_by_id = {c.act_testcase_id: c for c in baseline.cases}
    run_by_id = {c.act_testcase_id: c for c in run.cases}
    if set(base_by_id) != set(run_by_id):
        only_base = sorted(set(base_by_id) - set(run_by_id))
        only_run = sorted(set(run_by_id) - set(base_by_id))
        raise ValueError(
            f"baseline and Run A case sets differ — cannot pair. only in baseline: {only_base}; only in run: {only_run}"
        )

    by_class: dict[str, list[tuple[Any, Any]]] = {}
    for tid, bc in base_by_id.items():
        rc = run_by_id[tid]
        if bc.gold_flag != rc.gold_flag:
            raise ValueError(
                f"gold_flag drifted for case {tid} (baseline {bc.gold_flag}, run {rc.gold_flag}) — "
                "the gold oracle must be identical across the two runs; only the drafter's input may change"
            )
        by_class.setdefault(bc.axe_rule, []).append((bc, rc))

    classes: list[ClassVerdict] = []
    for axe_rule in sorted(by_class):
        improved_ids: list[str] = []
        regressed_ids: list[str] = []
        for bc, rc in by_class[axe_rule]:
            base_right = bc.drafter_flag == bc.gold_flag
            run_right = rc.drafter_flag == rc.gold_flag
            if not base_right and run_right:
                improved_ids.append(bc.act_testcase_id)
            elif base_right and not run_right:
                regressed_ids.append(bc.act_testcase_id)
        b, c = len(improved_ids), len(regressed_ids)
        p = sign_test_p(b, c)
        classes.append(
            ClassVerdict(
                axe_rule=axe_rule,
                n_paired=len(by_class[axe_rule]),
                improved=b,
                regressed=c,
                improved_ids=tuple(sorted(improved_ids)),
                regressed_ids=tuple(sorted(regressed_ids)),
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
