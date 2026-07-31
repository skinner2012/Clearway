"""The anchored judging path, proven end to end before a call is spent.

The stub is the point: every response here is a sha256 of the ask, so nothing below is evidence about
the judge and everything below is evidence about the harness — the ask count and its gate, the frozen
bytes reaching the model unchanged, the two collapses in their pinned order, and the unit travelling out
beside the cells. The mutation gate is re-counted through the pre-flight's own correctness predicate
rather than through the function under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clearway.eval.judge_anchored import (
    CONFIGURATION,
    CONFORMANCE_FLIP,
    DETECTION_AXIS,
    NATURAL,
    SC_SWAP,
    STUB_DISCLAIMER,
    StubJudgeClient,
    anchored_asks,
    draft_row,
    dry_run,
    injected_results,
    judged_cases_from,
    report_path,
    run_pass,
    score_anchored,
)
from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_preflight import conformance_correct
from clearway.eval.stats import is_flag
from clearway.judge import FindingInput, Judge, verdict_from
from clearway.schemas.models import Conformance, JudgeResult

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"
_DRAFTER_MODEL = "gemma4:31b"


def _artifact() -> dict:
    return json.loads(_REPLAY.read_text())


def _judge(salt: str = "t") -> tuple[Judge, StubJudgeClient]:
    client = StubJudgeClient(salt=salt)
    return Judge(client, drafter_model=_DRAFTER_MODEL), client


def test_a_pass_asks_once_per_draft_twice_over_and_a_third_time_where_the_draft_was_right() -> None:
    """The ask count and its gate, counted here through the pre-flight's own correctness predicate.

    The flip is applied only to a conformance-correct draft, because flipping a wrong verdict can land
    on the right one and the mutation stops being known-wrong. Counting the gate a second way is the
    check: if the two disagree, one of them is applying a different collapse to ACT gold.
    """
    artifact = _artifact()
    asks = anchored_asks(artifact)
    counts = {m: sum(1 for a in asks if a.mutation == m) for m in (NATURAL, SC_SWAP, CONFORMANCE_FLIP)}
    drafts = [(c, d) for c in artifact["cases"] for d in c["drafts"]]
    correct = sum(1 for c, d in drafts if conformance_correct(Conformance(d["conformance"]), c["expected"]))

    assert counts[NATURAL] == counts[SC_SWAP] == len(drafts)
    assert counts[CONFORMANCE_FLIP] == correct
    assert len(asks) == 2 * len(drafts) + correct


def test_both_mutations_really_are_known_wrong() -> None:
    """A mutation that left the draft right would put a correct draft in the injected denominator."""
    artifact = _artifact()
    gold = {c["act_testcase_id"]: set(c["gold_success_criteria"]) for c in artifact["cases"]}
    natural = {a.finding_id: a.draft for a in anchored_asks(artifact) if a.mutation == NATURAL}
    for ask in anchored_asks(artifact):
        if ask.mutation == SC_SWAP:
            cited = {c.sc_id for c in ask.draft.citations}
            assert cited and not (cited & gold[ask.act_testcase_id]), ask.finding_id
            assert ask.draft.conformance is natural[ask.finding_id].conformance  # the verdict is untouched
        if ask.mutation == CONFORMANCE_FLIP:
            assert is_flag(ask.draft.conformance) != is_flag(natural[ask.finding_id].conformance)


def test_every_ask_is_the_frozen_block_plus_a_draft_presentation() -> None:
    """The finding side is sent verbatim: the whole difference between two asks sits after those bytes."""
    artifact = _artifact()
    asks = anchored_asks(artifact)
    record = load_record()
    prepared = prepared_inputs(record)
    blocks = {row["finding_id"]: row["finding_block"] for row in record["rows"]}

    judge, client = _judge()
    run_pass(judge, prepared, asks[:12], run_id="r")
    for ask, request in zip(asks[:12], client.requests, strict=True):
        assert request.startswith(blocks[ask.finding_id])
        assert "DRAFTED ROW (grade this)" in request.removeprefix(blocks[ask.finding_id])
        assert "DRAFTED ROW" not in blocks[ask.finding_id]


def test_a_finding_with_no_frozen_block_is_refused_rather_than_judged() -> None:
    artifact = _artifact()
    judge, _ = _judge()
    with pytest.raises(KeyError, match="no frozen finding-side block"):
        run_pass(judge, {"nothing": FindingInput(finding_id="nothing", block="x")}, anchored_asks(artifact), "r")


def test_the_case_collapse_releases_only_where_every_finding_was_released() -> None:
    artifact = _artifact()
    releases = {d["finding_id"]: True for c in artifact["cases"] for d in c["drafts"]}
    all_clear = judged_cases_from(artifact, releases)
    assert len(all_clear) == len(artifact["cases"])
    assert all(all(c.judge_passes) for c in all_clear)

    multi = next(c for c in artifact["cases"] if len(c["drafts"]) > 1)
    releases[multi["drafts"][0]["finding_id"]] = False
    one_hand = {c.act_testcase_id: c for c in judged_cases_from(artifact, releases)}[multi["act_testcase_id"]]
    assert not all(one_hand.judge_passes)
    assert sum(1 for p in one_hand.judge_passes if not p) == 1  # exactly the one hand, not the case


def test_scoring_records_the_unit_at_both_denominators() -> None:
    artifact = _artifact()
    asks = anchored_asks(artifact)
    prepared = prepared_inputs(load_record())
    passes = []
    for index in range(3):
        judge, _ = _judge(f"p{index}")
        passes.append(run_pass(judge, prepared, asks, run_id=f"r{index}"))
    scoring = score_anchored(artifact, asks, passes)

    assert (scoring.per_case.unit, scoring.per_case.n) == ("case", len(artifact["cases"]))
    assert (scoring.per_finding.unit, scoring.per_finding.n) == (
        "finding",
        sum(len(c["drafts"]) for c in artifact["cases"]),
    )
    assert len(scoring.releases) == scoring.per_finding.n
    # ⚠️ The injected denominators are per mutated DRAFT and the unit argument never re-bases them.
    flip_n = sum(1 for a in asks if a.mutation == CONFORMANCE_FLIP)
    swap_n = sum(1 for a in asks if a.mutation == SC_SWAP)
    for scored in (scoring.per_case, scoring.per_finding):
        assert scored.confusion.injected_conformance_flip.n == flip_n
        assert scored.confusion.injected_sc_swap.n == swap_n


def test_each_mutation_is_detected_on_the_axis_it_moved() -> None:
    """An SC swap edits the citation and leaves the verdict alone, so only the citation axis sees it.

    Pinned against the acceptance builder's own rule rather than restated: that path records
    `caught = not swapped.citation_correct` and `caught = not flipped.conformance_correct`, and two
    paths answering the same question off different fields is how a detection rate comes to describe
    something nobody asked about.
    """
    builder = (_REPO / "clearway" / "eval" / "offline_build.py").read_text()
    assert '"caught": not swapped.citation_correct' in builder
    assert '"caught": not flipped.conformance_correct' in builder
    assert DETECTION_AXIS == {SC_SWAP: "citation_correct", CONFORMANCE_FLIP: "conformance_correct"}

    artifact = _artifact()
    asks = anchored_asks(artifact)
    # one pass in which the judge disputes every citation and endorses every verdict: the swap is
    # caught everywhere, the flip nowhere.
    disputes_citation = [
        JudgeResult(
            finding_id=a.finding_id,
            run_id="r",
            judge_model="m",
            judge_version="v",
            verdict=verdict_from(False, True),
            citation_correct=False,
            conformance_correct=True,
            rationale="",
        )
        for a in asks
    ]
    swaps = injected_results(asks, [disputes_citation], SC_SWAP)
    flips = injected_results(asks, [disputes_citation], CONFORMANCE_FLIP)
    assert swaps and all(r.caught for r in swaps)
    assert flips and not any(r.caught for r in flips)


def test_a_natural_draft_has_no_detection_axis_because_it_is_not_a_mutation() -> None:
    with pytest.raises(ValueError, match="no detection axis"):
        injected_results(anchored_asks(_artifact()), [[]], NATURAL)


def test_a_frozen_draft_record_round_trips_into_the_row_the_judge_is_shown() -> None:
    record = _artifact()["cases"][0]["drafts"][0]
    row = draft_row(record)
    assert row.finding_id == record["finding_id"]
    assert row.conformance.value == record["conformance"]
    assert [c.sc_id for c in row.citations] == record["cited_sc_ids"]


def test_the_dry_run_spends_nothing_and_says_so_in_its_own_text() -> None:
    receipt = dry_run(passes=1)
    assert receipt["model_calls_spent"] == 0
    assert receipt["stubbed"] is True
    assert receipt["stub_disclaimer"] == STUB_DISCLAIMER
    assert receipt["stub_responses_served"] == receipt["asks_over_the_whole_configuration"]
    assert receipt["asks_over_the_whole_configuration"] == receipt["asks_per_pass"]["total"]


def test_an_even_pass_count_is_refused_at_the_door_rather_than_inside_the_collapse() -> None:
    """A strict majority across an even number of passes can tie, and a tie has no majority to take."""
    with pytest.raises(ValueError, match="ODD number of passes"):
        dry_run(passes=2)


def test_the_receipt_names_its_configuration() -> None:
    """Two dry receipts now sit side by side and their booleans answer different questions, so each
    has to say which one it holds — a marker on only the newer file leaves the pair ambiguous."""
    receipt = json.loads(report_path().read_text())
    assert receipt["configuration"] == CONFIGURATION == "anchored"
    assert "grades that draft" in receipt["configuration_meaning"]


def test_the_committed_receipt_is_what_a_rerun_produces() -> None:
    """Deterministic end to end — the stub is a hash, and nothing in the record reads a clock."""
    on_disk = json.loads(report_path().read_text())
    assert on_disk == dry_run(passes=on_disk["passes"])
