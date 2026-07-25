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
denominator, the SC∩ACT construct-validity read, the SC-citation precision) is computed here and
travels in `sensitivity_notes`, since `DrafterScore` is `extra="forbid"` and has no home for them.

**The SC∩ACT reads are the whole citation measurement, and they are judge-free by construction** —
`cited_sc_ids` intersected with `gold_success_criteria`, nothing else consulted. `sc_citation_match`
(the schema field) is the case-level hit rate: did the drafter cite *any* gold criterion. It is a
one-sided ruler — a row that cites broadly wins it for free — so `sensitivity_notes` carries its
other side, the id-level precision, computed over the same subset. Both are strict: a real but
not-gold citation counts as wrong, so the pair is a *direction and a floor*, never evidence that a
citation is useful.

The one number this module does not compute is `remediation_technique_match`: inferring which WCAG
technique a drafted fix implies takes a model, and this scorer stays pure. It is computed by the
technique-classification pass (`technique_match`) and PASSED IN, so the score carries it without this
module ever making a call. Absent that pass it stays `None` — no pass, no number.
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
from clearway.schemas.models import Conformance, DrafterScore, ExemptMetric, TechniqueMatch

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


def _sc_precision_counts(cases: list[DraftedCase]) -> tuple[int, int]:
    """(cited-and-gold, cited) over the SAME subset `_sc_match_counts` scores — the correctly-flagged
    failed cases — micro-averaged over SC ids rather than over cases.

    `sc_citation_match` asks *did any cited id land in gold*, which a broad citer wins for free: cite
    five criteria and one of them is likely right. Precision asks *what share of what it cited was
    right*, and moves the other way under the same behaviour. The two together are what make a
    citation-budget change legible — narrowing the citation set can only lower the first and can only
    raise the second, so reporting either alone reads as a win or a loss that isn't there.

    Deterministic, gold-only, no judge — the same ruler as every other number here.
    """
    matched = cited_total = 0
    for c in cases:
        if c.expected != FAILED or not _flagged(c):
            continue
        cited = {sc for d in c.drafts if is_flag(d.conformance) for sc in d.cited_sc_ids}
        matched += len(cited & set(c.gold_success_criteria))
        cited_total += len(cited)
    return matched, cited_total


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
    has nowhere to put — the report folds `sensitivity_notes` into `OfflineEvalScorecard.notes`."""

    score: DrafterScore
    sensitivity_notes: str


def _rate(k: int, n: int) -> float:
    return k / n if n else 0.0


def _technique_note(technique_match: TechniqueMatch | None) -> str:
    """The remediation-direction sentence for the notes, in whichever of its two truthful forms applies.

    With a metric it reports κ and its limits from the shape alone. Without one it says the pass did not
    run and states the coverage limit — imported lazily from the classification module, which imports
    this one transitively, so the coverage stays DERIVED from the gold rather than restated here."""
    if technique_match is None:
        from clearway.eval.technique_match import coverage_note

        return (
            "remediation_technique_match is None: no technique-classification pass ran for this score. The "
            "ACT technique gold IS vendored (the export's wcag-technique keys), so the metric is available; "
            f"it simply was not computed here. {coverage_note()}"
        )
    covered = ", ".join(technique_match.covered_classes)
    uncovered = ", ".join(technique_match.uncovered_classes)
    n_classes = len(technique_match.covered_classes) + len(technique_match.uncovered_classes)
    return (
        f"remediation_technique_match is CHANCE-CORRECTED: Cohen's κ {technique_match.kappa:+.3f} "
        f"(n={technique_match.n}, bootstrap CI [{technique_match.ci_low:+.3f}, {technique_match.ci_high:+.3f}], "
        f"raw agreement {technique_match.raw_agreement:.3f} — context and the constant-classifier tell, never "
        f"the metric, because rule-level technique gold lets a constant answer score high on raw match). "
        f"Coverage is {len(technique_match.covered_classes)} of {n_classes} scored classes ({covered}); "
        f"{uncovered} carry no ACT technique requirement and are absent from the number, not passing it. It "
        "scores DIRECTION — a fix pointing at the right technique — as a floor and a regression guard; whether "
        "a fix is USEFUL still needs a human specialist and is unmeasured."
    )


def _sensitivity_notes(cases: list[DraftedCase], technique_match: TechniqueMatch | None) -> str:
    fp_k, _ = _fp_counts(cases)
    fp_nt_k, fp_nt_n = _fp_counts(cases, include_trivial=False)
    r2_k, r2_n = _recall_counts(cases, partial_flags=False)
    f2_k, f2_n = _fp_counts(cases, partial_flags=False)
    cv_k, cv_n = _construct_validity_counts(cases)
    sp_k, sp_n = _sc_precision_counts(cases)
    sc_k, sc_cases = _sc_match_counts(cases)
    abstained = _abstained_n(cases)
    return (
        f"FP over the {fp_nt_n} non-trivial true negatives (dropping the passed honest-misses that mint "
        f"no finding) = {fp_nt_k}/{fp_nt_n} = {_rate(fp_nt_k, fp_nt_n):.3f}; the headline FP uses all "
        f"true negatives. partially_supports scored as CLEAN instead of FLAGS → recall {r2_k}/{r2_n} = "
        f"{_rate(r2_k, r2_n):.3f}, FP {f2_k}/{f2_n} = {_rate(f2_k, f2_n):.3f}. Construct-validity: among "
        f"failed cases whose cited SC intersects the ACT SC (n={cv_n}), conformance-correct on {cv_k} "
        f"({_rate(cv_k, cv_n):.3f}). SC-citation PRECISION over the same {sc_cases} correctly-flagged failed "
        f"cases the headline sc_citation_match ({sc_k}/{sc_cases}) is taken over, micro-averaged over ids "
        f"instead of cases: {sp_k}/{sp_n} = {_rate(sp_k, sp_n):.3f} of the SC ids cited are in the ACT gold "
        f"set, {_rate(sp_n, sc_cases):.2f} ids cited per case. Report the pair — the headline alone rewards "
        f"citing broadly, precision alone rewards citing nothing. not_applicable drafts (n={abstained}) are "
        f"CLEAN under the primary "
        f"collapse but reported separately as abstained_n, never folded silently. "
        f"{_technique_note(technique_match)}"
    )


def score_drafter(cases: list[DraftedCase], *, technique_match: TechniqueMatch | None = None) -> DrafterScoring:
    """Score the drafter against ACT gold → `DrafterScore` + sensitivity notes.

    Per-case recall/FP/SC-match (with clustering-honest `effective_n` ≈ #rules), per-finding ECE +
    over-confidence gap, and the NA abstention count. Raises if there are no drafted findings at all
    (ECE has nothing to measure) — a benchmark that drafted nothing is an error, not a 0.0.

    `technique_match` is the remediation fix-direction metric, computed by the classification pass and
    carried through untouched — this scorer stays pure and makes no call to obtain it. Left unset it is
    `None`, and the notes say so rather than implying the metric does not exist.
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
        remediation_technique_match=technique_match,
        abstained_n=_abstained_n(cases),
    )
    return DrafterScoring(score=score, sensitivity_notes=_sensitivity_notes(cases, technique_match))
