"""The primary endpoint: D, the retained-cell rule, the null rate and the pre-committed verdict.

D is the number of pool cases whose verdict moves when the *wrong* picture is attached behind a
byte-identical prompt. Everything here is pure over frozen passes, so the arithmetic — and every rule
that could quietly inflate it — is checked with no model running and no calls spent.

The four traps this file holds shut, in the order they would bite:

* **a cell counted that should have been excluded.** Three samples that disagree in either condition
  mean the stack moved on its own, and a cell like that cannot distinguish pixels from drift.
* **a null rate estimated from the retained cells only.** That denominator is conditioned on the very
  stability the endpoint acts on, and it biases toward confirmation. The rate is pooled over every
  condition that took repeats, including the cells D excludes.
* **a refuted verdict published when nothing was measurable.** Below two retained cells, D ≥ 2 is
  unreachable by construction, so a mechanical reading would print a false negative as the headline.
* **a receipt that says a picture moved when none did.** The digests are checked against the frozen
  permutation, so "we ran it mismatched" is evidence rather than an intention.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_conditions import (
    LEAKY_NO_IMAGE,
    OPAQUE_MISMATCHED_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_WITH_IMAGE,
    RECEIPT,
    Condition,
)
from clearway.eval.image_score import (
    M7_DRIFT_RATE,
    VERDICT_CONFIRMED,
    VERDICT_INCONCLUSIVE,
    VERDICT_REFUTED,
    VERDICT_UNINTERPRETABLE,
    endpoint_d,
    endpoint_reading,
    endpoint_verdict,
    null_rate,
    receipt_assertion,
    specificity_control,
)
from clearway.eval.run_scope import OutOfScope, cases_for

_FROZEN = json.loads(CAPTURE_ARTIFACT.read_text())
# `finding_id → (act_testcase_id, own bytes, the wrong bytes)`, read from the frozen permutation so a
# synthetic pass sends exactly what the real conditions have to send.
_MAPPING = {row["finding_id"]: row for row in _FROZEN["resolved_permutation"]}
_GOLD = {case["act_testcase_id"]: case["expected"] for case in cases_for(OPAQUE_WITH_IMAGE.scope)}
_IDS = [row["act_testcase_id"] for row in _FROZEN["resolved_permutation"]]
_FINDINGS = {row["act_testcase_id"]: fid for fid, row in _MAPPING.items()}
# The vendored pages sit at a different path, so their findings hash to different ids. Read from the
# frozen rehearsal rather than invented: the endpoint checks a live pass against that rehearsal, and a
# synthetic pass carrying made-up ids would exercise the check with input it can only reject.
_LEAKY_FINDINGS = {
    row["act_testcase_id"]: row["finding_id"]
    for row in json.loads(RECEIPT.read_text())["rows"]
    if row["condition"] == LEAKY_NO_IMAGE.condition_id
}


def _image_ref(condition: Condition, case_id: str) -> str | None:
    row = _MAPPING[_FINDINGS[case_id]]
    if condition is OPAQUE_WITH_IMAGE:
        return str(row["with_image_ref"])
    if condition is OPAQUE_MISMATCHED_IMAGE:
        return str(row["mismatched_image_ref"])
    return None


def _row(condition: Condition, case_id: str, conformance: str) -> dict[str, Any]:
    finding_id = _FINDINGS[case_id] if condition.scope is OPAQUE_WITH_IMAGE.scope else _LEAKY_FINDINGS[case_id]
    return {
        "receipt": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "act_testcase_id": case_id,
            "finding_id": finding_id,
            "target": "img",
            "image_sha256": _image_ref(condition, case_id),
            "media_type": "image/png" if condition.carries_image else None,
            # One prompt per finding across the opaque conditions, one payload per condition: the
            # byte-identical-prompt premise, in the shape the receipt check reads it.
            "prompt_sha256": f"{case_id[:8]}".ljust(64, "p"),
            "payload_sha256": f"{case_id[:8]}{condition.attaches}".ljust(64, "q"),
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


def _flipped(*case_ids: str) -> dict[str, str]:
    return {case_id: ("does_not_support" if case_id in case_ids else "supports") for case_id in _IDS}


def _stable(condition: Condition, verdicts: dict[str, str]) -> dict[str, Any]:
    return _pass(condition, verdicts, verdicts, verdicts)


# --- D, counted over the cells that can carry it -----------------------------


def test_d_counts_the_cells_whose_verdict_moved_when_the_picture_did() -> None:
    """The endpoint itself: same prompt, wrong pixels, and two cells answered differently."""
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _all("supports")),
        _stable(OPAQUE_MISMATCHED_IMAGE, _flipped(_IDS[0], _IDS[2])),
    )
    assert endpoint["cells"] == 7
    assert endpoint["retained"] == 7
    assert endpoint["excluded"] == []
    assert endpoint["d"] == 2
    assert {row["act_testcase_id"] for row in endpoint["by_case"] if row["counted_in_d"]} == {_IDS[0], _IDS[2]}


def test_two_conditions_that_answer_identically_report_d_zero() -> None:
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _all("supports")), _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports"))
    )
    assert endpoint["d"] == 0
    assert endpoint["retained"] == 7


def test_a_cell_whose_samples_disagree_is_excluded_from_d_and_named() -> None:
    """Three samples share a byte-identical ask, so a cell that moved between them moved on its own —
    it cannot tell a picture from drift, and excluding it costs power rather than buying confirmation."""
    drifting = _pass(OPAQUE_WITH_IMAGE, _all("supports"), _flipped(_IDS[1]), _all("supports"))
    endpoint = endpoint_d(drifting, _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports")))

    assert endpoint["retained"] == 6
    assert endpoint["excluded"] == [_IDS[1]]
    assert endpoint["d"] == 0


def test_a_cell_is_excluded_when_either_condition_drifted_not_only_the_first() -> None:
    drifting = _pass(OPAQUE_MISMATCHED_IMAGE, _all("supports"), _all("supports"), _flipped(_IDS[3]))
    endpoint = endpoint_d(_stable(OPAQUE_WITH_IMAGE, _all("supports")), drifting)
    assert endpoint["excluded"] == [_IDS[3]]


def test_an_excluded_cell_that_disagreed_is_reported_but_never_counted() -> None:
    """The disagreement is real and is recorded — it just cannot be evidence, because the same cell
    disagreed with itself under an identical ask."""
    drifting = _pass(OPAQUE_WITH_IMAGE, _all("supports"), _all("does_not_support"), _all("supports"))
    endpoint = endpoint_d(drifting, _stable(OPAQUE_MISMATCHED_IMAGE, _all("does_not_support")))

    assert endpoint["retained"] == 0
    assert endpoint["d"] == 0
    assert endpoint["differing_cells_including_excluded"] == 7


def test_the_cells_are_paired_by_case_and_carry_which_picture_each_side_sent() -> None:
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _all("supports")), _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports"))
    )
    assert [row["act_testcase_id"] for row in endpoint["by_case"]] == _IDS
    for row in endpoint["by_case"]:
        frozen = _MAPPING[_FINDINGS[row["act_testcase_id"]]]
        assert row["true_image"] == frozen["true_image"]
        assert row["mismatched_image"] == frozen["mismatched_image"]
        assert row["live"] == frozen["live"]


def test_the_live_cells_describe_the_power_and_never_filter_the_test() -> None:
    """Power is described by the four live cells; D is defined over all seven. A dead cell that moves
    is evidence the manipulation touched something other than perception, so it stays in."""
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _all("supports")),
        _stable(OPAQUE_MISMATCHED_IMAGE, _flipped(specificity_control()["act_testcase_id"])),
    )
    assert endpoint["cells"] == 7
    assert endpoint["live_cells"] == 4
    assert endpoint["d"] == 1
    assert endpoint["specificity_control"]["differs"] is True
    assert "other than perception" in endpoint["specificity_control"]["reading"]


def test_the_specificity_control_is_derived_from_the_frozen_permutation() -> None:
    """Named in the spec as `a2333ec76e` — a hex-digest alt that describes no picture at all. Derived
    from the frozen mapping rather than transcribed, so a set that moved cannot leave it pointing at
    a case that is no longer the control."""
    control = specificity_control()
    assert control["act_testcase_id"].startswith("a2333ec76e")
    assert control["live"] is False


def test_the_direction_of_every_disagreement_is_recorded_as_a_secondary() -> None:
    """Pre-registered as a strengthening, reported and never gated on: gating on direction would
    re-import a denominator conditioned on the result."""
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _flipped(_IDS[0])),
        _stable(OPAQUE_MISMATCHED_IMAGE, _flipped(_IDS[2])),
    )
    assert endpoint["d"] == 2
    assert endpoint["direction"]["toward_flag"] == 1
    assert endpoint["direction"]["toward_clean"] == 1
    assert endpoint["direction"]["predicted"] == "toward_flag"


def test_a_pass_missing_the_sample_that_defines_its_verdicts_is_refused() -> None:
    """Pass 1 is canonical throughout this project. Silently reading a later sample instead would
    define the endpoint's verdicts from a replicate that exists only to say how stable pass 1 is."""
    without_canonical = _stable(OPAQUE_WITH_IMAGE, _all("supports"))
    without_canonical["samples"] = without_canonical["samples"][1:]
    with pytest.raises(OutOfScope, match="no canonical verdict"):
        endpoint_d(without_canonical, _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports")))


def test_a_pair_that_is_not_the_endpoint_s_two_conditions_is_refused() -> None:
    with pytest.raises(OutOfScope, match="with-image"):
        endpoint_d(_stable(OPAQUE_NO_IMAGE, _all("supports")), _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports")))


def test_the_two_conditions_the_wrong_way_round_are_refused() -> None:
    """`with_image` and `mismatched` are not interchangeable: the direction check reads one against
    the other, and swapping them would silently reverse it."""
    with pytest.raises(OutOfScope, match="with-image"):
        endpoint_d(_stable(OPAQUE_MISMATCHED_IMAGE, _all("supports")), _stable(OPAQUE_WITH_IMAGE, _all("supports")))


def test_conditions_covering_different_cases_are_refused() -> None:
    short = _stable(OPAQUE_MISMATCHED_IMAGE, {k: v for k, v in _all("supports").items() if k != _IDS[0]})
    with pytest.raises(OutOfScope, match="same cases"):
        endpoint_d(_stable(OPAQUE_WITH_IMAGE, _all("supports")), short)


# --- the null rate, and why it is pooled over everything ---------------------


def test_the_null_rate_pools_every_condition_that_took_repeats() -> None:
    """Including the cells D excludes. Estimating it from the retained cells only would condition the
    denominator on the very stability the endpoint acts on."""
    drifting = _pass(OPAQUE_WITH_IMAGE, _all("supports"), _flipped(_IDS[1]), _all("supports"))
    measured = null_rate([_stable(OPAQUE_NO_IMAGE, _all("supports")), drifting])

    assert measured["pairs"] == 42  # two conditions × 7 findings × the 3 pairs three samples make
    assert measured["disagreeing_pairs"] == 2
    assert measured["measured_rate"] == pytest.approx(2 / 42)


def test_a_one_sample_condition_supplies_no_replicates_and_is_named() -> None:
    measured = null_rate([_pass(LEAKY_NO_IMAGE, _all("supports")), _stable(OPAQUE_NO_IMAGE, _all("supports"))])
    assert measured["pairs"] == 21
    assert measured["not_measurable"] == [LEAKY_NO_IMAGE.condition_id]


def test_a_clean_run_floors_at_the_earlier_milestone_s_measured_drift() -> None:
    """The `max` rule. M8's own estimate is low-resolution, so a lucky clean run cannot buy a null
    rate of zero — under which any single disagreement would look decisive."""
    measured = null_rate([_stable(OPAQUE_WITH_IMAGE, _all("supports"))])
    assert measured["measured_rate"] == 0.0
    assert measured["rate"] == M7_DRIFT_RATE
    assert measured["source"] == "M7"


def test_a_noisier_run_than_the_floor_raises_the_null_rate_rather_than_being_capped() -> None:
    noisy = _pass(OPAQUE_WITH_IMAGE, _all("supports"), _all("does_not_support"), _all("supports"))
    measured = null_rate([noisy])
    assert measured["measured_rate"] == pytest.approx(14 / 21)
    assert measured["rate"] == pytest.approx(14 / 21)
    assert measured["source"] == "M8"


def test_the_null_rate_needs_at_least_one_condition_with_repeats() -> None:
    with pytest.raises(OutOfScope, match="no replicates"):
        null_rate([_pass(LEAKY_NO_IMAGE, _all("supports"))])


# --- the four pre-committed verdicts -----------------------------------------


def test_the_verdicts_are_a_function_of_d_and_the_retained_count_alone() -> None:
    assert endpoint_verdict(2, 7) == VERDICT_CONFIRMED
    assert endpoint_verdict(5, 7) == VERDICT_CONFIRMED
    assert endpoint_verdict(1, 7) == VERDICT_INCONCLUSIVE
    assert endpoint_verdict(0, 7) == VERDICT_REFUTED


def test_fewer_than_two_retained_cells_is_uninterpretable_and_never_refuted() -> None:
    """D ≥ 2 is unreachable by construction below two cells, so a mechanical reading would publish a
    false negative as the milestone's headline."""
    assert endpoint_verdict(0, 1) == VERDICT_UNINTERPRETABLE
    assert endpoint_verdict(1, 1) == VERDICT_UNINTERPRETABLE
    assert endpoint_verdict(0, 0) == VERDICT_UNINTERPRETABLE


def test_the_reading_prints_the_null_rate_it_used_and_the_tail_over_the_retained_cells() -> None:
    endpoint = endpoint_d(
        _stable(OPAQUE_WITH_IMAGE, _all("supports")),
        _stable(OPAQUE_MISMATCHED_IMAGE, _flipped(_IDS[0], _IDS[2])),
    )
    reading = endpoint_reading(endpoint, null_rate([_stable(OPAQUE_NO_IMAGE, _all("supports"))]))

    assert reading["verdict"] == VERDICT_CONFIRMED
    assert reading["d"] == 2
    assert reading["retained"] == 7
    assert reading["null_rate"] == M7_DRIFT_RATE
    assert reading["p_value"] == pytest.approx(0.007, abs=5e-4)
    assert "under-detect" in reading["note"]


def test_the_tail_is_computed_over_the_retained_cells_not_over_all_seven() -> None:
    """A shrunken denominator costs power, and the p-value has to say so rather than quietly keep
    quoting a seven-cell tail."""
    drifting = _pass(OPAQUE_WITH_IMAGE, _all("supports"), _flipped(_IDS[1], _IDS[3], _IDS[4]), _all("supports"))
    endpoint = endpoint_d(drifting, _stable(OPAQUE_MISMATCHED_IMAGE, _flipped(_IDS[0], _IDS[2])))
    reading = endpoint_reading(endpoint, null_rate([_stable(OPAQUE_NO_IMAGE, _all("supports"))]))

    assert reading["retained"] == 4
    assert reading["d"] == 2
    assert reading["p_value"] == pytest.approx(0.002007, abs=5e-6)


# --- the receipts: proof the manipulation was actually run mismatched --------


def _four_passes() -> dict[Condition, dict[str, Any]]:
    return {
        LEAKY_NO_IMAGE: _pass(LEAKY_NO_IMAGE, _all("supports")),
        OPAQUE_NO_IMAGE: _stable(OPAQUE_NO_IMAGE, _all("supports")),
        OPAQUE_WITH_IMAGE: _stable(OPAQUE_WITH_IMAGE, _all("supports")),
        OPAQUE_MISMATCHED_IMAGE: _stable(OPAQUE_MISMATCHED_IMAGE, _all("supports")),
    }


def test_the_live_receipts_are_checked_against_the_frozen_mapping_on_every_sample() -> None:
    """Not only the canonical one: a condition whose second and third samples sent the case's own
    bytes would still be three samples of something, and the endpoint would read it as stability."""
    assertion = receipt_assertion(_four_passes())
    assert assertion["failures"] == []
    assert assertion["samples_checked"] == 3
    assert assertion["rows_checked"] == 3 * 4 * 7


def test_a_mismatched_row_that_sent_the_case_s_own_bytes_fails() -> None:
    passes = _four_passes()
    own = _MAPPING[_FINDINGS[_IDS[0]]]["with_image_ref"]
    passes[OPAQUE_MISMATCHED_IMAGE]["samples"][2]["rows"][0]["receipt"]["image_sha256"] = own
    assertion = receipt_assertion(passes)
    assert any("OWN bytes" in failure for failure in assertion["failures"])


def test_a_with_image_row_that_sent_the_wrong_picture_fails() -> None:
    passes = _four_passes()
    wrong = _MAPPING[_FINDINGS[_IDS[0]]]["mismatched_image_ref"]
    passes[OPAQUE_WITH_IMAGE]["samples"][0]["rows"][0]["receipt"]["image_sha256"] = wrong
    assertion = receipt_assertion(passes)
    assert any("frozen mapping says" in failure for failure in assertion["failures"])


def test_a_moved_prompt_across_the_opaque_conditions_fails() -> None:
    """The premise the whole endpoint rests on: only the pixels differ."""
    passes = _four_passes()
    passes[OPAQUE_MISMATCHED_IMAGE]["samples"][0]["rows"][0]["receipt"]["prompt_sha256"] = "0" * 64
    assertion = receipt_assertion(passes)
    assert any("byte-identical prompts" in failure for failure in assertion["failures"])


def test_the_assertion_needs_all_four_conditions() -> None:
    passes = _four_passes()
    del passes[LEAKY_NO_IMAGE]
    with pytest.raises(OutOfScope, match="all four"):
        receipt_assertion(passes)


def test_the_digests_sent_live_are_the_ones_the_model_free_rehearsal_pre_registered() -> None:
    """The dry receipt froze what each condition must attach before a single call was spent. A live
    pass that attached something else is a different experiment wearing this one's name."""
    assertion = receipt_assertion(_four_passes())
    assert assertion["matches_dry_receipt"] is True

    # A digest of a genuinely different picture, not just another case's: four of the seven findings
    # render the same photograph, so "some other case's image_ref" is often the same bytes.
    passes = _four_passes()
    own = _MAPPING[_FINDINGS[_IDS[0]]]["with_image_ref"]
    other = next(ref for ref in (row["with_image_ref"] for row in _MAPPING.values()) if ref != own)
    passes[OPAQUE_WITH_IMAGE]["samples"][0]["rows"][0]["receipt"]["image_sha256"] = other
    assert receipt_assertion(passes)["matches_dry_receipt"] is False
