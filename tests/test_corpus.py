"""T1 acceptance: WCAG corpus ingestion → pgvector, and vector retrieval.

Two layers, mirroring the seam design:
- **offline** (default): parse a committed WCAG JSON excerpt, then run the full
  chunk → embed → upsert → query pipeline with `FakeEmbedder` + `InMemoryCorpusStore`.
  No network, no DB, no Ollama — proves the *mechanics*.
- **gated** (`corpus_up`): the real path — `LiteLLMEmbedder` (Ollama) + `PgCorpusStore`
  (Postgres/pgvector). Proves *retrieval quality*: the documented acceptance query
  "images need a text alternative" retrieves SC 1.1.1. Skips cleanly when either the DB
  or Ollama is down, so the offline suite stays green.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from clearway.corpus import (
    EMBED_DIM,
    FakeEmbedder,
    InMemoryCorpusStore,
    LiteLLMEmbedder,
    PgCorpusStore,
    build_corpus_version,
    ingest,
    parse_wcag_json,
)

SAMPLE = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "corpus" / "wcag_sample.json"


def _sample() -> dict:
    return json.loads(SAMPLE.read_text())


# --- parser / chunker (offline) ----------------------------------------------


def test_parse_yields_one_chunk_per_sc_with_grounding_metadata() -> None:
    chunks = parse_wcag_json(_sample(), corpus_version="test@1")
    by_id = {c.chunk_id: c for c in chunks}
    # 4.1.1 (obsoleted in 2.2, versions without "2.2") is filtered out — corpus stays at the
    # 86-SC reference set the oracle's L0 uses; only 2.2-applicable SCs remain.
    assert set(by_id) == {"sc:1.1.1", "sc:1.4.3"}
    assert "sc:4.1.1" not in by_id

    non_text = by_id["sc:1.1.1"]
    assert non_text.sc_ids == ["1.1.1"]  # the exact grounding key
    assert non_text.source == "WCAG-SC"
    assert non_text.url == "https://www.w3.org/TR/WCAG22/#non-text-content"
    assert non_text.corpus_version == "test@1"
    assert non_text.embedding is None  # parser does not embed


def test_chunk_text_has_handle_and_is_stripped_of_html() -> None:
    (non_text,) = [c for c in parse_wcag_json(_sample(), corpus_version="v") if c.chunk_id == "sc:1.1.1"]
    assert non_text.text.startswith("Non-text Content.")
    assert "<" not in non_text.text and ">" not in non_text.text  # HTML removed
    assert "text alternative" in non_text.text  # normative body preserved


# --- corpus_version (offline) ------------------------------------------------


def test_corpus_version_encodes_model_and_dim() -> None:
    version = build_corpus_version(FakeEmbedder())
    assert version == f"wcag22-fake-embedder-{EMBED_DIM}@1"


# --- FakeEmbedder (offline) --------------------------------------------------


def test_fake_embedder_is_deterministic_and_right_dimension() -> None:
    embedder = FakeEmbedder()
    a = embedder.embed_documents(["images need a text alternative"])[0]
    b = embedder.embed_documents(["images need a text alternative"])[0]
    assert len(a) == EMBED_DIM
    assert a == b  # same text → same vector
    # doc and query prefixes differ, so the same core text embeds differently
    assert embedder.embed_query("images need a text alternative") != a


# --- ingest pipeline (offline: FakeEmbedder + InMemoryCorpusStore) -----------


def test_ingest_pipeline_stores_and_scopes_by_corpus_version() -> None:
    embedder = FakeEmbedder()
    store = InMemoryCorpusStore()
    version = build_corpus_version(embedder)
    chunks = parse_wcag_json(_sample(), corpus_version=version)

    stored = ingest(chunks, embedder, store)
    assert stored == 2
    assert store.count(version) == 2
    assert store.count("some-other-version") == 0  # queries never leak across versions

    hits = store.query(embedder.embed_query("contrast"), k=1, corpus_version=version)
    assert len(hits) == 1
    assert hits[0].embedding is None  # the vector is not carried back to the caller
    # determinism: identical query → identical ordering on a frozen corpus
    again = store.query(embedder.embed_query("contrast"), k=2, corpus_version=version)
    assert [h.chunk_id for h in store.query(embedder.embed_query("contrast"), k=2, corpus_version=version)] == [
        h.chunk_id for h in again
    ]


def test_upsert_rejects_unembedded_chunks() -> None:
    store = InMemoryCorpusStore()
    chunks = parse_wcag_json(_sample(), corpus_version="v")  # embedding is None
    with pytest.raises(ValueError, match="no embedding"):
        store.upsert(chunks)


# --- gated integration: real Ollama + real pgvector --------------------------


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def _postgres_up() -> bool:
    try:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", connect_timeout=1):
            return True
    except Exception:
        return False


corpus_up = pytest.mark.skipif(
    not (_ollama_up() and _postgres_up()),
    reason="corpus stack not running (need Ollama + `docker compose up -d postgres`)",
)


@corpus_up
def test_real_ingest_and_retrieval_finds_1_1_1() -> None:
    """The documented acceptance: a known query retrieves SC 1.1.1's chunk, deterministically,
    from the real pgvector store using real nomic embeddings. Runs under a throwaway
    corpus_version so it never disturbs a real ingested corpus."""
    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    version = build_corpus_version(embedder) + "-pytest"
    chunks = parse_wcag_json(_sample(), corpus_version=version)

    try:
        assert ingest(chunks, embedder, store) == 2
        hits = store.query(embedder.embed_query("images need a text alternative"), k=1, corpus_version=version)
        assert hits and hits[0].sc_ids == ["1.1.1"]
    finally:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", autocommit=True) as conn:
            conn.execute("DELETE FROM corpus_chunk WHERE corpus_version = %s", (version,))
