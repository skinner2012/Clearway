"""Per-class drafter κ — reproduces the pre-registered anchors from the frozen artifacts.

The anchors (κ, n, error split) are stated in the milestone spec BEFORE this code existed, so these
tests pin the instrument against numbers that could not be tuned to fit. Every number is a
deterministic replay of a checked-in run artifact — no model, no network, no clock.
"""

from __future__ import annotations

import json
from pathlib import Path

from clearway.eval.drafter_kappa import (
    CEILING_PREREGISTRATION,
    ClassCeiling,
    ClassKappa,
    ClassKappaCI,
    class_ceilings,
    class_kappa_cis,
    class_kappas,
)

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"


def _artifact(name: str = "run_1.json") -> dict:
    return json.loads((_RUNS / name).read_text())


def _by_axe(name: str = "run_1.json", *, partial_flags: bool = True) -> dict[str, ClassKappa]:
    return {c.axe_rule: c for c in class_kappas(_artifact(name), partial_flags=partial_flags)}


def test_reproduces_the_pre_registered_kappa_anchors() -> None:
    k = _by_axe()
    assert round(k["document-title"].kappa, 3) == 0.000  # the constant classifier — κ exposes it
    assert round(k["empty-heading"].kappa, 3) == 0.675  # the control — real signal, clearly positive
    assert round(k["label"].kappa, 3) == 0.127
    assert round(k["link-name"].kappa, 3) == 0.250


def test_class_sizes_and_failed_passed_splits() -> None:
    k = _by_axe()
    assert (k["document-title"].n, k["document-title"].failed, k["document-title"].passed) == (5, 2, 3)
    assert (k["empty-heading"].n, k["empty-heading"].failed, k["empty-heading"].passed) == (13, 5, 8)
    assert (k["label"].n, k["label"].failed, k["label"].passed) == (11, 5, 6)
    assert (k["link-name"].n, k["link-name"].failed, k["link-name"].passed) == (24, 11, 13)


def test_error_split_fp_and_miss_per_class() -> None:
    k = _by_axe()
    assert (k["document-title"].fp, k["document-title"].fn) == (3, 0)
    assert (k["empty-heading"].fp, k["empty-heading"].fn) == (1, 1)
    assert (k["label"].fp, k["label"].fn) == (4, 1)
    assert (k["link-name"].fp, k["link-name"].fn) == (5, 4)


def test_link_class_pools_the_two_link_rules() -> None:
    link = _by_axe()["link-name"]
    assert link.rule_names == ("Link in context is descriptive", "Link is descriptive")
    assert link.n == 24  # 20 minting cases + 4 honest misses, both link rules pooled


def test_honest_misses_are_carried_in() -> None:
    # empty-heading is 11 minting cases + 2 honest misses; dropping the misses would read n=11 and
    # inflate κ the way a miss-dropping recall does.
    assert _by_axe()["empty-heading"].n == 13


def test_drafter_is_deterministic_identical_kappa_across_frozen_runs() -> None:
    per_run = [
        {c.axe_rule: round(c.kappa, 6) for c in class_kappas(_artifact(r))}
        for r in ("run_1.json", "run_2.json", "run_3.json")
    ]
    assert per_run[0] == per_run[1] == per_run[2]


def test_partial_flags_false_moves_only_the_link_class() -> None:
    true_ = _by_axe()
    false_ = _by_axe(partial_flags=False)
    # only the link class carries partially_supports drafts, so only it moves
    assert round(false_["link-name"].kappa, 3) == 0.408
    assert false_["link-name"].fp == 3  # two partially_supports cry-wolves become clean
    for axe in ("document-title", "empty-heading", "label"):
        assert round(false_[axe].kappa, 3) == round(true_[axe].kappa, 3)


def test_raw_agreement_reported_beside_kappa() -> None:
    # the control's high agreement AND positive κ together are what prove the capability is real
    assert round(_by_axe()["empty-heading"].raw_agreement, 3) == 0.846


def test_pure_same_artifact_yields_identical_result() -> None:
    a = _artifact()
    assert class_kappas(a) == class_kappas(a)


def _ci_by_axe(name: str = "run_1.json", *, partial_flags: bool = True) -> dict[str, ClassKappaCI]:
    return {c.axe_rule: c for c in class_kappa_cis(_artifact(name), partial_flags=partial_flags)}


def test_ci_bounds_reproduce_the_spec() -> None:
    ci = _ci_by_axe()
    assert (round(ci["label"].ci_low, 3), round(ci["label"].ci_high, 3)) == (-0.375, 0.633)
    assert (round(ci["empty-heading"].ci_low, 3), round(ci["empty-heading"].ci_high, 3)) == (0.156, 1.000)
    assert (round(ci["document-title"].ci_low, 3), round(ci["document-title"].ci_high, 3)) == (0.000, 0.000)


def test_document_title_flagged_constant_classifier_zero_width() -> None:
    dt = _ci_by_axe()["document-title"]
    assert dt.ci_low == dt.ci_high == 0.0
    assert dt.constant_classifier is True
    assert dt.degenerate_share == 1.0  # the drafter stream is constant on every resample


def test_only_document_title_is_a_constant_classifier() -> None:
    ci = _ci_by_axe()
    assert [axe for axe, c in ci.items() if c.constant_classifier] == ["document-title"]


def test_ci_bounds_are_bit_reproducible() -> None:
    a = _artifact()
    assert [(c.ci_low, c.ci_high) for c in class_kappa_cis(a)] == [(c.ci_low, c.ci_high) for c in class_kappa_cis(a)]


def test_ci_is_not_a_wilson_proportion_interval() -> None:
    # A Wilson interval for a proportion is bounded to [0, 1]; κ can go negative. label's lower bound is
    # < 0, which a proportion interval could never produce — proof κ is not routed through Wilson.
    assert _ci_by_axe()["label"].ci_low < 0.0


def test_every_class_records_seed_and_resamples() -> None:
    for c in class_kappa_cis(_artifact()):
        assert c.resamples == 10000
        assert c.seed == 0
        assert 0.0 <= c.degenerate_share <= 1.0


def test_ci_point_kappa_matches_the_class_kappa() -> None:
    point = {c.axe_rule: round(c.kappa, 6) for c in class_kappas(_artifact())}
    with_ci = {c.axe_rule: round(c.kappa, 6) for c in class_kappa_cis(_artifact())}
    assert point == with_ci


def _ceil_by_axe(name: str = "run_1.json", *, partial_flags: bool = True) -> dict[str, ClassCeiling]:
    return {c.axe_rule: c for c in class_ceilings(_artifact(name), partial_flags=partial_flags)}


def test_ceiling_rows_reproduce_the_pre_registered_table() -> None:
    ceil = _ceil_by_axe()
    assert (ceil["link-name"].errors, ceil["link-name"].p_value) == (9, 0.5**9)  # 0.0020
    assert (ceil["label"].errors, ceil["label"].p_value) == (5, 0.5**5)  # 0.0312
    assert (ceil["document-title"].errors, ceil["document-title"].p_value) == (3, 0.5**3)  # 0.1250
    assert (ceil["empty-heading"].errors, ceil["empty-heading"].p_value) == (2, 0.5**2)  # 0.2500


def test_certifiability_verdicts() -> None:
    ceil = _ceil_by_axe()
    assert ceil["link-name"].certifiable is True
    assert ceil["label"].certifiable is True
    assert ceil["document-title"].certifiable is False  # 0.125 > alpha at ANY fix quality — a size limit
    assert ceil["empty-heading"].certifiable is False  # the control


def test_ceiling_error_split_matches_class_kappa() -> None:
    kap = {c.axe_rule: c for c in class_kappas(_artifact())}
    for c in class_ceilings(_artifact()):
        k = kap[c.axe_rule]
        assert (c.fp, c.fn, c.errors) == (k.fp, k.fn, k.fp + k.fn)


def test_alpha_is_pre_registered_on_every_row() -> None:
    assert all(c.alpha == 0.05 for c in class_ceilings(_artifact()))


def test_pre_registration_prose_states_the_limits() -> None:
    text = CEILING_PREREGISTRATION.lower()
    assert "one-sided" in text
    assert "gold set" in text
    assert "noise floor" in text


def test_partial_flags_false_shifts_only_the_link_ceiling() -> None:
    true_ = _ceil_by_axe()
    false_ = _ceil_by_axe(partial_flags=False)
    # link's two partially_supports cry-wolves vanish → errors 9→7, still certifiable; no verdict flips
    assert false_["link-name"].errors == 7
    assert false_["link-name"].certifiable is True
    for axe in ("document-title", "empty-heading", "label"):
        assert false_[axe].errors == true_[axe].errors
        assert false_[axe].certifiable == true_[axe].certifiable
