"""The drafter sends the picture — on the judgment path, and provably nowhere else.

What is asserted here, and why each one is not decoration:

* the image reaches the client on the judgment path (the channel exists at all);
* the prompt is **byte-identical** with and without it, so two calls can differ in pixels alone — the
  premise the image endpoint's statistic is defined over;
* the assembled path **refuses** a picture rather than dropping it, because a dropped one leaves a row
  indistinguishable from one whose model looked and was unmoved;
* the request that was sent is recorded on the result, so a receipt can name the exact bytes;
* and the frozen payload control still holds when re-derived through a real `Drafter` call — the
  independent second direction on the same claim `test_drafter_payload` makes through the prompt
  builders.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from clearway.drafter import Drafter, ImageOnAssembledPath, is_fallback_draft
from clearway.drafter.llm import _LLMDraft
from clearway.eval.act_image_gold import _minting_findings as image_minting_findings
from clearway.eval.drafter_payload import baseline_failures, build_baseline, citations_for, load_baseline
from clearway.eval.image_reachability import ACT_IMAGE
from clearway.eval.run_scope import IMAGE_OPAQUE, RunScope, cases_for
from clearway.llm import FakeLLMClient, ImagePart, LLMRequest, LocalLLMClient
from clearway.scanner.capture import ImageStore
from clearway.schemas.models import AxeBucket, Citation, Conformance, Finding, Severity

_JUDGMENT = '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"Describe it.","confidence":0.7}'
_REMEDIATION = '{"remediation":"Add an alt attribute describing the photograph."}'

_PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"
_JPEG = b"\xff\xd8\xfffake-jpeg-bytes"


def _image_finding(bucket: AxeBucket = AxeBucket.PASSES, tags: list[str] | None = None) -> Finding:
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
    )


def _cite() -> list[Citation]:
    return [Citation(sc_id="1.1.1", url="https://www.w3.org/TR/WCAG22/#non-text-content", source="WCAG-SC")]


# --- the channel ------------------------------------------------------------


def test_the_picture_reaches_the_client_on_the_judgment_path() -> None:
    client = FakeLLMClient(_JUDGMENT)
    image = ImagePart(_JPEG, "image/jpeg")
    row = Drafter(client).draft(_image_finding(), _cite(), image)
    (request,) = client.requests
    assert request.image_ref == hashlib.sha256(_JPEG).hexdigest()
    assert request.image_media_type == "image/jpeg"
    assert row.conformance is Conformance.DOES_NOT_SUPPORT  # the draft still assembles normally


def test_attaching_a_picture_changes_no_byte_of_either_prompt() -> None:
    """The endpoint's construction: same frozen page, same help, same candidates, only the pixels
    differ. If attaching an image moved one character of the text, D would be measuring a changed
    prompt and calling it perception."""
    finding, citations = _image_finding(), _cite()
    without = FakeLLMClient(_JUDGMENT)
    with_image = FakeLLMClient(_JUDGMENT)
    Drafter(without).draft(finding, citations)
    Drafter(with_image).draft(finding, citations, ImagePart(_PNG, "image/png"))
    (bare,), (attached,) = without.requests, with_image.requests
    assert (bare.system, bare.user, bare.schema) == (attached.system, attached.user, attached.schema)
    assert bare.image_ref is None and attached.image_ref is not None
    assert bare.sha256 != attached.sha256  # the payload hash still records the difference


def test_the_prompt_never_says_a_picture_is_attached() -> None:
    """Pre-registered and reported as a limitation: the model is never told to look. Keeping the text
    identical across conditions is what D requires, and this is the side effect of it."""
    client = FakeLLMClient(_JUDGMENT)
    Drafter(client).draft(_image_finding(), _cite(), ImagePart(_PNG, "image/png"))
    (request,) = client.requests
    text = (request.system + request.user).lower()
    for word in ("image is attached", "attached image", "the picture", "look at"):
        assert word not in text


def test_two_findings_differing_only_in_pixels_send_identical_text() -> None:
    """The mismatched condition in miniature: one finding, two pictures, one prompt."""
    finding, citations = _image_finding(), _cite()
    client = FakeLLMClient(_JUDGMENT)
    drafter = Drafter(client)
    drafter.draft(finding, citations, ImagePart(_PNG, "image/png"))
    drafter.draft(finding, citations, ImagePart(_JPEG, "image/jpeg"))
    first, second = client.requests
    assert first.user == second.user and first.system == second.system
    assert first.image_ref != second.image_ref


# --- the assembled path takes no picture ------------------------------------


def test_the_assembled_path_refuses_a_picture_instead_of_dropping_it() -> None:
    confirmed = _image_finding(bucket=AxeBucket.VIOLATIONS, tags=["wcag2a", "wcag111"])
    client = FakeLLMClient(_REMEDIATION)
    with pytest.raises(ImageOnAssembledPath, match="would be dropped"):
        Drafter(client).draft(confirmed, _cite(), ImagePart(_PNG, "image/png"))
    assert client.requests == []  # refused before anything was sent


def test_the_assembled_path_still_drafts_normally_with_no_picture() -> None:
    confirmed = _image_finding(bucket=AxeBucket.VIOLATIONS, tags=["wcag2a", "wcag111"])
    client = FakeLLMClient(_REMEDIATION)
    row = Drafter(client).draft(confirmed, _cite())
    (request,) = client.requests
    assert request.image_ref is None
    assert request.schema == "_LLMRemediation"
    assert is_fallback_draft(row) is False


def test_a_text_class_finding_carries_no_picture_when_none_is_passed() -> None:
    """The cross-class half: nothing about the image channel reaches a class that never asked for one."""
    label = Finding(
        id="f-label",
        source_url="file:///case.html",
        rule_id="label",
        target="#email",
        html='<input id="email">',
        help="The form field has an accessible name — judge whether it describes the field",
        impact=Severity.SERIOUS,
        source_bucket=AxeBucket.PASSES,
    )
    client = FakeLLMClient(_JUDGMENT)
    Drafter(client).draft(label, _cite())
    assert [r.image_ref for r in client.requests] == [None]


# --- the request is recorded, so a receipt can name what was sent -----------


def test_the_result_records_the_request_that_was_actually_sent() -> None:
    image = ImagePart(_JPEG, "image/jpeg")
    result = Drafter(FakeLLMClient(_JUDGMENT)).draft_with_usage(_image_finding(), _cite(), image)
    assert result.request is not None
    assert result.request.image_ref == image.ref
    assert result.request.schema == "_LLMDraft"
    assert result.request.sha256 == LLMRequest.of(result.request.system, result.request.user, _LLMDraft, image).sha256


def test_a_fallback_still_records_the_request_it_failed_on() -> None:
    """A pass that aborts on a fallback needs to know which ask produced it — including whether a
    picture was attached, since an unparseable response to a multimodal request is the first thing a
    provider problem would look like."""
    image = ImagePart(_PNG, "image/png")
    result = Drafter(FakeLLMClient("not json", "still not json")).draft_with_usage(_image_finding(), _cite(), image)
    assert is_fallback_draft(result.row) is True
    assert result.request is not None and result.request.image_ref == image.ref


def test_every_retry_sends_the_identical_ask() -> None:
    client = FakeLLMClient("not json", _JUDGMENT)
    image = ImagePart(_PNG, "image/png")
    result = Drafter(client).draft_with_usage(_image_finding(), _cite(), image)
    assert len(client.requests) == 2
    assert client.requests[0] == client.requests[1] == result.request


# --- the payload control, re-derived through a real Drafter call ------------


def _sent_request(scope: RunScope, case: dict[str, Any], finding: Finding) -> LLMRequest:
    client = FakeLLMClient(_JUDGMENT)
    result = Drafter(client).draft_with_usage(finding, citations_for(case["axe_rule"]))
    (sent,) = client.requests
    assert result.request == sent  # what was recorded is what went out
    return sent


def test_the_frozen_payload_control_holds_through_the_wired_drafter() -> None:
    """M8 Control 6 from the second direction. `test_drafter_payload` compares the frozen hashes
    against the prompt builders; this compares them against what a real `Drafter` call — dispatch,
    retries and image parameter included — actually hands the client. Both must agree with a
    measurement taken before the image was wired in.

    Scoped to the opaque set: it is the set the endpoint runs on, and the two directions cover the
    same code, so re-scanning both image sets here would buy a second copy of the same evidence.
    """
    frozen = load_baseline()
    rows = [
        {
            "scope": IMAGE_OPAQUE.scope_id,
            "act_testcase_id": case["act_testcase_id"],
            "target": finding.target,
            "payload_sha256": _sent_request(IMAGE_OPAQUE, case, finding).sha256,
        }
        for case in cases_for(IMAGE_OPAQUE)
        for finding in IMAGE_OPAQUE.minting_findings(IMAGE_OPAQUE.root / case["path"], case["axe_rule"])
    ]
    assert len(rows) == 7
    scoped = {key: value for key, value in frozen.items() if key[0] == IMAGE_OPAQUE.scope_id}
    failures = baseline_failures(rows, scoped)
    assert failures == [], "; ".join(failures)


def test_the_builder_and_the_drafter_agree_with_each_other_too() -> None:
    """Not a third copy of the control — the point is that the two paths are interchangeable, so a
    future change that moved only one of them is caught even if the frozen file were regenerated."""
    built = {(r["scope"], r["act_testcase_id"], r["target"]): r["payload_sha256"] for r in build_baseline()["payloads"]}
    for case in cases_for(IMAGE_OPAQUE):
        for finding in IMAGE_OPAQUE.minting_findings(IMAGE_OPAQUE.root / case["path"], case["axe_rule"]):
            key = (IMAGE_OPAQUE.scope_id, case["act_testcase_id"], finding.target)
            assert built[key] == _sent_request(IMAGE_OPAQUE, case, finding).sha256


# --- Acceptance 2: the real model, the real pipeline prompt, a real capture ---


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


ollama_up = pytest.mark.skipif(not _ollama_up(), reason="Ollama not running (need `ollama serve` + gemma4:31b)")

# A case that MINTS a real image finding and renders its picture, and that no measurement reads: it is
# one half of a prompt-level twin pair, excluded from the gold pool by the exclusion rule. So this
# smoke test spends nothing held out — the endpoint's seven cases are untouched by it.
_SMOKE_CASE = "499be2117059dba5f38526df06b711d0125eccd7"


@ollama_up
def test_real_drafter_carries_a_captured_picture_through_the_pipeline_prompt(tmp_path: Path) -> None:
    """M8 Acceptance 2. The transport probe established that LiteLLM carries an image part, a schema
    and the model's thinking in one request; it did so with a hand-written two-sentence prompt. This
    runs the **production** path end to end instead: a real scan captures the picture, the real
    per-finding prompt is built with its candidate criteria, the picture rides the real `Drafter`
    call, and the response has to parse as a real `DraftRow`.

    Asserted: the row is not the fallback (so the provider accepted image + schema together on a full
    prompt), and the request the drafter reports sending carries exactly the digest the scan captured.
    The model's *wording* is never asserted — that is a measurement, and it belongs to the conditions.
    """
    case = ACT_IMAGE / "html" / f"{_SMOKE_CASE}.html"
    store = ImageStore(tmp_path / "captured")
    (finding,) = image_minting_findings(case, store)
    assert finding.image_ref is not None
    image = ImagePart(store.read(finding.image_ref), store.media_type(finding.image_ref))

    result = Drafter(LocalLLMClient()).draft_with_usage(finding, citations_for(finding.rule_id), image)

    assert is_fallback_draft(result.row) is False
    assert isinstance(result.row.conformance, Conformance)
    assert 0.0 <= result.row.confidence <= 1.0
    assert result.row.remediation.strip() != ""
    assert result.request is not None
    assert result.request.image_ref == finding.image_ref
    assert result.request.image_media_type == image.media_type
