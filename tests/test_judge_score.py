"""The pure judge scorer: the judge measured AGAINST ACT gold on the conformance axis — a 2×2 with the
two errors kept separate (miss rate exempt, false-alarm rate with a CI), κ vs gold, and the injected
detection rates. Hand-built streams with known cells so every rate is exact.
"""

from __future__ import annotations

import pytest

from clearway.eval.judge_score import (
    InjectedResult,
    JudgedDraft,
    confusion,
    detection_rate,
    score_judge,
)


def _d(rule: str, *, act_correct: bool, judge_pass: bool) -> JudgedDraft:
    return JudgedDraft(rule_name=rule, act_correct=act_correct, judge_pass=judge_pass)


def _one_of_each() -> list[JudgedDraft]:
    return [
        _d("heading", act_correct=True, judge_pass=True),  # correct_release
        _d("label", act_correct=False, judge_pass=True),  # missed_error (dangerous)
        _d("link", act_correct=True, judge_pass=False),  # false_alarm (annoying)
        _d("title", act_correct=False, judge_pass=False),  # correct_catch
    ]


def test_confusion_tallies_the_four_cells() -> None:
    c = confusion(_one_of_each())
    assert (c.correct_release, c.missed_error, c.false_alarm, c.correct_catch) == (1, 1, 1, 1)
    assert (c.wrong_total, c.correct_total) == (2, 2)


def test_miss_rate_is_the_dangerous_half_and_exempt() -> None:
    """missed_error / naturally-wrong = 1/2; it ships exempt (its n, a mandatory reason, no CI)."""
    conf = score_judge(_one_of_each(), conformance_flip=[], sc_swap=[])
    assert conf.miss_rate.value == pytest.approx(0.5)
    assert conf.miss_rate.n == 2
    assert conf.miss_rate.exempt_reason


def test_false_alarm_rate_carries_a_ci() -> None:
    """false_alarm / actually-correct = 1/2, with a Wilson interval that brackets it."""
    fa = score_judge(_one_of_each(), conformance_flip=[], sc_swap=[]).false_alarm_rate
    assert (fa.value, fa.n) == (pytest.approx(0.5), 2)
    assert fa.ci_low < 0.5 < fa.ci_high


def test_kappa_is_zero_when_judge_matches_gold_at_chance() -> None:
    """The balanced one-of-each set has the judge agreeing with gold exactly at chance → κ = 0."""
    conf = score_judge(_one_of_each(), conformance_flip=[], sc_swap=[])
    assert conf.kappa == pytest.approx(0.0, abs=1e-9)


def test_a_rubber_stamp_judge_has_a_high_miss_rate() -> None:
    """A judge that passes everything catches none of the wrong drafts — miss rate pinned at 1.0, the
    exact failure the separate reporting exists to expose (a single κ could hide it)."""
    drafts = [
        _d("heading", act_correct=False, judge_pass=True),
        _d("label", act_correct=False, judge_pass=True),
        _d("link", act_correct=True, judge_pass=True),
    ]
    conf = score_judge(drafts, conformance_flip=[], sc_swap=[])
    assert (conf.missed_error, conf.correct_catch) == (2, 0)
    assert conf.miss_rate.value == pytest.approx(1.0)


def test_injected_detection_is_the_fraction_caught_with_ci() -> None:
    """Detection = caught / injected, each an upper bound; the two mutations report independently."""
    flip = [
        InjectedResult("heading", caught=True),
        InjectedResult("label", caught=True),
        InjectedResult("link", caught=False),
    ]
    swap = [InjectedResult("title", caught=True), InjectedResult("title", caught=True)]
    conf = score_judge(_one_of_each(), conformance_flip=flip, sc_swap=swap)
    assert (conf.injected_conformance_flip.value, conf.injected_conformance_flip.n) == (pytest.approx(2 / 3), 3)
    assert (conf.injected_sc_swap.value, conf.injected_sc_swap.n) == (pytest.approx(1.0), 2)


def test_detection_rate_effective_n_is_the_rule_count() -> None:
    """Two injected drafts from ONE rule → effective n of 1, not 2 (the clustering caveat, again)."""
    ci = detection_rate([InjectedResult("heading", caught=True), InjectedResult("heading", caught=False)])
    assert ci.n == 2
    assert ci.effective_n == 1


def test_empty_injection_reads_as_no_data() -> None:
    conf = score_judge(_one_of_each(), conformance_flip=[], sc_swap=[])
    assert conf.injected_conformance_flip.n == 0
    assert (conf.injected_conformance_flip.ci_low, conf.injected_conformance_flip.ci_high) == (0.0, 1.0)


def test_rationale_note_is_recorded() -> None:
    conf = score_judge(_one_of_each(), conformance_flip=[], sc_swap=[], rationale_note="regenerated to argue the flip")
    assert conf.rationale_coherence_note == "regenerated to argue the flip"


def test_no_natural_drafts_raises() -> None:
    with pytest.raises(ValueError, match="nothing to grade|no judged drafts"):
        score_judge([], conformance_flip=[], sc_swap=[])
