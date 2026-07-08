"""Retriever: `Finding` → `Citation[]`.

`Retriever` (rag.py) is the real RAG retriever the production spine uses (M1). `retrieve`
(stub.py) is the canned implementation the spine currently still runs on — the cutover to
the real retriever (and stub's retirement to a test double) lands in the next change.
"""

from clearway.retriever.rag import Retriever
from clearway.retriever.stub import retrieve

__all__ = ["Retriever", "retrieve"]
