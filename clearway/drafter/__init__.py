"""Drafter: `Finding` + `Citation[]` → `DraftRow`.

`Drafter` (llm.py) is the real LLM drafter the production spine uses; its model call goes through
the shared gateway (`clearway.llm`). The canned drafter was retired to a test double
(`tests/stubs.py`) once real drafting landed.
"""

from clearway.drafter.llm import FALLBACK_REMEDIATION, Drafter, DraftResult, is_fallback_draft

__all__ = [
    "FALLBACK_REMEDIATION",
    "DraftResult",
    "Drafter",
    "is_fallback_draft",
]
