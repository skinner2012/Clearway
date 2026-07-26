"""The shared LLM gateway seam: the provider-agnostic client protocol, the value types every
client speaks (`LLMUsage`, `Completion`, `ImagePart`, `LLMRequest`), and a deterministic offline
fake for tests.

Concrete clients live beside this module — `local.py` (Ollama via LiteLLM) and `cloud.py` (the
cloud reference judge). Both satisfy `LLMClient`, so callers (drafter, judge) depend only on this
seam, never on a provider.

A request may carry one picture
-------------------------------
`complete_json` takes an optional `ImagePart`: the bytes and the media type, nothing else. The
text is untouched by it — the picture travels as a second content part, never as a sentence saying
one is attached — which is the property the image experiment's whole statistic rests on: two
requests whose prompts are byte-identical and whose pixels differ.

`ImagePart` carries **bytes plus a declared media type, and no name.** An image reaches a model as
`data:<media-type>;base64,…` and is decoded by that declared type, so the type is the one piece of
metadata that changes what the model sees; a file name is the one piece that must never be trusted
for it (`scanner/capture.served_content_type` sniffs it from the bytes, and the derived image set
names JPEG assets `.png` on purpose to prove the point).

`LLMRequest` is what a call **would send**, as a value: the prompts, the schema's name and the
image's digest — hashable, so "did this ticket move a prompt" is answerable by comparing two hex
strings instead of by re-running a model. It is provider-independent on purpose: the same request
hashes identically whether a local chat client or a cloud Responses client serializes it, because
what it identifies is the *ask*, not the wire format.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMUsage:
    """Operational telemetry from one LLM call — captured once at the call site and used to fill
    both the OTel spans/metrics and the `Trace` operational fields. Every field is optional: a
    fake/offline client that makes no real call reports all-`None`, which is the honest value (no
    call happened). `cost_usd` is ~0 for local Ollama but captured anyway so the cloud-vs-local
    cost comparison is data-ready."""

    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None


class Completion(NamedTuple):
    """What a client's `complete_json` returns: the raw JSON content **plus** its usage, so
    token/cost/latency are never discarded at the call seam."""

    content: str
    usage: LLMUsage


@dataclass(frozen=True)
class ImagePart:
    """One picture attached to a request: the bytes, and the media type to declare for them.

    No name and no path, deliberately — an image travels to a model as `data:<media-type>;base64,…`
    and is decoded by the *declared* type, so a name that suggested a format would be the one field
    able to lie about what the model sees. `ref` is the sha256 of the bytes, the same digest the
    content-addressed store names them by, so what a request carried is auditable after the fact.

    Empty bytes are refused rather than encoded: a zero-length data URI is a request that looks
    multimodal and shows the model nothing, which is the exact failure a picture channel must never
    produce quietly.
    """

    data: bytes
    media_type: str

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("an ImagePart with no bytes would send a request that looks multimodal and shows nothing")
        if not self.media_type:
            raise ValueError(
                "an ImagePart needs the media type to declare — a data: URI is decoded by it, and it is "
                "sniffed from the bytes (scanner.capture.served_content_type), never taken from a name"
            )

    @property
    def ref(self) -> str:
        """The sha256 of the bytes — the same reference `Finding.image_ref` and the store carry."""
        return hashlib.sha256(self.data).hexdigest()

    def data_url(self) -> str:
        """The `data:<media-type>;base64,…` form providers take. `base64` is stdlib: carrying a
        picture adds no dependency."""
        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode()}"


class LLMRequest(NamedTuple):
    """What one call would send, as a comparable value: the two prompts, the response schema's name,
    and the attached picture's digest and media type (`None`/`None` when none is attached).

    It exists so a change to a prompt is *measurable* rather than argued. Wiring an image channel is
    exactly the kind of change that can move text nobody meant to move, and re-running a model to
    find out costs hours and still cannot separate a moved prompt from ordinary sampling drift. Two
    hex strings can.

    Deliberately provider-independent: it identifies the ask, not the wire format, so the same
    request hashes the same through the local chat client and the cloud Responses client. The bytes
    themselves are *not* in it — only their digest — so a recorded request stays small enough to
    freeze beside a run.
    """

    system: str
    user: str
    schema: str
    image_ref: str | None
    image_media_type: str | None

    @classmethod
    def of(cls, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None) -> LLMRequest:
        return cls(
            system=system,
            user=user,
            schema=schema.__name__,
            image_ref=image.ref if image is not None else None,
            image_media_type=image.media_type if image is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self._asdict())

    @property
    def sha256(self) -> str:
        """The digest of the whole ask — prompts, schema and the attached picture's digest.

        Canonical means sorted keys and no ASCII escaping, so the same request always hashes to the
        same string, and the image slot is present as `null` when no picture is attached: a payload
        measured before an image channel existed and one measured after must be comparable, and they
        only are if the shape is fixed from the start rather than grown a field later.
        """
        return _digest(self.to_dict())

    @property
    def prompt_sha256(self) -> str:
        """The digest of the **text** alone — system, user and schema, with the picture excluded.

        The two hashes answer different questions and both are needed, which is why neither is a
        substitute for the other. `sha256` asks "is this the same ask", so it moves when the pixels
        move — that is what proves a manipulation actually ran. `prompt_sha256` asks "is the model
        reading the same words", which must hold *across* conditions that differ only in pixels: it is
        the premise the image endpoint is defined over, and with only the full hash available it would
        be unfalsifiable, since a changed prompt and a changed picture would look identical.
        """
        return _digest({key: self.to_dict()[key] for key in ("system", "user", "schema")})


def _digest(payload: dict[str, Any]) -> str:
    """One canonical serialization for both hashes above, so they can never disagree about what
    canonical means."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@runtime_checkable
class LLMClient(Protocol):
    """The seam the drafter and judge depend on. Real (LiteLLM → Ollama / cloud) or fake (tests)."""

    @property
    def model(self) -> str: ...

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        """Return the model's raw JSON content **and its usage** for a system+user prompt under a
        response schema, optionally with one picture attached.

        `image=None` is the whole of the pre-image behaviour and must stay byte-identical on the
        wire: a caller that attaches nothing sends exactly the request it always sent.
        """
        ...


class FakeLLMClient:
    """Deterministic offline client for unit tests: returns canned raw strings, never a network
    call. Pass one or more responses; each call yields the next (the last repeats). Output
    *quality* is proven by the gated integration tests against the real models — the fake only
    exercises call-site mechanics (assembly, parsing, retry-then-fallback).

    It **records every request it was handed** (`requests`). That is not a test convenience: what a
    caller sent — including whether it attached a picture at all — is otherwise unobservable without
    a real model, and "the image silently never left the drafter" is the failure mode a picture
    channel is most likely to ship. The recorded `LLMRequest` carries the image's digest rather than
    its bytes, so an assertion names the exact picture."""

    _DEFAULT_RESPONSE = '{"conformance":"does_not_support","cited_sc_ids":[],"remediation":"","confidence":0.5}'

    def __init__(self, *responses: str, model: str = "fake-llm", usage: LLMUsage | None = None) -> None:
        self._responses = list(responses) or [self._DEFAULT_RESPONSE]
        self._model = model
        # Default all-`None`: a fake makes no real call, so it has no honest usage to report. Tests
        # that exercise the usage seam pass an explicit `usage=`.
        self._usage = usage if usage is not None else LLMUsage()
        self._i = 0
        self.requests: list[LLMRequest] = []

    @property
    def model(self) -> str:
        return self._model

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        self.requests.append(LLMRequest.of(system, user, schema, image))
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return Completion(response, self._usage)
