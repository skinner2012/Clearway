"""Guard for the two frozen text-only conditions and the difference derived from them.

These are the only records that `leaky/no-image` and `opaque/no-image` ever ran, and the model calls
that produced them cannot be recovered — re-running would call the model again under whatever prompt
is current, which is a different measurement wearing the same filename. So what is checked here is
that each pass is the run it says it is, that both were drafted by the model this project is pinned
to, and that the descriptive report is *derived* from them rather than hand-maintained beside them.

No model call. Rebuild the report with `uv run python -m clearway.eval.image_score`.
"""

from __future__ import annotations

import json
from typing import Any

from clearway.eval.drafter_payload import load_baseline
from clearway.eval.image_conditions import LEAKY_NO_IMAGE, OPAQUE_NO_IMAGE
from clearway.eval.image_pass import canonical_rows, load_pass, pass_failures, pinned_corpus_version
from clearway.eval.image_score import REPORT, ablation_gate_provenance, build_report
from clearway.llm.local import _DEFAULT_MODEL

# The digest M6 and M7 ran, and the one M8's Control 1 pins every condition to. Written out rather
# than read from the machine: a control that reads the live tag would agree with whatever is loaded.
_PINNED_DIGEST = "6316f0629137b426c9d9b853ffc4c8209589f30ee39aebede6285096c0ff47e7"

LEAKY = load_pass(LEAKY_NO_IMAGE)
OPAQUE = load_pass(OPAQUE_NO_IMAGE)
FROZEN: dict[str, Any] = json.loads(REPORT.read_text())


def test_both_conditions_are_the_runs_they_say_they_are() -> None:
    assert pass_failures(LEAKY) == []
    assert pass_failures(OPAQUE) == []
    assert len(LEAKY["samples"]) == 1
    assert len(OPAQUE["samples"]) == 3


def test_one_model_throughout_and_it_is_the_one_the_earlier_milestones_ran() -> None:
    """M8 Control 1. A condition drafted by a different build of the model is a different experiment,
    and the digest is the only part of that claim a tag cannot fake."""
    for artifact in (LEAKY, OPAQUE):
        assert artifact["drafter_model"] == _DEFAULT_MODEL
        assert artifact["drafter_model_digest"] == _PINNED_DIGEST


def test_neither_condition_attached_a_picture() -> None:
    for artifact in (LEAKY, OPAQUE):
        refs = {row["receipt"]["image_sha256"] for sample in artifact["samples"] for row in sample["rows"]}
        assert refs == {None}, artifact["condition"]["condition"]


def test_the_two_conditions_carry_different_eval_set_ids_and_the_same_config() -> None:
    """One pipeline configuration over two case sets — the shape that makes the difference between
    them a property of the pages rather than of the run."""
    assert LEAKY["eval_set_id"] == "act-image-leaky@1"
    assert OPAQUE["eval_set_id"] == "act-image-opaque@1"
    assert LEAKY["config_id"] == OPAQUE["config_id"] == "single-multimodal@1"


def test_both_were_drafted_against_the_pinned_candidate_criteria() -> None:
    """The one input the hashes cannot reveal. A run drafted against a pinned block and one drafted
    against live retrieval are different measurements even when every other field matches."""
    for artifact in (LEAKY, OPAQUE):
        assert artifact["citations"]["source"] == "pinned"
        assert artifact["corpus_version"] == pinned_corpus_version()


def test_the_live_payloads_are_the_ones_measured_before_the_image_was_wired_in() -> None:
    """M8 Control 6, discharged on a **live** pass rather than only in a rehearsal.

    Both text-only conditions send exactly the payloads frozen against the pre-wiring drafter. That
    the comparison is even possible is the payoff of pinning the candidate criteria: a retrieved block
    would make every live hash unique to its retrieval, and the control could then only ever be
    checked by a builder re-running its own code.
    """
    control = load_baseline()
    checked = 0
    for artifact in (LEAKY, OPAQUE):
        for sample in artifact["samples"]:
            for row in sample["rows"]:
                receipt = row["receipt"]
                key = (receipt["scope"], receipt["act_testcase_id"], receipt["target"])
                assert control[key] == receipt["payload_sha256"], key
                checked += 1
    assert checked == 7 + 21


def test_the_two_conditions_cover_the_same_seven_cases() -> None:
    """Paired by case, so a set that drifted would make the difference a comparison of two pools."""
    cases = [{row["receipt"]["act_testcase_id"] for row in canonical_rows(a)} for a in (LEAKY, OPAQUE)]
    assert cases[0] == cases[1]
    assert len(cases[0]) == 7


def test_the_frozen_report_is_derived_from_the_passes_and_rebuilds_identically() -> None:
    """The report holds no number of its own. If it ever disagrees with the passes it was built
    from, the passes win — so the disagreement has to be loud rather than editable."""
    assert build_report() == FROZEN


def test_the_report_states_what_the_difference_licenses_and_carries_the_fixture_caveat() -> None:
    difference = FROZEN["difference"]
    assert difference["cases"] == 7
    assert difference["moved"] == difference["toward_flag"] + difference["toward_clean"]
    assert difference["moved"] == difference["moved_on_cue_cases"] + difference["moved_off_cue_cases"]
    assert difference["moved"] == difference["moved_on_cue_cases_stem"] + difference["moved_off_cue_cases_stem"]
    assert "ablation gate" in difference["reading"]
    assert "fixture artifact" in difference["caveat"]


def test_the_descriptive_condition_reports_its_stability_as_unmeasured() -> None:
    assert FROZEN["instability"][LEAKY_NO_IMAGE.condition_id]["measurable"] is False
    assert FROZEN["instability"][OPAQUE_NO_IMAGE.condition_id]["measurable"] is True


def test_the_report_points_at_the_real_ablation_gate_and_pins_the_bytes_it_passed_on() -> None:
    """This report is not the gate and must not be read as one. What ties it to the gate is the
    checksum of the ablated set, so pages that moved after the gate ran cannot pass unnoticed."""
    gate = FROZEN["ablation_gate"]
    assert gate["gate"].startswith("clearway.eval.image_opaque.ablation_failures")
    assert gate["opaque_set_checksums_sha256"] == ablation_gate_provenance()["opaque_set_checksums_sha256"]
