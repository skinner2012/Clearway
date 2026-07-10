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
from clearway.corpus.store import CorpusStore, ScMeta
from clearway.schemas.models import Citation, CorpusChunk, EvidenceQuery, Finding

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
        self._sc_meta: dict[str, ScMeta] | None = None  # loaded once, lazily (below)

    @property
    def corpus_version(self) -> str:
        """The frozen corpus this retriever serves — the MCP server pins/reports it."""
        return self._corpus_version

    def retrieve(self, finding: Finding) -> list[Citation]:
        """Retrieve the top-k grounding SCs for a finding, nearest-first, as `Citation`s."""
        return self._retrieve_text(self._query_text(finding))

    def retrieve_query(self, query: EvidenceQuery) -> list[Citation]:
        """Retrieve grounding SCs for a reuse-shaped `EvidenceQuery` — the entry point the MCP
        tool calls. Composes the same query text as `retrieve(finding)` (rule_id + problem text),
        so a `Finding` and its lossless `EvidenceQuery` retrieve identically; the RAG core below
        is shared and unchanged."""
        return self._retrieve_text(f"{query.rule_id} {query.description}".strip())

    def _retrieve_text(self, text: str) -> list[Citation]:
        """The shared RAG core: embed the composed query → vector-search the frozen corpus →
        map the nearest chunks to `Citation`s. Both `retrieve` and `retrieve_query` funnel here."""
        embedding = self._embedder.embed_query(text)
        chunks = self._store.query(embedding, k=self._k, corpus_version=self._corpus_version)
        return _chunks_to_citations(chunks, self._sc_meta_map())

    def _sc_meta_map(self) -> dict[str, ScMeta]:
        """The SC-id → metadata join table for this corpus_version, fetched once and cached —
        the corpus is frozen, so one lookup serves every finding (no query per retrieve)."""
        if self._sc_meta is None:
            self._sc_meta = self._store.sc_meta(self._corpus_version)
        return self._sc_meta

    @staticmethod
    def _query_text(finding: Finding) -> str:
        """Compose the search query: the axe rule id + its human-readable help is the strongest
        signal for the SC that governs the rule (e.g. 'image-alt Images must have alt text')."""
        return f"{finding.rule_id} {finding.help}".strip()


def build_default_retriever() -> Retriever:
    """Construct the production RAG retriever: real embedder (LiteLLM → Ollama) + pgvector store,
    frozen at the current `corpus_version`. The single builder the orchestrator's default retrieve
    step and the MCP server both call, so in-process and over-MCP retrieval are identical (same
    embedder, same corpus_version). The corpus stack is imported lazily so it's required only when
    a caller actually retrieves."""
    from clearway.corpus import LiteLLMEmbedder, PgCorpusStore, build_corpus_version

    embedder = LiteLLMEmbedder()
    return Retriever(embedder, PgCorpusStore(), build_corpus_version(embedder))


def _chunks_to_citations(chunks: list[CorpusChunk], sc_meta: dict[str, ScMeta]) -> list[Citation]:
    """Map retrieved chunks to citations: one `Citation` per SC id across the top-k, deduped,
    nearest-first order preserved.

    `title`/`level` are joined in from the corpus's `sc_meta` reference table (T1); an SC absent
    from it degrades to empty title / `None` level rather than failing. `sc_id` + `source` + `url`
    come from the chunk; `technique_id` stays None until the Techniques corpus is ingested.
    """
    citations: list[Citation] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sc_id in chunk.sc_ids:
            if sc_id in seen:
                continue
            seen.add(sc_id)
            meta = sc_meta.get(sc_id)
            citations.append(
                Citation(
                    sc_id=sc_id,
                    title=meta.title if meta else "",
                    level=meta.level if meta else None,
                    source=chunk.source,
                    url=chunk.url,
                )
            )
    return citations
