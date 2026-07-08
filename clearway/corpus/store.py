"""The `CorpusStore` seam — persists embedded `CorpusChunk`s and answers vector queries.

`PgCorpusStore` is the real store (Postgres + pgvector, ARCHITECTURE §4.1); `InMemoryCorpusStore`
is its offline stand-in for unit tests. Both are keyed by `(corpus_version, chunk_id)` so
multiple corpus builds can coexist and a query is always scoped to one frozen version —
retrieval must never mix vectors from different embedding regimes.
"""

from __future__ import annotations

import math
import os
from typing import Protocol, runtime_checkable

from clearway.schemas.models import CorpusChunk

_DEFAULT_DB_URL = "postgresql://clearway:clearway@localhost:5432/clearway"
_TABLE = "corpus_chunk"


@runtime_checkable
class CorpusStore(Protocol):
    """The seam corpus/ (write) and retriever/ (read) depend on."""

    def ensure_schema(self, dim: int) -> None:
        """Create the extension + table + index if absent (idempotent)."""
        ...

    def upsert(self, chunks: list[CorpusChunk]) -> int:
        """Insert/replace embedded chunks (by (corpus_version, chunk_id)); return the count."""
        ...

    def query(self, embedding: list[float], k: int, corpus_version: str) -> list[CorpusChunk]:
        """Top-k nearest chunks (cosine) within one corpus_version, closest first."""
        ...

    def count(self, corpus_version: str) -> int:
        """How many chunks are stored under a corpus_version."""
        ...


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - cosine similarity — matches pgvector's `<=>` operator so the fake orders like the DB."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - dot / (na * nb)


class InMemoryCorpusStore:
    """Offline stand-in for `PgCorpusStore`: a dict keyed by (corpus_version, chunk_id) with
    a pure-Python cosine search. Exercises the ingestion + query *mechanics* without a DB."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], tuple[CorpusChunk, list[float]]] = {}

    def ensure_schema(self, dim: int) -> None:
        # nothing to create in memory; kept for seam parity with PgCorpusStore
        return None

    def upsert(self, chunks: list[CorpusChunk]) -> int:
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"chunk {chunk.chunk_id!r} has no embedding; embed before upsert")
            self._rows[(chunk.corpus_version, chunk.chunk_id)] = (chunk, list(chunk.embedding))
        return len(chunks)

    def query(self, embedding: list[float], k: int, corpus_version: str) -> list[CorpusChunk]:
        scored = [
            (_cosine_distance(embedding, vec), chunk)
            for (cv, _), (chunk, vec) in self._rows.items()
            if cv == corpus_version
        ]
        scored.sort(key=lambda pair: pair[0])
        # return copies without the vector — downstream (retriever/) needs text + metadata, not the embedding
        return [chunk.model_copy(update={"embedding": None}) for _, chunk in scored[:k]]

    def count(self, corpus_version: str) -> int:
        return sum(1 for cv, _ in self._rows if cv == corpus_version)


class PgCorpusStore:
    """Real store: Postgres + pgvector. Uses a plain psycopg connection (no ORM) — the DDL and
    the `<=>` nearest-neighbour query are written out explicitly, in keeping with the repo's
    hand-rolled ethos."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url: str = db_url or os.getenv("CLEARWAY_DB_URL") or _DEFAULT_DB_URL

    def _connect(self):  # type: ignore[no-untyped-def]
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self._db_url, autocommit=True)
        register_vector(conn)
        return conn

    @staticmethod
    def _vec(embedding: list[float]):  # type: ignore[no-untyped-def]
        # A plain list binds as float8[] (no `vector <=> float8[]` operator); pgvector's `Vector`
        # binds as the vector type, so both the query param and inserts carry an explicit type.
        from pgvector import Vector

        return Vector(embedding)

    def ensure_schema(self, dim: int) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "  corpus_version text NOT NULL,"
                "  chunk_id       text NOT NULL,"
                "  sc_ids         text[] NOT NULL,"
                "  text           text NOT NULL,"
                "  source         text NOT NULL DEFAULT '',"
                "  url            text NOT NULL DEFAULT '',"
                f"  embedding      vector({dim}) NOT NULL,"
                "  PRIMARY KEY (corpus_version, chunk_id)"
                ")"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {_TABLE}_embedding_idx "
                f"ON {_TABLE} USING hnsw (embedding vector_cosine_ops)"
            )

    def upsert(self, chunks: list[CorpusChunk]) -> int:
        if not chunks:
            return 0
        rows = []
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"chunk {chunk.chunk_id!r} has no embedding; embed before upsert")
            rows.append(
                (
                    chunk.corpus_version,
                    chunk.chunk_id,
                    chunk.sc_ids,
                    chunk.text,
                    chunk.source,
                    chunk.url,
                    self._vec(chunk.embedding),
                )
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {_TABLE} (corpus_version, chunk_id, sc_ids, text, source, url, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (corpus_version, chunk_id) DO UPDATE SET "
                    "sc_ids = EXCLUDED.sc_ids, text = EXCLUDED.text, source = EXCLUDED.source, "
                    "url = EXCLUDED.url, embedding = EXCLUDED.embedding",
                    rows,
                )
        return len(rows)

    def query(self, embedding: list[float], k: int, corpus_version: str) -> list[CorpusChunk]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT chunk_id, sc_ids, text, source, url, corpus_version FROM {_TABLE} "
                    "WHERE corpus_version = %s ORDER BY embedding <=> %s LIMIT %s",
                    (corpus_version, self._vec(embedding), k),
                )
                return [
                    CorpusChunk(
                        chunk_id=row[0], sc_ids=row[1], text=row[2], source=row[3], url=row[4], corpus_version=row[5]
                    )
                    for row in cur.fetchall()
                ]

    def count(self, corpus_version: str) -> int:
        with self._connect() as conn:
            row = conn.execute(f"SELECT count(*) FROM {_TABLE} WHERE corpus_version = %s", (corpus_version,)).fetchone()
            return int(row[0]) if row else 0
