"""The pure drafter scorer: recall / FP / SC-match scored PER CASE against ACT gold, calibration per
finding, honest-misses carried as drafts-less cases. A small hand-built set with known outcomes so
every rate is asserted exactly — this is subject #1's whole score, so a drift here is a wrong headline.
"""

from __future__ import annotations

import pytest

from clearway.eval.drafter_score import (
    DraftedCase,
    DraftedFinding,
    score_drafter,
)
from clearway.schemas.models import Conformance


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


def test_remediation_technique_match_not_wired() -> None:
    assert score_drafter(_sample()).score.remediation_technique_match is None


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
