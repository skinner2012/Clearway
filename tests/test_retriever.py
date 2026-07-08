"""T2 acceptance: the real RAG `Retriever` maps a `Finding` to grounding `Citation`s.

Two layers, mirroring the corpus seam design:
- **offline** (default): drive the `Retriever` with `FakeEmbedder` + `InMemoryCorpusStore` to
  prove the *mechanics* — query composition, chunk→Citation mapping (option A: title/level
  empty), dedup by SC, the `k` knob, and determinism. No network, no DB, no Ollama.
- **gated** (`corpus_up`): the real path — `LiteLLMEmbedder` (Ollama) + `PgCorpusStore` — proves
  *retrieval quality*: an axe-detectable finding (`image-alt`) retrieves the SC its axe tag
  implies (1.1.1), the sanity-check against the oracle. Skips cleanly when the stack is down.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from clearway.corpus import (
    FakeEmbedder,
    InMemoryCorpusStore,
    LiteLLMEmbedder,
    PgCorpusStore,
    build_corpus_version,
    ingest,
    parse_wcag_json,
)
from clearway.retriever import Retriever
from clearway.retriever.rag import _DEFAULT_K
from clearway.schemas.models import Citation, CorpusChunk, Finding

SAMPLE = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "corpus" / "wcag_sample.json"
_VERSION = "test@1"


def _finding(rule_id: str, help_text: str = "") -> Finding:
    return Finding(id=f"h:{rule_id}", source_url="file://home.html", rule_id=rule_id, target="x", help=help_text)


def _chunk(chunk_id: str, sc_ids: list[str], *, source: str = "WCAG-SC", url: str = "") -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id, sc_ids=sc_ids, text=f"text for {chunk_id}", source=source, url=url, corpus_version=_VERSION
    )


def _seed(*chunks: CorpusChunk) -> tuple[FakeEmbedder, InMemoryCorpusStore]:
    """Embed + upsert chunks into an in-memory store under `_VERSION`, returning the seam pair."""
    embedder = FakeEmbedder()
    store = InMemoryCorpusStore()
    ingest(list(chunks), embedder, store)
    return embedder, store


# --- real Retriever mechanics (offline: FakeEmbedder + InMemoryCorpusStore) --


def test_maps_chunk_fields_and_leaves_title_level_empty() -> None:
    embedder, store = _seed(_chunk("sc:1.1.1", ["1.1.1"], url="https://www.w3.org/TR/WCAG22/#non-text-content"))
    (citation,) = Retriever(embedder, store, _VERSION, k=1).retrieve(_finding("image-alt"))
    assert isinstance(citation, Citation)
    assert citation.sc_id == "1.1.1"
    assert citation.source == "WCAG-SC"
    assert citation.url == "https://www.w3.org/TR/WCAG22/#non-text-content"
    # option A: the corpus persists neither title nor level as a structured field.
    assert citation.title == ""
    assert citation.level is None
    assert citation.technique_id is None


def test_dedups_to_one_citation_per_sc_across_chunks() -> None:
    # two chunks grounding the same SC (e.g. an SC chunk + a technique chunk) → one citation.
    embedder, store = _seed(_chunk("sc:1.1.1", ["1.1.1"]), _chunk("tech:H37", ["1.1.1"], source="Technique"))
    citations = Retriever(embedder, store, _VERSION, k=5).retrieve(_finding("image-alt"))
    assert [c.sc_id for c in citations] == ["1.1.1"]


def test_k_bounds_the_number_of_chunks_pulled() -> None:
    embedder, store = _seed(_chunk("sc:1.1.1", ["1.1.1"]), _chunk("sc:1.4.3", ["1.4.3"]), _chunk("sc:3.1.1", ["3.1.1"]))
    citations = Retriever(embedder, store, _VERSION, k=2).retrieve(_finding("image-alt"))
    assert len(citations) == 2  # one SC per chunk, capped at k
    assert _DEFAULT_K == 5  # the documented default knob


def test_query_composes_rule_id_and_help() -> None:
    seen: list[str] = []

    class SpyEmbedder(FakeEmbedder):
        def embed_query(self, text: str) -> list[float]:
            seen.append(text)
            return super().embed_query(text)

    store = InMemoryCorpusStore()
    ingest([_chunk("sc:1.1.1", ["1.1.1"])], (embedder := SpyEmbedder()), store)
    Retriever(embedder, store, _VERSION).retrieve(_finding("image-alt", "Images must have alternate text"))
    assert seen == ["image-alt Images must have alternate text"]


def test_deterministic_across_runs_on_frozen_corpus() -> None:
    embedder, store = _seed(_chunk("sc:1.1.1", ["1.1.1"]), _chunk("sc:1.4.3", ["1.4.3"]))
    retriever = Retriever(embedder, store, _VERSION, k=2)
    finding = _finding("color-contrast", "Elements must meet minimum contrast")
    assert [c.sc_id for c in retriever.retrieve(finding)] == [c.sc_id for c in retriever.retrieve(finding)]


def test_empty_corpus_returns_no_citations() -> None:
    embedder = FakeEmbedder()
    store = InMemoryCorpusStore()
    store.ensure_schema(embedder.dim)
    assert Retriever(embedder, store, _VERSION).retrieve(_finding("image-alt")) == []


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
def test_real_retriever_grounds_image_alt_in_sc_1_1_1() -> None:
    """The T2 acceptance sanity-check: an axe-detectable finding retrieves the SC its axe tag
    implies. `image-alt` → SC 1.1.1 must be in the top-k. Runs under a throwaway corpus_version
    (ingesting the committed sample) so it never disturbs a real ingested corpus."""
    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    version = build_corpus_version(embedder) + "-pytest-t2"
    chunks = parse_wcag_json(json.loads(SAMPLE.read_text()), corpus_version=version)

    try:
        ingest(chunks, embedder, store)
        finding = _finding("image-alt", "Images must have an alternate text")
        citations = Retriever(embedder, store, version).retrieve(finding)
        assert "1.1.1" in [c.sc_id for c in citations]
    finally:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", autocommit=True) as conn:
            conn.execute("DELETE FROM corpus_chunk WHERE corpus_version = %s", (version,))
