"""The shared LLM gateway seam: the provider-agnostic client protocol, the value types every
client speaks (`LLMUsage`, `Completion`), and a deterministic offline fake for tests.

Concrete clients live beside this module — `local.py` (Ollama via LiteLLM) and `cloud.py` (the
cloud reference judge). Both satisfy `LLMClient`, so callers (drafter, judge) depend only on this
seam, never on a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol, runtime_checkable

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


@runtime_checkable
class LLMClient(Protocol):
    """The seam the drafter and judge depend on. Real (LiteLLM → Ollama / cloud) or fake (tests)."""

    @property
    def model(self) -> str: ...

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> Completion:
        """Return the model's raw JSON content **and its usage** for a system+user prompt under a
        response schema."""
        ...


class FakeLLMClient:
    """Deterministic offline client for unit tests: returns canned raw strings, never a network
    call. Pass one or more responses; each call yields the next (the last repeats). Output
    *quality* is proven by the gated integration tests against the real models — the fake only
    exercises call-site mechanics (assembly, parsing, retry-then-fallback)."""

    _DEFAULT_RESPONSE = '{"conformance":"does_not_support","cited_sc_ids":[],"remediation":"","confidence":0.5}'

    def __init__(self, *responses: str, model: str = "fake-llm", usage: LLMUsage | None = None) -> None:
        self._responses = list(responses) or [self._DEFAULT_RESPONSE]
        self._model = model
        # Default all-`None`: a fake makes no real call, so it has no honest usage to report. Tests
        # that exercise the usage seam pass an explicit `usage=`.
        self._usage = usage if usage is not None else LLMUsage()
        self._i = 0

    @property
    def model(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> Completion:
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return Completion(response, self._usage)
