"""Corpus: WCAG sources → chunk → embed → pgvector (ARCHITECTURE §6, M1). The RAG grounding
that retriever/ queries. See `CorpusChunk` in CONTRACTS §3 for the stored shape."""

from clearway.corpus.embed import EMBED_DIM, Embedder, FakeEmbedder, LiteLLMEmbedder
from clearway.corpus.ingest import REV, build_corpus_version, ingest
from clearway.corpus.store import CorpusStore, InMemoryCorpusStore, PgCorpusStore
from clearway.corpus.wcag import WCAG_JSON_URL, fetch_wcag_json, parse_wcag_json

__all__ = [
    "EMBED_DIM",
    "REV",
    "WCAG_JSON_URL",
    "CorpusStore",
    "Embedder",
    "FakeEmbedder",
    "InMemoryCorpusStore",
    "LiteLLMEmbedder",
    "PgCorpusStore",
    "build_corpus_version",
    "fetch_wcag_json",
    "ingest",
    "parse_wcag_json",
]
