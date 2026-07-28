"""Guard for the two frozen image conditions and the endpoint derived from them.

`opaque/with-image` and `opaque/mismatched-image` are the milestone's primary measurement, and the
model calls that produced them cannot be recovered: re-running would call the model again under
whatever prompt is current, which is a different experiment wearing the same filename. So what is
checked here is that each pass is the run it says it is, that both were drafted by the model this
project is pinned to, that the pictures they sent are the ones a mapping frozen before any verdict
existed says they should have sent — and that the endpoint report is *derived* from them rather than
maintained beside them.

No model call. Rebuild the reports with `uv run python -m clearway.eval.image_score`.
"""

from __future__ import annotations

import json
from typing import Any

from clearway.eval.image_conditions import (
    CONDITIONS,
    LEAKY_NO_IMAGE,
    OPAQUE_MISMATCHED_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_WITH_IMAGE,
)
from clearway.eval.image_pass import canonical_rows, load_pass, pass_failures, pinned_corpus_version
from clearway.eval.image_score import (
    ENDPOINT_REPORT,
    M7_DRIFT_RATE,
    VERDICT_CONFIRMED,
    VERDICT_INCONCLUSIVE,
    VERDICT_REFUTED,
    VERDICT_UNINTERPRETABLE,
    build_endpoint_report,
)
from clearway.llm.local import _DEFAULT_MODEL

# The digest M6 and M7 ran, and the one M8's Control 1 pins every condition to. Written out rather
# than read from the machine: a control that reads the live tag would agree with whatever is loaded.
_PINNED_DIGEST = "6316f0629137b426c9d9b853ffc4c8209589f30ee39aebede6285096c0ff47e7"

PASSES = {condition: load_pass(condition) for condition in CONDITIONS}
WITH_IMAGE = PASSES[OPAQUE_WITH_IMAGE]
MISMATCHED = PASSES[OPAQUE_MISMATCHED_IMAGE]
FROZEN: dict[str, Any] = json.loads(ENDPOINT_REPORT.read_text())


def _receipts(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    return [row["receipt"] for sample in artifact["samples"] for row in sample["rows"]]


# --- the two passes are the runs they claim to be ----------------------------


def test_both_image_conditions_are_the_runs_they_say_they_are() -> None:
    for condition, artifact in ((OPAQUE_WITH_IMAGE, WITH_IMAGE), (OPAQUE_MISMATCHED_IMAGE, MISMATCHED)):
        assert pass_failures(artifact) == [], condition.condition_id
        assert len(artifact["samples"]) == 3
        assert len(canonical_rows(artifact)) == 7


def test_one_model_throughout_and_it_is_the_one_the_earlier_milestones_ran() -> None:
    """M8 Control 1, now across all four conditions: a condition drafted by a different build of the
    model is a different experiment, and the digest is the part of that claim a tag cannot fake."""
    for artifact in PASSES.values():
        assert artifact["drafter_model"] == _DEFAULT_MODEL
        assert artifact["drafter_model_digest"] == _PINNED_DIGEST


def test_every_row_of_both_image_conditions_actually_carried_a_picture() -> None:
    """The failure this closes reads as a result: a condition that quietly drafted text-only would
    show no movement, and no movement is exactly what 'the pixels are not attended' looks like."""
    for artifact in (WITH_IMAGE, MISMATCHED):
        refs = {row["image_sha256"] for row in _receipts(artifact)}
        assert None not in refs
        assert all(len(ref) == 64 for ref in refs)


def test_all_four_conditions_were_drafted_against_the_pinned_candidate_criteria() -> None:
    for artifact in PASSES.values():
        assert artifact["citations"]["source"] == "pinned"
        assert artifact["corpus_version"] == pinned_corpus_version()


def test_the_three_opaque_conditions_asked_byte_identical_prompts() -> None:
    """The premise the endpoint rests on, checked on the live passes rather than on the rehearsal:
    only the pixels differ between them."""
    prompts: dict[str, set[str]] = {}
    for condition in (OPAQUE_NO_IMAGE, OPAQUE_WITH_IMAGE, OPAQUE_MISMATCHED_IMAGE):
        for row in _receipts(PASSES[condition]):
            prompts.setdefault(row["finding_id"], set()).add(row["prompt_sha256"])
    assert len(prompts) == 7
    assert all(len(seen) == 1 for seen in prompts.values())


def test_the_three_opaque_conditions_sent_three_different_payloads() -> None:
    """The other half of 'only the pixels change': identical prompts plus a moved picture must move
    the ask. One hash cannot carry both claims, which is why two are recorded."""
    payloads: dict[str, set[str]] = {}
    for condition in (OPAQUE_NO_IMAGE, OPAQUE_WITH_IMAGE, OPAQUE_MISMATCHED_IMAGE):
        for row in _receipts(PASSES[condition]):
            payloads.setdefault(row["finding_id"], set()).add(row["payload_sha256"])
    assert all(len(seen) == 3 for seen in payloads.values())


def test_the_leaky_condition_still_carries_no_picture() -> None:
    assert {row["image_sha256"] for row in _receipts(PASSES[LEAKY_NO_IMAGE])} == {None}


# --- the endpoint report is derived, not maintained --------------------------


def test_the_frozen_endpoint_report_rebuilds_identically_from_the_passes() -> None:
    """The report holds no number of its own. If it ever disagrees with the passes it was built from,
    the passes win — so the disagreement has to be loud rather than editable."""
    assert build_endpoint_report() == FROZEN


def test_the_receipts_prove_the_manipulation_ran_mismatched_on_every_sample() -> None:
    """7/7 with the sha256 the frozen mapping names, and differing exactly where it says — the only
    evidence that D is a statistic about pictures at all."""
    receipts = FROZEN["receipts"]
    assert receipts["failures"] == []
    assert receipts["dry_receipt_failures"] == []
    assert receipts["matches_dry_receipt"] is True
    assert receipts["findings"] == 7
    assert receipts["digests_differ"] == 7
    assert receipts["samples_checked"] == 3


def test_d_is_reported_with_its_retained_cell_count_and_the_cells_it_lost() -> None:
    """Never D alone: below two retained cells D ≥ 2 is unreachable by construction, so the count is
    what tells a reader whether the measurement had the power to say anything."""
    reading, endpoint = FROZEN["reading"], FROZEN["endpoint"]
    assert endpoint["cells"] == 7
    assert reading["d"] == endpoint["d"]
    assert reading["retained"] == endpoint["retained"]
    assert len(reading["excluded"]) == endpoint["cells"] - endpoint["retained"]
    assert endpoint["d"] <= endpoint["differing_cells_including_excluded"]


def test_the_verdict_is_one_of_the_four_pre_committed_readings() -> None:
    assert FROZEN["reading"]["verdict"] in {
        VERDICT_CONFIRMED,
        VERDICT_INCONCLUSIVE,
        VERDICT_REFUTED,
        VERDICT_UNINTERPRETABLE,
    }


def test_the_null_rate_is_the_max_of_the_measured_one_and_the_earlier_milestone_s() -> None:
    """Both printed, per the pre-registered rule: M8's own estimate is 63 pairs, which corroborates
    M7's figure rather than replacing it, and cannot buy a null rate of zero."""
    null = FROZEN["null_rate"]
    assert null["rate"] == max(null["measured_rate"], M7_DRIFT_RATE)
    assert null["source"] in {"M7", "M8"}
    assert FROZEN["reading"]["null_rate"] == null["rate"]


def test_the_null_rate_is_pooled_over_every_condition_that_took_repeats() -> None:
    """Including the cells D excludes — a rate estimated from the retained cells alone would be
    conditioned on the very stability the endpoint acts on."""
    null = FROZEN["null_rate"]
    assert null["pairs"] == 3 * 7 * 3  # three sampled conditions × 7 findings × 3 sample pairs
    assert null["not_measurable"] == [LEAKY_NO_IMAGE.condition_id]


def test_the_per_condition_instability_counts_are_recorded_for_all_four() -> None:
    """Recorded, not gated on: instability concentrated in the mismatched condition relative to
    with-image would itself be weak evidence the pixels are doing something."""
    assert set(FROZEN["instability"]) == {c.condition_id for c in CONDITIONS}
    assert FROZEN["instability"][LEAKY_NO_IMAGE.condition_id]["measurable"] is False


def test_the_specificity_control_is_reported_inside_d_and_never_filtered_out() -> None:
    control = FROZEN["endpoint"]["specificity_control"]
    assert control["act_testcase_id"].startswith("a2333ec76e")
    assert control["live"] is False
    assert control["act_testcase_id"] in {row["act_testcase_id"] for row in FROZEN["endpoint"]["by_case"]}


def test_the_report_carries_the_sentence_that_d_under_detects_attendance() -> None:
    """A mismatched picture may produce genuine uncertainty that the stability filter codes as noise.
    The bias is conservative, and the report has to say so rather than leave it to a reader."""
    assert "under-detect" in FROZEN["reading"]["note"]


def test_the_report_declares_that_the_candidate_criteria_were_pinned() -> None:
    """It qualifies every number in the milestone: these are not the candidates production retrieval
    would surface. Identical across the four conditions, so it cannot move D."""
    assert "PINNED" in FROZEN["note"]
