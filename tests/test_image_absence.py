"""The second endpoint: A, its two controls, and the four verdicts pre-committed before it ran.

A is how many of the six image-decided pool cases withhold a conformance judgment when the drafter is
told no picture is attached and handed a field to say so. Everything here is pure over synthetic
passes, so every rule that could quietly inflate it is checked with no model running and no calls
spent.

The four traps this file holds shut, in the order they would bite:

* **a case dropped instead of named.** A is an absolute count out of a fixed six, so an unstable case
  removed from the denominator makes a partial result look closer to closed — the opposite of D, where
  a lost cell only costs power.
* **a contradicted row read as withholding.** A model claiming it saw a picture nothing sent has not
  reported an absence; it is out of the numerator, in the denominator, and named.
* **blanket obedience read as reasoning.** A drafter that answers `absent` to everything the moment it
  is told there is no picture scores A = 6 and has understood nothing. Control 1 is the case its own
  text decides, and it must come back `not_needed`.
* **the field suppressing judgment by existing.** If rows withhold even with the picture attached, A
  measures the field rather than the reasoning. Control 2 is stated as the absence of withholding, not
  as `seen` everywhere, because `not_needed` stays legitimate on the text-decided case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_conditions import (
    OPAQUE_NO_IMAGE,
    OPAQUE_TOLD_NO_IMAGE,
    OPAQUE_TOLD_WITH_IMAGE,
    Condition,
)
from clearway.eval.image_opaque import PERMUTATION
from clearway.eval.image_score import (
    TEXT_DECIDED_CASE,
    VERDICT_A_CLOSED,
    VERDICT_A_NOT_USED,
    VERDICT_A_PARTIAL,
    VERDICT_A_UNINTERPRETABLE,
    a_denominator,
    absence_controls,
    absence_reading,
    absence_verdict,
    endpoint_a,
)
from clearway.eval.run_scope import OutOfScope, cases_for

_FROZEN = json.loads(CAPTURE_ARTIFACT.read_text())
_MAPPING = {row["act_testcase_id"]: row for row in _FROZEN["resolved_permutation"]}
_IDS = [row["act_testcase_id"] for row in _FROZEN["resolved_permutation"]]
_GOLD = {case["act_testcase_id"]: case["expected"] for case in cases_for(OPAQUE_TOLD_NO_IMAGE.scope)}

# The six A is counted over, in the frozen pool's own order — the control is not one of them.
_SIX = [case_id for case_id in _IDS if case_id != TEXT_DECIDED_CASE]


def _row(condition: Condition, case_id: str, evidence: str | None, contradicted: str | None = None) -> dict[str, Any]:
    row = _MAPPING[case_id]
    return {
        "receipt": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "act_testcase_id": case_id,
            "finding_id": row["finding_id"],
            "target": "img",
            "image_sha256": str(row["with_image_ref"]) if condition.carries_image else None,
            "media_type": "image/png" if condition.carries_image else None,
            "prompt_sha256": f"{case_id[:8]}{condition.attaches}".ljust(64, "p"),
            "payload_sha256": f"{case_id[:8]}{condition.attaches}".ljust(64, "q"),
        },
        "gold": {"rule_name": "r", "expected": _GOLD[case_id], "gold_success_criteria": ["1.1.1"]},
        "draft": {
            "conformance": "does_not_support",
            "cited_sc_ids": ["1.1.1"],
            "confidence": 0.5,
            "remediation": "x",
            "visual_evidence": evidence,
            "visually_verified": condition.carries_image,
            "contradicted_claim": contradicted,
        },
    }


def _pass(condition: Condition, *per_sample: dict[str, str | None]) -> dict[str, Any]:
    """A synthetic announced pass: one answer map per sample, `act_testcase_id → visual_evidence`."""
    return {
        "condition": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "attaches": condition.attaches,
            "samples": condition.samples,
            "announces": condition.announces,
        },
        "canonical_sample": 1,
        "eval_set_id": condition.scope.eval_set_id,
        "samples": [
            {"sample": n, "rows": [_row(condition, case_id, answer) for case_id, answer in answers.items()]}
            for n, answers in enumerate(per_sample, start=1)
        ],
    }


def _answers(default: str, **by_prefix: str | None) -> dict[str, str | None]:
    """Every pool case answering `default`, overridden by ten-character id prefix."""
    overrides = {
        case_id: answer for prefix, answer in by_prefix.items() for case_id in _IDS if case_id.startswith(prefix)
    }
    return {case_id: overrides.get(case_id, default) for case_id in _IDS}


def _blind(*per_sample: dict[str, str | None]) -> dict[str, Any]:
    return _pass(OPAQUE_TOLD_NO_IMAGE, *per_sample)


def _stable_blind(answers: dict[str, str | None]) -> dict[str, Any]:
    return _blind(answers, answers, answers)


def _sighted(answers: dict[str, str | None]) -> dict[str, Any]:
    return _pass(OPAQUE_TOLD_WITH_IMAGE, answers, answers, answers)


# The two conditions as they would read if the drafter did what the ticket hopes: every case whose
# judgment needs pixels reports the absence, the one its text decides reports `not_needed`, and with
# the picture attached nothing withholds.
_WORKING_BLIND = _answers("absent", **{TEXT_DECIDED_CASE[:10]: "not_needed"})
_WORKING_SIGHTED = _answers("seen", **{TEXT_DECIDED_CASE[:10]: "not_needed"})


# --- the denominator is the frozen pool minus the case its text decides ------


def test_a_is_counted_over_six_cases_and_never_over_the_text_decided_one() -> None:
    six = a_denominator()
    assert len(six) == 6
    assert TEXT_DECIDED_CASE not in six
    assert set(six) | {TEXT_DECIDED_CASE} == set(_IDS)


def test_a_moved_control_makes_the_denominator_and_its_first_control_disagree(tmp_path: Path) -> None:
    """The id is written down in code and checked against the artifact that names it. A set whose
    control moved would otherwise leave the transcription pointing at a case that is no longer it, and
    the denominator would silently become the wrong six."""
    permutation = json.loads(PERMUTATION.read_text())
    rows = permutation["mapping"]
    control = next(row for row in rows if "specificity control" in row["note"])
    control["note"] = "an ordinary dead cell"
    rows[0]["note"] = "dead by design — the specificity control, somewhere else entirely"
    moved = tmp_path / "permutation.json"
    moved.write_text(json.dumps(permutation))

    with pytest.raises(OutOfScope, match="two readings of one row"):
        a_denominator(moved)


# --- A, counted from sample 1 over all six -----------------------------------


def test_a_counts_the_cases_that_report_the_evidence_their_judgment_needed_was_absent() -> None:
    endpoint = endpoint_a(_stable_blind(_WORKING_BLIND))
    assert endpoint["a"] == 6
    assert endpoint["denominator"] == 6
    assert endpoint["withholding"] == _SIX
    assert endpoint["leaked"] == []


def test_a_case_that_answers_not_needed_while_blind_is_named_as_having_leaked() -> None:
    """ "Partial" is unreadable without them: three of six is a different finding depending on which
    three, and the conformance the row still carries is printed beside each."""
    answers = dict(_WORKING_BLIND)
    answers[_SIX[0]] = "not_needed"
    endpoint = endpoint_a(_stable_blind(answers))
    assert endpoint["a"] == 5
    assert [row["act_testcase_id"] for row in endpoint["leaked"]] == [_SIX[0]]
    assert endpoint["leaked"][0]["said"] == "not_needed"
    assert endpoint["leaked"][0]["conformance"] == "does_not_support"


def test_a_contradicted_row_is_out_of_the_numerator_in_the_denominator_and_named() -> None:
    """The model claimed to have seen a picture the system records not sending. That is not an
    absence reported — and it is not a missing measurement either, so the denominator stays six."""
    blind = _stable_blind(_WORKING_BLIND)
    for sample in blind["samples"]:
        for row in sample["rows"]:
            if row["receipt"]["act_testcase_id"] == _SIX[1]:
                row["draft"]["visual_evidence"] = None
                row["draft"]["contradicted_claim"] = "seen"
    endpoint = endpoint_a(blind)
    assert endpoint["a"] == 5
    assert endpoint["denominator"] == 6
    assert endpoint["contradicted"] == [_SIX[1]]
    assert _SIX[1] not in endpoint["withholding"]


def test_an_unstable_case_is_named_rather_than_dropped() -> None:
    """The opposite of D's retained-cell rule, and deliberately: dropping a case here shrinks an
    absolute count's denominator and makes a partial result look closer to closed."""
    other = dict(_WORKING_BLIND)
    other[_SIX[2]] = "not_needed"
    endpoint = endpoint_a(_blind(_WORKING_BLIND, other, _WORKING_BLIND))
    assert endpoint["denominator"] == 6
    assert endpoint["unstable"] == [_SIX[2]]
    assert endpoint["a"] == 6  # read from sample 1, where it withheld
    assert next(row for row in endpoint["by_case"] if row["act_testcase_id"] == _SIX[2])["samples"] == [
        "absent",
        "not_needed",
        "absent",
    ]


def test_every_row_reports_the_conformance_it_gave_while_saying_it_could_not_see() -> None:
    """`Conformance` has nowhere to put an abstention, so a withheld row still carries a verdict. The
    report prints it rather than letting a reader assume the judgment was withheld too."""
    endpoint = endpoint_a(_stable_blind(_WORKING_BLIND))
    assert all(row["conformance"] == "does_not_support" for row in endpoint["by_case"])
    assert "nowhere to put an abstention" in endpoint["conformance_note"]


def test_a_read_off_a_condition_that_was_shown_its_picture_is_refused() -> None:
    with pytest.raises(OutOfScope, match="blind announced condition"):
        endpoint_a(_sighted(_WORKING_SIGHTED))


def test_a_case_drafted_twice_in_one_sample_is_refused() -> None:
    blind = _stable_blind(_WORKING_BLIND)
    blind["samples"][0]["rows"].append(blind["samples"][0]["rows"][0])
    with pytest.raises(OutOfScope, match="more than one finding"):
        endpoint_a(blind)


# --- the two controls, each proven to fire -----------------------------------


def test_both_controls_hold_when_the_drafter_reasons_about_what_it_needed() -> None:
    controls = absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_WORKING_SIGHTED))
    assert all(control["holds"] for control in controls.values())
    assert controls["text_decided_case_reports_not_needed"]["visual_evidence"] == "not_needed"
    assert controls["sighted_rows_never_withhold"]["withholding"] == []


def test_control_one_fails_when_the_drafter_answers_absent_to_everything() -> None:
    """Blanket obedience: the drafter is repeating the sentence it was handed, and under it A = 6
    means nothing about reasoning."""
    controls = absence_controls(_stable_blind(_answers("absent")), _sighted(_WORKING_SIGHTED))
    assert controls["text_decided_case_reports_not_needed"]["holds"] is False
    assert controls["sighted_rows_never_withhold"]["holds"] is True


def test_control_one_fails_equally_on_a_contradicted_claim() -> None:
    """`seen` on a blind row is a contradiction the guard turns into a degraded row, and a control
    reading only `not_needed` vs `absent` would score that silence as a pass."""
    blind = _stable_blind(_WORKING_BLIND)
    for sample in blind["samples"]:
        for row in sample["rows"]:
            if row["receipt"]["act_testcase_id"] == TEXT_DECIDED_CASE:
                row["draft"]["visual_evidence"] = None
                row["draft"]["contradicted_claim"] = "seen"
    controls = absence_controls(blind, _sighted(_WORKING_SIGHTED))
    assert controls["text_decided_case_reports_not_needed"]["holds"] is False
    assert controls["text_decided_case_reports_not_needed"]["contradicted_claim"] == "seen"


def test_control_two_fails_when_a_row_withholds_with_its_picture_attached() -> None:
    """The mechanism suppressing judgment by its mere existence — under which A measures the field
    rather than the reasoning."""
    controls = absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_answers("absent")))
    assert controls["sighted_rows_never_withhold"]["holds"] is False
    assert len(controls["sighted_rows_never_withhold"]["withholding"]) == 7


def test_control_two_tolerates_not_needed_on_the_case_its_text_decides() -> None:
    """Stated as the absence of withholding rather than as `seen` on all seven: `not_needed` stays
    correct for a hex-digest alt even with the picture attached, and a stricter predicate would fail
    a correct implementation."""
    controls = absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_WORKING_SIGHTED))
    assert controls["sighted_rows_never_withhold"]["holds"] is True


def test_neither_control_reads_confidence_and_both_report_it() -> None:
    controls = absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_WORKING_SIGHTED))
    assert controls["text_decided_case_reports_not_needed"]["confidence"] == 0.5
    assert len(controls["sighted_rows_never_withhold"]["confidence"]) == 7


# --- the four pre-committed verdicts -----------------------------------------


def test_a_failed_control_is_uninterpretable_at_every_value_of_a() -> None:
    """Checked first, and for every A: with blanket obedience and reasoning indistinguishable, each
    value of A means both things at once."""
    assert [absence_verdict(a, controls_hold=False) for a in range(7)] == [VERDICT_A_UNINTERPRETABLE] * 7


def test_the_verdict_table_is_the_pre_registered_one() -> None:
    assert [absence_verdict(a, controls_hold=True) for a in range(7)] == [
        VERDICT_A_NOT_USED,
        VERDICT_A_NOT_USED,
        VERDICT_A_NOT_USED,
        VERDICT_A_PARTIAL,
        VERDICT_A_PARTIAL,
        VERDICT_A_PARTIAL,
        VERDICT_A_CLOSED,
    ]


def test_a_verdict_read_against_a_moved_denominator_is_refused() -> None:
    """The thresholds are counts out of six. Read against five they would be a different rule wearing
    the pre-registered one's name."""
    with pytest.raises(OutOfScope, match="moved denominator"):
        absence_verdict(3, controls_hold=True, denominator=5)


def test_the_reading_names_the_failed_control_rather_than_only_the_verdict() -> None:
    endpoint = endpoint_a(_stable_blind(_WORKING_BLIND))
    controls = absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_answers("absent")))
    reading = absence_reading(endpoint, controls)
    assert reading["verdict"] == VERDICT_A_UNINTERPRETABLE
    assert reading["controls_failed"] == ["sighted_rows_never_withhold"]


def test_the_reading_states_that_a_does_not_decide_whether_the_marking_ships() -> None:
    """The marking shipped on its own evidence with no model call. What A decides is whether the
    announcement becomes production's default — a separately declared prompt change."""
    reading = absence_reading(
        endpoint_a(_stable_blind(_WORKING_BLIND)),
        absence_controls(_stable_blind(_WORKING_BLIND), _sighted(_WORKING_SIGHTED)),
    )
    assert reading["verdict"] == VERDICT_A_CLOSED
    assert "announce_image" in reading["does_not_decide"]


def test_the_conditions_a_is_read_over_are_not_the_ones_d_is() -> None:
    """Named here so the separation is asserted rather than remembered: the announced pair drafts the
    same seven cases under a different pipeline configuration, and never enters D."""
    assert OPAQUE_TOLD_NO_IMAGE.announces and OPAQUE_TOLD_WITH_IMAGE.announces
    assert not OPAQUE_NO_IMAGE.announces
    assert OPAQUE_TOLD_NO_IMAGE.config_id != OPAQUE_NO_IMAGE.config_id
    assert OPAQUE_TOLD_NO_IMAGE.scope.eval_set_id == OPAQUE_NO_IMAGE.scope.eval_set_id
