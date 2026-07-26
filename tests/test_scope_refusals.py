"""The readings that used to answer for a scope they never covered, and now refuse.

Each of these paths returned something before: zero grouped cases, zero discordant pairs, an empty id
list, a blank mechanism cell, a prediction nobody moved. None of those is distinguishable in a report
from a real measurement that came out zero, and that is the whole defect — an unmeasured class and a
class measured at zero rendered identically, so a run over the wrong case set read as a run that found
nothing.

The image pool is the out-of-scope case set throughout, because it is the one that actually exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from clearway.eval import run_scope
from clearway.eval.drafter_kappa import _grouped, class_kappas
from clearway.eval.image_reachability import HTML, IMAGE_AXE_RULE
from clearway.eval.paired import attribute_against_prior, pair_verdicts
from clearway.eval.referent_injection_score import score_run
from clearway.eval.run_scope import OutOfScope
from clearway.eval.verdict_vector import build_verdict_vector
from clearway.schemas.models import CaseVerdict, VerdictVector

_IMAGE_RULE_NAME = "Image accessible name is descriptive"


def _case(tid: str, rule_name: str, axe_rule: str, expected: str, conformance: str) -> dict[str, Any]:
    return {
        "act_testcase_id": tid,
        "rule_name": rule_name,
        "axe_rule": axe_rule,
        "expected": expected,
        "gold_success_criteria": ["1.1.1"],
        "drafts": [
            {
                "finding_id": f"f-{tid}",
                "target": "img",
                "conformance": conformance,
                "cited_sc_ids": [],
                "confidence": 0.9,
            }
        ],
    }


def _artifact(cases: list[dict[str, Any]], *, eval_set_id: str = "act-image-leaky@1") -> dict[str, Any]:
    return {
        "run_ids": ["image-pass1"],
        "config_id": "single-multimodal@1",
        "eval_set_id": eval_set_id,
        "corpus_version": "corpus@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "deadbeef",
        "axe_core_version": "4.12.1",
        "act_export_hash": "abc",
        "created_at": "2026-07-26T00:00:00+00:00",
        "cases": cases,
        "honest_misses": [],
    }


def _image_artifact() -> dict[str, Any]:
    return _artifact(
        [
            _case("img1", _IMAGE_RULE_NAME, IMAGE_AXE_RULE, "failed", "does_not_support"),
            _case("img2", _IMAGE_RULE_NAME, IMAGE_AXE_RULE, "passed", "supports"),
        ]
    )


def _vector(cases: list[CaseVerdict], run_id: str = "r") -> VerdictVector:
    return VerdictVector(
        partial_flags=True,
        cases=cases,
        run_ids=[run_id],
        config_id="single-multimodal@1",
        eval_set_id="act-image-leaky@1",
        corpus_version="corpus@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        axe_core_version="4.12.1",
        act_export_hash="abc",
        created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        rationale="test",
    )


def _verdict(tid: str, *, axe_rule: str, right: bool) -> CaseVerdict:
    return CaseVerdict(
        act_testcase_id=tid, axe_rule=axe_rule, drafter_flag=right, gold_flag=True, conformances=["supports"]
    )


# ---------------------------------------------------------------------------------------------------
# scoping an out-of-scope artifact used to produce an empty but schema-valid answer
# ---------------------------------------------------------------------------------------------------


def test_an_artifact_whose_classes_are_all_out_of_scope_raises_instead_of_grouping_to_nothing() -> None:
    with pytest.raises(OutOfScope, match="image-alt"):
        _grouped(_image_artifact())


def test_the_unscoped_reading_still_recovers_an_out_of_scope_artifact() -> None:
    # `scoped=False` is the escape hatch that already existed; the guard must not close it.
    assert {c.axe_rule for c in class_kappas(_image_artifact(), scoped=False)} == {IMAGE_AXE_RULE}


def test_an_out_of_scope_artifact_cannot_become_an_empty_verdict_vector() -> None:
    with pytest.raises(OutOfScope):
        build_verdict_vector(_image_artifact())


# ---------------------------------------------------------------------------------------------------
# a pooled endpoint over classes the run does not contain reads as "no movement"
# ---------------------------------------------------------------------------------------------------


def test_a_pooled_endpoint_with_no_pooled_class_present_raises_instead_of_reporting_no_movement() -> None:
    base = _vector([_verdict("img1", axe_rule=IMAGE_AXE_RULE, right=False)])
    run = _vector([_verdict("img1", axe_rule=IMAGE_AXE_RULE, right=True)])
    with pytest.raises(OutOfScope, match="pooled"):
        pair_verdicts(base, run)


def test_the_pool_is_declared_once_and_both_modules_read_that_one_declaration() -> None:
    # It was declared in two modules, so correcting one left the other silently wrong.
    from clearway.eval import drafter_kappa_baseline, paired

    assert paired.POOLED_AXE_RULES is run_scope.POOLED_AXE_RULES
    assert drafter_kappa_baseline.POOLED_AXE_RULES is run_scope.POOLED_AXE_RULES
    with pytest.raises(OutOfScope, match="pooled"):
        run_scope.assert_pooled_classes_present({IMAGE_AXE_RULE})


# ---------------------------------------------------------------------------------------------------
# attribution against a baseline sharing no case printed "prior run intact"
# ---------------------------------------------------------------------------------------------------


def test_attribution_against_a_baseline_that_does_not_cover_the_run_raises() -> None:
    prior = _vector([_verdict("img1", axe_rule="label", right=False)], "prior-1")
    run = _vector([_verdict("img1", axe_rule="label", right=True)], "run-1")
    baseline = _vector([_verdict("other", axe_rule="label", right=False)], "baseline-1")
    with pytest.raises(OutOfScope, match="img1"):
        attribute_against_prior(baseline, prior, run)


# ---------------------------------------------------------------------------------------------------
# `.get()`-defaulted mechanism inputs rendered an unknown class as blank
# ---------------------------------------------------------------------------------------------------


def test_a_class_with_no_pre_change_prompt_count_raises_instead_of_rendering_empty() -> None:
    from clearway.eval.referent_injection_score import _distinct_prompts_before

    assert _distinct_prompts_before("label") == 6
    with pytest.raises(OutOfScope, match=IMAGE_AXE_RULE):
        _distinct_prompts_before(IMAGE_AXE_RULE)


def test_a_class_absent_from_the_baselines_reachable_errors_raises() -> None:
    from clearway.eval.referent_injection_score import _baseline_reachable_for

    assert _baseline_reachable_for({"label": ["a"]}, "label") == ["a"]
    with pytest.raises(OutOfScope, match=IMAGE_AXE_RULE):
        _baseline_reachable_for({"label": ["a"]}, IMAGE_AXE_RULE)


# ---------------------------------------------------------------------------------------------------
# one set's pre-registered predictions scored into another set's result
# ---------------------------------------------------------------------------------------------------


def test_a_prediction_naming_cases_this_run_does_not_contain_is_refused() -> None:
    cases = [_case("k1", "Link in context is descriptive", "link-name", "failed", "does_not_support")]
    runs = [_artifact(cases, eval_set_id="act-acceptance@1"), _artifact(cases, eval_set_id="act-acceptance@1")]
    baseline = _vector([_verdict("k1", axe_rule="link-name", right=False)])
    foreign = [{"prediction_id": "destination-outside-dom", "act_testcase_ids": ["a-case-from-another-set"]}]
    with pytest.raises(OutOfScope, match="a-case-from-another-set"):
        score_run(runs, baseline, {"link-name": []}, {}, predictions=foreign)


# ---------------------------------------------------------------------------------------------------
# a scan without the asset tree mints the identical finding over an image that never arrived
# ---------------------------------------------------------------------------------------------------


def test_the_acceptance_minting_helper_refuses_a_case_from_another_gold_tree() -> None:
    from clearway.eval.act_gold import _minting_findings

    case = HTML / "be6b29e220d6afbd827625c602ec49027e73fdf1.html"
    with pytest.raises(OutOfScope, match="asset"):
        _minting_findings(case, IMAGE_AXE_RULE)


def test_the_refusal_does_not_catch_the_acceptance_cases_that_carry_an_absolute_image() -> None:
    """Two of the 44 scored cases reference an absolute `/test-assets/` image and render it broken. Their
    gold turns on `alt` text, which is in the DOM either way, so refusing them would drop real gold — a
    guard written against the markup rather than against the set would do exactly that."""
    from clearway.eval.act_gold import _ACT_GOLD, _minting_findings

    case = _ACT_GOLD / "html" / "49a6b0a208fa118829c6622ffc1dc2ce150a1ce1.html"
    assert '<img src="/test-assets/' in case.read_text(encoding="utf-8")
    assert _minting_findings(case, "empty-heading")
