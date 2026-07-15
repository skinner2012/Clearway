"""Score subject #1 — the drafter — by deterministic comparison against ACT gold. No LLM, no network.

The headline is the drafter's answer to two questions: does it FIND real problems (recall on the ACT
failed cases) and does it CRY WOLF (false-positive rate on the ACT passed cases — the number that,
left high, inverts the product's value). Both are scored PER CASE, not per finding: within one ACT
case the elements are homogeneous (the same judgment repeated), so counting each minted finding
separately would pseudo-replicate and report a falsely tight interval. A case counts as flagged if
ANY of its findings raises an alarm — the specialist experiences one flag on the page as "go look".

Case-level scoring reconciles exactly to the stratum sizes the gold defines: the failed and passed
HONEST MISSES (cases that mint no finding at all) are carried in as cases with no drafts —
`drafts=()` — so a failed honest-miss counts as an automatic MISS (the drafter never got the chance)
and a passed honest-miss as trivially clean. The caller MUST include them, or recall is overstated.

Calibration (ECE, over-confidence gap) is the one measure kept PER FINDING — confidence is a
per-draft signal — reusing the frozen-set curve math. Everything the schema exempts or reports
separately (the NA abstention count, the partially_supports sensitivity, the non-trivial FP
denominator, the SC∩ACT construct-validity read) is computed here and travels in `sensitivity_notes`,
since `DrafterScore` is `extra="forbid"` and has no home for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from clearway.eval.confidence import (
    ConfidencePoint,
    bin_points,
    expected_calibration_error,
    overconfidence_gap,
)
from clearway.eval.stats import is_flag, metric_ci_or_empty
from clearway.schemas.models import Conformance, DrafterScore, ExemptMetric

FAILED = "failed"  # ACT expected outcome → a true positive (a real problem the drafter must find)
PASSED = "passed"  # ACT expected outcome → a true negative (clean content it must not flag)

_ECE_EXEMPT_REASON = (
    "single populated confidence bin at this n — there is nothing to bin, so the raw gap is reported "
    "without a CI (the two-figure n+CI exemption)"
)


@dataclass(frozen=True)
class DraftedFinding:
    """One finding's drafted verdict on a case — the fields scoring needs. `cited_sc_ids` is the
    drafter's citation set (already resolved to dotted ids); `confidence` is its self-report."""

    conformance: Conformance
    cited_sc_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class DraftedCase:
    """One ACT case as the drafter answered it. `drafts=()` means the case minted NO finding — a
    failed honest-miss (an automatic recall miss) or a passed honest-miss (trivially clean). `expected`
    is the ACT outcome (`failed`/`passed`); `gold_success_criteria` are the gold SC ids for SC-match."""

    act_testcase_id: str
    rule_name: str
    expected: str
    gold_success_criteria: tuple[str, ...]
    drafts: tuple[DraftedFinding, ...]


def _validate(cases: list[DraftedCase]) -> None:
    bad = {c.expected for c in cases} - {FAILED, PASSED}
    if bad:
        raise ValueError(f"cases carry non-binary ACT outcomes {sorted(bad)} — expected only failed/passed")


def _flagged(case: DraftedCase, *, partial_flags: bool = True) -> bool:
    """Flag-if-any: the case raises an alarm iff at least one of its findings does. An honest-miss
    (no drafts) never flags — a miss on the failed side, correctly-clean on the passed side."""
    return any(is_flag(d.conformance, partial_flags=partial_flags) for d in case.drafts)


def _rules(cases: list[DraftedCase]) -> int:
    """The clustering-honest effective n for a stratum: the number of distinct ACT rules in it. The
    cases within a rule share one drafter framing, so this — not the case count — is the real precision."""
    return len({c.rule_name for c in cases})


def _recall_counts(cases: list[DraftedCase], *, partial_flags: bool = True) -> tuple[int, int]:
    """(flagged, total) over the failed cases — recall. Honest-miss failed cases sit in the denominator
    and never in the numerator, so they count as the misses they are."""
    failed = [c for c in cases if c.expected == FAILED]
    return sum(1 for c in failed if _flagged(c, partial_flags=partial_flags)), len(failed)


def _fp_counts(
    cases: list[DraftedCase], *, partial_flags: bool = True, include_trivial: bool = True
) -> tuple[int, int]:
    """(flagged, total) over the passed cases — the cry-wolf rate. `include_trivial=False` drops the
    passed honest-misses (which mint nothing and so cannot cry wolf), giving the non-trivial denominator."""
    passed = [c for c in cases if c.expected == PASSED]
    if not include_trivial:
        passed = [c for c in passed if c.drafts]
    return sum(1 for c in passed if _flagged(c, partial_flags=partial_flags)), len(passed)


def _sc_match_counts(cases: list[DraftedCase]) -> tuple[int, int]:
    """(matched, total) over the CORRECTLY-FLAGGED failed cases only — SC-match is meaningless on a
    case the drafter never flagged. A case matches when the SC ids cited by its flagging findings
    intersect the gold SC set."""
    flagged_failed = [c for c in cases if c.expected == FAILED and _flagged(c)]
    matched = 0
    for c in flagged_failed:
        cited = {sc for d in c.drafts if is_flag(d.conformance) for sc in d.cited_sc_ids}
        if cited & set(c.gold_success_criteria):
            matched += 1
    return matched, len(flagged_failed)


def _construct_validity_counts(cases: list[DraftedCase]) -> tuple[int, int]:
    """(conformance-correct, total) over the failed cases whose cited SC intersects the ACT SC — the
    construct-validity read: when the drafter cites the right criterion, does it also get conformance
    right? A subset of recall, reported to separate 'right answer' from 'right answer for the right reason'."""
    subset = []
    for c in cases:
        if c.expected != FAILED:
            continue
        cited = {sc for d in c.drafts for sc in d.cited_sc_ids}
        if cited & set(c.gold_success_criteria):
            subset.append(c)
    return sum(1 for c in subset if _flagged(c)), len(subset)


def _calibration_points(cases: list[DraftedCase]) -> list[ConfidencePoint]:
    """One point per drafted finding: its confidence paired with whether its verdict is conformance-
    correct on the primary binary axis (flagged == the case should be flagged). Honest-miss cases have
    no drafts, so they contribute no calibration point."""
    points: list[ConfidencePoint] = []
    for c in cases:
        should_flag = c.expected == FAILED
        for d in c.drafts:
            points.append(ConfidencePoint(confidence=d.confidence, correct=is_flag(d.conformance) == should_flag))
    return points


def _abstained_n(cases: list[DraftedCase]) -> int:
    return sum(1 for c in cases for d in c.drafts if d.conformance is Conformance.NOT_APPLICABLE)


@dataclass(frozen=True)
class DrafterScoring:
    """The drafter's `DrafterScore` (the schema payload) plus the sensitivity/method prose the schema
    has nowhere to put — the report folds `sensitivity_notes` into `AcceptanceScorecard.notes`."""

    score: DrafterScore
    sensitivity_notes: str


def _rate(k: int, n: int) -> float:
    return k / n if n else 0.0


def _sensitivity_notes(cases: list[DraftedCase]) -> str:
    fp_k, _ = _fp_counts(cases)
    fp_nt_k, fp_nt_n = _fp_counts(cases, include_trivial=False)
    r2_k, r2_n = _recall_counts(cases, partial_flags=False)
    f2_k, f2_n = _fp_counts(cases, partial_flags=False)
    cv_k, cv_n = _construct_validity_counts(cases)
    abstained = _abstained_n(cases)
    return (
        f"FP over the {fp_nt_n} non-trivial true negatives (dropping the passed honest-misses that mint "
        f"no finding) = {fp_nt_k}/{fp_nt_n} = {_rate(fp_nt_k, fp_nt_n):.3f}; the headline FP uses all "
        f"true negatives. partially_supports scored as CLEAN instead of FLAGS → recall {r2_k}/{r2_n} = "
        f"{_rate(r2_k, r2_n):.3f}, FP {f2_k}/{f2_n} = {_rate(f2_k, f2_n):.3f}. Construct-validity: among "
        f"failed cases whose cited SC intersects the ACT SC (n={cv_n}), conformance-correct on {cv_k} "
        f"({_rate(cv_k, cv_n):.3f}). not_applicable drafts (n={abstained}) are CLEAN under the primary "
        f"collapse but reported separately as abstained_n, never folded silently. remediation_technique_"
        f"match is not wired (ACT G/F technique metadata is not vendored) — see the not-measured list."
    )


def score_drafter(cases: list[DraftedCase]) -> DrafterScoring:
    """Score the drafter against ACT gold → `DrafterScore` + sensitivity notes.

    Per-case recall/FP/SC-match (with clustering-honest `effective_n` ≈ #rules), per-finding ECE +
    over-confidence gap, and the NA abstention count. Raises if there are no drafted findings at all
    (ECE has nothing to measure) — a benchmark that drafted nothing is an error, not a 0.0.
    """
    _validate(cases)
    recall_k, recall_n = _recall_counts(cases)
    fp_k, fp_n = _fp_counts(cases)
    sc_k, sc_n = _sc_match_counts(cases)
    failed = [c for c in cases if c.expected == FAILED]
    passed = [c for c in cases if c.expected == PASSED]

    points = _calibration_points(cases)
    if not points:
        raise ValueError("no drafted findings to score — the drafter produced nothing to calibrate")
    ece = expected_calibration_error(bin_points(points))

    score = DrafterScore(
        recall=metric_ci_or_empty(recall_k, recall_n, effective_n=_rules(failed)),
        false_positive_rate=metric_ci_or_empty(fp_k, fp_n, effective_n=_rules(passed)),
        sc_citation_match=metric_ci_or_empty(sc_k, sc_n, effective_n=_rules([c for c in failed if _flagged(c)])),
        expected_calibration_error=ExemptMetric(value=ece, n=len(points), exempt_reason=_ECE_EXEMPT_REASON),
        overconfidence_gap=overconfidence_gap(points),
        remediation_technique_match=None,
        abstained_n=_abstained_n(cases),
    )
    return DrafterScoring(score=score, sensitivity_notes=_sensitivity_notes(cases))
