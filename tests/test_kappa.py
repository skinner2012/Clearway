"""Judge-calibration math — pure, offline, fully deterministic.

Cohen's κ against a hand-computed reference (Landis-style 2×2), the perfect / worse-than-chance /
no-variance edges (the [-1, 1] landmine), raw agreement, and the mechanical human-verdict
derivation that puts the human rater on the judge's own categorical scale.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clearway.eval.kappa import (
    KAPPA_THRESHOLD,
    Agreement,
    agreements_from_artifact,
    analyze,
    build_report,
    cohen_kappa,
    human_verdict,
    is_correct,
    raw_agreement,
)
from clearway.schemas.models import CalibrationReport, Citation, Conformance, DraftRow, GoldLabel, JudgeVerdict

C = JudgeVerdict.CORRECT
P = JudgeVerdict.PARTIAL
X = JudgeVerdict.INCORRECT


# --- Cohen's κ ----------------------------------------------------------------


def test_kappa_matches_a_hand_computed_reference() -> None:
    """A textbook 2×2: 20 (yes,yes), 5 (yes,no), 10 (no,yes), 15 (no,no) → p_o=0.7, p_e=0.5, κ=0.4."""
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_kappa_is_one_on_perfect_agreement() -> None:
    a = ["A", "B", "A", "B"]
    assert cohen_kappa(a, a) == pytest.approx(1.0)


def test_kappa_is_negative_when_worse_than_chance() -> None:
    """The landmine: judge worse than chance must surface as a NEGATIVE κ, never clamp to 0."""
    a = ["A", "A", "B", "B"]
    b = ["B", "B", "A", "A"]
    assert cohen_kappa(a, b) == pytest.approx(-1.0)


def test_kappa_is_zero_when_a_rater_has_no_variance() -> None:
    """Both raters constant on one class → κ undefined (1 - p_e == 0) → reported 0.0, not a crash
    and not a misleading 1.0. Raw agreement carries the real (here perfect) story."""
    constant = [C, C, C]
    assert cohen_kappa(constant, constant) == 0.0
    assert raw_agreement(constant, constant) == pytest.approx(1.0)


def test_raw_agreement_is_the_matching_proportion() -> None:
    assert raw_agreement([C, C, P, X], [C, P, P, C]) == pytest.approx(0.5)


@pytest.mark.parametrize("bad", [([C, C], [C]), ([], [])])
def test_misaligned_or_empty_streams_raise(bad: tuple[list, list]) -> None:
    with pytest.raises(ValueError):
        cohen_kappa(*bad)


def test_threshold_is_the_pre_committed_substantial_bar() -> None:
    assert KAPPA_THRESHOLD == 0.6


# --- human verdict derivation -------------------------------------------------


def _gold(*scs: str, conformance: Conformance = Conformance.DOES_NOT_SUPPORT) -> GoldLabel:
    return GoldLabel(
        finding_id="f1",
        gold_success_criteria=list(scs),
        gold_conformance=conformance,
        labeller="tester",
        gold_version="test@1",
    )


def _draft(conformance: Conformance, *scs: str) -> DraftRow:
    return DraftRow(
        finding_id="f1",
        conformance=conformance,
        citations=[Citation(sc_id=s) for s in scs],
        confidence=0.9,
    )


def test_human_verdict_correct_when_both_dimensions_match() -> None:
    assert human_verdict(_draft(Conformance.DOES_NOT_SUPPORT, "1.1.1"), _gold("1.1.1")) is C


def test_human_verdict_partial_when_only_conformance_wrong() -> None:
    assert human_verdict(_draft(Conformance.SUPPORTS, "1.1.1"), _gold("1.1.1")) is P


def test_human_verdict_partial_when_only_citation_wrong() -> None:
    assert human_verdict(_draft(Conformance.DOES_NOT_SUPPORT, "4.1.2"), _gold("1.1.1")) is P


def test_human_verdict_incorrect_when_both_wrong() -> None:
    assert human_verdict(_draft(Conformance.SUPPORTS, "4.1.2"), _gold("1.1.1")) is X


def test_human_verdict_citation_is_exact_set_match() -> None:
    """An extra SC beyond the gold set is a wrong citation — mirrors the judge rubric (a superfluous
    SC is 'wrong or irrelevant'). An empty citation set is likewise not a match."""
    assert human_verdict(_draft(Conformance.DOES_NOT_SUPPORT, "1.1.1", "2.4.4"), _gold("1.1.1")) is P
    assert human_verdict(_draft(Conformance.DOES_NOT_SUPPORT), _gold("1.1.1")) is P


# --- analyze (the full agreement picture) -------------------------------------


def test_analyze_reports_kappa_binary_and_per_class_counts() -> None:
    human = [C, C, P, X, C]
    judge = [C, P, P, X, C]
    result = analyze(human, judge)
    assert isinstance(result, Agreement)
    assert result.n == 5
    assert result.agreement == pytest.approx(0.8)  # 4 of 5 match
    # per-class marginals + the diagonal (both-agree) counts
    assert result.human_counts == {C: 3, P: 1, X: 1}
    assert result.judge_counts == {C: 2, P: 2, X: 1}
    assert result.agree_by_class == {C: 2, P: 1, X: 1}
    # binary collapse: correct-vs-not is [T,T,F,F,T] vs [T,F,F,F,T] — the one miss (C vs P at #1)
    # is a T-vs-F disagreement → p_o=0.8, p_e=0.48, κ=0.32/0.52
    assert result.kappa_binary == pytest.approx(0.32 / 0.52)


def test_is_correct_collapses_partial_and_incorrect_to_not_correct() -> None:
    assert is_correct(C) is True
    assert is_correct(P) is False
    assert is_correct(X) is False


# --- report assembly from a (synthetic) frozen artifact ----------------------


def _row(
    lever: str, draft_conf: str, draft_scs: list[str], gold_conf: str, gold_scs: list[str], jc: bool, jconf: bool
) -> dict:
    # verdict/rationale are deliberately bogus — agreements_from_artifact must RECOMPUTE from raw,
    # never read the stored 3-way verdict.
    return {
        "finding_id": "f",
        "lever": lever,
        "draft": {"conformance": draft_conf, "cited_sc_ids": draft_scs, "confidence": 0.9, "remediation": ""},
        "gold": {"gold_success_criteria": gold_scs, "gold_conformance": gold_conf},
        "judge": {"citation_correct": jc, "conformance_correct": jconf, "verdict": "BOGUS", "rationale": "x"},
    }


def test_agreements_from_artifact_recomputes_verdicts_from_raw() -> None:
    artifact = {
        "drafts": [
            _row("natural", "does_not_support", ["1.1.1"], "does_not_support", ["1.1.1"], True, True),  # correct
            _row("false_supports", "supports", ["1.1.1"], "does_not_support", ["1.1.1"], True, False),  # partial
            _row("natural", "supports", ["1.1.1"], "supports", ["1.1.1"], True, True),  # correct
            _row("wrong_sc", "does_not_support", ["4.1.2"], "does_not_support", ["1.1.1"], False, True),  # partial
        ]
    }
    balanced, natural = agreements_from_artifact(artifact)
    # balanced = all four; both raters recompute to [correct, partial, correct, partial] → perfect
    assert balanced.n == 4
    assert balanced.agreement == pytest.approx(1.0)
    assert balanced.kappa == pytest.approx(1.0)
    assert balanced.human_counts == {C: 2, P: 2, X: 0}
    # natural = the two lever=="natural" rows, both correct → constant streams → κ degenerate (0.0)
    assert natural.n == 2
    assert natural.agreement == pytest.approx(1.0)
    assert natural.kappa == 0.0


def _agreement(kappa: float) -> Agreement:
    return Agreement(
        n=30,
        kappa=kappa,
        kappa_binary=kappa,
        agreement=0.8,
        human_counts={C: 10, P: 10, X: 10},
        judge_counts={C: 10, P: 10, X: 10},
        agree_by_class={C: 8, P: 8, X: 8},
    )


def test_build_report_trusts_when_balanced_kappa_clears_the_bar() -> None:
    when = datetime(2026, 7, 13, tzinfo=timezone.utc)
    report = build_report(_agreement(0.7), _agreement(0.1), created_at=when)
    assert isinstance(report, CalibrationReport)
    assert report.judge_kappa == pytest.approx(0.7)  # the BALANCED κ is the gate
    assert report.judge_trusted is True
    assert report.kappa_threshold == KAPPA_THRESHOLD
    assert report.n == 30
    assert report.confidence_bins == []  # T4 fills the curve
    assert report.created_at == when
    assert "0.700" in report.bias_notes  # both κ's disclosed in the honesty note


def test_build_report_distrusts_when_below_the_bar() -> None:
    report = build_report(_agreement(0.5), _agreement(0.0), created_at=datetime(2026, 7, 13, tzinfo=timezone.utc))
    assert report.judge_trusted is False


def test_build_report_accepts_explicit_bias_notes() -> None:
    report = build_report(
        _agreement(0.7), _agreement(0.1), created_at=datetime(2026, 7, 13, tzinfo=timezone.utc), bias_notes="custom"
    )
    assert report.bias_notes == "custom"
