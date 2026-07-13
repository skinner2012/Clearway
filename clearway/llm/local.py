"""The local chat client: an Ollama model via LiteLLM, structured output at temperature 0.

Two provider details this gets right that a naive `litellm.completion(...)` would not:
1. Ollama chat models need the `ollama_chat/` prefix; plain `ollama/` silently drops structured
   output and returns markdown (verified against gemma4/qwen). `response_format` + an explicit
   prompt (exact enum values, decimal confidence) yields strict-schema JSON.
2. Usage is best-effort telemetry, pulled defensively — never worth crashing a run over.
"""

from __future__ import annotations

import os
import time

from pydantic import BaseModel

from clearway.llm.client import Completion, LLMUsage

_DEFAULT_MODEL = "gemma4:31b"
_DEFAULT_BASE_URL = "http://localhost:11434"


class LocalLLMClient:
    """Real chat client: an Ollama model via LiteLLM, structured output at temperature 0."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model: str = model or os.getenv("CLEARWAY_CHAT_MODEL") or _DEFAULT_MODEL
        self._base_url: str = base_url or os.getenv("CLEARWAY_OLLAMA_BASE_URL") or _DEFAULT_BASE_URL

    @property
    def model(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> Completion:
        import litellm

        start = time.perf_counter()
        response = litellm.completion(
            model=f"ollama_chat/{self._model}",  # ollama_chat/, NOT ollama/ — see module docstring
            api_base=self._base_url,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        content: str = response.choices[0].message.content or ""
        return Completion(content, _usage_from(response, latency_ms))


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
