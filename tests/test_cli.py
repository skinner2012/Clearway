"""`clearway` CLI smoke tests — the user-facing entrypoint over the orchestrator.

The `run` and `eval` tests inject the canned spine (`offline_spine`) and pass `--no-emit`, so they
exercise argument parsing and the printed stratified summary without the corpus stack, Ollama, or
OTel (emission is proven end-to-end by the stack-gated test_observability.py). `eval` still scans
the real fixture pages with headless Chromium. The `corpus-*` test is stack-gated (real Ollama +
pgvector), since those subcommands construct the real embedder/store.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.cli import main

FIXTURE = str(Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages" / "home.html")


@pytest.fixture
def offline_spine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `clearway run`/`clearway eval` use the canned retriever + drafter stubs and an
    in-memory checkpoint store instead of building the real RAG retriever, LLM drafter, and
    Postgres store, so the CLI tests exercise the CLI glue without needing the corpus stack,
    Ollama, or Postgres (see run._default_retrieve / _default_draft / _default_store). Patched via
    importlib because the re-exported `run` *function* shadows the submodule under plain attribute
    access."""
    import importlib

    from clearway.orchestrator import InMemoryOrchestratorStore

    run_module = importlib.import_module("clearway.orchestrator.run")
    monkeypatch.setattr(run_module, "_default_retrieve", lambda: canned_retrieve)
    monkeypatch.setattr(run_module, "_default_draft", lambda: canned_draft)
    monkeypatch.setattr(run_module, "_default_store", lambda: InMemoryOrchestratorStore())


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


def test_cli_run_no_emit_exits_zero(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["run", FIXTURE, "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "citation_hallucination_rate=0.667" in out
    assert "emitted" not in out  # --no-emit must not touch OTel


def test_cli_eval_no_emit_reports_the_stratified_set(offline_spine, capsys) -> None:  # type: ignore[no-untyped-def]
    """`clearway eval` runs the whole m1-core@1 set and prints the honest stratification: the two
    incomplete fixtures give 2 UNVERIFIABLE of 5 citations → unverifiable_share = 0.400."""
    code = main(["eval", "--no-emit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "m1-core@1" in out
    assert "unverifiable_share=0.400" in out
    assert "emitted" not in out  # --no-emit must not touch OTel


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
