"""The paired-thesis harness: discordant b/c and the pre-registered sign tests, Run A vs the baseline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clearway.eval.paired import ClassVerdict, PooledVerdict, pair_verdicts
from clearway.schemas.models import CaseVerdict, VerdictVector


def _vector(cases: list[CaseVerdict]) -> VerdictVector:
    """A VerdictVector with the provenance fields filled — only `cases` matters to the pairing."""
    return VerdictVector(
        partial_flags=True,
        cases=cases,
        run_ids=["r"],
        config_id="m1-single@1",
        eval_set_id="act-acceptance@1",
        corpus_version="corpus@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        axe_core_version="4.12.1",
        act_export_hash="abc",
        created_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        rationale="test",
    )


def _case(tid: str, rule: str, drafter_flag: bool, gold_flag: bool) -> CaseVerdict:
    return CaseVerdict(
        act_testcase_id=tid,
        axe_rule=rule,
        drafter_flag=drafter_flag,
        gold_flag=gold_flag,
        conformances=["does_not_support"] if drafter_flag else ["supports"],
    )


def test_all_reachable_errors_fixed_no_regression_certifies() -> None:
    # baseline wrong on all 5 label cases (drafter CLEAN where gold FLAG); run fixes all 5.
    base = _vector([_case(f"l{i}", "label", drafter_flag=False, gold_flag=True) for i in range(5)])
    run = _vector([_case(f"l{i}", "label", drafter_flag=True, gold_flag=True) for i in range(5)])
    result = pair_verdicts(base, run)
    label = next(c for c in result.classes if c.axe_rule == "label")
    assert (label.improved, label.regressed) == (5, 0)
    assert label.p_value == pytest.approx(0.03125)
    assert label.verdict == "certified"


def test_one_regression_breaks_certification() -> None:
    # run fixes 4 of 5 but breaks a previously-correct case → b=4, c=1, p=0.109.
    base = _vector(
        [_case(f"l{i}", "label", drafter_flag=False, gold_flag=True) for i in range(5)]
        + [_case("ok", "label", drafter_flag=True, gold_flag=True)]
    )
    run = _vector(
        [_case(f"l{i}", "label", drafter_flag=(i < 4), gold_flag=True) for i in range(5)]
        + [_case("ok", "label", drafter_flag=False, gold_flag=True)]
    )
    label = next(c for c in pair_verdicts(base, run).classes if c.axe_rule == "label")
    assert (label.improved, label.regressed) == (4, 1)
    assert label.verdict == "worked_but_uncertifiable"


def test_no_movement_is_failed() -> None:
    base = _vector([_case(f"l{i}", "label", drafter_flag=False, gold_flag=True) for i in range(5)])
    run = _vector([_case(f"l{i}", "label", drafter_flag=False, gold_flag=True) for i in range(5)])
    label = next(c for c in pair_verdicts(base, run).classes if c.axe_rule == "label")
    assert (label.improved, label.regressed) == (0, 0)
    assert label.verdict == "failed"


def test_pooled_sums_across_label_and_link_name() -> None:
    base = _vector(
        [_case(f"l{i}", "label", drafter_flag=False, gold_flag=True) for i in range(3)]
        + [_case(f"k{i}", "link-name", drafter_flag=False, gold_flag=True) for i in range(3)]
        + [_case("h", "empty-heading", drafter_flag=False, gold_flag=True)]
    )
    run = _vector(
        [_case(f"l{i}", "label", drafter_flag=True, gold_flag=True) for i in range(3)]
        + [_case(f"k{i}", "link-name", drafter_flag=True, gold_flag=True) for i in range(3)]
        + [_case("h", "empty-heading", drafter_flag=True, gold_flag=True)]  # control moved — excluded from pool
    )
    result = pair_verdicts(base, run)
    assert isinstance(result.pooled, PooledVerdict)
    # pool is label+link-name only: 6 improvements, control's improvement not counted
    assert (result.pooled.improved, result.pooled.regressed) == (6, 0)
    assert result.pooled.axe_rules == ("label", "link-name")


def test_mismatched_case_sets_raise() -> None:
    base = _vector([_case("a", "label", drafter_flag=False, gold_flag=True)])
    run = _vector([_case("b", "label", drafter_flag=True, gold_flag=True)])
    with pytest.raises(ValueError, match="case sets differ"):
        pair_verdicts(base, run)


def test_document_title_ceiling_never_certifies() -> None:
    # 3 errors all fixed, zero regressions → best possible p = 0.125 > 0.05: uncertifiable by construction.
    base = _vector([_case(f"t{i}", "document-title", drafter_flag=True, gold_flag=False) for i in range(3)])
    run = _vector([_case(f"t{i}", "document-title", drafter_flag=False, gold_flag=False) for i in range(3)])
    dt = next(c for c in pair_verdicts(base, run).classes if c.axe_rule == "document-title")
    assert (dt.improved, dt.regressed) == (3, 0)
    assert dt.p_value == pytest.approx(0.125)
    assert dt.verdict == "worked_but_uncertifiable"
    assert dt.verdict != "certified"


def test_class_verdict_type_and_gold_unchanged_assertion() -> None:
    # gold_flag must match between baseline and run for a shared case — a gold drift is a hard error.
    base = _vector([_case("a", "label", drafter_flag=False, gold_flag=True)])
    run = _vector([_case("a", "label", drafter_flag=True, gold_flag=False)])
    with pytest.raises(ValueError, match="gold_flag drifted"):
        pair_verdicts(base, run)
    assert ClassVerdict  # symbol exported
