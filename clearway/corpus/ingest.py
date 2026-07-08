"""Ingest orchestration: chunks → embed → upsert, under a frozen `corpus_version`.

`corpus_version` encodes the **embedding model + dimension** (CONTRACTS: it "encodes the
embedding model + dimension"). That is deliberate: the embedder is welded to the corpus, so
a full re-embed is triggered *only* by changing the model/dim (a new version), while adding
*more* sources under the same model is an incremental upsert into the same version — no
re-embed of existing chunks. `REV` bumps only for a deliberate rebuild (e.g. a chunking-strategy
change) that should not mix with existing vectors.
"""

from __future__ import annotations

from clearway.corpus.embed import Embedder
from clearway.corpus.store import CorpusStore
from clearway.schemas.models import CorpusChunk

# Bump only for a deliberate rebuild under the same embedding model (e.g. a chunking change).
REV = 1


def build_corpus_version(embedder: Embedder, rev: int = REV) -> str:
    """`wcag22-<model>-<dim>@<rev>` — the frozen id that scopes every stored/queried vector."""
    model_slug = embedder.model.replace(":", "-").replace("/", "-")
    return f"wcag22-{model_slug}-{embedder.dim}@{rev}"


def ingest(chunks: list[CorpusChunk], embedder: Embedder, store: CorpusStore) -> int:
    """Embed the chunks' text and upsert them; returns the number stored.

    Chunks arrive without embeddings (the parser doesn't embed); we compute the document
    vectors here and attach them just before persisting.
    """
    store.ensure_schema(embedder.dim)
    if not chunks:
        return 0
    vectors = embedder.embed_documents([chunk.text for chunk in chunks])
    embedded = [chunk.model_copy(update={"embedding": vector}) for chunk, vector in zip(chunks, vectors, strict=True)]
    return store.upsert(embedded)
