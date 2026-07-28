"""The text-only difference: what removing the filename cue did, and what it partly measures.

Everything here is pure over frozen passes, so the arithmetic is checked without a model and the
synthetic passes below can say exactly what a pass would have to look like for each number to come
out the way it does.

Two traps this file exists to hold shut:

* **an unmeasurable number reported as zero.** The descriptive condition takes one sample, so its
  within-condition stability is not measured — which is not the same as measured and found perfect.
* **a difference read as an effect.** In the vendored condition several cases carry an `alt` that
  equals its own filename, and the help text says a filename does not describe. The report has to
  carry that measurement beside the difference, because part of the difference is a property of how
  a deprecated rule's fixtures were authored.
"""

from __future__ import annotations

from typing import Any

import pytest

from clearway.eval.image_conditions import LEAKY_NO_IMAGE, OPAQUE_NO_IMAGE, OPAQUE_WITH_IMAGE, Condition
from clearway.eval.image_score import (
    _cue_row,
    condition_summary,
    filename_cue,
    flagged,
    instability,
    text_only_difference,
)
from clearway.eval.run_scope import OutOfScope, cases_for

# The pool's gold, in manifest order, read from the manifest rather than transcribed.
_GOLD = {case["act_testcase_id"]: case["expected"] for case in cases_for(OPAQUE_NO_IMAGE.scope)}
_IDS = list(_GOLD)


def _row(condition: Condition, case_id: str, conformance: str) -> dict[str, Any]:
    return {
        "receipt": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "act_testcase_id": case_id,
            "finding_id": f"{condition.scope.scope_id}:{case_id[:8]}",
            "target": "img",
            "image_sha256": None,
            "media_type": None,
            "prompt_sha256": "a" * 64,
            "payload_sha256": "b" * 64,
        },
        "gold": {"rule_name": "r", "expected": _GOLD[case_id], "gold_success_criteria": ["1.1.1"]},
        "draft": {"conformance": conformance, "cited_sc_ids": ["1.1.1"], "confidence": 0.5, "remediation": "x"},
    }


def _pass(condition: Condition, *per_sample: dict[str, str]) -> dict[str, Any]:
    """A synthetic frozen pass: one verdict map per sample, `act_testcase_id → conformance`."""
    return {
        "condition": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "attaches": condition.attaches,
            "samples": condition.samples,
        },
        "canonical_sample": 1,
        "eval_set_id": condition.scope.eval_set_id,
        "samples": [
            {"sample": n, "rows": [_row(condition, case_id, verdict) for case_id, verdict in verdicts.items()]}
            for n, verdicts in enumerate(per_sample, start=1)
        ],
    }


def _all(conformance: str) -> dict[str, str]:
    return {case_id: conformance for case_id in _IDS}


# --- the binary collapse and correctness against gold ------------------------


def test_the_collapse_is_the_one_every_other_acceptance_number_uses() -> None:
    assert flagged(_row(OPAQUE_NO_IMAGE, _IDS[0], "does_not_support")) is True
    assert flagged(_row(OPAQUE_NO_IMAGE, _IDS[0], "partially_supports")) is True
    assert flagged(_row(OPAQUE_NO_IMAGE, _IDS[0], "supports")) is False
    assert flagged(_row(OPAQUE_NO_IMAGE, _IDS[0], "not_applicable")) is False


def test_a_condition_is_summarised_by_its_canonical_sample_against_gold() -> None:
    """Three of the seven are gold `failed`, so flagging everything is 3 right and 4 false alarms."""
    summary = condition_summary(
        _pass(OPAQUE_NO_IMAGE, _all("does_not_support"), _all("does_not_support"), _all("does_not_support"))
    )
    assert summary["cases"] == 7
    assert summary["flagged"] == 7
    assert summary["correct"] == 3
    assert summary["false_positives"] == 4
    assert summary["false_negatives"] == 0

    clean = condition_summary(_pass(LEAKY_NO_IMAGE, _all("supports")))
    assert clean["correct"] == 4
    assert clean["false_positives"] == 0
    assert clean["false_negatives"] == 3


def test_the_summary_reads_the_canonical_sample_and_not_the_others() -> None:
    """Pass 1 defines a verdict throughout this project; the repeats say how stable it is."""
    artifact = _pass(OPAQUE_NO_IMAGE, _all("supports"), _all("does_not_support"), _all("does_not_support"))
    assert condition_summary(artifact)["flagged"] == 0


# --- stability within a condition -------------------------------------------


def test_three_agreeing_samples_are_stable_and_supply_the_null_replicates() -> None:
    artifact = _pass(OPAQUE_NO_IMAGE, _all("supports"), _all("supports"), _all("supports"))
    measured = instability(artifact)
    assert measured["measurable"] is True
    assert measured["findings"] == 7
    assert measured["unstable_findings"] == []
    assert measured["disagreeing_pairs"] == 0
    assert measured["pairs"] == 21  # 7 findings × the 3 pairs three samples make


def test_one_finding_that_flips_is_named_and_counted_in_pairs() -> None:
    flipped = {**_all("supports"), _IDS[2]: "does_not_support"}
    artifact = _pass(OPAQUE_NO_IMAGE, _all("supports"), flipped, _all("supports"))
    measured = instability(artifact)
    assert measured["unstable_findings"] == [f"{OPAQUE_NO_IMAGE.scope.scope_id}:{_IDS[2][:8]}"]
    assert measured["unstable_cases"] == [_IDS[2]]
    assert measured["disagreeing_pairs"] == 2  # sample 2 disagrees with 1 and with 3
    assert measured["rate"] == pytest.approx(2 / 21)


def test_a_one_sample_condition_reports_stability_as_unmeasURED_never_as_zero() -> None:
    """The distinction the whole `run_scope` module exists over: an empty answer and a measured zero
    are indistinguishable in a report, and only one of them is true."""
    measured = instability(_pass(LEAKY_NO_IMAGE, _all("supports")))
    assert measured["measurable"] is False
    assert measured["pairs"] == 0
    assert "rate" not in measured
    assert "one sample" in measured["note"]


# --- the leaky → opaque difference ------------------------------------------


def test_the_two_conditions_are_paired_by_case_because_their_finding_ids_differ() -> None:
    """The ablated pages sit at different paths, and a finding id hashes its page's URL — so pairing
    on finding id would pair nothing at all and report a difference of zero over seven cases."""
    leaky = _pass(LEAKY_NO_IMAGE, _all("does_not_support"))
    opaque = _pass(OPAQUE_NO_IMAGE, _all("supports"), _all("supports"), _all("supports"))
    difference = text_only_difference(leaky, opaque)

    assert difference["cases"] == 7
    assert difference["moved"] == 7
    assert difference["toward_clean"] == 7
    assert difference["toward_flag"] == 0
    assert all(row["moved"] for row in difference["by_case"])
    assert {row["act_testcase_id"] for row in difference["by_case"]} == set(_IDS)


def test_conditions_that_agree_everywhere_report_a_difference_of_zero_and_say_what_that_means() -> None:
    leaky = _pass(LEAKY_NO_IMAGE, _all("supports"))
    opaque = _pass(OPAQUE_NO_IMAGE, _all("supports"), _all("supports"), _all("supports"))
    difference = text_only_difference(leaky, opaque)

    assert difference["moved"] == 0
    assert difference["differs"] is False
    assert "ablation gate" in difference["reading"]


def test_the_difference_is_split_by_whether_the_case_carried_the_filename_cue() -> None:
    """Where the difference sits matters more than its size: movement on a case whose `alt` equalled
    its own filename is the cue being removed; movement elsewhere is not."""
    cue_cases = [row["act_testcase_id"] for row in filename_cue()["cases"] if row["alt_equals_filename"]]
    moved = {**_all("supports"), cue_cases[0]: "does_not_support"}
    difference = text_only_difference(_pass(LEAKY_NO_IMAGE, moved), _pass(OPAQUE_NO_IMAGE, *[_all("supports")] * 3))

    assert difference["moved"] == 1
    assert difference["moved_on_cue_cases"] == 1
    assert difference["moved_off_cue_cases"] == 0


def test_the_cue_split_is_reported_under_both_readings_because_they_disagree_on_a_case() -> None:
    """`1ff696703e` carries the cue by stem and not verbatim. Filing its movement under the strict
    rule alone would count it as movement AWAY from the cue, which is the opposite of what it may be."""
    stem_only = next(
        row["act_testcase_id"]
        for row in filename_cue()["cases"]
        if row["alt_equals_filename_stem"] and not row["alt_equals_filename"]
    )
    moved = {**_all("supports"), stem_only: "does_not_support"}
    difference = text_only_difference(_pass(LEAKY_NO_IMAGE, moved), _pass(OPAQUE_NO_IMAGE, *[_all("supports")] * 3))

    assert difference["moved"] == 1
    assert difference["moved_on_cue_cases"] == 0
    assert difference["moved_on_cue_cases_stem"] == 1


def test_two_passes_of_the_same_condition_are_refused() -> None:
    with pytest.raises(OutOfScope, match="text-only conditions"):
        text_only_difference(_pass(LEAKY_NO_IMAGE, _all("supports")), _pass(LEAKY_NO_IMAGE, _all("supports")))


def test_a_condition_that_attaches_a_picture_is_refused() -> None:
    with pytest.raises(OutOfScope, match="text-only conditions"):
        text_only_difference(_pass(LEAKY_NO_IMAGE, _all("supports")), _pass(OPAQUE_WITH_IMAGE, *[_all("supports")] * 3))


def test_conditions_covering_different_cases_are_refused() -> None:
    """A difference computed over an intersection would report the cases that happened to overlap."""
    short = _pass(OPAQUE_NO_IMAGE, *[{k: v for k, v in _all("supports").items() if k != _IDS[0]}] * 3)
    with pytest.raises(OutOfScope, match="same cases"):
        text_only_difference(_pass(LEAKY_NO_IMAGE, _all("supports")), short)


# --- the fixture artifact, measured rather than asserted ---------------------


def test_the_filename_cue_is_measured_under_a_named_rule_and_both_readings_are_reported() -> None:
    """The spec says four of seven. That is four under one reading of "alt ≈ filename" and five under
    another, and a number nobody can reproduce is worth less than the two numbers plus the rule."""
    measured = filename_cue()
    assert measured["cases"] and len(measured["cases"]) == 7
    assert measured["alt_equals_filename"] == 4
    assert measured["alt_equals_filename_stem"] == 5
    assert measured["rule"].startswith("the last path segment of `src`")

    only_by_stem = [
        row["act_testcase_id"]
        for row in measured["cases"]
        if row["alt_equals_filename_stem"] and not row["alt_equals_filename"]
    ]
    assert len(only_by_stem) == 1
    assert only_by_stem[0].startswith("1ff696703e")


def test_the_help_text_the_caveat_leans_on_is_quoted_from_the_frozen_prompt() -> None:
    """The caveat is only a caveat if the prompt really does tell the model a filename does not
    describe. Quoted from the artifact, so a help string that changed breaks the sentence."""
    measured = filename_cue()
    assert measured["help_text"]
    assert all("filename" in help_text for help_text in measured["help_text"])


def test_the_caveat_carries_the_measured_counts_rather_than_a_transcribed_number() -> None:
    difference = text_only_difference(
        _pass(LEAKY_NO_IMAGE, _all("supports")), _pass(OPAQUE_NO_IMAGE, *[_all("supports")] * 3)
    )
    assert "4 of 7 cases have an alt equal to their own filename" in difference["caveat"]
    assert "5 of 7 once one extension is stripped" in difference["caveat"]
    assert "DEPRECATED" in difference["caveat"]


def test_a_pool_case_rendering_more_than_one_image_is_refused() -> None:
    """The measurement compares one alt against one src; the first of several would be a cue for a
    picture the finding may not even be about."""
    with pytest.raises(OutOfScope, match="renders 2 images"):
        _cue_row({"act_testcase_id": "x", "expected": "passed", "image_elements": [{}, {}]})
