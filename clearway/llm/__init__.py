"""Shared LLM gateway: the provider-agnostic client seam and its concrete clients.

`ARCHITECTURE.md` §6 reserves this module as the LiteLLM gateway. Everything that calls a model
(drafter, judge) depends on the `LLMClient` seam here, never on a provider directly; frozen
routing across models lands later.
"""

from clearway.llm.client import Completion, FakeLLMClient, LLMClient, LLMUsage
from clearway.llm.local import LocalLLMClient

__all__ = [
    "Completion",
    "FakeLLMClient",
    "LLMClient",
    "LLMUsage",
    "LocalLLMClient",
]
