"""Score subject #2 — the judge — AGAINST ACT gold, not as the ruler. No LLM, no network.

The whole milestone refuses to let an LLM grade an LLM once real gold exists, so here the judge is a
*subject*: we know the right answer, so the judge gets a confusion matrix against it. The axis is
CONFORMANCE ONLY — the judge's `conformance_correct` boolean vs whether the draft's conformance is
actually right — because the drafter is deliberately steered to cite SCs that disagree with ACT gold
(framing, not capability), so folding citation in would penalise the judge for our own choice and
pollute the one number that matters: the miss rate. Citation-catching is measured separately and
cleanly by the SC-swap injection.

The two errors are NEVER collapsed into one κ:
  - a **missed error** (judge passed a wrong draft) is dangerous — it reaches the specialist wearing
    "verified"; its rate is EXEMPT from the CI rule (too few naturally-wrong drafts to interval), and
    the trustworthy figure is the injected detection rate instead;
  - a **false alarm** (judge blocked a correct draft) is merely annoying, and carries a real CI.

Injected detection is an UPPER BOUND on real miss-catching, split into two mutations each with its own
n — a conformance flip (rationale regenerated to argue the flip, else the strawman inflates it) and an
SC swap (citation-catching only, secondary). This module does the pure confusion + detection math; the
live injection that produces the results lives with the builder.

⚠️ The cells have a UNIT, and `JudgeConfusion` has no field that says which
--------------------------------------------------------------------------
A confusion matrix over judged FINDINGS and one over judged CASES are the same four integers with the
same names on two different denominators, and they are indistinguishable on disk. So the unit is
required at the call site (`score_judge(..., unit=…)`) and travels back out on `JudgeScoring` for the
caller to record beside the cells — a scorer that defaulted it would let a per-case matrix be written,
published and read as a per-finding one, which is precisely what a unit-free gauge name cannot survive.

**The case collapse is `collapse_to_cases`, and it is not an average.** A case flags if ANY of its
findings does (the drafter scorer's own `_flagged`), and the judge releases a case only if it released
every finding on it. `act_correct` at the case is the CASE-LEVEL predicate — flag-if-any against the
gold outcome — and never a roll-up of the per-finding ones: a case whose gold says *failed* and whose
four findings split 1 flag / 3 clean is case-CORRECT while three of its findings are finding-wrong, so
deriving one from the other would silently move the ceiling. That is why the caller supplies it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clearway.eval.kappa import cohen_kappa
from clearway.eval.stats import metric_ci_or_empty
from clearway.schemas.models import ExemptMetric, JudgeConfusion, MetricCI

# The two units a judge confusion can be tallied on. Named constants rather than bare strings so the
# value written into a run artifact and the value a scorer was called with cannot drift apart.
CONFUSION_UNIT_FINDING = "finding"
CONFUSION_UNIT_CASE = "case"
CONFUSION_UNITS: tuple[str, ...] = (CONFUSION_UNIT_FINDING, CONFUSION_UNIT_CASE)

_MISS_RATE_EXEMPT_REASON = (
    "the judge's real-draft miss rate — too few naturally-wrong drafts to put a CI on; the injected "
    "conformance-flip detection rate is the trustworthy upper bound reported instead"
)


@dataclass(frozen=True)
class JudgedDraft:
    """One natural drafted finding as the judge graded it, on the conformance axis. `act_correct` is
    the deterministic truth (is the draft's conformance right vs ACT gold); `judge_pass` is the judge's
    `conformance_correct` boolean (it thinks the draft is right). `rule_name` feeds the effective n."""

    rule_name: str
    act_correct: bool
    judge_pass: bool


@dataclass(frozen=True)
class InjectedResult:
    """One KNOWN-WRONG injected draft the judge graded. By construction the draft is wrong, so the only
    question is whether the judge caught it — `caught` = the judge said "fail" (conformance wrong)."""

    rule_name: str
    caught: bool


@dataclass(frozen=True)
class JudgedCase:
    """One ACT case as the judge answered it, before the within-case collapse — the pinned unit's input.

    `judge_passes` holds one entry per MINTED finding on the case, each already the configuration's
    majority verdict across its passes (repeat passes collapse first, per finding; the case collapse is
    second, and the order is not interchangeable). `act_correct` is the case-level truth against ACT
    gold — flag-if-any over the case's drafts compared to the gold outcome — supplied by the caller
    that holds the drafts, never inferred from `judge_passes`, which says nothing about the drafter.
    """

    act_testcase_id: str
    rule_name: str
    act_correct: bool
    judge_passes: tuple[bool, ...]


class NoFindingToJudge(ValueError):
    """A case with no minted finding offered to the judge's stream.

    Refused rather than dropped or counted as a release: a case that mints nothing was never put to the
    judge, so it is not an observation at all — the drafter's stream carries those rows (a failed one is
    an automatic recall miss) and the judge's cannot. Collapsing one to "the judge raised no hand" would
    quietly add a `correct_release` or a `missed_error` the judge never had the chance to earn.
    """


def collapse_to_cases(cases: Sequence[JudgedCase]) -> list[JudgedDraft]:
    """Per-finding judge decisions → one `JudgedDraft` per case, flag-if-any within the case.

    The judge RELEASES a case only when it released every finding on it; one raised hand anywhere on the
    page is the specialist's "go look", which is the same rule the drafter scorer collapses under. The
    gold side is passed through untouched — see `JudgedCase.act_correct` for why it is not derived here.
    """
    collapsed: list[JudgedDraft] = []
    for case in cases:
        if not case.judge_passes:
            raise NoFindingToJudge(
                f"case {case.act_testcase_id!r} carries no judged finding — a case that minted nothing "
                "was never put to the judge, so it is not one of the judge's observations. Filter the "
                "non-minting rows out before collapsing rather than letting one read as a release."
            )
        collapsed.append(
            JudgedDraft(
                rule_name=case.rule_name,
                act_correct=case.act_correct,
                judge_pass=all(case.judge_passes),
            )
        )
    return collapsed


def _rules(items: list[JudgedDraft] | list[InjectedResult]) -> int:
    return len({i.rule_name for i in items})


@dataclass(frozen=True)
class Confusion:
    """The 2×2 of judge verdict × ACT gold on the conformance axis — the four counts, named for the
    consequence each carries so the dangerous cell is never hidden inside a summary number."""

    correct_release: int  # judge pass · ACT correct — ✅
    missed_error: int  # judge pass · ACT wrong — ⚠️ the dangerous half
    false_alarm: int  # judge fail · ACT correct — ⚠️ merely annoying
    correct_catch: int  # judge fail · ACT wrong — ✅

    @property
    def wrong_total(self) -> int:
        """Naturally-wrong drafts — the miss-rate denominator (and why it is too small to CI)."""
        return self.missed_error + self.correct_catch

    @property
    def correct_total(self) -> int:
        """Actually-correct drafts — the false-alarm-rate denominator."""
        return self.false_alarm + self.correct_release


def confusion(drafts: list[JudgedDraft]) -> Confusion:
    """Tally the four cells from the judged natural drafts."""
    return Confusion(
        correct_release=sum(1 for d in drafts if d.judge_pass and d.act_correct),
        missed_error=sum(1 for d in drafts if d.judge_pass and not d.act_correct),
        false_alarm=sum(1 for d in drafts if not d.judge_pass and d.act_correct),
        correct_catch=sum(1 for d in drafts if not d.judge_pass and not d.act_correct),
    )


def detection_rate(results: list[InjectedResult]) -> MetricCI:
    """Fraction of the known-wrong injected drafts the judge caught — an UPPER BOUND on real
    miss-catching (an injected error is cleaner and more catchable than a natural one). Carries a Wilson
    CI with the clustering-honest effective n; an empty injection set reads as no-data (n=0)."""
    caught = sum(1 for r in results if r.caught)
    return metric_ci_or_empty(caught, len(results), effective_n=_rules(results))


@dataclass(frozen=True)
class JudgeScoring:
    """The judge's `JudgeConfusion` plus the unit its cells are on, which the schema has nowhere to put.

    The twin of `DrafterScoring`, and for the same reason: `JudgeConfusion` is `extra="forbid"` and adding
    an eval-only field to a §3 shape makes every consumer handle it being absent forever, so the unit
    rides out here and goes into the run artifact beside the cells. `n` is the number of observations the
    cells were tallied over — findings or cases, per `unit` — because the four integers alone cannot say.
    """

    confusion: JudgeConfusion
    unit: str
    n: int


def score_judge(
    natural: list[JudgedDraft],
    *,
    unit: str,
    conformance_flip: list[InjectedResult],
    sc_swap: list[InjectedResult],
    rationale_note: str = "",
) -> JudgeScoring:
    """Assemble the judge's `JudgeConfusion`: the natural-draft confusion (miss rate exempt, false-alarm
    rate with CI, κ vs gold) plus the two injected detection rates. `rationale_note` records how the
    conformance-flip's rationale was regenerated to argue the flip (the LLM re-authorship is a bias to
    note). Raises on no natural drafts — there is nothing to grade, not a zero to report.

    `unit` is required and keyword-only. The cells are four integers whose meaning depends entirely on
    what one of them counts, and nothing downstream can recover it: a default here would let a caller
    that collapsed to cases and one that did not write indistinguishable artifacts.

    ⚠️ The two INJECTED rates are per mutated DRAFT whatever `unit` says — a mutation is applied to a
    draft, not to a case — so they keep their own denominators and are never re-based by this argument.
    """
    if unit not in CONFUSION_UNITS:
        raise ValueError(f"unknown confusion unit {unit!r} — expected one of {', '.join(CONFUSION_UNITS)}")
    if not natural:
        raise ValueError("no judged drafts to score the judge on")
    c = confusion(natural)
    miss_rate = c.missed_error / c.wrong_total if c.wrong_total else 0.0
    kappa = cohen_kappa([d.act_correct for d in natural], [d.judge_pass for d in natural])
    scored = JudgeConfusion(
        correct_release=c.correct_release,
        missed_error=c.missed_error,
        false_alarm=c.false_alarm,
        correct_catch=c.correct_catch,
        miss_rate=ExemptMetric(value=miss_rate, n=c.wrong_total, exempt_reason=_MISS_RATE_EXEMPT_REASON),
        false_alarm_rate=metric_ci_or_empty(
            c.false_alarm, c.correct_total, effective_n=_rules([d for d in natural if d.act_correct])
        ),
        kappa=kappa,
        injected_conformance_flip=detection_rate(conformance_flip),
        injected_sc_swap=detection_rate(sc_swap),
        rationale_coherence_note=rationale_note,
    )
    return JudgeScoring(confusion=scored, unit=unit, n=len(natural))
