"""The frozen finding-side input: is it the frozen run's findings, and do both configurations read it?

Offline and model-free. The record itself cannot be rebuilt here — building it needs a live scan and
live retrieval — so these tests do the two things a reader of the file needs done for it:

* **the file is the file it says it is** — its own digest, and every block against its own hash;
* **the finding side is byte-identical across the two configurations, asserted against the file** —
  the configuration that grades a draft sends these bytes plus a draft presentation, the configuration
  that never sees the draft sends these bytes alone, and no second rendering is involved in either.

The pure assembly (the corroboration arithmetic, the refusal) is exercised on small hand-built inputs
so a failure names the rule that broke rather than the live stack.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.judge_finding_input import (
    RebuiltInputMismatch,
    assert_matches_replay_pass,
    drafted_citations_inside_the_candidates,
    load_record,
    prepared_inputs,
    record_digest,
    report_path,
    rows_finding_map,
)
from clearway.eval.offline_inject import conformance_flip, sc_swap
from clearway.judge.judge import _drafted_row_block, _judge_user_prompt
from clearway.schemas.models import Citation, Conformance, DraftRow

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"
_REPLAY = _RUNS / "citation_grounding_run_1.json"

# The four verdicts a shared finding-side block must never carry: the block is the question, and under
# the blind configuration the answer is exactly what is withheld.
_CONFORMANCE_VALUES = tuple(c.value for c in Conformance)


@pytest.fixture(scope="module")
def record() -> dict[str, Any]:
    return load_record()


@pytest.fixture(scope="module")
def replay() -> dict[str, Any]:
    return json.loads(_REPLAY.read_text())


# --- the file is what it says it is -------------------------------------------------------------


def test_the_record_reproduces_its_own_digest(record: dict[str, Any]) -> None:
    """The freeze check. A rebuild needs live services, so the digest is what stands in for one."""
    assert record_digest(record) == record["reproducible_digest"]


def test_every_block_matches_the_digest_recorded_beside_it(record: dict[str, Any]) -> None:
    for row in record["rows"]:
        assert hashlib.sha256(row["finding_block"].encode()).hexdigest() == row["finding_block_sha256"]


def test_loading_refuses_a_block_edited_in_place(tmp_path: Path, record: dict[str, Any]) -> None:
    """An edited block would send bytes nobody froze, which is the one thing the freeze rules out."""
    tampered = json.loads(json.dumps(record))
    tampered["rows"][0]["finding_block"] += " (edited)"
    path = tmp_path / "judge_finding_input.json"
    path.write_text(json.dumps(tampered))
    with pytest.raises(RebuiltInputMismatch, match="does not match its recorded digest"):
        load_record(path)


def test_the_record_says_the_candidate_list_was_rebuilt_and_what_that_cannot_show(record: dict[str, Any]) -> None:
    provenance = record["candidate_list_provenance"]
    assert provenance["rebuilt_not_recovered"] is True
    assert "REBUILT" in provenance["statement"] and "not verification" in provenance["statement"]
    assert "corroborated at best, never asserted as verified" in provenance["cannot_establish"]
    assert record["judge_calls_spent"] == 0


# --- it is the frozen run's findings ------------------------------------------------------------


def test_the_rows_are_the_replay_passs_own_cases_elements_and_ids(
    record: dict[str, Any], replay: dict[str, Any]
) -> None:
    """The join the whole comparison rests on: same cases, same elements, same finding ids."""
    summary = assert_matches_replay_pass(record["rows"], replay)
    assert summary["cases"] == len(replay["cases"])
    assert summary["findings"] == sum(len(c["drafts"]) for c in replay["cases"])


def test_a_rebuild_over_different_findings_is_refused_rather_than_frozen() -> None:
    replay = {"cases": [{"act_testcase_id": "c1", "drafts": [{"finding_id": "f1", "target": "#a"}]}]}
    rows = [{"act_testcase_id": "c1", "finding_id": "f2", "target": "#a"}]
    with pytest.raises(RebuiltInputMismatch, match="not over the frozen pass's findings"):
        assert_matches_replay_pass(rows, replay)
    assert rows_finding_map(rows) == {"c1": (("f2", "#a"),)}


def test_the_provenance_pins_match_the_replay_pass(record: dict[str, Any]) -> None:
    corroboration = record["candidate_list_provenance"]["corroboration"]
    assert corroboration["corpus_version_matches_the_replay_pass"] is True
    assert corroboration["axe_core_version_matches_the_replay_pass"] is True
    assert corroboration["act_export_hash_matches_the_replay_pass"] is True


# --- both configurations read this file ---------------------------------------------------------


def _draft_of(row: dict[str, Any], replay: dict[str, Any]) -> DraftRow:
    """The frozen draft for one row, rebuilt as a `DraftRow` so a real prompt can be assembled."""
    draft = next(d for case in replay["cases"] for d in case["drafts"] if d["finding_id"] == row["finding_id"])
    return DraftRow(
        finding_id=draft["finding_id"],
        conformance=Conformance(draft["conformance"]),
        citations=[Citation(sc_id=s) for s in draft["cited_sc_ids"]],
        remediation=draft["remediation"],
        confidence=draft["confidence"],
    )


def test_the_finding_side_is_byte_identical_across_the_two_configurations(
    record: dict[str, Any], replay: dict[str, Any]
) -> None:
    """The acceptance property, asserted against the file.

    Three presentations of the draft per finding — the natural row and both injected mutations — plus
    the configuration that presents none. All four asks carry the frozen block, unmodified, and differ
    only after it. Nothing in this test renders a finding side: there is no `Finding` here to render one
    from, which is the point.
    """
    prepared = prepared_inputs(record)
    assert len(prepared) == len(record["rows"])
    for row in record["rows"]:
        block = row["finding_block"]
        natural = _draft_of(row, replay)
        gold = next(
            c["gold_success_criteria"]
            for c in replay["cases"]
            if any(d["finding_id"] == row["finding_id"] for d in c["drafts"])
        )
        for draft in (natural, sc_swap(natural, gold), conformance_flip(natural)):
            ask = _judge_user_prompt(prepared[row["finding_id"]], draft)
            assert ask == block + _drafted_row_block(draft), (
                "the ask is not the frozen block plus this draft's presentation, so something between "
                "the file and the model is rendering the finding side a second time"
            )
        # The blind configuration's whole input is the block itself — the same bytes, no assembly.
        assert prepared[row["finding_id"]].block == block


def test_the_draft_presentation_is_the_only_thing_that_moves(record: dict[str, Any], replay: dict[str, Any]) -> None:
    """A mutated draft must actually change the ask, or the identity above would be vacuous."""
    prepared = prepared_inputs(record)
    moved = 0
    for row in record["rows"]:
        natural = _draft_of(row, replay)
        flipped = conformance_flip(natural)
        first = _judge_user_prompt(prepared[row["finding_id"]], natural)
        second = _judge_user_prompt(prepared[row["finding_id"]], flipped)
        moved += first != second
        assert first.removeprefix(row["finding_block"]).startswith("\n\nDRAFTED ROW")
    assert moved == len(record["rows"]), "a conformance flip must move every ask it is applied to"


def test_the_shared_block_carries_no_draft_side_value(record: dict[str, Any]) -> None:
    """The blind configuration reads whole rows from this file, so the file must not hold the answer.

    ⚠️ The SC axis cannot be checked this way and deliberately is not: the drafter cites *from the
    shared candidate list*, so a drafted criterion legitimately appears in the block. That shared prior
    is the milestone's declared residual correlation, not a leak this test could catch.
    """
    for row in record["rows"]:
        assert "DRAFTED ROW" not in row["finding_block"]
        assert "conformance" not in row["finding_block"]
        for value in _CONFORMANCE_VALUES:
            assert value not in row["finding_block"]
    for row in record["rows"]:
        assert set(row.keys()) == {
            "act_testcase_id",
            "axe_rule",
            "target",
            "finding_id",
            "referent_sources",
            "referent_rendered",
            "candidate_sc_ids",
            "finding_block",
            "finding_block_sha256",
        }


# --- what the block actually carries ------------------------------------------------------------


def test_every_block_carries_the_candidate_list(record: dict[str, Any]) -> None:
    from clearway.judge import CANDIDATE_HEADING

    for row in record["rows"]:
        assert CANDIDATE_HEADING in row["finding_block"]
        assert row["candidate_sc_ids"], "a finding with no retrieved candidate would be a retrieval failure"
        for sc_id in row["candidate_sc_ids"]:
            assert f"- {sc_id} (" in row["finding_block"]


def test_the_referent_reaches_the_block_wherever_the_drafter_had_one(record: dict[str, Any]) -> None:
    """Per class, and the asymmetry is inherited: a class with no referent injection carries no line.

    The counts come from the record's own per-class summary rather than from a literal here, so a class
    whose capture rate changed shows up as a changed artifact rather than as a changed expectation.
    """
    for row in record["per_class"]:
        rendered = row["findings_with_a_rendered_referent"]
        assert rendered in (0, row["findings"]), (
            f"{row['axe_rule']} renders a referent on {rendered} of {row['findings']} findings — a class "
            "that carries the material on only some of its findings is an asymmetry inside one class, "
            "which no per-class read of the comparison would expect"
        )
    expected = {row["axe_rule"]: bool(row["findings_with_a_rendered_referent"]) for row in record["per_class"]}
    for row in record["rows"]:
        has_line = "Resolved " in row["finding_block"] or "Referent (" in row["finding_block"]
        assert has_line is expected[row["axe_rule"]] is row["referent_rendered"]


# --- the corroboration arithmetic (pure) --------------------------------------------------------


def test_a_citation_outside_todays_candidates_is_named_rather_than_counted_as_agreement() -> None:
    rows = [
        {"finding_id": "f1", "candidate_sc_ids": ["1.1.1", "2.4.4"]},
        {"finding_id": "f2", "candidate_sc_ids": ["1.1.1"]},
    ]
    replay = {
        "cases": [
            {
                "drafts": [
                    {"finding_id": "f1", "cited_sc_ids": ["2.4.4"]},
                    {"finding_id": "f2", "cited_sc_ids": ["3.3.2"]},
                ]
            }
        ]
    }
    out = drafted_citations_inside_the_candidates(rows, replay)
    assert out["drafts_citing_at_least_one_sc"] == 2
    assert out["drafts_whose_every_cited_sc_is_in_todays_candidate_list"] == 1
    assert out["drafts_citing_outside_todays_candidate_list"] == [
        {"finding_id": "f2", "sc_ids_not_in_todays_candidates": "3.3.2"}
    ]
    assert out["drafts_citing_nothing"] == 0


def test_a_clean_draft_that_cites_nothing_carries_no_corroboration_either_way() -> None:
    rows = [{"finding_id": "f1", "candidate_sc_ids": ["1.1.1"]}]
    replay = {"cases": [{"drafts": [{"finding_id": "f1", "cited_sc_ids": []}]}]}
    out = drafted_citations_inside_the_candidates(rows, replay)
    assert (out["drafts_citing_at_least_one_sc"], out["drafts_citing_nothing"]) == (0, 1)


def test_the_frozen_record_lives_where_the_reports_do() -> None:
    assert report_path().name == "judge_finding_input.json"
    assert report_path().parent.name == "reports"
