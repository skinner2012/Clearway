"""`clearway` CLI smoke tests — the user-facing entrypoint over the orchestrator.

The `run` tests are offline (`--no-emit`), exercising argument parsing, the `--clean`
lever, and the printed summary without touching OTel (emission is proven end-to-end by
the stack-gated test_observability.py). The `corpus-*` test is stack-gated (real Ollama +
pgvector), since those subcommands construct the real embedder/store.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from clearway.cli import main

FIXTURE = str(Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages" / "home.html")


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


def test_cli_run_no_emit_exits_zero(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["run", FIXTURE, "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "citation_hallucination_rate=0.667" in out
    assert "emitted" not in out  # --no-emit must not touch OTel


def test_cli_clean_no_emit_reports_zero(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["run", FIXTURE, "--clean", "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "citation_hallucination_rate=0.000" in out


@corpus_up
def test_cli_corpus_ingest_then_query_smoke(capsys) -> None:  # type: ignore[no-untyped-def]
    """Both corpus subcommands run end-to-end through the real embedder/store. `--limit`
    keeps it to a few real SCs (an idempotent re-upsert — SC 1.1.1 is first, so the query
    finds it); this exercises the CLI glue that the module-level tests don't touch."""
    assert main(["corpus-ingest", "--limit", "3"]) == 0
    ingest_out = capsys.readouterr().out
    assert "ingested" in ingest_out and "corpus_version=" in ingest_out

    assert main(["corpus-query", "images need a text alternative"]) == 0
    assert "1.1.1" in capsys.readouterr().out
