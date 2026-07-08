"""The real RAG retriever (M1) — replaces the M0 canned stub in the production spine.

A `Retriever` holds the embedder + store + frozen `corpus_version` once and answers per-finding:
build a query from the finding's rule + help text → embed it (`search_query:` prefix) → vector
search the frozen corpus in pgvector → map the nearest chunks to `Citation`s. Deterministic on a
frozen corpus (deterministic embed + stable `<=>` order), so two runs retrieve identically.

The M0 stub (`stub.py`) survives as the *offline test double* for the orchestrator spine — a
hash-based `FakeEmbedder` can exercise these mechanics but cannot reproduce semantic retrieval,
so the spine's exit-criterion tests inject the canned-correct stub instead of a fake corpus.
"""

from __future__ import annotations

from clearway.corpus.embed import Embedder
from clearway.corpus.store import CorpusStore
from clearway.schemas.models import Citation, CorpusChunk, Finding

# Top-k nearest chunks to pull per finding. Small enough to stay tight, large enough that the
# axe-tag-implied SC lands in the set (the acceptance sanity-check). Overridable per Retriever.
_DEFAULT_K = 5


class Retriever:
    """Real RAG retrieval: `Finding` → embedded query → pgvector search → `Citation[]`.

    `k` is a constructor knob (default `_DEFAULT_K`) so the retrieval width is a one-line change.
    """

    def __init__(self, embedder: Embedder, store: CorpusStore, corpus_version: str, k: int = _DEFAULT_K) -> None:
        self._embedder = embedder
        self._store = store
        self._corpus_version = corpus_version
        self._k = k

    def retrieve(self, finding: Finding) -> list[Citation]:
        """Retrieve the top-k grounding SCs for a finding, nearest-first, as `Citation`s."""
        embedding = self._embedder.embed_query(self._query_text(finding))
        chunks = self._store.query(embedding, k=self._k, corpus_version=self._corpus_version)
        return _chunks_to_citations(chunks)

    @staticmethod
    def _query_text(finding: Finding) -> str:
        """Compose the search query: the axe rule id + its human-readable help is the strongest
        signal for the SC that governs the rule (e.g. 'image-alt Images must have alt text')."""
        return f"{finding.rule_id} {finding.help}".strip()


def _chunks_to_citations(chunks: list[CorpusChunk]) -> list[Citation]:
    """Map retrieved chunks to citations: one `Citation` per SC id across the top-k, deduped,
    nearest-first order preserved.

    `title`/`level` are left empty in M1 (option A): the corpus persists neither as a structured
    field — the SC handle is baked into the chunk text — and neither is needed to ground or
    validate a citation. `sc_id` + `source` + `url` are; `technique_id` stays None until the
    Techniques corpus is ingested.
    """
    citations: list[Citation] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sc_id in chunk.sc_ids:
            if sc_id in seen:
                continue
            seen.add(sc_id)
            citations.append(Citation(sc_id=sc_id, source=chunk.source, url=chunk.url))
    return citations
