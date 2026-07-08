"""The `Embedder` seam — turns text into dense vectors for the corpus/retriever.

The real embedder routes **nomic-embed-text** through LiteLLM → Ollama (ARCHITECTURE §4.4):
provider-agnostic, so swapping to a cloud embedder later is a config change, not a code
change. The embedding model + dimension are *welded to the corpus* — they define the
`corpus_version`, and switching them means a full re-embed under a new version.

Two things this seam gets right that a naive `litellm.embedding(...)` call would not:
1. **Task prefixes.** nomic requires `search_document:` on stored chunks and `search_query:`
   on queries; mixing them up quietly degrades retrieval. `embed_documents` / `embed_query`
   make that distinction unforgeable at the call site.
2. **Testability.** Unit tests use `FakeEmbedder` (deterministic, offline); only the gated
   integration test touches the real model.
"""

from __future__ import annotations

import hashlib
import os
import struct
from typing import Protocol, runtime_checkable

# nomic-embed-text is 768-dim (verified against the running model before pinning). pgvector's
# column is `vector(EMBED_DIM)`, so this constant and the DDL must move together.
EMBED_DIM = 768

_DEFAULT_MODEL = "nomic-embed-text"
_DEFAULT_BASE_URL = "http://localhost:11434"

# nomic's required task prefixes (asymmetric retrieval): documents and queries are embedded
# under different instructions so a query vector lands near the documents that answer it.
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


@runtime_checkable
class Embedder(Protocol):
    """The seam corpus/ and retriever/ depend on. Real (LiteLLM→Ollama) or fake (tests)."""

    @property
    def model(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus chunks for storage (applies the document task prefix)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query (applies the query task prefix)."""
        ...


class LiteLLMEmbedder:
    """Real embedder: nomic-embed-text via LiteLLM → Ollama."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model: str = model or os.getenv("CLEARWAY_EMBED_MODEL") or _DEFAULT_MODEL
        self._base_url: str = base_url or os.getenv("CLEARWAY_OLLAMA_BASE_URL") or _DEFAULT_BASE_URL

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return EMBED_DIM

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        import litellm

        response = litellm.embedding(model=f"ollama/{self._model}", input=inputs, api_base=self._base_url)
        return [list(item["embedding"]) for item in response.data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed([_DOC_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([_QUERY_PREFIX + text])[0]


class FakeEmbedder:
    """Deterministic offline embedder for unit tests: same text → same vector, never a network
    call. It is NOT semantically meaningful — retrieval *quality* is proven by the gated
    integration test against the real model; the fake only exercises pipeline mechanics
    (identical text embeds identically, so an exact-text query retrieves its own chunk)."""

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self._dim = dim

    @property
    def model(self) -> str:
        return "fake-embedder"

    @property
    def dim(self) -> int:
        return self._dim

    def _vector(self, text: str) -> list[float]:
        # Expand a hash of the text into `dim` deterministic floats in [-1, 1].
        out: list[float] = []
        counter = 0
        while len(out) < self._dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            for i in range(0, len(digest), 4):
                (word,) = struct.unpack("<I", digest[i : i + 4])
                out.append((word / 0xFFFFFFFF) * 2.0 - 1.0)
                if len(out) >= self._dim:
                    break
            counter += 1
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(_DOC_PREFIX + t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(_QUERY_PREFIX + text)
