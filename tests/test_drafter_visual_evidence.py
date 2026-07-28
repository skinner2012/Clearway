"""The drafter records whether the judgment it made had the pixels it needed.

Three claims, and they fail in different directions:

* **the marking** — a pixel-decided finding drafted with no picture carries `visually_verified is
  False`, from the system's own fact; a class no picture decides carries `None`, not `False`, because
  "the question does not arise" and "unverified" are different statements about a row;
* **the guard** — a model claiming it saw a picture that was never sent is refused, and degrades
  through the existing validate-retry-then-fallback contract rather than a second failure mode;
* **the announcement is off by default, and gated twice when on** — the parameter keeps every
  existing caller byte-identical, and the class gate keeps every non-pixel-decided finding
  byte-identical even after the parameter is flipped. The second gate is what the frozen payload
  control rests on once the first one goes.
"""

from __future__ import annotations

import pytest

from clearway.drafter import Drafter, is_fallback_draft
from clearway.llm import FakeLLMClient, ImagePart
from clearway.schemas.models import AxeBucket, Citation, Finding, Severity, VisualEvidence

_PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"

_JUDGMENT = '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"Describe it.","confidence":0.7}'
_REMEDIATION = '{"remediation":"Add an alt attribute describing the photograph."}'


def _announced(value: str) -> str:
    return (
        '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"Describe it.",'
        f'"confidence":0.7,"visual_evidence":"{value}"}}'
    )


def _image_finding(bucket: AxeBucket = AxeBucket.PASSES, tags: list[str] | None = None, **extra: object) -> Finding:
    return Finding(
        id="f-image",
        source_url="file:///case.html",
        rule_id="image-alt",
        target="img",
        html='<img src="/img/a.png" alt="Nyhavn">',
        help="The image has an accessible name — judge whether it describes the image",
        impact=Severity.SERIOUS,
        axe_tags=tags if tags is not None else ["cat.text-alternatives"],
        source_bucket=bucket,
        **extra,  # type: ignore[arg-type]  # only ever a declared Finding field
    )


def _text_finding() -> Finding:
    return Finding(
        id="f-label",
        source_url="file:///case.html",
        rule_id="label",
        target="#email",
        html='<input id="email">',
        help="The form field has an accessible name — judge whether it describes the field",
        impact=Severity.SERIOUS,
        source_bucket=AxeBucket.PASSES,
    )


def _cite() -> list[Citation]:
    return [Citation(sc_id="1.1.1", url="https://www.w3.org/TR/WCAG22/#non-text-content", source="WCAG-SC")]


# --- the marking: the system's own fact, no model involved ------------------


def test_a_pixel_decided_finding_drafted_without_pixels_is_marked_unverified() -> None:
    """The defect this closes, in one row: the drafter answered a question about pixels with none."""
    row = Drafter(FakeLLMClient(_JUDGMENT)).draft(_image_finding(), _cite())
    assert row.visually_verified is False
    assert row.visual_evidence is None  # no model was asked, so no model claim


def test_the_same_finding_with_the_picture_attached_is_marked_verified() -> None:
    row = Drafter(FakeLLMClient(_JUDGMENT)).draft(_image_finding(), _cite(), ImagePart(_PNG, "image/png"))
    assert row.visually_verified is True


def test_a_class_no_picture_decides_is_neither_verified_nor_unverified() -> None:
    """The tri-state's whole point: two-valued, this row would have to say False and every text
    finding in the product would read as visually unverified."""
    row = Drafter(FakeLLMClient(_JUDGMENT)).draft(_text_finding(), _cite())
    assert row.visually_verified is None


def test_the_marking_is_keyed_to_the_rule_and_never_to_the_captured_reference() -> None:
    """`image_ref` is a property of the NODE and is `None` in exactly the case the marking exists for,
    so a marking inferred from it would be silent precisely when it matters. Both directions:
    a finding that captured a picture but was drafted without one is still unverified, and a text
    class stays out of the question even when its node happens to carry a reference."""
    captured = _image_finding(image_ref="a" * 64)
    assert Drafter(FakeLLMClient(_JUDGMENT)).draft(captured, _cite()).visually_verified is False

    text_with_reference = _text_finding().model_copy(update={"image_ref": "b" * 64})
    assert Drafter(FakeLLMClient(_JUDGMENT)).draft(text_with_reference, _cite()).visually_verified is None


def test_the_assembled_path_carries_neither_field() -> None:
    """A confirmed violation's verdict is axe's, not a judgment made with or without pixels — so the
    question does not arise, and no model wrote a claim about it."""
    confirmed = _image_finding(bucket=AxeBucket.VIOLATIONS, tags=["wcag2a", "wcag111"])
    row = Drafter(FakeLLMClient(_REMEDIATION)).draft(confirmed, _cite())
    assert is_fallback_draft(row) is False
    assert row.visually_verified is None and row.visual_evidence is None


def test_the_fallback_carries_neither_field() -> None:
    """Nothing was judged, so there is no judgment for either field to be about — and the fallback
    keeps one fixed signature for every way a draft can fail."""
    row = Drafter(FakeLLMClient("not json", "still not json")).draft(_image_finding(), _cite())
    assert is_fallback_draft(row) is True
    assert row.visually_verified is None and row.visual_evidence is None


# --- the guard: a claim the system contradicts ------------------------------


def test_a_row_claiming_seen_against_the_record_degrades_to_the_visible_fallback() -> None:
    client = FakeLLMClient(_announced("seen"))
    row = Drafter(client).draft(_image_finding(), _cite(), announce_image=True)
    assert is_fallback_draft(row) is True
    assert len(client.requests) == 2  # validate, retry once, then degrade — the existing contract
    assert row.visual_evidence is None  # the degraded row makes no claim of its own


def test_a_retry_that_stops_claiming_seen_ships() -> None:
    """Retry-then-degrade, not abort: the guard is the same failure mode as an off-schema response."""
    client = FakeLLMClient(_announced("seen"), _announced("absent"))
    row = Drafter(client).draft(_image_finding(), _cite(), announce_image=True)
    assert is_fallback_draft(row) is False
    assert row.visual_evidence is VisualEvidence.ABSENT and row.visually_verified is False


@pytest.mark.parametrize("claim", ["absent", "not_needed"])
def test_the_other_two_claims_are_not_contradictions(claim: str) -> None:
    """Both are answers a blind draft may correctly give — `not_needed` is the one that separates
    reasoning from obedience, so a guard refusing it would fail a correct implementation."""
    row = Drafter(FakeLLMClient(_announced(claim))).draft(_image_finding(), _cite(), announce_image=True)
    assert is_fallback_draft(row) is False
    assert row.visual_evidence is VisualEvidence(claim)


def test_the_claim_stands_when_the_picture_really_was_sent() -> None:
    row = Drafter(FakeLLMClient(_announced("seen"))).draft(
        _image_finding(), _cite(), ImagePart(_PNG, "image/png"), announce_image=True
    )
    assert row.visual_evidence is VisualEvidence.SEEN and row.visually_verified is True


def test_a_claim_against_a_class_the_marking_does_not_track_is_not_a_contradiction() -> None:
    """`seen` against `None` says nothing false: that judgment was never one pixels decide, so this
    module holds no record to contradict. The row also carries no claim, because a text class is
    never asked under the announced shape."""
    row = Drafter(FakeLLMClient(_announced("seen"))).draft(_text_finding(), _cite(), announce_image=True)
    assert is_fallback_draft(row) is False
    assert row.visual_evidence is None and row.visually_verified is None


# --- the announcement: off by default, gated twice when on ------------------


def test_the_default_asks_exactly_what_it_asked_before() -> None:
    client = FakeLLMClient(_JUDGMENT)
    Drafter(client).draft(_image_finding(), _cite())
    (request,) = client.requests
    assert request.schema == "_LLMDraft"
    assert "visual_evidence" not in (request.system + request.user)


def test_the_unannounced_shape_cannot_carry_a_claim_by_accident() -> None:
    """A model volunteering the field where it was not asked for it is dropped, not honoured — the
    field is absent from the shape the answer is validated under."""
    row = Drafter(FakeLLMClient(_announced("seen"))).draft(_image_finding(), _cite())
    assert is_fallback_draft(row) is False  # not a contradiction either: nothing was claimed
    assert row.visual_evidence is None


@pytest.mark.parametrize(
    ("image", "expected"),
    [(None, "NO picture of this element is attached"), (ImagePart(_PNG, "image/png"), "IS attached")],
)
def test_the_announcement_states_which_way_it_is(image: ImagePart | None, expected: str) -> None:
    """It renders in both directions: "no picture is attached" is the half the defect is about."""
    client = FakeLLMClient(_announced("absent" if image is None else "seen"))
    Drafter(client).draft(_image_finding(), _cite(), image, announce_image=True)
    (request,) = client.requests
    assert expected in request.user
    assert "visual_evidence" in request.system  # the field's rules travel with the announcement
    assert request.schema == "_LLMDraftVisualEvidence"


def test_a_class_outside_the_pixel_decided_rules_is_byte_identical_with_the_announcement_on() -> None:
    """The second gate. The parameter alone would keep existing callers still; this is what keeps the
    frozen payload control still once the parameter is flipped on."""
    finding, citations = _text_finding(), _cite()
    off, on = FakeLLMClient(_JUDGMENT), FakeLLMClient(_JUDGMENT)
    Drafter(off).draft(finding, citations)
    Drafter(on).draft(finding, citations, announce_image=True)
    (quiet,), (announced,) = off.requests, on.requests
    assert quiet.prompt_sha256 == announced.prompt_sha256
    assert quiet.sha256 == announced.sha256


def test_the_announced_ask_moves_both_hashes_on_a_class_it_applies_to() -> None:
    """The reason for the second schema class: `LLMRequest` records the schema's NAME, so an ask that
    moved would otherwise be invisible to the control built to catch exactly that."""
    finding, citations = _image_finding(), _cite()
    off, on = FakeLLMClient(_JUDGMENT), FakeLLMClient(_announced("absent"))
    Drafter(off).draft(finding, citations)
    Drafter(on).draft(finding, citations, announce_image=True)
    (quiet,), (announced,) = off.requests, on.requests
    assert quiet.prompt_sha256 != announced.prompt_sha256
    assert quiet.schema == "_LLMDraft" and announced.schema == "_LLMDraftVisualEvidence"
