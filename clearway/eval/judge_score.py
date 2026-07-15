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
"""

from __future__ import annotations

from dataclasses import dataclass

from clearway.eval.kappa import cohen_kappa
from clearway.eval.stats import metric_ci_or_empty
from clearway.schemas.models import ExemptMetric, JudgeConfusion, MetricCI

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


def score_judge(
    natural: list[JudgedDraft],
    *,
    conformance_flip: list[InjectedResult],
    sc_swap: list[InjectedResult],
    rationale_note: str = "",
) -> JudgeConfusion:
    """Assemble the judge's `JudgeConfusion`: the natural-draft confusion (miss rate exempt, false-alarm
    rate with CI, κ vs gold) plus the two injected detection rates. `rationale_note` records how the
    conformance-flip's rationale was regenerated to argue the flip (the LLM re-authorship is a bias to
    note). Raises on no natural drafts — there is nothing to grade, not a zero to report.
    """
    if not natural:
        raise ValueError("no judged drafts to score the judge on")
    c = confusion(natural)
    miss_rate = c.missed_error / c.wrong_total if c.wrong_total else 0.0
    kappa = cohen_kappa([d.act_correct for d in natural], [d.judge_pass for d in natural])
    return JudgeConfusion(
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
