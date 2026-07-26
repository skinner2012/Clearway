"""The cloud reference client: an OpenAI model via LiteLLM's Responses API (`/v1/responses`),
structured output via a JSON-schema `text.format`.

Why Responses, not Chat Completions: the cloud judge is a reasoning-class model, and Responses is
its native surface (stronger reasoning behaviour + better cache utilisation, and OpenAI's
recommended API for new integrations). Reasoning models take no `temperature` knob; determinism
comes from a pinned snapshot + a fixed reasoning effort + a fixed prompt — the honest best a cloud
model offers (a dated snapshot is still not bit-reproducible).

Satisfies the shared `LLMClient` seam, so callers depend only on that, never on the provider.

**It takes the seam's `image` parameter and refuses a non-`None` one.** Signature parity is required
— the drafter and the judge depend on one protocol — but the roles this client serves send no
pixels: the judge grades a drafted row against a finding's text, and the technique classifier is
handed a remediation sentence and deliberately nothing else. So the honest options were an
unexercised Responses image part (untested code on a paid path, which a later caller would read as
supported) or a refusal that says so. Silently dropping the picture was never one: the local client
is the only place the image channel is measured, and a cloud call that quietly discarded a picture
would produce a complete-looking answer to a question nobody asked.
"""

from __future__ import annotations

import os
import time

from pydantic import BaseModel

from clearway.llm.client import Completion, ImagePart, LLMUsage

_DEFAULT_MODEL = "gpt-5.6-luna"
_DEFAULT_EFFORT = "medium"

# The technique classifier is a SEPARATE role with its own pin, never the judge's. Three model roles
# exist and are never conflated: the local drafter writes the evidence, the judge grades no-oracle
# judgment items, and this one infers which WCAG technique a drafted remediation implies — a
# classification scored against ACT gold, not a verdict anyone trusts.
_TECHNIQUE_MODEL = "gpt-5.6-sol"
_TECHNIQUE_EFFORT = "medium"


class CloudLLMClient:
    """Real cloud client: an OpenAI reasoning model via LiteLLM's Responses API, structured output
    at a fixed reasoning effort. `LLMClient`-shaped, so the judge depends only on the seam."""

    def __init__(self, model: str | None = None, reasoning_effort: str | None = None) -> None:
        self._model: str = model or os.getenv("CLEARWAY_JUDGE_MODEL") or _DEFAULT_MODEL
        self._effort: str = reasoning_effort or os.getenv("CLEARWAY_JUDGE_EFFORT") or _DEFAULT_EFFORT

    @property
    def model(self) -> str:
        return self._model

    @property
    def reasoning_effort(self) -> str:
        return self._effort

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        import litellm

        if image is not None:
            raise NotImplementedError(
                "this cloud client sends no images: its roles (the reference judge, the technique "
                f"classifier) are text-only by design, and the Responses image part is unexercised. "
                f"Refused rather than dropped — a discarded picture ({image.ref[:8]}…) would return a "
                "complete-looking answer to a question the model was never shown."
            )
        start = time.perf_counter()
        response = litellm.responses(
            model=f"openai/{self._model}",
            instructions=system,
            input=user,
            reasoning={"effort": self._effort},
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                }
            },
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        content: str = getattr(response, "output_text", "") or ""
        return Completion(content, _usage_from_responses(response, latency_ms))


def technique_classifier_client() -> CloudLLMClient:
    """The technique classifier as its own configured role — `CLEARWAY_TECHNIQUE_MODEL` /
    `CLEARWAY_TECHNIQUE_EFFORT`, falling back to the pins above.

    Deliberately a different model from BOTH the drafter (which wrote the remediation being classified,
    so grading its own output would be self-preference) and the judge (a distinct role that still exists
    and keeps its own config — the two are never merged). Passing the model explicitly also stops the
    constructor falling back to the judge's environment variables.
    """
    return CloudLLMClient(
        model=os.getenv("CLEARWAY_TECHNIQUE_MODEL") or _TECHNIQUE_MODEL,
        reasoning_effort=os.getenv("CLEARWAY_TECHNIQUE_EFFORT") or _TECHNIQUE_EFFORT,
    )


def _usage_from_responses(response: object, latency_ms: float) -> LLMUsage:
    """Pull tokens + cost off a LiteLLM Responses object. The Responses usage shape uses
    `input_tokens` / `output_tokens` (not `prompt` / `completion`). Cost is best-effort — swallow to
    `None` if LiteLLM cannot price the snapshot rather than crash a run over telemetry."""
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "input_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None)
    try:
        import litellm

        cost_usd: float | None = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 — pricing is best-effort telemetry
        cost_usd = None
    return LLMUsage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd, latency_ms=latency_ms)
