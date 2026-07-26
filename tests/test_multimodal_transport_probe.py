"""Guard for the frozen multimodal transport receipt.

The receipt answers one question that no code in this repo can answer offline: does the provider
layer carry an image part, a `response_format` schema and the model's own thinking in ONE request?
It was established by a real call and frozen, so what is checked here is that the answer still
belongs to the model the client actually uses — a drafter model swapped without re-probing would
otherwise inherit a "yes" that was never established for it.

No model call. Re-establish the receipt with `uv run python scripts/probe_multimodal_litellm.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from clearway.drafter.llm import _LLMDraft
from clearway.llm.local import _DEFAULT_MODEL

RECEIPT = json.loads(
    (Path(__file__).resolve().parent.parent / "benchmark" / "reports" / "multimodal_transport_probe.json").read_text()
)


def test_the_provider_returned_schema_valid_json_for_a_multimodal_request() -> None:
    assert RECEIPT["schema_valid_json_returned"] is True
    assert RECEIPT["validation_error"] is None
    # the real drafter schema, and a body that satisfies it — not a hand-written probe shape
    assert RECEIPT["schema"] == _LLMDraft.__name__
    assert _LLMDraft.model_validate(RECEIPT["parsed"])


def test_the_probe_ran_on_the_model_the_client_uses() -> None:
    assert RECEIPT["model"] == _DEFAULT_MODEL
    assert RECEIPT["provider_prefix"] == "ollama_chat/"  # `ollama/` silently drops structured output
    assert RECEIPT["temperature"] == 0.0
    assert RECEIPT["model_digest"], "the served digest is the provenance link to the runs before this"


def test_the_receipt_declares_what_it_spent_and_what_it_sent() -> None:
    """A model call that leaves no artifact is the easiest kind to lose from a run count, so the
    receipt states its own spend — including the attempt whose response was thrown away."""
    assert RECEIPT["model_calls_spent"] == 2
    assert RECEIPT["image"]["media_type"] == "image/png"
    assert RECEIPT["image"]["bytes"] > 0 and RECEIPT["image"]["sha256"]
    # thinking came back in the same response and did not displace the structured content
    assert RECEIPT["reasoning_returned"] is True
