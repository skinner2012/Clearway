"""The frozen finding-side input: is it the frozen run's findings, and do both configurations read it?

Offline and model-free. The record itself cannot be rebuilt here — building it needs a live scan and
live retrieval — so these tests do the two things a reader of the file needs done for it:

* **the file is the file it says it is** — a literal digest, a full re-derivation of every field the
  builder computes from the frozen rows, and every block against its own hash;
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

from clearway.drafter.llm import _user_prompt, referent_blocks
from clearway.eval.judge_finding_input import (
    ParityBroken,
    RebuiltInputMismatch,
    _row,
    assert_matches_replay_pass,
    assert_single_bucket,
    build_record,
    drafted_citations_inside_the_candidates,
    gold_sc_reachability,
    load_record,
    prepared_inputs,
    record_digest,
    report_path,
    rows_finding_map,
)
from clearway.eval.offline_inject import conformance_flip, sc_swap
from clearway.judge import finding_input
from clearway.judge.judge import _drafted_row_block, _judge_user_prompt
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    Conformance,
    DraftRow,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

# One retrieved candidate, so a hand-built row renders a real candidate block.
_CITATION = Citation(sc_id="2.4.6", url="https://www.w3.org/TR/WCAG22/#headings-and-labels", source="WCAG-SC")


def _referent_finding(rule_id: str) -> Finding:
    """A finding of `rule_id` carrying every referent source populated — the maximal input a class's
    injection could possibly use, so a class that still renders nothing renders nothing by class.

    `source_bucket` is stated rather than defaulted: the schema's default is `violations`, and every
    finding in the set this module freezes is a quality-review `passes` item."""
    excerpt = ReferentExcerpt(text="x", source=ReferentSource.ACCESSIBLE_NAME)
    return Finding(
        id=f"f:{rule_id}",
        source_url="file://q.html",
        rule_id=rule_id,
        target="x",
        html="<x/>",
        help="h",
        source_bucket=AxeBucket.PASSES,
        referent=NodeReferent(
            accessible_name=excerpt,
            document_title=excerpt,
            page_topic=excerpt,
            section_heading=excerpt,
            surrounding_context=excerpt,
        ),
    )


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


# The frozen record's digest, as a literal — layer 1 of the freeze.
#
# ⚠️ Self-consistency is not a freeze: `record_digest` is computed from the file's own bytes, so any
# edit that also recomputes the digest passes that check. This literal is what makes a wholesale
# rewrite fail. It moves only when a deliberate rebuild moves it, and a rebuild needs the live scanner
# and the live embedder — so a failure here means either the input genuinely changed (in which case the
# blocks any judge configuration would send have changed, and nothing measured under the old ones
# describes the new ones) or the file was edited by hand.
_FROZEN_DIGEST = "bd12b2c85c66037ac29abe49b505b5416e12e8becf5e30aa04a36620873bff66"


def test_the_record_reproduces_its_own_digest(record: dict[str, Any]) -> None:
    """Layer 3's arithmetic: the digest matches the content it is computed over."""
    assert record_digest(record) == record["reproducible_digest"]


def test_the_digest_is_pinned_to_a_literal(record: dict[str, Any]) -> None:
    """Layer 1: without this, a rewrite that recomputes its own digest is indistinguishable from a build."""
    assert record["reproducible_digest"] == _FROZEN_DIGEST


def test_every_derived_field_re_derives_from_the_frozen_rows(record: dict[str, Any]) -> None:
    """Layer 2, and it is the one with reach: rebuild the WHOLE record from the frozen rows.

    `build_record` is pure given `rows`, so everything the file carries beyond the rows themselves — the
    corroboration arithmetic, the citation ranks, the gold-reachability counts, `per_class`, the parity
    block, every line of provenance prose — is re-derived here and compared against what is on disk. The
    live scan and the live retrieval that produced the rows are the only things this cannot check, which
    is why the rows are also hashed individually.
    """
    rebuilt = build_record(
        rows=record["rows"],
        replay_path=_REPLAY,
        corpus_version=record["pins"]["corpus_version"],
    )
    assert rebuilt == record, "a derived field on disk is not what the builder produces from these rows"
    assert rebuilt["reproducible_digest"] == _FROZEN_DIGEST


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
        assert rendered == sum(1 for r in record["rows"] if r["axe_rule"] == row["axe_rule"] and r["referent_rendered"])


def test_a_class_reporting_zero_reports_it_because_the_drafter_has_no_block_for_it() -> None:
    """The 0/11 has to be a property of the CLASS, not of what those pages happened to contain.

    Established by handing the drafter's builder a finding of that class carrying **every** referent
    source populated: it still renders nothing. Without this the zero is indistinguishable from eleven
    fixtures that merely captured no referent, and only one of those two says the judge is seeing what
    the drafter saw.
    """
    for row_rule in ("empty-heading",):
        finding = _referent_finding(row_rule)
        assert referent_blocks(finding) == ""
    for injected in ("label", "document-title", "link-name"):
        assert referent_blocks(_referent_finding(injected)) != ""


@pytest.mark.parametrize(
    "html,sources,expected",
    [
        # The false positive the old text probe would have produced: the page's own markup carries the
        # phrase, and the block interpolates that HTML verbatim.
        ("<h2>Resolved (Referent (issues</h2>", {}, False),
        # The false negative: a `label` finding whose accessible name did not resolve still injects the
        # nearest section heading, and that line names neither "Resolved" nor "Referent (".
        ("<input id='x'>", {"section_heading": "Billing address"}, True),
    ],
)
def test_the_referent_flag_is_the_builders_answer_and_not_a_phrase_in_the_block(
    html: str, sources: dict[str, str], expected: bool
) -> None:
    rule = "empty-heading" if not sources else "label"
    finding = Finding(
        id="f",
        source_url="file://q.html",
        rule_id=rule,
        target="x",
        html=html,
        help="h",
        referent=NodeReferent(
            **{k: ReferentExcerpt(text=v, source=ReferentSource.NEAREST_SECTION_HEADING) for k, v in sources.items()}
        )
        if sources
        else None,
    )
    row = _row({"act_testcase_id": "c", "axe_rule": rule}, finding, [_CITATION])
    assert row["referent_rendered"] is expected
    if expected:
        assert "Nearest section heading" in row["finding_block"]
        assert "Resolved " not in row["finding_block"]  # the false-negative path, in one line
    else:
        assert "Resolved " in row["finding_block"]  # the phrase is present; the flag still says no


# --- parity with the drafter's prompt, and the condition it rests on -----------------------------


def test_the_parity_claim_names_the_single_bucket_condition_and_the_surviving_differences(
    record: dict[str, Any],
) -> None:
    """ "The two readers are shown the same facts" is TRUE HERE and false in general.

    The drafter opens its user prompt with a provenance sentence keyed to the finding's bucket; this
    block has no counterpart, and the judge's rubric states the quality-review stance once for every
    finding it grades. Those agree only while the set is single-bucket, so the record has to say so.
    """
    parity = record["parity_with_the_drafters_prompt"]
    assert parity["source_bucket_asserted_on_every_finding"] == AxeBucket.PASSES.value
    assert "source_bucket" in parity["conditional_on_a_single_bucket_set"]
    assert any("ORDER" in difference for difference in parity["surviving_differences"])
    assert any("you may cite" in difference for difference in parity["surviving_differences"])


def test_a_finding_from_another_bucket_is_refused_rather_than_frozen() -> None:
    """A scope change that admits another bucket must fail here, not quietly void the parity claim."""
    for bucket in (AxeBucket.VIOLATIONS, AxeBucket.INCOMPLETE):
        finding = _referent_finding("label").model_copy(update={"source_bucket": bucket})
        with pytest.raises(ParityBroken, match="only at parity"):
            assert_single_bucket(finding)
    assert_single_bucket(_referent_finding("label"))  # the bucket this set is entirely made of


def test_the_order_of_the_shared_material_really_does_differ_between_the_two_readers() -> None:
    """The recorded limitation, pinned rather than asserted in prose alone.

    Same sentences, different position: the drafter appends the referent after its instruction line, so
    its candidates come first; the judge's finding side renders the referent first and ends on the
    candidates. If a later change made the two orders agree, this test fails and the limitation comes
    out of the record — which is the outcome the limitation is documented to invite.
    """
    finding = _referent_finding("link-name")
    drafter_prompt = _user_prompt(finding, [_CITATION])
    judge_block = finding_input(finding, [_CITATION]).block
    referent = referent_blocks(finding)
    assert drafter_prompt.index("Candidate WCAG") < drafter_prompt.index(referent.strip().splitlines()[0])
    assert judge_block.index(referent.strip().splitlines()[0]) < judge_block.index("Candidate WCAG")


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


def test_the_rank_of_each_cited_criterion_is_recorded_because_it_is_checkable() -> None:
    """Order evidence exists and must not be filed as impossible.

    Membership is the set half; the rank of a cited criterion inside today's ORDERED list is the order
    half, and it is strictly stronger. Both are weak — that is what `cannot_establish` is for — but an
    available check recorded as unavailable is the inverse of declining one deliberately.
    """
    rows = [{"finding_id": "f1", "candidate_sc_ids": ["1.1.1", "2.4.4", "3.3.2"]}]
    replay = {"cases": [{"drafts": [{"finding_id": "f1", "cited_sc_ids": ["3.3.2", "1.1.1"]}]}]}
    out = drafted_citations_inside_the_candidates(rows, replay)
    assert out["rank_of_each_cited_sc_in_todays_ordered_list"] == {"1": 1, "3": 1}
    assert out["cited_sc_instances_ranked"] == 2


def test_a_citation_outside_the_list_is_not_given_a_rank() -> None:
    """A rank for a criterion that is not in the list would be an invented position."""
    rows = [{"finding_id": "f1", "candidate_sc_ids": ["1.1.1"]}]
    replay = {"cases": [{"drafts": [{"finding_id": "f1", "cited_sc_ids": ["9.9.9"]}]}]}
    out = drafted_citations_inside_the_candidates(rows, replay)
    assert out["cited_sc_instances_ranked"] == 0
    assert out["rank_of_each_cited_sc_in_todays_ordered_list"] == {}


def test_the_frozen_ranks_and_membership_agree_with_each_other(record: dict[str, Any]) -> None:
    """Re-derived from the file, not copied from the record's own totals: one SC per citing draft, so
    the ranked instances must equal the citing drafts, and every rank must be a real position."""
    cited = record["candidate_list_provenance"]["corroboration"]["drafted_citations"]
    ranks = {int(k): v for k, v in cited["rank_of_each_cited_sc_in_todays_ordered_list"].items()}
    widths = {len(row["candidate_sc_ids"]) for row in record["rows"]}
    assert sum(ranks.values()) == cited["cited_sc_instances_ranked"]
    assert cited["drafts_citing_at_least_one_sc"] + cited["drafts_citing_nothing"] == len(record["rows"])
    assert max(ranks) <= min(widths), "a rank cannot exceed the shortest candidate list it was read from"


def test_gold_reachability_is_counted_on_both_denominators_and_kept_out_of_the_corroboration() -> None:
    """Adequacy, not provenance — so it must not sit where a reader takes it for identity evidence."""
    rows = [
        {"act_testcase_id": "c1", "finding_id": "f1", "candidate_sc_ids": ["1.1.1", "2.4.4"]},
        {"act_testcase_id": "c2", "finding_id": "f2", "candidate_sc_ids": ["1.1.1"]},
    ]
    replay = {
        "cases": [
            {"act_testcase_id": "c1", "gold_success_criteria": ["1.1.1", "2.4.4"]},
            {"act_testcase_id": "c2", "gold_success_criteria": ["2.4.6"]},
        ]
    }
    out = gold_sc_reachability(rows, replay)
    assert (out["findings"], out["findings_whose_candidate_list_covers_their_whole_gold_set"]) == (2, 1)
    assert (out["gold_sc_instances"], out["gold_sc_instances_inside_the_candidate_list"]) == (3, 2)
    assert out["findings_with_an_unreachable_gold_criterion"] == [
        {"finding_id": "f2", "gold_sc_ids_not_retrieved": "2.4.6"}
    ]


def test_the_frozen_set_has_no_finding_whose_gold_criterion_was_unreachable(
    record: dict[str, Any], replay: dict[str, Any]
) -> None:
    """Re-derived here from the file plus the replay pass, rather than read off the record's own counts:
    a gold criterion outside the candidate list would put the SC axis on that finding on the retriever
    rather than on either rater."""
    recomputed = gold_sc_reachability(record["rows"], replay)
    assert recomputed == record["retrieval_adequacy"]
    assert recomputed["findings_with_an_unreachable_gold_criterion"] == []
    assert recomputed["findings_whose_candidate_list_covers_their_whole_gold_set"] == len(record["rows"])
    assert recomputed["gold_sc_instances_inside_the_candidate_list"] == recomputed["gold_sc_instances"]
    assert "retrieval_adequacy" not in record["candidate_list_provenance"]
    assert "adequacy" not in json.dumps(record["candidate_list_provenance"]["corroboration"])


def test_a_clean_draft_that_cites_nothing_carries_no_corroboration_either_way() -> None:
    rows = [{"finding_id": "f1", "candidate_sc_ids": ["1.1.1"]}]
    replay = {"cases": [{"drafts": [{"finding_id": "f1", "cited_sc_ids": []}]}]}
    out = drafted_citations_inside_the_candidates(rows, replay)
    assert (out["drafts_citing_at_least_one_sc"], out["drafts_citing_nothing"]) == (0, 1)


def test_the_frozen_record_lives_where_the_reports_do() -> None:
    assert report_path().name == "judge_finding_input.json"
    assert report_path().parent.name == "reports"
