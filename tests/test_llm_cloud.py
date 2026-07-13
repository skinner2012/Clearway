"""The cloud reference client — offline config + a gated live structured-output check.

Two layers, mirroring the other client seams:
- **offline** (default): model/effort resolve from args → env → code default, no network.
- **gated** (`openai_up`): a real `/v1/responses` call returns strict-schema JSON with usage. Skips
  when OPENAI_API_KEY is absent from the process environment (`.env` is not auto-loaded).
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, ConfigDict, Field

from clearway.llm import CloudLLMClient


def test_model_and_effort_resolve_from_args() -> None:
    client = CloudLLMClient(model="some-model", reasoning_effort="high")
    assert client.model == "some-model"
    assert client.reasoning_effort == "high"


def test_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLEARWAY_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("CLEARWAY_JUDGE_EFFORT", raising=False)
    client = CloudLLMClient()
    assert client.model == "gpt-5.6-luna"
    assert client.reasoning_effort == "medium"


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEARWAY_JUDGE_MODEL", "gpt-from-env")
    monkeypatch.setenv("CLEARWAY_JUDGE_EFFORT", "low")
    client = CloudLLMClient()
    assert client.model == "gpt-from-env"
    assert client.reasoning_effort == "low"


# --- gated integration: real OpenAI Responses API ----------------------------


class _Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")  # -> additionalProperties:false, required for strict mode

    verdict: bool = Field(..., description="true if 2 + 2 equals 4")
    rationale: str = Field(..., description="one short sentence")


openai_up = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set in the environment")


@openai_up
def test_cloud_client_returns_strict_schema_json() -> None:
    """The real Responses path returns JSON that satisfies the supplied Pydantic schema, and usage
    is captured off the Responses shape (input_tokens/output_tokens)."""
    completion = CloudLLMClient().complete_json(
        system="You are a precise grader. Output only the JSON object.",
        user="Is 2 + 2 = 4? Give your verdict and a one-sentence rationale.",
        schema=_Probe,
    )
    parsed = _Probe.model_validate_json(completion.content)  # strict-schema JSON parses cleanly
    assert parsed.verdict is True
    assert parsed.rationale
    assert completion.usage.tokens_in and completion.usage.tokens_out  # usage captured, not discarded
