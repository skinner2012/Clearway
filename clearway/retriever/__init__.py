"""Retriever: `Finding` → `Citation[]`.

`Retriever` (rag.py) is the real RAG retriever the production spine uses (M1). The canned
retriever was retired to a test double (`tests/stubs.py`) once real retrieval landed.
"""

from clearway.retriever.rag import Retriever

__all__ = ["Retriever"]
