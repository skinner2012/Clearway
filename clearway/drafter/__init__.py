"""Drafter: `Finding` + `Citation[]` → `DraftRow`.

`Drafter` (llm.py) is the real LLM drafter the production spine uses (M1). `draft` (stub.py) is
the canned implementation the spine currently still runs on — the cutover to the real drafter
(and stub's retirement to a test double) lands in the following changes.
"""

from clearway.drafter.llm import Drafter, FakeLLMClient, LiteLLMClient, LLMClient
from clearway.drafter.stub import draft

__all__ = ["Drafter", "FakeLLMClient", "LLMClient", "LiteLLMClient", "draft"]
