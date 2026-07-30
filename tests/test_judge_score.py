"""The pure judge scorer: the judge measured AGAINST ACT gold on the conformance axis — a 2×2 with the
two errors kept separate (miss rate exempt, false-alarm rate with a CI), κ vs gold, and the injected
detection rates. Hand-built streams with known cells so every rate is exact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clearway.eval.judge_score import (
    CONFUSION_UNIT_CASE,
    CONFUSION_UNIT_FINDING,
    InjectedResult,
    JudgedCase,
    JudgedDraft,
    NoFindingToJudge,
    collapse_to_cases,
    confusion,
    detection_rate,
    score_judge,
)
from clearway.eval.offline import _judged_drafts, judged_cases


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
    conf = score_judge(_one_of_each(), unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[]).confusion
    assert conf.miss_rate.value == pytest.approx(0.5)
    assert conf.miss_rate.n == 2
    assert conf.miss_rate.exempt_reason


def test_false_alarm_rate_carries_a_ci() -> None:
    """false_alarm / actually-correct = 1/2, with a Wilson interval that brackets it."""
    scored = score_judge(_one_of_each(), unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[])
    fa = scored.confusion.false_alarm_rate
    assert (fa.value, fa.n) == (pytest.approx(0.5), 2)
    assert fa.ci_low < 0.5 < fa.ci_high


def test_kappa_is_zero_when_judge_matches_gold_at_chance() -> None:
    """The balanced one-of-each set has the judge agreeing with gold exactly at chance → κ = 0."""
    conf = score_judge(_one_of_each(), unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[]).confusion
    assert conf.kappa == pytest.approx(0.0, abs=1e-9)


def test_a_rubber_stamp_judge_has_a_high_miss_rate() -> None:
    """A judge that passes everything catches none of the wrong drafts — miss rate pinned at 1.0, the
    exact failure the separate reporting exists to expose (a single κ could hide it)."""
    drafts = [
        _d("heading", act_correct=False, judge_pass=True),
        _d("label", act_correct=False, judge_pass=True),
        _d("link", act_correct=True, judge_pass=True),
    ]
    conf = score_judge(drafts, unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[]).confusion
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
    conf = score_judge(_one_of_each(), unit=CONFUSION_UNIT_FINDING, conformance_flip=flip, sc_swap=swap).confusion
    assert (conf.injected_conformance_flip.value, conf.injected_conformance_flip.n) == (pytest.approx(2 / 3), 3)
    assert (conf.injected_sc_swap.value, conf.injected_sc_swap.n) == (pytest.approx(1.0), 2)


def test_detection_rate_effective_n_is_the_rule_count() -> None:
    """Two injected drafts from ONE rule → effective n of 1, not 2 (the clustering caveat, again)."""
    ci = detection_rate([InjectedResult("heading", caught=True), InjectedResult("heading", caught=False)])
    assert ci.n == 2
    assert ci.effective_n == 1


def test_empty_injection_reads_as_no_data() -> None:
    conf = score_judge(_one_of_each(), unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[]).confusion
    assert conf.injected_conformance_flip.n == 0
    assert (conf.injected_conformance_flip.ci_low, conf.injected_conformance_flip.ci_high) == (0.0, 1.0)


def test_rationale_note_is_recorded() -> None:
    conf = score_judge(
        _one_of_each(),
        unit=CONFUSION_UNIT_FINDING,
        conformance_flip=[],
        sc_swap=[],
        rationale_note="regenerated to argue the flip",
    ).confusion
    assert conf.rationale_coherence_note == "regenerated to argue the flip"


def test_no_natural_drafts_raises() -> None:
    with pytest.raises(ValueError, match="nothing to grade|no judged drafts"):
        score_judge([], unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[])


# --- the case collapse: the pinned observation unit --------------------------------------------


def _c(case_id: str, rule: str, *, act_correct: bool, judge_passes: tuple[bool, ...]) -> JudgedCase:
    return JudgedCase(act_testcase_id=case_id, rule_name=rule, act_correct=act_correct, judge_passes=judge_passes)


def test_a_case_is_released_only_when_every_finding_on_it_was() -> None:
    """Flag-if-any: one raised hand anywhere on the page is the specialist's "go look"."""
    collapsed = collapse_to_cases(
        [
            _c("all-clear", "label", act_correct=True, judge_passes=(True, True, True)),
            _c("one-hand", "label", act_correct=True, judge_passes=(True, False, True)),
            _c("all-hands", "link", act_correct=False, judge_passes=(False, False)),
        ]
    )
    assert [d.judge_pass for d in collapsed] == [True, False, False]
    assert [d.rule_name for d in collapsed] == ["label", "label", "link"]


def test_the_collapse_carries_the_case_level_gold_through_untouched() -> None:
    """`act_correct` is the case's own predicate and the collapse must not re-derive it.

    The case below is right at the case level (gold says flag, one finding flags) while most of its
    findings are wrong at the finding level — exactly the shape that makes the two denominators differ.
    A collapse that inferred the gold side from `judge_passes` would report a `missed_error` here.
    """
    collapsed = collapse_to_cases([_c("mixed", "label", act_correct=True, judge_passes=(True, True, True, True))])
    assert (collapsed[0].act_correct, collapsed[0].judge_pass) == (True, True)


def test_a_case_that_minted_nothing_is_refused_rather_than_read_as_a_release() -> None:
    """A non-minting case was never put to the judge, so it is not one of the judge's observations."""
    with pytest.raises(NoFindingToJudge, match="never put to the judge"):
        collapse_to_cases([_c("honest-miss", "label", act_correct=False, judge_passes=())])


def test_the_collapse_changes_the_cells_and_the_unit_records_which() -> None:
    """The whole reason the unit is mandatory: the same stream scores differently at the two units.

    Three findings on one case — the judge raises one hand — is one `false_alarm` per case and two
    `correct_release`s plus one `false_alarm` per finding. Same judge, same drafts, different matrix.
    """
    findings = [
        _d("label", act_correct=True, judge_pass=True),
        _d("label", act_correct=True, judge_pass=False),
        _d("label", act_correct=True, judge_pass=True),
    ]
    per_finding = score_judge(findings, unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[])
    per_case = score_judge(
        collapse_to_cases([_c("one", "label", act_correct=True, judge_passes=(True, False, True))]),
        unit=CONFUSION_UNIT_CASE,
        conformance_flip=[],
        sc_swap=[],
    )
    assert (per_finding.unit, per_finding.n) == ("finding", 3)
    assert (per_case.unit, per_case.n) == ("case", 1)
    assert (per_finding.confusion.correct_release, per_finding.confusion.false_alarm) == (2, 1)
    assert (per_case.confusion.correct_release, per_case.confusion.false_alarm) == (0, 1)


def test_an_unknown_unit_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown confusion unit"):
        score_judge(_one_of_each(), unit="draft", conformance_flip=[], sc_swap=[])


# --- the collapse on the real judged passes -----------------------------------------------------

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"


def test_the_collapse_moves_the_real_confusion_and_neither_matrix_can_say_which_it_is() -> None:
    """The unit change is material on the only passes that carry per-finding judge output.

    These are the earlier unscoped acceptance passes — 63 judged findings on 47 minting cases — not the
    scoped replay pass the routing comparison uses, which mints 54 findings on 40. Both figures are
    re-derived here rather than restated: the point is that four integers with the same field names
    describe two different measurements, which is why `JudgeScoring` carries the unit out with them.
    """
    artifact = json.loads((_RUNS / "run_1.json").read_text())
    per_finding = score_judge(_judged_drafts(artifact), unit=CONFUSION_UNIT_FINDING, conformance_flip=[], sc_swap=[])
    per_case = score_judge(
        collapse_to_cases(judged_cases(artifact)), unit=CONFUSION_UNIT_CASE, conformance_flip=[], sc_swap=[]
    )
    f, c = per_finding.confusion, per_case.confusion
    assert (per_finding.n, per_case.n) == (63, 47)
    assert (f.correct_release, f.missed_error, f.false_alarm, f.correct_catch) == (31, 16, 8, 8)
    assert (c.correct_release, c.missed_error, c.false_alarm, c.correct_catch) == (24, 9, 7, 7)
    assert f.kappa != c.kappa and f.miss_rate.value != c.miss_rate.value
    assert f.model_dump().keys() == c.model_dump().keys()  # nothing on the shape distinguishes them


def test_the_case_stream_holds_one_entry_per_minting_case_and_no_honest_misses() -> None:
    artifact = json.loads((_RUNS / "run_1.json").read_text())
    cases = judged_cases(artifact)
    assert len(cases) == len(artifact["cases"])
    assert {c.act_testcase_id for c in cases}.isdisjoint({m["act_testcase_id"] for m in artifact["honest_misses"]})
    assert sum(len(c.judge_passes) for c in cases) == len(_judged_drafts(artifact))
