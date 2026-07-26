"""The gateway seam carries one picture — and carries nothing when there is none.

Three properties are load-bearing beyond "it works", and each is pinned here:

1. **No picture, no change.** A call that attaches nothing must serialize exactly as it did before
   the parameter existed, or every already-frozen run becomes unreproducible.
2. **The picture is a part, never a sentence.** The prompt text is untouched by attaching one, which
   is what lets two requests differ in pixels alone — the premise the image endpoint is defined over,
   and the reason the model is never told to look.
3. **A dropped picture is loud.** The cloud client refuses one instead of discarding it, and an
   empty `ImagePart` is refused at construction; both would otherwise produce a complete-looking
   answer to a question the model was never shown.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from pydantic import BaseModel

from clearway.llm import CloudLLMClient, FakeLLMClient, ImagePart, LLMClient, LLMRequest, LocalLLMClient
from clearway.llm.local import _user_content

# A one-pixel PNG's leading bytes are enough: nothing here decodes an image, and the digest of a
# short literal is as real a digest as any.
_PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"
_JPEG = b"\xff\xd8\xfffake-jpeg-bytes"


class _Schema(BaseModel):
    ok: bool


class _Message:
    content = '{"ok": true}'


class _Choice:
    message = _Message()


class _FakeResponse:
    choices = (_Choice(),)
    usage = None


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the kwargs the local client hands LiteLLM, without making a call."""
    seen: dict[str, Any] = {}

    def _fake_completion(**kwargs: Any) -> _FakeResponse:
        seen.update(kwargs)
        return _FakeResponse()

    import litellm

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    return seen


# --- ImagePart: bytes and a declared type, never a name ----------------------


def test_the_reference_is_the_sha256_of_the_bytes() -> None:
    """The same digest the content-addressed store names the bytes by, so what a request carried can
    be checked against what was captured."""
    assert ImagePart(_PNG, "image/png").ref == hashlib.sha256(_PNG).hexdigest()


def test_the_data_url_declares_the_media_type_it_was_given() -> None:
    """The declared type is what decodes the picture at the far end, and the derived image set names
    JPEG assets `.png` on purpose — so an ImagePart carries the type it was handed and never guesses
    one from a name it does not have."""
    url = ImagePart(_JPEG, "image/jpeg").data_url()
    assert url == f"data:image/jpeg;base64,{base64.b64encode(_JPEG).decode()}"
    assert base64.b64decode(url.split(",", 1)[1]) == _JPEG


def test_an_empty_or_untyped_image_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="no bytes"):
        ImagePart(b"", "image/png")
    with pytest.raises(ValueError, match="media type"):
        ImagePart(_PNG, "")


# --- LLMRequest: the ask as a comparable value -------------------------------


def test_the_request_hash_moves_with_the_prompt_the_schema_and_the_picture() -> None:
    """Everything that changes what the model is asked must change the hash — otherwise a payload
    check would pass over a request that had silently moved."""
    base = LLMRequest.of("sys", "user", _Schema)
    assert base.sha256 == LLMRequest.of("sys", "user", _Schema).sha256  # deterministic

    class _Other(BaseModel):
        ok: bool

    assert LLMRequest.of("sys2", "user", _Schema).sha256 != base.sha256
    assert LLMRequest.of("sys", "user2", _Schema).sha256 != base.sha256
    assert LLMRequest.of("sys", "user", _Other).sha256 != base.sha256
    assert LLMRequest.of("sys", "user", _Schema, ImagePart(_PNG, "image/png")).sha256 != base.sha256


def test_a_request_with_no_picture_records_the_image_slot_as_absent() -> None:
    """The slot exists whether or not a picture does, so a payload measured before this channel and
    one measured after are the same shape and can be compared at all."""
    assert LLMRequest.of("sys", "user", _Schema).to_dict() == {
        "system": "sys",
        "user": "user",
        "schema": "_Schema",
        "image_ref": None,
        "image_media_type": None,
    }


def test_the_request_records_the_digest_and_type_but_never_the_bytes() -> None:
    """A recorded request is frozen beside a run; the bytes live in the store, addressed by the very
    digest recorded here."""
    image = ImagePart(_JPEG, "image/jpeg")
    request = LLMRequest.of("sys", "user", _Schema, image)
    assert request.image_ref == image.ref
    assert request.image_media_type == "image/jpeg"
    assert "base64" not in repr(request)


def test_two_requests_differing_only_in_pixels_share_their_prompts_and_not_their_hash() -> None:
    """The endpoint's whole construction in one assertion: byte-identical text, different picture."""
    a = LLMRequest.of("sys", "user", _Schema, ImagePart(_PNG, "image/png"))
    b = LLMRequest.of("sys", "user", _Schema, ImagePart(_JPEG, "image/jpeg"))
    assert (a.system, a.user, a.schema) == (b.system, b.user, b.schema)
    assert a.sha256 != b.sha256


# --- the local client: a content-part list only when there is a part ---------


def test_no_image_sends_the_plain_string_content_it_always_sent(captured: dict[str, Any]) -> None:
    LocalLLMClient().complete_json("sys", "user text", _Schema)
    assert captured["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user text"},
    ]


def test_an_image_rides_as_a_second_content_part_beside_the_unchanged_text(captured: dict[str, Any]) -> None:
    image = ImagePart(_JPEG, "image/jpeg")
    LocalLLMClient().complete_json("sys", "user text", _Schema, image)
    system, user = captured["messages"]
    assert system == {"role": "system", "content": "sys"}
    assert user["content"] == [
        {"type": "text", "text": "user text"},
        {"type": "image_url", "image_url": {"url": image.data_url()}},
    ]


def test_attaching_a_picture_changes_no_other_part_of_the_request(captured: dict[str, Any]) -> None:
    """Structured output, temperature and the provider prefix are what make a draft comparable with
    every draft that came before it; a picture must move none of them."""
    LocalLLMClient().complete_json("sys", "user", _Schema, ImagePart(_PNG, "image/png"))
    assert captured["temperature"] == 0.0
    assert captured["response_format"] is _Schema
    assert captured["model"].startswith("ollama_chat/")
    assert captured["timeout"] > 0


def test_the_user_content_helper_is_the_only_thing_the_image_touches() -> None:
    """Pinned directly as well as through the client: the no-image branch returns the string itself,
    not a one-part list that happens to render the same."""
    assert _user_content("text", None) == "text"
    parts = _user_content("text", ImagePart(_PNG, "image/png"))
    assert isinstance(parts, list) and len(parts) == 2


# --- the fake: what a caller sent is observable without a model -------------


def test_the_fake_records_every_request_including_whether_a_picture_was_attached() -> None:
    client = FakeLLMClient('{"ok":true}')
    client.complete_json("sys", "one", _Schema)
    client.complete_json("sys", "two", _Schema, ImagePart(_PNG, "image/png"))
    assert [r.user for r in client.requests] == ["one", "two"]
    assert [r.image_ref for r in client.requests] == [None, hashlib.sha256(_PNG).hexdigest()]


def test_both_clients_and_the_fake_still_satisfy_the_seam() -> None:
    assert isinstance(FakeLLMClient(), LLMClient)
    assert isinstance(LocalLLMClient(), LLMClient)
    assert isinstance(CloudLLMClient(), LLMClient)


# --- the cloud client: parity in the signature, refusal in the body ---------


def test_the_cloud_client_refuses_a_picture_rather_than_dropping_it() -> None:
    """Its roles are text-only and the Responses image part is unexercised. A silent drop would
    answer a question the model was never shown, which is the failure this seam exists to prevent."""
    with pytest.raises(NotImplementedError, match="sends no images"):
        CloudLLMClient().complete_json("sys", "user", _Schema, ImagePart(_PNG, "image/png"))
