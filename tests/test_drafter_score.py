"""The pure drafter scorer: recall / FP / SC-match scored PER CASE against ACT gold, calibration per
finding, honest-misses carried as drafts-less cases. A small hand-built set with known outcomes so
every rate is asserted exactly — this is subject #1's whole score, so a drift here is a wrong headline.
"""

from __future__ import annotations

import pytest

from clearway.eval.drafter_score import (
    DraftedCase,
    DraftedFinding,
    _sc_precision_counts,
    score_drafter,
)
from clearway.schemas.models import Conformance, TechniqueMatch

_TECHNIQUE_MATCH = TechniqueMatch(
    kappa=0.5,
    n=16,
    ci_low=0.1,
    ci_high=0.9,
    seed=0,
    resamples=10_000,
    degenerate_share=0.0,
    constant_classifier=False,
    raw_agreement=0.75,
    covered_classes=["document-title", "label"],
    uncovered_classes=["empty-heading", "link-name"],
    classifier_model="fake-classifier",
)


def _f(conformance: Conformance, *sc: str, confidence: float = 0.8) -> DraftedFinding:
    return DraftedFinding(conformance=conformance, cited_sc_ids=tuple(sc), confidence=confidence)


def _case(rule: str, expected: str, gold: tuple[str, ...], *drafts: DraftedFinding) -> DraftedCase:
    return DraftedCase(
        act_testcase_id=f"{rule}-{expected}-{len(drafts)}",
        rule_name=rule,
        expected=expected,
        gold_success_criteria=gold,
        drafts=tuple(drafts),
    )


DNS = Conformance.DOES_NOT_SUPPORT
SUP = Conformance.SUPPORTS
PARTIAL = Conformance.PARTIALLY_SUPPORTS
NA = Conformance.NOT_APPLICABLE


def _sample() -> list[DraftedCase]:
    return [
        # --- failed (true positives) ---
        _case("heading", "failed", ("2.4.6",), _f(DNS, "2.4.6", confidence=0.9)),  # hit, SC match
        _case("heading", "failed", ("2.4.6",), _f(SUP, "2.4.6", confidence=0.8)),  # miss (drafter said clean)
        _case("link", "failed", ("2.4.9",)),  # honest-miss → auto miss (no drafts)
        _case("link", "failed", ("2.4.9",), _f(DNS, "1.3.1", confidence=0.7)),  # hit but wrong SC
        # --- passed (true negatives) ---
        _case("label", "passed", ("2.4.6",), _f(SUP, "2.4.6", confidence=0.9)),  # correctly clean
        _case("label", "passed", ("2.4.6",), _f(DNS, "2.4.6", confidence=0.6)),  # cry wolf → FP
        _case("title", "passed", ("2.4.2",)),  # passed honest-miss → trivially clean
        _case("title", "passed", ("2.4.2",), _f(SUP, "2.4.2"), _f(PARTIAL, "2.4.2")),  # partial flags → FP
        _case("label", "passed", ("2.4.6",), _f(NA, "2.4.6")),  # abstain → clean, counted separately
    ]


def test_recall_is_per_case_over_all_failed_including_honest_miss() -> None:
    """2 of 4 failed cases flagged (the honest-miss and the missed case are misses); effective_n is the
    2 distinct failed rules, not the 4 cases."""
    r = score_drafter(_sample()).score.recall
    assert (r.value, r.n, r.effective_n) == (pytest.approx(0.5), 4, 2)


def test_false_positive_rate_uses_flag_if_any_over_all_true_negatives() -> None:
    """2 of 5 passed cases cry wolf (the cry-wolf case and the partially_supports case); the passed
    honest-miss sits in the denominator as trivially clean."""
    fp = score_drafter(_sample()).score.false_positive_rate
    assert (fp.value, fp.n, fp.effective_n) == (pytest.approx(0.4), 5, 2)


def test_sc_match_is_over_correctly_flagged_failed_only() -> None:
    """Of the 2 correctly-flagged failed cases, 1 cited a gold SC (the other cited 1.3.1 for a 2.4.9
    finding) — so SC-match is 1/2, computed only where the drafter actually flagged."""
    sc = score_drafter(_sample()).score.sc_citation_match
    assert (sc.value, sc.n) == (pytest.approx(0.5), 2)


def test_sc_precision_is_id_level_over_the_same_subset_as_the_hit_rate() -> None:
    """The other side of the SC∩ACT read, and the reason it exists. The two correctly-flagged failed
    cases cite one id each — "2.4.6" (gold) and "1.3.1" (not gold for a 2.4.9 case) — so precision is
    1/2 over 2 cited IDS, where the headline hit rate is 1/2 over 2 CASES. They come apart the moment
    a row cites broadly, which is what a citation budget changes."""
    assert _sc_precision_counts(_sample()) == (1, 2)

    broad = _sample() + [_case("heading", "failed", ("2.4.6",), _f(DNS, "2.4.6", "1.3.1", "4.1.2", "2.4.2"))]
    assert _sc_precision_counts(broad) == (2, 6), "citing four ids to hit one buys the hit rate, costs precision"
    assert score_drafter(broad).score.sc_citation_match.value == pytest.approx(2 / 3)


def test_sc_precision_reads_only_the_flagging_findings_and_never_a_judge_field() -> None:
    """A clean draft's citations are not evidence about a flag, so a non-flagging draft on a flagged
    case contributes nothing — the same subset rule the hit rate uses. And nothing here consults a
    judge: `cited_sc_ids` against `gold_success_criteria` is the whole computation."""
    cases = [_case("heading", "failed", ("2.4.6",), _f(DNS, "2.4.6"), _f(SUP, "1.3.1", "4.1.2"))]
    assert _sc_precision_counts(cases) == (1, 1)


def test_sensitivity_notes_report_precision_beside_the_headline_hit_rate() -> None:
    """Both sides travel together, or a narrowed citation set reads as a pure loss (hit rate down)
    and a broadened one as a pure win."""
    notes = score_drafter(_sample()).sensitivity_notes
    assert "SC-citation PRECISION" in notes
    assert "1/2 = 0.500" in notes  # 1 of 2 cited ids in gold
    assert "1.00 ids cited per case" in notes


def test_abstentions_counted_separately_not_as_flags() -> None:
    """The single not_applicable draft is CLEAN (does not cry wolf) yet surfaces as abstained_n."""
    score = score_drafter(_sample()).score
    assert score.abstained_n == 1


def test_calibration_is_per_finding_and_exempt_from_ci() -> None:
    """8 drafted findings → 8 calibration points (honest-miss cases contribute none); ECE ships as an
    exempt figure carrying its n and a mandatory reason, and the over-confidence gap is a real number."""
    score = score_drafter(_sample()).score
    assert score.expected_calibration_error.n == 8
    assert 0.0 <= score.expected_calibration_error.value <= 1.0
    assert score.expected_calibration_error.exempt_reason
    assert -1.0 <= score.overconfidence_gap <= 1.0


def test_remediation_technique_match_is_none_only_when_no_classification_pass_ran() -> None:
    """The metric exists and the ACT technique gold is vendored; absent a classification pass there is
    simply no number, and the notes say that rather than implying the metric is unavailable."""
    scoring = score_drafter(_sample())
    assert scoring.score.remediation_technique_match is None
    assert "no technique-classification pass ran" in scoring.sensitivity_notes
    assert "2 of 4 scored classes" in scoring.sensitivity_notes


def test_remediation_technique_match_is_carried_through_when_supplied() -> None:
    """The pure scorer never calls a model: the fix-direction metric is computed by the classification
    pass and threaded onto the score untouched, with its coverage limit repeated in the notes."""
    scoring = score_drafter(_sample(), technique_match=_TECHNIQUE_MATCH)
    assert scoring.score.remediation_technique_match == _TECHNIQUE_MATCH
    assert "CHANCE-CORRECTED" in scoring.sensitivity_notes
    assert "2 of 4 scored classes (document-title, label)" in scoring.sensitivity_notes
    assert "empty-heading, link-name carry no ACT technique requirement" in scoring.sensitivity_notes
    assert "never" in scoring.sensitivity_notes and "USEFUL" in scoring.sensitivity_notes


def test_sensitivity_notes_carry_the_flagged_alternatives() -> None:
    """The notes must state the non-trivial FP denominator (4, dropping the passed honest-miss), the
    partially_supports-as-clean recompute (FP falls to 1/5), and the construct-validity subset."""
    notes = score_drafter(_sample()).sensitivity_notes
    assert "2/4" in notes  # non-trivial FP: 2 flagged over 4 minting true negatives
    assert "1/5" in notes  # partially_supports scored clean → only the genuine cry-wolf remains
    assert "abstained_n" in notes
    assert "technique" in notes


def test_partially_supports_is_a_flag_under_the_primary_rule() -> None:
    """The title case flags ONLY because of its partially_supports finding — proof the primary collapse
    treats partial as an alarm (the sensitivity line shows the other reading)."""
    only_partial = [_case("title", "passed", ("2.4.2",), _f(PARTIAL, "2.4.2"))]
    # one true negative, flagged by a partial → FP 1/1 under the primary rule
    fp = score_drafter([*only_partial, _case("heading", "failed", ("2.4.6",), _f(DNS, "2.4.6"))]).score
    assert fp.false_positive_rate.value == pytest.approx(1.0)


def test_empty_stratum_reports_no_data_not_a_measured_zero() -> None:
    """With no passed cases the FP rate is an honest empty triple (n=0, CI [0,1]), not a measured 0.0."""
    fp = score_drafter([_case("heading", "failed", ("2.4.6",), _f(DNS, "2.4.6"))]).score.false_positive_rate
    assert (fp.n, fp.ci_low, fp.ci_high) == (0, 0.0, 1.0)


def test_no_drafted_findings_raises() -> None:
    """A set of only honest-misses has nothing to calibrate — an error, never a fabricated 0.0 ECE."""
    with pytest.raises(ValueError, match="nothing to calibrate"):
        score_drafter([_case("link", "failed", ("2.4.9",)), _case("title", "passed", ("2.4.2",))])


def test_non_binary_outcome_rejected() -> None:
    with pytest.raises(ValueError, match="non-binary"):
        score_drafter([_case("heading", "inapplicable", ("2.4.6",), _f(SUP, "2.4.6"))])
