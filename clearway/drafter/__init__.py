"""Drafter: `Finding` + `Citation[]` → `DraftRow`.

`Drafter` (llm.py) is the real LLM drafter the production spine uses (M1). The canned drafter was
retired to a test double (`tests/stubs.py`) once real drafting landed.
"""

from clearway.drafter.llm import Drafter, FakeLLMClient, LiteLLMClient, LLMClient

__all__ = ["Drafter", "FakeLLMClient", "LLMClient", "LiteLLMClient"]
