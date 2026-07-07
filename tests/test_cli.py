"""`clearway` CLI smoke tests — the user-facing entrypoint over the orchestrator.

Offline: both run with `--no-emit`, so they exercise argument parsing, the `--clean`
lever, and the printed summary without touching OTel (emission is proven end-to-end by
the stack-gated test_observability.py).
"""

from __future__ import annotations

from pathlib import Path

from clearway.cli import main

FIXTURE = str(Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages" / "home.html")


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
