"""The local chat client: an Ollama model via LiteLLM, structured output at temperature 0.

Three provider details this gets right that a naive `litellm.completion(...)` would not:
1. Ollama chat models need the `ollama_chat/` prefix; plain `ollama/` silently drops structured
   output and returns markdown (verified against gemma4/qwen). `response_format` + an explicit
   prompt (exact enum values, decimal confidence) yields strict-schema JSON.
2. Usage is best-effort telemetry, pulled defensively — never worth crashing a run over.
3. **Every request is bounded by a timeout.** Without one a lost response blocks forever: the
   server accepts the request, never dispatches it, and the client sits in `recv()` with no error,
   no log line and no end. Observed on a long acceptance sweep — the pass stopped for hours and
   looked identical to slow drafting, because a stalled call and a slow call are the same thing to
   a caller that cannot time out. A bound converts that into a raised exception, which the
   per-case checkpoint already knows how to resume from. The default is deliberately generous: a
   real draft on the longest prompt runs a few minutes, so this fires only on a stall, never on
   honest slowness.

The timeout bounds *waiting*, not sampling, so it cannot change what a reachable model returns —
at `temperature=0` a draft made with it is byte-identical to one made without.

A picture, when one is attached
------------------------------
The user message becomes an OpenAI-shaped content-part list — the text part first, then the image as
a `data:` URI — which LiteLLM translates for the provider. Two properties this keeps:

* **No picture, no change.** With `image=None` the content is the same plain string it always was, so
  every existing call is byte-identical on the wire to the one it made before this channel existed.
* **The text never mentions the picture.** The image is a part beside the prompt, not a sentence
  inside it, so two requests can differ in pixels alone — the premise the image experiment's
  statistic is defined over, and the reason the model is never told to look.

That this provider carries an image part, a `response_format` schema and the model's own thinking in
ONE request was measured before anything was built (`benchmark/reports/multimodal_transport_probe.json`)
— it is not assumed, because the sibling `ollama/` prefix drops structured output silently and a
dropped image part would be invisible in exactly the same way.
"""

from __future__ import annotations

import os
import time
from typing import Any

from pydantic import BaseModel

from clearway.llm.client import Completion, ImagePart, LLMUsage

_DEFAULT_MODEL = "gemma4:31b"
_DEFAULT_BASE_URL = "http://localhost:11434"
# Seconds to wait for one completion before giving up. Far above the slowest observed real draft
# (~3 min on the longest injected prompt) so it never truncates honest work, and far below the
# unbounded wait it replaces.
_DEFAULT_TIMEOUT_S = 900.0


class LocalLLMClient:
    """Real chat client: an Ollama model via LiteLLM, structured output at temperature 0."""

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout_s: float | None = None) -> None:
        self._model: str = model or os.getenv("CLEARWAY_CHAT_MODEL") or _DEFAULT_MODEL
        self._base_url: str = base_url or os.getenv("CLEARWAY_OLLAMA_BASE_URL") or _DEFAULT_BASE_URL
        self._timeout_s: float = timeout_s or float(os.getenv("CLEARWAY_CHAT_TIMEOUT_S") or _DEFAULT_TIMEOUT_S)

    @property
    def model(self) -> str:
        return self._model

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        import litellm

        start = time.perf_counter()
        response = litellm.completion(
            model=f"ollama_chat/{self._model}",  # ollama_chat/, NOT ollama/ — see module docstring
            api_base=self._base_url,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": _user_content(user, image)}],
            response_format=schema,
            temperature=0.0,
            timeout=self._timeout_s,  # bounds waiting only — see module docstring
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        content: str = response.choices[0].message.content or ""
        return Completion(content, _usage_from(response, latency_ms))


def _user_content(user: str, image: ImagePart | None) -> str | list[dict[str, Any]]:
    """The user message: the plain string when nothing is attached, the two-part content list when a
    picture is.

    The string branch is not an optimisation — it is the guarantee that a call attaching no picture
    sends exactly what it sent before this parameter existed, so no already-frozen run becomes
    unreproducible. The text part carries the prompt unchanged; the picture is a sibling part.
    """
    if image is None:
        return user
    return [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image.data_url()}}]


def _usage_from(response: object, latency_ms: float) -> LLMUsage:
    """Pull tokens + cost off a LiteLLM chat `ModelResponse`, defensively — usage is best-effort
    telemetry, never worth crashing a run over. `completion_cost` is ~0 for local Ollama and may
    raise for models it can't price; we swallow that to 0.0 (the call did happen)."""
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", None)
    tokens_out = getattr(usage, "completion_tokens", None)
    try:
        import litellm

        cost_usd: float | None = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 — pricing is best-effort; a local model reports ~0 anyway
        cost_usd = 0.0
    return LLMUsage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd, latency_ms=latency_ms)
