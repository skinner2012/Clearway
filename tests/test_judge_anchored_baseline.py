"""The live anchored harness, exercised without spending anything.

Everything here runs against fakes. What is under test is the machinery a paid run needs and a
stubbed one does not: that a restart replays instead of re-spending, that a replayed answer is
refused when it answers a different question, that usage survives the seam the judge drops it at,
that the floor bar is the order-invariant movement rather than the larger `improved` column, and
that the two axes are collapsed independently so a three-way split on the pair cannot tie.

The frozen record is pinned in three layers at the bottom of this file, because a record's own digest
passes any edit that recomputes it: a literal digest, a full re-derivation of every computed field
from the answers in the file, and — the layer only a paid artifact can have — a re-render of all 147
asks against the prompt digests the calls were made under, so the frozen answers are demonstrably
answers to today's questions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.judge_anchored import NATURAL, anchored_asks, run_pass
from clearway.eval.judge_anchored_baseline import (
    CallLedger,
    LedgerMismatch,
    RecordingJudgeClient,
    axis_majorities,
    between_configuration_difference,
    build_record,
    case_act_wrong,
    disagreement_profile,
    one_way_wins,
    record_digest,
    rederive_frozen_record,
    report_path,
    result_rows,
    results_from_rows,
    routing_flag_streams,
)
from clearway.eval.judge_observation_unit import DegenerateClustering
from clearway.judge import Judge, verdict_from
from clearway.llm import Completion, FakeLLMClient, ImagePart, LLMRequest, LLMUsage
from clearway.schemas.models import JudgeResult

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"
_DRAFTER_MODEL = "gemma4:31b"
_VERDICT = '{"citation_correct": true, "conformance_correct": false, "rationale": "because"}'
_OFF_SCHEMA = "not json at all"


def _artifact() -> dict[str, Any]:
    return json.loads(_REPLAY.read_text())


def _usage() -> LLMUsage:
    return LLMUsage(tokens_in=1200, tokens_out=40, cost_usd=0.0031, latency_ms=4200.0)


def _results(asks: Any, pattern: list[tuple[bool, bool]]) -> list[JudgeResult]:
    """One `JudgeResult` per ask, cycling a pattern of the two booleans."""
    return [
        JudgeResult(
            finding_id=ask.finding_id,
            run_id="r",
            judge_model="fake-judge",
            judge_version="prompt=deadbeef; effort=test",
            verdict=verdict_from(*pattern[index % len(pattern)]),
            citation_correct=pattern[index % len(pattern)][0],
            conformance_correct=pattern[index % len(pattern)][1],
            rationale="because",
        )
        for index, ask in enumerate(asks)
    ]


def test_the_recording_client_keeps_the_usage_the_judge_throws_away(tmp_path: Path) -> None:
    """`judge_prepared` returns a `JudgeResult`, which has nowhere to put tokens, cost or latency."""
    ledger = CallLedger.open(tmp_path / "calls.jsonl")
    client = RecordingJudgeClient(FakeLLMClient(_VERDICT, model="fake-judge", usage=_usage()), ledger, 1)
    judge = Judge(client, drafter_model=_DRAFTER_MODEL)

    from clearway.judge import FindingInput
    from clearway.schemas.models import Conformance, DraftRow

    draft = DraftRow(finding_id="f1", conformance=Conformance.SUPPORTS, citations=[], remediation="", confidence=0.5)
    result = judge.judge_prepared(FindingInput(finding_id="f1", block="FINDING\n- axe rule: label"), draft, "r")

    assert not hasattr(result, "cost_usd")  # the seam the wrapper exists to work around
    assert client.spent == 1
    assert [row["cost_usd"] for row in ledger.rows] == [0.0031]
    assert [row["latency_ms"] for row in ledger.rows] == [4200.0]
    assert [row["tokens_in"] for row in ledger.rows] == [1200]


def test_a_resumed_run_replays_the_ledger_instead_of_calling_again(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    first = FakeLLMClient(_VERDICT, model="fake-judge", usage=_usage())
    RecordingJudgeClient(first, CallLedger.open(path), 1).complete_json("sys", "user", _schema())
    assert len(first.requests) == 1

    second = FakeLLMClient(_VERDICT, model="fake-judge", usage=_usage())
    resumed = RecordingJudgeClient(second, CallLedger.open(path), 1)
    completion = resumed.complete_json("sys", "user", _schema())

    assert second.requests == []  # nothing reached the inner client
    assert (resumed.spent, resumed.replayed) == (0, 1)
    assert completion.content == _VERDICT
    assert completion.usage.cost_usd == 0.0031


def test_a_replayed_answer_to_a_different_prompt_is_refused(tmp_path: Path) -> None:
    """A ledger is only a saving if replaying it is indistinguishable from having made the call."""
    path = tmp_path / "calls.jsonl"
    RecordingJudgeClient(FakeLLMClient(_VERDICT, usage=_usage()), CallLedger.open(path), 1).complete_json(
        "sys", "the original ask", _schema()
    )
    resumed = RecordingJudgeClient(FakeLLMClient(_VERDICT, usage=_usage()), CallLedger.open(path), 1)
    with pytest.raises(LedgerMismatch, match="asks have moved under the ledger"):
        resumed.complete_json("sys", "a different ask", _schema())


def test_a_retry_is_recorded_as_its_own_call_so_the_count_is_not_the_ask_count(tmp_path: Path) -> None:
    """The judge retries an off-schema response; the ledger sees two calls where the artifact sees one row."""
    ledger = CallLedger.open(tmp_path / "calls.jsonl")
    client = RecordingJudgeClient(FakeLLMClient(_OFF_SCHEMA, _VERDICT, usage=_usage()), ledger, 1)
    judge = Judge(client, drafter_model=_DRAFTER_MODEL)

    from clearway.judge import FindingInput
    from clearway.schemas.models import Conformance, DraftRow

    draft = DraftRow(finding_id="f1", conformance=Conformance.SUPPORTS, citations=[], remediation="", confidence=0.5)
    judge.judge_prepared(FindingInput(finding_id="f1", block="block"), draft, "r")

    assert client.spent == 2  # one ask, two calls — the gap a floor-quoted total hides
    assert len(ledger.rows) == 2


def _schema() -> Any:
    from pydantic import BaseModel

    class _Verdict(BaseModel):
        citation_correct: bool
        conformance_correct: bool
        rationale: str

    return _Verdict


def test_the_floor_bar_is_the_order_invariant_movement_not_the_improved_column() -> None:
    """Which pass of a same-configuration pair is called 'before' is arbitrary, so 3/6 is 6/3."""
    rows = [
        {"improved": 3, "regressed": 6},
        {"improved": 4, "regressed": 2},
        {"improved": 5, "regressed": 3},
    ]
    assert one_way_wins(rows) == 6
    assert max(row["improved"] for row in rows) == 5  # the reading the correction replaced


def test_each_axis_is_collapsed_on_its_own_because_the_pair_can_split_three_ways() -> None:
    """Three passes returning three distinct (citation, conformance) pairs have no joint majority."""
    artifact = _artifact()
    asks = anchored_asks(artifact)
    naturals = [a for a in asks if a.mutation == NATURAL]
    passes = [
        _results(asks, [(True, True)]),
        _results(asks, [(True, False)]),
        _results(asks, [(False, True)]),
    ]
    majorities = axis_majorities(asks, passes)

    assert len(majorities) == len(naturals)
    assert all(m == {"citation_correct": True, "conformance_correct": True} for m in majorities.values())


def test_the_disagreement_event_is_wider_than_the_routing_decision() -> None:
    """Group A counts either axis; the confusion matrix's flag is the conformance axis alone."""
    artifact = _artifact()
    asks = anchored_asks(artifact)
    passes = [_results(asks, [(False, True), (True, False), (True, True)])] * 3
    profile = disagreement_profile(artifact, asks, passes)
    overall = profile["overall"]

    assert overall["findings"] == sum(len(c["drafts"]) for c in artifact["cases"])
    assert overall["disagreements"] > overall["conformance_axis_disagreements"]
    assert (
        overall["composition"]["conformance_only"] + overall["composition"]["sc_only"] + overall["composition"]["both"]
        == overall["disagreements"]
    )
    # the routing flag count is the conformance-axis subtotal, not the disagreement count
    flags = sum(1 for case in routing_flag_streams(artifact, asks, passes)[0] for flag in case if flag)
    assert flags == overall["conformance_axis_disagreements"]


def test_the_case_gold_predicate_is_the_cases_own_and_not_a_roll_up() -> None:
    artifact = _artifact()
    wrong = case_act_wrong(artifact)
    assert len(wrong) == len(artifact["cases"])
    # a case can be right while findings inside it are wrong — that is the collapse, and it is why
    # the ceiling at the case is smaller than the ceiling at the finding
    findings_wrong = sum(
        1
        for case in artifact["cases"]
        for d in case["drafts"]
        if (d["conformance"] in ("does_not_support", "partially_supports")) != (case["expected"] == "failed")
    )
    assert sum(wrong) < findings_wrong


def test_frozen_rows_from_a_different_run_are_refused_rather_than_realigned() -> None:
    artifact = _artifact()
    asks = anchored_asks(artifact)
    rows = result_rows(asks, _results(asks, [(True, True)]))
    with pytest.raises(LedgerMismatch, match="different runs"):
        results_from_rows(asks, rows[:-1], judge_model="m", judge_version="v", run_id="r")

    shuffled = [rows[1], rows[0], *rows[2:]]
    with pytest.raises(LedgerMismatch, match="not this configuration's asks"):
        results_from_rows(asks, shuffled, judge_model="m", judge_version="v", run_id="r")


def test_the_record_is_a_function_of_its_own_frozen_rows() -> None:
    """The property the freeze rests on: no clock, no network and no model inside `build_record`."""
    from clearway.eval.judge_finding_input import load_record
    from clearway.eval.run_artifacts import acceptance_pass_paths

    artifact = _artifact()
    asks = anchored_asks(artifact)
    pass_rows = [result_rows(asks, _results(asks, [(True, True), (False, True), (True, False)]))] * 3
    transport = [
        {
            "pass": p,
            "ordinal": i,
            "prompt_sha256": "0" * 64,
            "content": _VERDICT,
            "tokens_in": 10,
            "tokens_out": 2,
            "cost_usd": 0.01,
            "latency_ms": 100.0,
        }
        for p in (1, 2, 3)
        for i in range(len(asks))
    ]
    kwargs: dict[str, Any] = dict(
        artifact=artifact,
        replay_path=_REPLAY,
        input_record=load_record(),
        pass_rows=pass_rows,
        transport=transport,
        judge_model="fake-judge",
        judge_version="prompt=deadbeef; effort=test",
        judged_paths=acceptance_pass_paths(),
        ledger={"path": "x", "calls_made_in_this_process": 0, "calls_replayed_from_the_ledger": 0, "note": "n"},
    )
    first = build_record(created_at="2026-01-01T00:00:00+00:00", wall_clock_seconds=1.0, **kwargs)
    second = build_record(created_at="2027-02-02T00:00:00+00:00", wall_clock_seconds=999.0, **kwargs)

    assert first["reproducible_digest"] == second["reproducible_digest"] == record_digest(first)
    assert first["cost"]["transport_calls"] == len(asks) * 3
    assert first["cost"]["calls_beyond_one_per_ask"] == 0


def test_the_two_halves_of_the_citation_habit_are_counted_separately() -> None:
    """A judge can dispute a citation it was shown, or dispute the absence of one — different events.

    Counting only the first makes an axis made entirely of the second read as clean, which is the
    misreading the artefact block exists to prevent.
    """
    artifact = _artifact()
    asks = anchored_asks(artifact)
    # a pass that disputes every citation and endorses every verdict: the whole SC axis lights up
    profile = disagreement_profile(artifact, asks, [_results(asks, [(False, True)])] * 3)
    artefact = profile["sc_axis_artefact"]

    rows = profile["rows"]
    cites_while_clean = {r["finding_id"] for r in rows if r["drafter_cites_on_a_clean_row"]}
    cites_nothing = {r["finding_id"] for r in rows if r["drafter_cites_nothing"]}
    assert not cites_while_clean & cites_nothing  # a row cites or it does not
    assert artefact["drafter_rows_that_cite_while_clean"] == len(cites_while_clean)
    assert artefact["drafter_rows_that_cite_nothing"] == len(cites_nothing)
    # with every row disagreeing on the SC axis, each half's landing count is its own size
    assert artefact["sc_axis_disagreements"] == len(rows)
    assert artefact["sc_axis_disagreements_on_rows_that_cite_while_clean"] == len(cites_while_clean)
    assert artefact["sc_axis_disagreements_on_rows_that_cite_nothing"] == len(cites_nothing)


def test_the_recorded_cost_says_it_is_a_price_table_rather_than_a_bill() -> None:
    """The client prices each call from a local table; nothing here observed what was charged."""
    from clearway.eval.judge_anchored_baseline import cost_block

    block = cost_block([{"tokens_in": 10, "tokens_out": 2, "cost_usd": 0.01, "latency_ms": 100.0}], asks_made=1)
    assert "not " in block["pricing_source"] and "billed" in block["pricing_source"]
    assert block["cost_priced_on"] == "1 of 1 calls"

    unpriced = cost_block([{"tokens_in": 10, "tokens_out": 2, "cost_usd": None, "latency_ms": 100.0}], asks_made=1)
    assert unpriced["cost_priced_on"] == "0 of 1 calls"
    assert unpriced["cost_usd"]["n"] == 0


def test_the_ledger_block_names_the_run_that_paid_and_survives_a_re_derivation() -> None:
    """A block carried across verbatim would keep describing a process that no longer wrote the file.

    `--rederive` makes no call at all, so a count named for "this process" is false the moment it runs;
    the block is reassembled from the two integers instead, which also keeps its own note current.
    """
    from clearway.eval.judge_anchored_baseline import PAID_CALLS, REPLAYED_CALLS, ledger_block

    block = ledger_block(paid=441, replayed=0)
    assert block[PAID_CALLS] == 441
    assert block[REPLAYED_CALLS] == 0
    assert "this process" not in block["note"]
    assert "BOUGHT" in block["note"]
    # the frozen record carries the same shape, and re-derivation regenerates rather than copies it
    frozen = _frozen()
    assert set(frozen["ledger"]) == set(block)
    assert rederive_frozen_record()["ledger"] == frozen["ledger"]
    # a hand-edited note is caught even though `ledger` sits outside the digest
    tampered = {**frozen, "ledger": {**frozen["ledger"], "note": "nothing to see"}}
    assert record_digest(tampered) == frozen["reproducible_digest"]
    assert rederive_frozen_record()["ledger"] != tampered["ledger"]


def test_two_configurations_are_refused_when_their_finding_orders_differ() -> None:
    """The earlier passes are ordered by the scoped cluster map and this run by the artifact's cases.

    They coincide today. A silent divergence would zip one configuration's answers against another's
    findings and publish the misalignment as a difference of opinion, so it is asserted, not assumed.
    """
    from clearway.eval.run_artifacts import acceptance_pass_paths

    artifact = _artifact()
    asks = anchored_asks(artifact)
    passes = [_results(asks, [(True, True)])] * 3
    # a case the scoped map drops — its rule is not one the gold still scores — leaves the artifact's
    # case order one cluster longer than the stream the earlier passes are read into
    artifact["cases"][0]["rule_name"] = "a rule the gold does not score"
    with pytest.raises(DegenerateClustering, match="cannot be paired position by position"):
        between_configuration_difference(artifact, asks, passes, acceptance_pass_paths())


# ---------------------------------------------------------------------------------------------
# The freeze — three layers, because a record's own digest passes any edit that recomputes it
# ---------------------------------------------------------------------------------------------

# The frozen record's digest over everything a re-derivation reproduces. Moving it means the
# measurement moved: re-record it by running the builder (`--rederive` for a computation change, the
# paid entry point for anything that moves an ask), never by retyping this string.
_FROZEN_DIGEST = "dfb7acd4a1ff534388ad49727e0bda197b379548e3e71490e5f9614c1ec1efd9"


def _frozen() -> dict[str, Any]:
    return json.loads(report_path().read_text())


def test_the_frozen_record_re_derives_from_the_answers_it_holds() -> None:
    """Every computed field, rebuilt by its own builder over the file's own responses."""
    frozen = _frozen()
    assert frozen["reproducible_digest"] == _FROZEN_DIGEST
    assert record_digest(frozen) == _FROZEN_DIGEST
    assert rederive_frozen_record() == frozen


def test_the_frozen_answers_are_answers_to_the_asks_as_they_stand_today() -> None:
    """The layer a digest cannot give: re-render every ask and match the digest it was answered under.

    A frozen response is only evidence while the question it answered is the question the code still
    asks. This re-assembles all 147 asks through the real judge — no model, only the prompt — and
    compares each one against the digest the paid call recorded, per pass.
    """
    from clearway.eval.judge_finding_input import load_record, prepared_inputs

    frozen = _frozen()
    asks = anchored_asks(_artifact())
    recorder = _DigestRecorder()
    run_pass(Judge(recorder, drafter_model=_DRAFTER_MODEL), prepared_inputs(load_record()), asks, run_id="freeze")

    for index in range(frozen["passes"]):
        recorded = [row["prompt_sha256"] for row in frozen["transport"] if row["pass"] == index + 1]
        assert recorded == recorder.digests, f"pass {index + 1} answered a different set of asks"


def test_the_frozen_ledger_is_one_row_per_ask_in_the_order_they_were_made() -> None:
    """A gap or a repeat in the ordinals would break the replay the ledger exists to make safe."""
    frozen = _frozen()
    asks_per_pass = frozen["asks_per_pass"]["total"]
    for index in range(frozen["passes"]):
        rows = [row for row in frozen["transport"] if row["pass"] == index + 1]
        assert [row["ordinal"] for row in rows] == list(range(asks_per_pass))
    assert frozen["cost"]["transport_calls"] == asks_per_pass * frozen["passes"]
    assert [len(block["results"]) for block in frozen["pass_results"]] == [asks_per_pass] * frozen["passes"]


class _DigestRecorder:
    """An `LLMClient` that answers nothing and records what each ask would have been sent as."""

    model = "fake-judge"
    reasoning_effort = "medium"

    def __init__(self) -> None:
        self.digests: list[str] = []

    def complete_json(self, system: str, user: str, schema: type[Any], image: ImagePart | None = None) -> Completion:
        self.digests.append(LLMRequest.of(system, user, schema, image).prompt_sha256)
        return Completion(_VERDICT, LLMUsage(tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=0.0))
