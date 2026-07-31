"""The blind judging path, proven end to end before a call is spent.

The stub is the point: every answer here is a sha256 of the ask, so nothing below is evidence about
the judge and everything below is evidence about the harness — one ask per finding and no mutation,
the frozen block reaching the model with no draft appended, agreement computed in code, the two
collapses in their pinned order, and the unit travelling out beside the cells.

Two things this file exists to check that a copy of the anchored tests would not: that the reuse of
the anchored harness is *verified* rather than assumed (the anchored stub answers a schema this
configuration rejects), and that the distinct-ask count is measured rather than inherited.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.judge_anchored import StubJudgeClient
from clearway.eval.judge_anchored_baseline import report_path as anchored_report_path
from clearway.eval.judge_blind import (
    CONFIGURATION,
    STUB_DISCLAIMER,
    BlindOutcome,
    StubBlindJudgeClient,
    anchored_majority_releases,
    axis_majorities,
    between_configuration_difference,
    blind_asks,
    blind_attempts_per_call,
    conformance_majorities,
    direction_block,
    disagreement_profile,
    distinct_ask_profile,
    dry_run,
    releases,
    report_path,
    run_pass,
    sc_axis_coupling,
    score_blind,
)
from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_observation_unit import OBSERVATION_UNIT
from clearway.eval.judge_score import CONFUSION_UNIT_CASE, CONFUSION_UNIT_FINDING
from clearway.judge import BlindAnswer, BlindJudge, FindingInput, JudgeError
from clearway.schemas.models import Citation, Conformance, DraftRow, JudgeVerdict

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"
_DRAFTER_MODEL = "gemma4:31b"


def _artifact() -> dict[str, Any]:
    return json.loads(_REPLAY.read_text())


def _judge(salt: str = "t") -> tuple[BlindJudge, StubBlindJudgeClient]:
    client = StubBlindJudgeClient(salt=salt)
    return BlindJudge(client, drafter_model=_DRAFTER_MODEL), client


def _passes(artifact: dict[str, Any], count: int = 3) -> tuple[list[Any], list[list[BlindOutcome]]]:
    asks = blind_asks(artifact)
    prepared = prepared_inputs(load_record())
    passes = []
    for index in range(count):
        judge, _ = _judge(f"p{index}")
        passes.append(run_pass(judge, prepared, asks, run_id=f"r{index}"))
    return asks, passes


def _outcome(judge: BlindJudge, conformance: Conformance, *sc_ids: str) -> BlindOutcome:
    """One blind answer compared against a fixed draft — `supports`, citing 1.1.1."""
    answer = BlindAnswer(finding_id="f", conformance=conformance, cited_sc_ids=sc_ids, rationale="r")
    draft = DraftRow(
        finding_id="f", conformance=Conformance.SUPPORTS, citations=[Citation(sc_id="1.1.1")], confidence=0.9
    )
    return BlindOutcome(answer=answer, result=judge.compare(answer, draft, "r"))


# --- the asks -----------------------------------------------------------------


def test_a_pass_asks_once_per_finding_and_runs_no_mutation() -> None:
    """The whole cost difference from the anchored side, and the reason is in `NO_MUTATIONS_HERE`."""
    artifact = _artifact()
    asks = blind_asks(artifact)
    drafts = [d for c in artifact["cases"] for d in c["drafts"]]
    assert len(asks) == len(drafts)
    assert [a.finding_id for a in asks] == [d["finding_id"] for d in drafts]  # same order as anchored


def test_every_ask_is_the_frozen_block_and_nothing_else() -> None:
    """The blinding, asserted on the bytes that left: no draft, no suffix, no re-rendering."""
    artifact = _artifact()
    asks = blind_asks(artifact)
    record = load_record()
    prepared = prepared_inputs(record)
    blocks = {row["finding_id"]: row["finding_block"] for row in record["rows"]}

    judge, client = _judge()
    run_pass(judge, prepared, asks[:12], run_id="r")
    for ask, request in zip(asks[:12], client.requests, strict=True):
        assert request == blocks[ask.finding_id]
        assert "DRAFTED ROW" not in request
        assert ask.draft.conformance.value not in request.split("- HTML:")[0]


def test_a_finding_with_no_frozen_block_is_refused_rather_than_judged() -> None:
    artifact = _artifact()
    judge, _ = _judge()
    with pytest.raises(KeyError, match="no frozen finding-side block"):
        run_pass(judge, {"nothing": FindingInput(finding_id="nothing", block="x")}, blind_asks(artifact), "r")


# --- the reuse of the anchored harness, verified rather than assumed ----------


def test_the_anchored_stub_cannot_answer_this_configuration() -> None:
    """A runner reused across two configurations must fail loudly on the wrong one.

    The anchored stub returns the anchored schema's two booleans. Handed to the blind judge it produces
    no parseable answer at all, and the judge raises rather than degrading to a fabricated verdict —
    which is the property that makes reusing the rest of the harness safe.
    """
    judge = BlindJudge(StubJudgeClient(salt="x"), drafter_model=_DRAFTER_MODEL)
    with pytest.raises(JudgeError):
        judge.answer(FindingInput(finding_id="f", block="B"))


def test_the_two_configurations_walk_the_same_findings_in_the_same_order() -> None:
    """What makes the anchored per-case and per-finding streams reusable here without re-deriving them."""
    from clearway.eval.judge_anchored import NATURAL, anchored_asks

    artifact = _artifact()
    anchored = [a.finding_id for a in anchored_asks(artifact) if a.mutation == NATURAL]
    assert anchored == [a.finding_id for a in blind_asks(artifact)]


# --- agreement is computed in code -------------------------------------------


def test_the_routing_decision_is_the_conformance_axis_and_the_majority_is_per_axis() -> None:
    judge, _ = _judge()
    artifact = _artifact()
    asks, passes = _passes(artifact)
    majorities = axis_majorities(asks, passes)
    released = releases(asks, passes)
    assert set(released) == {a.finding_id for a in asks}
    assert all(released[fid] is majorities[fid]["conformance_correct"] for fid in released)


def test_a_four_valued_verdict_with_no_strict_majority_is_undecided_rather_than_fatal() -> None:
    """The pinned `majority_stream` refuses a tie because a routing decision must not be a coin flip.
    This quantity is descriptive and four-valued, so three distinct answers is a reportable outcome."""
    judge, _ = _judge()
    three_ways = [
        [_outcome(judge, Conformance.SUPPORTS)],
        [_outcome(judge, Conformance.PARTIALLY_SUPPORTS)],
        [_outcome(judge, Conformance.DOES_NOT_SUPPORT)],
    ]
    ask = blind_asks(_artifact())[0]
    only = [type(ask)(**{**ask.__dict__, "finding_id": "f"})]
    assert conformance_majorities(only, three_ways)["f"] is None

    two_of_three = [three_ways[0], three_ways[0], three_ways[2]]
    assert conformance_majorities(only, two_of_three)["f"] is Conformance.SUPPORTS


def test_scoring_records_the_unit_at_both_denominators_and_holds_no_injected_rate() -> None:
    artifact = _artifact()
    asks, passes = _passes(artifact)
    scoring = score_blind(artifact, asks, passes)
    assert scoring.per_case.unit == CONFUSION_UNIT_CASE == OBSERVATION_UNIT
    assert scoring.per_case.n == len(artifact["cases"])
    assert scoring.per_finding.unit == CONFUSION_UNIT_FINDING
    assert scoring.per_finding.n == len(asks)
    # Empty rather than zero: no mutation was ever run on this side.
    assert scoring.per_case.confusion.injected_conformance_flip.n == 0
    assert scoring.per_case.confusion.injected_sc_swap.n == 0


def test_the_direction_of_a_disagreement_needs_the_judges_own_verdict() -> None:
    rows = [
        {
            "conformance_disagreement": True,
            "judge_conformance": "does_not_support",
            "judge_strictness": 2,
            "draft_strictness": 0,
        },
        {
            "conformance_disagreement": True,
            "judge_conformance": "supports",
            "judge_strictness": 0,
            "draft_strictness": 1,
        },
        {
            "conformance_disagreement": True,
            "judge_conformance": "not_applicable",
            "judge_strictness": None,
            "draft_strictness": 0,
        },
        {"conformance_disagreement": True, "judge_conformance": None, "judge_strictness": None, "draft_strictness": 2},
        {
            "conformance_disagreement": False,
            "judge_conformance": "supports",
            "judge_strictness": 0,
            "draft_strictness": 0,
        },
    ]
    block = direction_block(rows)
    assert block["conformance_disagreements"] == 4
    assert block["judge_stricter"] == 1
    assert block["drafter_stricter"] == 1
    assert block["off_the_strictness_axis"] == 2  # not_applicable, and the undecided verdict
    assert block["undecided_judge_verdict"] == 1


def test_the_disagreement_rate_is_per_finding_and_carries_its_absolute_counts() -> None:
    artifact = _artifact()
    asks, passes = _passes(artifact)
    profile = disagreement_profile(artifact, asks, passes, prepared_inputs(load_record()))
    assert profile["unit"] == "finding"
    overall = profile["overall"]
    assert overall["findings"] == len(asks)
    assert overall["disagreements"] == sum(row["disagreements"] for row in profile["per_class"])
    assert 0 < overall["distinct_cases_touched"] <= len(artifact["cases"])
    composition = overall["composition"]
    assert composition["conformance_only"] + composition["sc_only"] + composition["both"] == overall["disagreements"]


# --- the distinct-ask count, measured rather than inherited -------------------


def test_the_two_axes_are_coupled_and_the_artifact_counts_the_rows_it_happens_on() -> None:
    """The SC axis is largely a restatement of the conformance axis, and a reader must not treat the
    three composition shares as three independent channels.

    The three groups partition the set, and the third group's premise is checked rather than asserted:
    a flagging draft that cited nothing would carry the same forced mismatch as the second group and
    would not belong in the free-of-the-verdict count.
    """
    from clearway.eval.stats import is_flag

    artifact = _artifact()
    block = sc_axis_coupling(artifact)
    rows = [d for c in artifact["cases"] for d in c["drafts"]]
    assert block["findings"] == len(rows)
    assert (
        block["clean_draft_citing_nothing"]
        + block["clean_draft_citing_anyway"]
        + block["flagging_draft_carrying_an_sc_judgment_free_of_the_verdict"]
        == block["findings"]
    )
    assert not [d for d in rows if is_flag(Conformance(d["conformance"])) and not d["cited_sc_ids"]]
    assert "must never be" in block["note"] and "DIFFERENT QUESTIONS" in block["note"]


def test_every_per_class_row_carries_its_own_ask_duplication() -> None:
    """The classes are not equally independent, and the caveat has to meet the reader of the table.

    Taken from the distinct-ask profile rather than recomputed, so the two can never disagree.
    """
    receipt = json.loads(report_path().read_text())
    duplication = {row["axe_rule"]: row for row in receipt["distinct_asks"]["per_class"]}
    for row in receipt["disagreement"]["per_class"]:
        assert row["distinct_asks"] == duplication[row["axe_rule"]]["distinct_asks"]
        assert row["findings_in_a_duplicate_group"] == duplication[row["axe_rule"]]["findings_in_a_duplicate_group"]
        assert row["distinct_asks"] <= row["findings"]


def test_the_coupling_block_rides_with_the_disagreement_profile() -> None:
    """It has to sit where the SC counts are read, not in a module docstring nobody opens."""
    receipt = json.loads(report_path().read_text())
    assert receipt["disagreement"]["sc_axis_coupling"]["findings"] == receipt["disagreement"]["overall"]["findings"]


def test_the_distinct_ask_count_is_measured_through_the_path_that_sends_it() -> None:
    """The anchored side's figure is an upper bound: the blind ask is the block alone, so removing the
    draft can only merge more asks together. Counted here, per class, over the rendered prompts."""
    artifact = _artifact()
    asks = blind_asks(artifact)
    prepared = prepared_inputs(load_record())
    profile = distinct_ask_profile(asks, prepared)

    assert profile["asks"] == len(asks)
    assert profile["distinct_asks"] <= profile["asks"]
    assert profile["distinct_asks"] == profile["distinct_frozen_blocks"]  # the prompt appends nothing
    assert sum(row["findings"] for row in profile["per_class"]) == profile["asks"]
    assert (
        profile["findings_in_a_duplicate_group"]
        == profile["asks"] - profile["distinct_asks"] + (profile["duplicate_groups"])
    )
    assert profile["duplicate_groups_spanning_more_than_one_case"] <= profile["duplicate_groups"]


def test_a_duplicated_block_is_counted_as_one_ask() -> None:
    """The property the whole measurement rests on, on a two-row case built for it."""
    artifact = _artifact()
    asks = blind_asks(artifact)[:2]
    same = {a.finding_id: FindingInput(finding_id=a.finding_id, block="IDENTICAL") for a in asks}
    profile = distinct_ask_profile(asks, same)
    assert profile["asks"] == 2
    assert profile["distinct_asks"] == 1
    assert profile["findings_in_a_duplicate_group"] == 2


# --- the contrast that did not exist until this configuration ran -------------


def test_the_between_configuration_contrast_runs_against_the_frozen_anchored_decisions() -> None:
    """One variable — the judge's prompt — over the same drafts and the same frozen finding side.

    ⚠️ The blind half here is stubbed, so the correlation is a harness number. What is asserted is the
    shape and the pairing: the anchored side is rebuilt through the anchored harness' own majority, and
    the two streams cover the same findings.
    """
    artifact = _artifact()
    asks, passes = _passes(artifact)
    anchored = anchored_majority_releases(artifact, json.loads(anchored_report_path().read_text()))
    assert set(anchored) == {a.finding_id for a in asks}

    block = between_configuration_difference(artifact, asks, passes, anchored)
    assert block["findings"] == len(asks)
    assert block["cases"] == len(artifact["cases"])
    assert 0 <= block["findings_whose_routing_decision_differs"] <= block["findings"]
    assert 0 <= block["cases_whose_collapsed_decision_differs"] <= block["cases"]
    assert block["icc"] is None or -1.0 <= block["icc"] <= 1.0
    # The record has to SAY which case it is, without a reader knowing the sign convention — and it
    # says it by reporting the sign rather than by grading itself against an invented cutoff.
    assert block["sign"] == ("negative" if block["icc"] < 0 else "positive" if block["icc"] > 0 else "zero")
    assert "COSTING POWER" in block["reading"] and block["sign"] in block["reading"]


def test_a_missing_anchored_decision_is_refused_rather_than_paired_around() -> None:
    artifact = _artifact()
    asks, passes = _passes(artifact)
    partial = {a.finding_id: True for a in asks[:-1]}
    with pytest.raises(Exception, match="did not run over the same findings"):
        between_configuration_difference(artifact, asks, passes, partial)


# --- the dry run and its receipt ---------------------------------------------


def test_the_dry_run_spends_nothing_and_says_so_in_its_own_text() -> None:
    receipt = dry_run(passes=1)
    assert receipt["model_calls_spent"] == 0
    assert receipt["stubbed"] is True
    assert receipt["stub_disclaimer"] == STUB_DISCLAIMER
    assert receipt["stub_responses_served"] == receipt["asks_over_the_whole_configuration"]
    assert receipt["asks_over_the_whole_configuration"] == receipt["asks_per_pass"]["total"]


def test_the_paid_figure_is_declared_as_a_floor_with_its_ceiling() -> None:
    """A retry leaves no trace on disk, so the ask count is what a live run costs at best.

    The stubbed count in the same receipt is exact and is labelled separately: a stub cannot return an
    unparseable answer, which is a fact about the stub and not a bound on a paid run.
    """
    receipt = json.loads(report_path().read_text())
    budget = receipt["paid_call_budget_if_run_live"]
    assert budget["floor"] == receipt["asks_over_the_whole_configuration"]
    assert budget["ceiling"] == budget["floor"] * budget["max_attempts_per_call"]
    assert budget["max_attempts_per_call"] == blind_attempts_per_call() > 1
    assert "NEVER quote the floor as the spend" in budget["note"]
    assert receipt["stub_responses_served"] == budget["floor"]  # exact here, and only because of the stub


def test_the_receipt_names_its_configuration_and_the_unit_of_every_cell() -> None:
    """Two markers, and the second is not a substitute for the first: one says what a cell counts, the
    other says what `citation_correct` means."""
    receipt = json.loads(report_path().read_text())
    assert receipt["configuration"] == CONFIGURATION == "blind"
    assert "computed in code" in receipt["configuration_meaning"]
    assert receipt["confusion"]["per_case"]["unit"] == CONFUSION_UNIT_CASE
    assert receipt["confusion"]["per_finding"]["unit"] == CONFUSION_UNIT_FINDING


def test_an_even_pass_count_is_refused_at_the_door_rather_than_inside_the_collapse() -> None:
    with pytest.raises(ValueError, match="ODD number of passes"):
        dry_run(passes=2)


def test_the_committed_receipt_is_what_a_rerun_produces() -> None:
    """Deterministic end to end — the stub is a hash, and nothing in the record reads a clock."""
    on_disk = json.loads(report_path().read_text())
    assert on_disk == dry_run(passes=on_disk["passes"])


def test_the_verdict_derivation_is_the_anchored_one() -> None:
    """Same rule, so the two configurations' `verdict` fields mean the same thing about their own
    booleans — which is exactly why the configuration marker is needed to say what those booleans are."""
    judge, _ = _judge()
    both = _outcome(judge, Conformance.SUPPORTS, "1.1.1")
    assert both.result.verdict is JudgeVerdict.CORRECT
    one = _outcome(judge, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    assert one.result.verdict is JudgeVerdict.PARTIAL
    neither = _outcome(judge, Conformance.DOES_NOT_SUPPORT, "9.9.9")
    assert neither.result.verdict is JudgeVerdict.INCORRECT
