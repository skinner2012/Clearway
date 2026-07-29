"""Guard for the two frozen announced conditions and the endpoint A derived from them.

`opaque/told-no-image` and `opaque/told-with-image` cost 42 model calls that cannot be recovered:
re-running would call the model again under whatever prompt is current, which is a different
experiment wearing the same filename. So what is checked here is that each pass is the run it says it
is, that both were drafted by the model this project is pinned to, that the announcement actually
reached the model on every row — and that the report is *derived* from them rather than maintained
beside them.

Two claims are asserted here that belong to no other file:

* **the announced conditions never entered D.** Their prompts differ from all four of D's by
  construction — an announcement sentence and a differently-named response schema, both inside
  `prompt_sha256` — so no hash is shared. Checked, because "by construction" is the kind of claim that
  survives a refactor that quietly broke it.
* **D did not move.** Its four passes are pinned by `test_blind_judgment.py`; what is pinned *here* is
  the number a reader would compare against — D itself, its retained-cell count and its null rate,
  written out as literals so a re-derivation that changed them fails rather than being re-frozen.

No model call. Rebuild the report with `uv run python -m clearway.eval.image_score`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from clearway.eval.image_conditions import (
    ANNOUNCED_CONDITIONS,
    CONDITIONS,
    OPAQUE_NO_IMAGE,
    OPAQUE_TOLD_NO_IMAGE,
    OPAQUE_TOLD_WITH_IMAGE,
)
from clearway.eval.image_pass import canonical_rows, load_pass, pass_failures, pass_path, pinned_corpus_version
from clearway.eval.image_score import (
    ABSENCE_REPORT,
    ENDPOINT_REPORT,
    TEXT_DECIDED_CASE,
    VERDICT_A_CLOSED,
    VERDICT_A_NOT_USED,
    VERDICT_A_PARTIAL,
    VERDICT_A_UNINTERPRETABLE,
    build_absence_report,
)
from clearway.llm.local import _DEFAULT_MODEL

# The digest M6, M7 and D all ran, and the one every condition of this milestone is pinned to. Written
# out rather than read from the machine: a control that reads the live tag agrees with whatever loaded.
_PINNED_DIGEST = "6316f0629137b426c9d9b853ffc4c8209589f30ee39aebede6285096c0ff47e7"

# The two passes this ticket bought, with the digest they froze under. 42 model calls that cannot be
# re-spent, so a diff over their bytes is the only check there is.
FROZEN_ANNOUNCED: dict[Path, str] = {
    pass_path(OPAQUE_TOLD_NO_IMAGE): "c12a4bb2cbd987f6056db9afd2786bcb9338fbf586858cca26db674da895f285",
    pass_path(OPAQUE_TOLD_WITH_IMAGE): "3574a97651d8b15904b654b067c8a15fb573999645e2e08581c4a73e853ea6d0",
}

# D as it stood before this ticket existed, transcribed so "D is unchanged" is a comparison and not a
# sentence. A re-derivation that moved any of the three fails here.
D_BEFORE = {"d": 1, "retained": 6, "null_rate": 0.031746031746031744}

PASSES = {condition: load_pass(condition) for condition in ANNOUNCED_CONDITIONS}
BLIND = PASSES[OPAQUE_TOLD_NO_IMAGE]
SIGHTED = PASSES[OPAQUE_TOLD_WITH_IMAGE]
FROZEN: dict[str, Any] = json.loads(ABSENCE_REPORT.read_text())


def _rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for sample in artifact["samples"] for row in sample["rows"]]


# --- the two passes are the runs they claim to be ----------------------------


def test_both_announced_conditions_are_the_runs_they_say_they_are() -> None:
    for condition, artifact in PASSES.items():
        assert pass_failures(artifact) == [], condition.condition_id
        assert len(artifact["samples"]) == 3
        assert len(canonical_rows(artifact)) == 7
        assert artifact["condition"]["announces"] is True


def test_one_model_throughout_and_it_is_the_one_the_earlier_milestones_ran() -> None:
    for artifact in PASSES.values():
        assert artifact["drafter_model"] == _DEFAULT_MODEL
        assert artifact["drafter_model_digest"] == _PINNED_DIGEST


def test_the_announced_pair_moved_the_configuration_and_left_the_case_set_alone() -> None:
    """The pages are byte-identical to the ones D was drafted over, so the eval-set id must not move;
    the prompt and the response schema are both different, which is what a config id names."""
    for artifact in PASSES.values():
        assert artifact["config_id"] == "single-multimodal-announced@1"
        assert artifact["eval_set_id"] == OPAQUE_NO_IMAGE.scope.eval_set_id
        assert artifact["corpus_version"] == pinned_corpus_version()
        assert artifact["citations"]["source"] == "pinned"


def test_the_announcement_reached_the_model_on_every_row() -> None:
    """The silent failure this closes reads as a result: a condition that ran with the announcement
    off would be 21 complete-looking rows whose every answer to "could you see it" is empty, which in
    a report is a drafter that declined to say rather than one that was never asked."""
    for condition, artifact in PASSES.items():
        answered = [
            row for row in _rows(artifact) if row["draft"]["visual_evidence"] or row["draft"]["contradicted_claim"]
        ]
        assert len(answered) == 21, condition.condition_id


def test_the_blind_condition_carried_no_picture_and_the_sighted_one_carried_one_everywhere() -> None:
    assert {row["receipt"]["image_sha256"] for row in _rows(BLIND)} == {None}
    refs = {row["receipt"]["image_sha256"] for row in _rows(SIGHTED)}
    assert None not in refs
    assert all(len(ref) == 64 for ref in refs)


def test_the_system_fact_agrees_with_what_each_condition_attached() -> None:
    """`visually_verified` is written by the drafter from what it held at the seam, never copied from
    the condition — so the two agreeing is a check rather than a tautology."""
    assert {row["draft"]["visually_verified"] for row in _rows(BLIND)} == {False}
    assert {row["draft"]["visually_verified"] for row in _rows(SIGHTED)} == {True}


# --- the report is derived, not maintained -----------------------------------


def test_the_frozen_absence_report_rebuilds_identically_from_the_passes() -> None:
    assert build_absence_report() == FROZEN


def test_a_is_reported_with_both_controls_and_one_of_the_four_verdicts() -> None:
    endpoint, reading, controls = FROZEN["endpoint"], FROZEN["reading"], FROZEN["controls"]
    assert endpoint["denominator"] == 6
    assert endpoint["excluded_case"] == TEXT_DECIDED_CASE
    assert set(controls) == {"text_decided_case_reports_not_needed", "sighted_rows_never_withhold"}
    assert reading["verdict"] in {
        VERDICT_A_CLOSED,
        VERDICT_A_PARTIAL,
        VERDICT_A_NOT_USED,
        VERDICT_A_UNINTERPRETABLE,
    }


def test_the_measured_result_is_six_of_six_under_two_controls_that_hold() -> None:
    """The reading as it froze. Both controls are checked before A, because under either failing,
    blanket obedience and reasoning are indistinguishable at every value of A."""
    endpoint, reading, controls = FROZEN["endpoint"], FROZEN["reading"], FROZEN["controls"]
    assert controls["text_decided_case_reports_not_needed"]["visual_evidence"] == "not_needed"
    assert controls["sighted_rows_never_withhold"]["withholding"] == []
    assert reading["controls_hold"] is True
    assert (endpoint["a"], endpoint["denominator"]) == (6, 6)
    assert endpoint["leaked"] == []
    assert reading["verdict"] == VERDICT_A_CLOSED


def test_every_case_is_reported_with_the_conformance_it_gave_while_withholding() -> None:
    """The instrument has nowhere to put an abstention, so a withheld row still ships a verdict — and
    four of the six shipped `supports`, i.e. "this image is fine", while reporting they could not see
    it. Reporting the absence and acting on it are two different things, and the report shows both."""
    by_case = FROZEN["endpoint"]["by_case"]
    assert all(row["conformance"] for row in by_case)
    assert sum(1 for row in by_case if row["conformance"] == "supports") == 4


def test_per_case_sample_agreement_is_reported_beside_a() -> None:
    """A is read from sample 1 over all six, and an unstable case would be NAMED rather than dropped —
    an absolute count out of a fixed six cannot lose a case without making a partial result look
    closer to closed."""
    endpoint = FROZEN["endpoint"]
    assert endpoint["cases_agreeing_across_samples"] == 6
    assert endpoint["unstable"] == []
    assert all(len(row["samples"]) == 3 for row in endpoint["by_case"])


def test_the_receipts_prove_both_conditions_sent_what_the_frozen_mapping_says() -> None:
    """42 rows over 3 samples, read through the same rule D's four are held to — including that the
    two announcement states asked two different prompts, which IS the manipulation here."""
    receipts = FROZEN["receipts"]
    assert receipts["failures"] == []
    assert receipts["samples_checked"] == 3
    assert receipts["rows_checked"] == 42


def test_the_baseline_a_moved_from_is_re_run_rather_than_transcribed() -> None:
    """0 of 28, under the identical detector rule, over the rows frozen before this ticket existed."""
    baseline = FROZEN["baseline"]
    assert (baseline["blind_rows"], baseline["blind_rows_signalling"]) == (28, 0)
    assert baseline["signalling"] == []


def test_no_contradicted_row_was_recorded_and_the_channel_was_there_for_one() -> None:
    """The guard never fired against this model. That is a measured zero, not an absent mechanism —
    the channel carrying a refused claim is exercised offline in `test_drafter_visual_evidence.py`."""
    assert FROZEN["endpoint"]["contradicted"] == []
    assert all(row["draft"]["contradicted_claim"] is None for row in _rows(BLIND))


# --- the two experiments never met -------------------------------------------


def test_no_announced_prompt_is_a_prompt_any_condition_of_d_asked() -> None:
    """Why these two are a separate registry: D is defined over byte-identical prompts differing only
    in pixels, and an announced condition's prompt differs from all four by construction."""
    assert FROZEN["prompts_vs_d"]["shared_prompt_hashes"] == 0
    assert FROZEN["prompts_vs_d"]["differ"] is True
    assert FROZEN["prompts_vs_d"]["d_conditions"] == [c.condition_id for c in CONDITIONS]


def test_d_did_not_move_when_a_was_measured() -> None:
    """D is not recomputed by this endpoint and its null rate is not re-estimated. Both are read back
    off the frozen report and compared against literals transcribed before A existed — so a
    re-derivation that moved either fails here rather than being re-frozen to match."""
    reading = json.loads(ENDPOINT_REPORT.read_text())["reading"]
    assert {key: reading[key] for key in D_BEFORE} == D_BEFORE


def test_the_announced_conditions_are_absent_from_d_s_null_replicates() -> None:
    """Their instability is their own figure. Six conditions instead of four would move a denominator
    the endpoint was already read against."""
    null = json.loads(ENDPOINT_REPORT.read_text())["null_rate"]
    assert null["pairs"] == 3 * 7 * 3  # D's three sampled conditions only
    assert set(FROZEN["instability"]) == {c.condition_id for c in ANNOUNCED_CONDITIONS}


# --- what cost 42 calls does not move ----------------------------------------


def test_neither_announced_pass_moved_after_it_was_frozen() -> None:
    for path, digest in FROZEN_ANNOUNCED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
            f"{path.name} changed. It is 21 model calls that cannot be re-spent — a moved one is a "
            "re-run under a different question wearing this one's filename, never a test updated to match."
        )
