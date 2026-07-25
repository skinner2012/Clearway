"""Attribution of a later run against the run before it: did this run's one prompt change undo what the
previous run bought?

The pooled thesis is scored against the frozen pre-change baseline and answers "did the change help".
That is a different question from "did this run eat the last one", and the second is the one a run
carrying a single further prompt change has to answer — the rule being that a later tweak does not get
to consume an earlier fix. These tests pin the distinction case by case, because a class can regress
overall while losing none of the prior run's wins, and can lose a prior win while its totals look flat.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clearway.eval.paired import attribute_against_prior
from clearway.schemas.models import CaseVerdict, VerdictVector


def _vec(cases: list[CaseVerdict], run_id: str) -> VerdictVector:
    return VerdictVector(
        partial_flags=True,
        cases=cases,
        run_ids=[run_id],
        config_id="m1-single@1",
        eval_set_id="act-acceptance@1",
        corpus_version="corpus@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        axe_core_version="4.12.1",
        act_export_hash="abc",
        created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        rationale="test",
    )


def _case(tid: str, *, right: bool, axe_rule: str = "label") -> CaseVerdict:
    """One case whose gold says FAIL, with the drafter either right (flagged) or wrong (clean)."""
    return CaseVerdict(
        act_testcase_id=tid, axe_rule=axe_rule, drafter_flag=right, gold_flag=True, conformances=["supports"]
    )


def _triple(states: dict[str, tuple[bool, bool, bool]]) -> tuple[VerdictVector, VerdictVector, VerdictVector]:
    """`{case_id: (baseline_right, prior_right, run_right)}` → the three vectors, in that order."""
    base = _vec([_case(t, right=s[0]) for t, s in states.items()], "baseline-1")
    prior = _vec([_case(t, right=s[1]) for t, s in states.items()], "prior-1")
    run = _vec([_case(t, right=s[2]) for t, s in states.items()], "run-1")
    return base, prior, run


def test_a_run_identical_to_the_prior_one_moves_nothing_and_eats_nothing() -> None:
    base, prior, run = _triple({"a": (False, True, True), "b": (True, True, True)})
    attribution = attribute_against_prior(base, prior, run)
    cls = attribution.classes[0]
    assert (cls.improved, cls.regressed) == (0, 0)
    assert cls.prior_gains_lost == ()
    assert attribution.eats_prior_run is False


def test_undoing_a_win_the_prior_run_bought_is_flagged_as_eating_it() -> None:
    """Baseline wrong → prior run right → this run wrong again. That case is exactly the gain the prior
    run bought and this run gave back, and it is the trigger for rolling the change back."""
    base, prior, run = _triple({"a": (False, True, False)})
    attribution = attribute_against_prior(base, prior, run)
    cls = attribution.classes[0]
    assert cls.prior_gains_lost == ("a",)
    assert cls.regressed == 1
    assert attribution.eats_prior_run is True


def test_a_regression_on_a_case_the_prior_run_never_fixed_is_not_eating_it() -> None:
    """Baseline right → prior right → this run wrong. A real regression, but not one that consumes the
    prior run's fix, because that case was never part of the fix. Conflating the two would trigger a
    rollback for something the earlier run never bought."""
    base, prior, run = _triple({"a": (True, True, False)})
    attribution = attribute_against_prior(base, prior, run)
    cls = attribution.classes[0]
    assert cls.regressed == 1
    assert cls.prior_gains_lost == ()
    assert attribution.eats_prior_run is False


def test_fixing_something_the_prior_run_left_broken_counts_as_an_improvement() -> None:
    base, prior, run = _triple({"a": (False, False, True)})
    attribution = attribute_against_prior(base, prior, run)
    cls = attribution.classes[0]
    assert (cls.improved, cls.regressed) == (1, 0)
    assert cls.improved_ids == ("a",)
    assert attribution.eats_prior_run is False


def test_a_class_can_net_flat_while_still_eating_a_prior_win() -> None:
    """One prior win given back, one new case fixed: improved and regressed both 1, so the totals look
    like nothing happened. The prior gain is still gone, and that is what decides the rollback."""
    base, prior, run = _triple({"a": (False, True, False), "b": (False, False, True)})
    attribution = attribute_against_prior(base, prior, run)
    cls = attribution.classes[0]
    assert (cls.improved, cls.regressed) == (1, 1)
    assert cls.prior_gains_lost == ("a",)
    assert attribution.eats_prior_run is True


def test_attribution_is_reported_per_class_so_a_change_can_be_made_class_conditional() -> None:
    """The remedy for eating a prior run is rollback OR making the change class-conditional, so which
    class lost the gain has to be named, not just that some class did."""
    base = _vec([_case("a", right=False), _case("k", right=False, axe_rule="link-name")], "baseline-1")
    prior = _vec([_case("a", right=True), _case("k", right=True, axe_rule="link-name")], "prior-1")
    run = _vec([_case("a", right=True), _case("k", right=False, axe_rule="link-name")], "run-1")

    attribution = attribute_against_prior(base, prior, run)
    by_rule = {c.axe_rule: c for c in attribution.classes}
    assert by_rule["label"].prior_gains_lost == ()
    assert by_rule["link-name"].prior_gains_lost == ("k",)
    assert attribution.eats_prior_run is True


def test_run_ids_of_both_sides_are_carried_so_the_comparison_is_auditable() -> None:
    base, prior, run = _triple({"a": (False, True, True)})
    attribution = attribute_against_prior(base, prior, run)
    assert attribution.prior_run_ids == ("prior-1",)
    assert attribution.run_run_ids == ("run-1",)


def test_a_differing_case_set_is_refused_rather_than_paired_on_the_overlap() -> None:
    base, prior, _ = _triple({"a": (False, True, True)})
    run = _vec([_case("a", right=True), _case("z", right=True)], "run-1")
    with pytest.raises(ValueError, match="case sets differ"):
        attribute_against_prior(base, prior, run)


def test_gold_drift_between_the_runs_is_a_hard_error() -> None:
    """Only the drafter's input may change between two runs. A moved gold label means the two vectors
    are not measuring the same thing, and pairing them would quietly compare different questions."""
    base, prior, _ = _triple({"a": (False, True, True)})
    flipped = CaseVerdict(
        act_testcase_id="a", axe_rule="label", drafter_flag=True, gold_flag=False, conformances=["supports"]
    )
    with pytest.raises(ValueError, match="gold_flag drifted"):
        attribute_against_prior(base, prior, _vec([flipped], "run-1"))


def test_the_attribution_serialises_for_the_frozen_result() -> None:
    base, prior, run = _triple({"a": (False, True, False)})
    payload = attribute_against_prior(base, prior, run).to_dict()
    assert payload["eats_prior_run"] is True
    assert payload["classes"][0]["prior_gains_lost"] == ["a"]
