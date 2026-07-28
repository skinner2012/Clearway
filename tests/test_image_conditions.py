"""What each condition sends, and the receipt that proves it.

The claim this file exists to make checkable: **the picture the frozen permutation names is the
picture the drafter actually attached** — per finding, per condition. Nothing in a drafted row can
show that, and a byte count cannot either, because four of the seven findings render the same
photograph.

So the frozen mapping is transcribed here a second time, by hand, from the spec's own table. If the
receipt, the permutation artifact and this transcription ever disagree, the disagreement is loud.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clearway.drafter import Drafter
from clearway.eval.drafter_payload import load_baseline
from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_conditions import (
    ATTACHES_MISMATCHED_IMAGE,
    CONDITIONS,
    LEAKY_NO_IMAGE,
    OPAQUE_MISMATCHED_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_WITH_IMAGE,
    RECEIPT,
    Condition,
    ImageChannel,
    condition_by_id,
    drafted_findings,
    dry_receipt,
    receipt_failures,
    refs_for,
)
from clearway.eval.image_opaque import PERMUTATION
from clearway.eval.run_scope import IMAGE_OPAQUE, OutOfScope
from clearway.llm import FakeLLMClient

# A canned answer, so the assembly path runs with no model. Its content is irrelevant here: these
# tests are about the request, never about the response.
_CANNED = '{"conformance":"supports","cited_sc_ids":["1.1.1"],"remediation":"x","confidence":0.5}'

# The spec's permutation table, transcribed independently of the builder: case → (true, attached).
# Hand-written on purpose — a table derived from the artifact under test would agree with it however
# wrong both were. Keyed by the ten-character prefix the spec's own table prints, so the transcription
# is of the spec and carries none of the artifact's own strings.
_TABLE: dict[str, tuple[str, str]] = {
    "be6b29e220": ("w3c-logo", "bread"),
    "cfd1636ab4": ("nyhavn", "w3c-logo"),
    "1ff696703e": ("nyhavn", "bread"),
    "607ad4964a": ("bread", "w3c-logo"),
    "530266c611": ("w3c-logo", "nyhavn"),
    "f7406b89f8": ("nyhavn", "bread"),
    "a2333ec76e": ("nyhavn", "w3c-logo"),
}


@pytest.fixture(scope="module")
def rebuilt() -> dict[str, Any]:
    """One model-free rehearsal of all four conditions (28 drafts through the real Drafter)."""
    return dry_receipt()


@pytest.fixture(scope="module")
def frozen() -> dict[str, Any]:
    return dict(json.loads(RECEIPT.read_text()))


def _labels() -> dict[str, str]:
    """`image ref → label`, from the frozen permutation — the only place names and bytes are joined."""
    images = json.loads(PERMUTATION.read_text())["images"]
    return {image["sha256"]: label for label, image in images.items()}


def _case_ids() -> set[str]:
    return {row["act_testcase_id"] for row in json.loads(CAPTURE_ARTIFACT.read_text())["captures"]}


def _prefixes(case_ids: set[str]) -> set[str]:
    return {case_id[:10] for case_id in case_ids}


# --- one definition of a sample, shared by the rehearsal and a live pass -----


def test_one_sample_is_every_pool_finding_drafted_once_with_its_condition_s_picture() -> None:
    """The rehearsal and a live pass must draft the *same* work list under the *same* attachment rule.

    Two copies of this loop would be two definitions of what a sample is, and they would diverge in
    the direction that costs most: a live pass that drafts six findings, or one that quietly sends no
    picture, produces an artifact that reads as a completed condition either way.
    """
    drafter = Drafter(FakeLLMClient(_CANNED))
    drafted = list(drafted_findings(OPAQUE_WITH_IMAGE, drafter))

    assert len(drafted) == 7
    assert {case["act_testcase_id"][:10] for case, _, _ in drafted} == set(_TABLE)
    labels = _labels()
    for case, finding, result in drafted:
        assert result.request is not None
        assert result.request.image_ref == refs_for(OPAQUE_WITH_IMAGE)[finding.id]
        assert labels[str(result.request.image_ref)] == _TABLE[case["act_testcase_id"][:10]][0]


def test_a_text_only_condition_drafts_the_same_findings_and_sends_no_picture() -> None:
    drafter = Drafter(FakeLLMClient(_CANNED))
    drafted = list(drafted_findings(OPAQUE_NO_IMAGE, drafter))

    assert len(drafted) == 7
    assert all(result.request is not None and result.request.image_ref is None for _, _, result in drafted)


# --- the receipt is what the frozen mapping says ----------------------------


def test_the_frozen_receipt_rebuilds_byte_identically(rebuilt: dict[str, Any], frozen: dict[str, Any]) -> None:
    """Determinism of the whole chain — scan, mint, resolve the picture, record what was sent."""
    assert rebuilt == frozen


def test_every_condition_covers_every_pool_finding(frozen: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    for row in frozen["rows"]:
        counts[row["condition"]] = counts.get(row["condition"], 0) + 1
    assert counts == {c.condition_id: 7 for c in CONDITIONS}
    assert len(frozen["rows"]) == 28


def test_the_frozen_receipt_passes_its_own_checks(frozen: dict[str, Any]) -> None:
    failures = receipt_failures(frozen["rows"])
    assert failures == [], "; ".join(failures)


def test_the_receipt_matches_the_hand_transcribed_permutation(frozen: dict[str, Any]) -> None:
    """M8 Control 7. Both image conditions, read back as image NAMES against the spec's table."""
    labels = _labels()
    sent: dict[str, dict[str, str]] = {}
    for row in frozen["rows"]:
        if row["image_sha256"] is not None:
            sent.setdefault(row["act_testcase_id"][:10], {})[row["condition"]] = labels[row["image_sha256"]]
    assert set(sent) == set(_TABLE)
    for prefix, (true_image, attached) in _TABLE.items():
        assert sent[prefix][OPAQUE_WITH_IMAGE.condition_id] == true_image, prefix
        assert sent[prefix][OPAQUE_MISMATCHED_IMAGE.condition_id] == attached, prefix


def test_no_case_is_ever_shown_its_own_bytes_in_the_mismatched_condition(frozen: dict[str, Any]) -> None:
    """Byte-level, not label-level: four cases are the same photograph, so a mapping that deranges
    names can still hand a case its own pixels back."""
    by_case: dict[str, dict[str, str | None]] = {}
    for row in frozen["rows"]:
        by_case.setdefault(row["act_testcase_id"], {})[row["condition"]] = row["image_sha256"]
    for case_id, sent in by_case.items():
        assert sent[OPAQUE_WITH_IMAGE.condition_id] != sent[OPAQUE_MISMATCHED_IMAGE.condition_id], case_id


def test_the_text_only_conditions_attach_nothing(frozen: dict[str, Any]) -> None:
    text_only = {LEAKY_NO_IMAGE.condition_id, OPAQUE_NO_IMAGE.condition_id}
    rows = [row for row in frozen["rows"] if row["condition"] in text_only]
    assert len(rows) == 14
    assert {row["image_sha256"] for row in rows} == {None}
    assert {row["media_type"] for row in rows} == {None}


def test_the_media_type_comes_from_the_bytes_and_not_from_the_uniform_png_names(frozen: dict[str, Any]) -> None:
    """Every asset in the ablated set is named `.png` and two of the three are JPEG. A type derived
    from the name would send `image/png` for all seven, and the model would be told a lie about the
    bytes it is decoding."""
    labels = _labels()
    types = {
        labels[row["image_sha256"]]: row["media_type"] for row in frozen["rows"] if row["image_sha256"] is not None
    }
    assert types == {"w3c-logo": "image/png", "nyhavn": "image/jpeg", "bread": "image/jpeg"}


# --- the prompt is identical across conditions; the payload is not ----------


def test_the_three_opaque_conditions_share_one_prompt_per_finding(frozen: dict[str, Any]) -> None:
    """The endpoint's premise, checked on the recorded requests rather than assumed from the code."""
    opaque = {c.condition_id for c in CONDITIONS if c.scope is IMAGE_OPAQUE}
    prompts: dict[str, set[str]] = {}
    for row in frozen["rows"]:
        if row["condition"] in opaque:
            prompts.setdefault(row["finding_id"], set()).add(row["prompt_sha256"])
    assert len(prompts) == 7
    assert all(len(hashes) == 1 for hashes in prompts.values())


def test_the_three_opaque_conditions_never_share_a_payload(frozen: dict[str, Any]) -> None:
    """The other half: identical text and three distinct payloads is what "only the pixels change"
    means. Identical payloads under different pictures would mean no picture moved."""
    opaque = {c.condition_id for c in CONDITIONS if c.scope is IMAGE_OPAQUE}
    payloads: dict[str, set[str]] = {}
    for row in frozen["rows"]:
        if row["condition"] in opaque:
            payloads.setdefault(row["finding_id"], set()).add(row["payload_sha256"])
    assert all(len(hashes) == 3 for hashes in payloads.values())


def test_the_no_image_payloads_are_the_pre_wiring_control(frozen: dict[str, Any]) -> None:
    """The two artifacts meet: the text-only payloads a condition sends are the same hashes measured
    against the drafter before the image was wired into it."""
    control = load_baseline()
    for row in frozen["rows"]:
        if row["image_sha256"] is None:
            key = (row["scope"], row["act_testcase_id"], row["target"])
            assert control[key] == row["payload_sha256"], key


# --- every check is proven to fire ------------------------------------------


def _rows(frozen: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in frozen["rows"]]


def _first(rows: list[dict[str, Any]], condition: Condition) -> dict[str, Any]:
    return next(row for row in rows if row["condition"] == condition.condition_id)


def test_a_wrong_picture_in_either_image_condition_fails(frozen: dict[str, Any]) -> None:
    for condition in (OPAQUE_WITH_IMAGE, OPAQUE_MISMATCHED_IMAGE):
        rows = _rows(frozen)
        _first(rows, condition)["image_sha256"] = "0" * 64
        assert any("frozen mapping says" in f for f in receipt_failures(rows)), condition.condition_id


def test_a_case_shown_its_own_bytes_while_mismatched_fails(frozen: dict[str, Any]) -> None:
    """The failure that would leave D structurally unable to move, and would otherwise look like a
    clean run: the manipulation never actually swapped the picture."""
    rows = _rows(frozen)
    row = _first(rows, OPAQUE_MISMATCHED_IMAGE)
    own = next(
        r["image_sha256"]
        for r in rows
        if r["condition"] == OPAQUE_WITH_IMAGE.condition_id and r["finding_id"] == row["finding_id"]
    )
    row["image_sha256"] = own
    assert any("its OWN bytes" in f for f in receipt_failures(rows))


def test_a_picture_on_a_text_only_condition_fails(frozen: dict[str, Any]) -> None:
    rows = _rows(frozen)
    _first(rows, OPAQUE_NO_IMAGE)["image_sha256"] = "1" * 64
    assert any("attached a picture and must not" in f for f in receipt_failures(rows))


def test_a_condition_missing_a_finding_fails(frozen: dict[str, Any]) -> None:
    """A silently short pass: seven cells become six and the endpoint's denominator changes with no
    error anywhere."""
    rows = _rows(frozen)
    rows.remove(_first(rows, OPAQUE_WITH_IMAGE))
    assert len(rows) == 27
    assert any("6 rows for 7 findings" in f for f in receipt_failures(rows))


def test_a_moved_prompt_across_conditions_fails(frozen: dict[str, Any]) -> None:
    rows = _rows(frozen)
    _first(rows, OPAQUE_WITH_IMAGE)["prompt_sha256"] = "2" * 64
    assert any("different prompts across the opaque conditions" in f for f in receipt_failures(rows))


def test_two_conditions_sending_the_identical_payload_fails(frozen: dict[str, Any]) -> None:
    rows = _rows(frozen)
    with_row = _first(rows, OPAQUE_WITH_IMAGE)
    mismatched = next(
        r
        for r in rows
        if r["condition"] == OPAQUE_MISMATCHED_IMAGE.condition_id and r["finding_id"] == with_row["finding_id"]
    )
    mismatched["payload_sha256"] = with_row["payload_sha256"]
    mismatched["image_sha256"] = with_row["image_sha256"]
    assert any("no picture moved" in f or "its OWN bytes" in f for f in receipt_failures(rows))


def test_an_unknown_condition_id_is_refused(frozen: dict[str, Any]) -> None:
    with pytest.raises(OutOfScope, match="not one of the four conditions"):
        condition_by_id("opaque/with-the-right-image")
    rows = _rows(frozen)
    rows[0]["condition"] = "invented"
    assert any("not one of the four conditions" in f for f in receipt_failures(rows))


# --- the channel refuses rather than drafting a picture-less image condition -


def test_the_channel_refuses_a_finding_no_frozen_reference_names() -> None:
    """The silent failure this closes: an image condition that quietly drafts text-only produces a row
    reading "the pixels made no difference" for a finding that was never shown any."""
    channel = ImageChannel(OPAQUE_WITH_IMAGE)
    with pytest.raises(OutOfScope, match="no frozen reference"):
        channel.for_finding("not-a-finding-id")


def test_a_text_only_condition_resolves_no_reference_at_all() -> None:
    assert refs_for(OPAQUE_NO_IMAGE) == {}
    assert ImageChannel(OPAQUE_NO_IMAGE).for_finding("not-a-finding-id") is None


def test_the_two_image_conditions_resolve_a_reference_for_every_pool_finding() -> None:
    with_image, mismatched = refs_for(OPAQUE_WITH_IMAGE), refs_for(OPAQUE_MISMATCHED_IMAGE)
    assert len(with_image) == len(mismatched) == 7
    assert set(with_image) == set(mismatched)
    assert all(with_image[fid] != mismatched[fid] for fid in with_image)


def test_the_pictures_load_as_bytes_with_a_sniffed_type() -> None:
    channel = ImageChannel(OPAQUE_WITH_IMAGE)
    for finding_id, ref in refs_for(OPAQUE_WITH_IMAGE).items():
        part = channel.for_finding(finding_id)
        assert part is not None
        assert part.ref == ref  # the store re-hashed the bytes on the way out
        assert part.media_type in {"image/png", "image/jpeg"}


# --- the conditions are the four the spec pre-registered --------------------


def test_the_four_conditions_and_their_sample_counts_are_the_pre_registered_ones() -> None:
    assert [c.condition_id for c in CONDITIONS] == [
        "leaky/no-image",
        "opaque/no-image",
        "opaque/with-image",
        "opaque/mismatched-image",
    ]
    assert [c.samples for c in CONDITIONS] == [1, 3, 3, 3]
    assert [c.carries_image for c in CONDITIONS] == [False, False, True, True]
    assert OPAQUE_MISMATCHED_IMAGE.attaches == ATTACHES_MISMATCHED_IMAGE


def test_the_receipt_records_the_scope_identity_of_every_condition(frozen: dict[str, Any]) -> None:
    """A run cannot stamp another run's identity: both image conditions carry the opaque set's id, and
    the descriptive one carries the vendored set's."""
    declared = {row["condition"]: row for row in frozen["conditions"]}
    assert declared["leaky/no-image"]["eval_set_id"] != declared["opaque/no-image"]["eval_set_id"]
    assert {row["config_id"] for row in frozen["conditions"]} == {"single-multimodal@1"}
    assert Path(RECEIPT).name == "image_condition_dry_receipt.json"
    assert _prefixes(_case_ids()) == set(_TABLE)
