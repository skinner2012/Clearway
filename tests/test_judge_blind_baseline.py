"""The blind configuration's paid runner, exercised end to end before it ever sees a cloud client.

**Nothing here spends anything.** `live_run` takes its client from a factory, so the same code path a
paid run takes — the ledger, the recording seam, the resume check, the record builder — is driven by
the deterministic stub. A runner proven only in its dry shape is a runner whose single-run assumptions
were never tested, and that failure mode has already cost this repo a re-run.

Every number these tests touch is a harness number. The stub's answers are a hash of the ask.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.judge_anchored_baseline import report_path as anchored_report_path
from clearway.eval.judge_blind import StubBlindJudgeClient, blind_asks
from clearway.eval.judge_blind_baseline import (
    NO_SUITE_WHILE_THIS_RUNS,
    answer_rows,
    build_record,
    live_run,
    outcomes_from_rows,
    record_digest,
    report_path,
)
from clearway.eval.judge_finding_input import load_record
from clearway.eval.judge_score import CONFUSION_UNIT_CASE, CONFUSION_UNIT_FINDING
from clearway.eval.judge_transport import PAID_CALLS, REPLAYED_CALLS, LedgerMismatch
from clearway.llm import LLMClient

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"


def _stub_factory() -> Callable[[], LLMClient]:
    """One salt per pass, so the majority-across-passes collapse has something to decide."""
    passes = iter(range(1, 100))

    def factory() -> LLMClient:
        return StubBlindJudgeClient(salt=f"pass-{next(passes)}")

    return factory  # type: ignore[return-value]


def _stubbed_run(tmp_path: Path, passes: int = 3) -> dict[str, Any]:
    return live_run(passes, client_factory=_stub_factory(), ledger_file=tmp_path / "ledger.jsonl")


def _artifact() -> dict[str, Any]:
    return json.loads(_REPLAY.read_text())


# --- the live path, driven by the stub ----------------------------------------


def test_a_full_stubbed_pass_through_the_live_path_produces_a_whole_record(tmp_path: Path) -> None:
    """Requirement six, asserted as a list: everything the dry receipt carries has to carry through,
    plus the two things only a real run can fill."""
    record = _stubbed_run(tmp_path)

    assert record["configuration"] == "blind"
    assert "computed in code" in record["configuration_meaning"]
    assert record["confusion"]["per_case"]["unit"] == CONFUSION_UNIT_CASE
    assert record["confusion"]["per_finding"]["unit"] == CONFUSION_UNIT_FINDING
    assert record["disagreement"]["sc_axis_coupling"]["findings"] == record["disagreement"]["overall"]["findings"]
    assert record["distinct_asks"]["distinct_asks"] <= record["distinct_asks"]["asks"]
    assert all("distinct_asks" in row for row in record["disagreement"]["per_class"])
    # the two a stub could not have produced from `dry_run`
    assert record["noise_floor"]["passes"] == 3
    assert set(record["between_configuration_difference"]) >= {"icc", "cases_whose_collapsed_decision_differs"}
    assert record["reproducible_digest"]


def test_the_transport_count_is_exact_and_the_pre_run_budget_is_still_a_floor(tmp_path: Path) -> None:
    """The recording client sits BELOW the judge, which is the whole reason the count can be exact:
    a retry appends its own row at the seam. The floor and the ceiling stay, labelled as what was
    knowable before the run."""
    record = _stubbed_run(tmp_path)
    asks = len(blind_asks(_artifact())) * 3

    assert record["cost"]["transport_calls"] == asks  # exact — the stub never retries
    assert record["cost"]["calls_beyond_one_per_ask"] == 0
    assert record["pre_run_budget"]["floor"] == asks
    assert record["pre_run_budget"]["ceiling"] == asks * record["pre_run_budget"]["max_attempts_per_call"]
    assert "superseded_by" in record["pre_run_budget"]
    assert "floor" in record["cost"]["calls_are_a_floor"]  # still a floor for the SPEND
    assert "not " in record["cost"]["pricing_source"] and "billed" in record["cost"]["pricing_source"]


def test_the_ledger_replays_the_second_time_rather_than_re_spending(tmp_path: Path) -> None:
    """Hundreds of paid calls take a long time and a killed run must not cost the whole thing twice.

    The second invocation makes no call at all and reproduces the first record's answers exactly.
    """
    ledger = tmp_path / "ledger.jsonl"
    first = live_run(3, client_factory=_stub_factory(), ledger_file=ledger)
    second = live_run(3, client_factory=_stub_factory(), ledger_file=ledger)

    assert first["ledger"][PAID_CALLS] == first["cost"]["transport_calls"]
    assert first["ledger"][REPLAYED_CALLS] == 0
    assert second["ledger"][PAID_CALLS] == 0
    assert second["ledger"][REPLAYED_CALLS] == first["cost"]["transport_calls"]
    assert second["pass_results"] == first["pass_results"]
    assert second["reproducible_digest"] == first["reproducible_digest"]


def test_an_even_pass_count_is_refused_before_any_client_is_built(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ODD number of passes"):
        live_run(2, client_factory=_stub_factory(), ledger_file=tmp_path / "ledger.jsonl")


# --- the freeze: re-derivation from the rows the record holds ------------------


def test_the_whole_record_re_derives_from_the_answers_it_holds(tmp_path: Path) -> None:
    """The freeze property, proven on the builder rather than on a digest checked against itself.

    Every computed field is a function of the frozen answer rows, so rebuilding from those rows must
    reproduce the record — which is what makes `--rederive` honest and a hand-edit detectable.
    """
    record = _stubbed_run(tmp_path)
    rebuilt = build_record(
        artifact=_artifact(),
        replay_path=_REPLAY,
        input_record=load_record(),
        pass_rows=[block["results"] for block in record["pass_results"]],
        transport=record["transport"],
        judge_model=record["judge_model"],
        judge_version=record["judge_version"],
        anchored_frozen=json.loads(anchored_report_path().read_text()),
        created_at=record["created_at"],
        wall_clock_seconds=record["wall_clock_seconds"],
        ledger=record["ledger"],
    )
    assert rebuilt == record


def test_the_fields_scheduled_to_move_sit_outside_the_digest(tmp_path: Path) -> None:
    """A digest that moved for a reason outside the record could not answer *did this record change?*"""
    record = _stubbed_run(tmp_path)
    moved = {
        **record,
        "created_at": "2099-01-01T00:00:00+00:00",
        "wall_clock_seconds": 1.0,
        "ledger": {**record["ledger"], "note": "different"},
    }
    assert record_digest(moved) == record["reproducible_digest"]
    edited = {**record, "confusion": {**record["confusion"], "per_case": {"unit": "case"}}}
    assert record_digest(edited) != record["reproducible_digest"]


def test_a_row_whose_conclusion_no_longer_follows_from_its_answer_is_refused(tmp_path: Path) -> None:
    """The two booleans ARE the comparison. A record that stores one and re-derives the other must not
    load, or a hand-edited conclusion would ride out under a re-derivation that looks clean."""
    artifact = _artifact()
    asks = blind_asks(artifact)
    record = _stubbed_run(tmp_path)
    rows = [dict(row) for row in record["pass_results"][0]["results"]]
    rows[0]["conformance_correct"] = not rows[0]["conformance_correct"]
    with pytest.raises(LedgerMismatch, match="no longer follows from its evidence"):
        outcomes_from_rows(asks, rows, judge_model="m", judge_version="v", run_id="r")


def test_rows_that_are_not_this_configurations_asks_are_refused(tmp_path: Path) -> None:
    artifact = _artifact()
    asks = blind_asks(artifact)
    record = _stubbed_run(tmp_path)
    rows = record["pass_results"][0]["results"]
    with pytest.raises(LedgerMismatch, match="different runs"):
        outcomes_from_rows(asks, rows[:-1], judge_model="m", judge_version="v", run_id="r")

    shuffled = [dict(rows[1]), *[dict(r) for r in rows[1:]]]
    with pytest.raises(LedgerMismatch, match="not\n?.*this configuration's asks|does not match ask"):
        outcomes_from_rows(asks, shuffled, judge_model="m", judge_version="v", run_id="r")


def test_the_judges_own_answer_survives_into_the_rows(tmp_path: Path) -> None:
    """`Direction of disagreement` needs it and nothing else carries it: once the process ends, an
    answer that was not written down is gone."""
    record = _stubbed_run(tmp_path)
    row = record["pass_results"][0]["results"][0]
    assert row["judge_conformance"] in {"supports", "partially_supports", "does_not_support", "not_applicable"}
    assert isinstance(row["judge_cited_sc_ids"], list)
    assert row["rationale"]


# --- what it must not touch ---------------------------------------------------


def test_it_reads_the_anchored_record_and_writes_nothing_back(tmp_path: Path) -> None:
    """441 paid calls sit in that file. This runner replays it and never regenerates it."""
    before = anchored_report_path().read_bytes()
    record = _stubbed_run(tmp_path)
    assert anchored_report_path().read_bytes() == before
    assert record["sources"]["anchored_configuration"]["path"] == anchored_report_path().name


def test_no_frozen_blind_record_exists_until_the_calls_are_spent() -> None:
    """⚠️ A stubbed record and a measured one are indistinguishable on shape. This pins that the
    reports directory holds no blind baseline at all — so nobody can mistake one for the other."""
    assert not report_path().exists(), (
        "benchmark/reports/judge_blind_baseline.json exists. If the paid run has happened, delete this "
        "test and add the freeze test that pins the frozen record; if it has not, a stubbed record has "
        "been written where a measurement belongs."
    )


def test_the_record_and_the_runner_both_warn_against_a_suite_run_mid_measurement(tmp_path: Path) -> None:
    record = _stubbed_run(tmp_path)
    assert record["no_suite_while_this_runs"] == NO_SUITE_WHILE_THIS_RUNS
    assert "DO NOT RUN THE TEST SUITE" in NO_SUITE_WHILE_THIS_RUNS


def test_answer_rows_and_outcomes_round_trip(tmp_path: Path) -> None:
    artifact = _artifact()
    asks = blind_asks(artifact)
    record = _stubbed_run(tmp_path)
    rows = record["pass_results"][0]["results"]
    outcomes = outcomes_from_rows(asks, rows, judge_model="m", judge_version="v", run_id="r")
    assert answer_rows(asks, outcomes) == rows
