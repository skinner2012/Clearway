"""Freeze the verifiable-item half of the confidence-calibration curve.

Live: runs the real forward path (scan → normalize → retrieve → draft → oracle) over the `m1-core`
verifiable set ONCE via `run_set`, then writes a checked-in JSON of `(confidence, oracle-correct)`
points that the pure confidence math in `confidence.py` replays network-free — the same freeze
discipline `calibration_build.py` uses for κ. The ORACLE scores these (axe hard-decides the
violations); the JUDGMENT half of the curve comes from the already-frozen `calibration_set.json`
(its natural drafts, trusted-judge-scored), so this script never re-runs the judge. This is the only
place the non-deterministic drafter is called for the confidence curve.

A verifiable point is one drafted finding the oracle could rule on: `correct` iff every oracle-checked
citation VERIFIED (no HALLUCINATED). Findings the oracle can't rule on (incomplete / judgment PASSES)
score UNVERIFIABLE and are dropped here — the trusted judge owns those, on the judgment side.

Not run by the test suite (needs the corpus stack + Ollama + the axe scanner). Invoke explicitly:
`uv run python -m clearway.eval.confidence_build`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.orchestrator.run import run_set
from clearway.retriever import build_default_retriever
from clearway.schemas.models import CitationVerdict, Trace

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_MANIFEST = _FIXTURES / "expected_m1.json"
_ARTIFACT = _FIXTURES / "confidence_calibration.json"

_CONFIDENCE_VERSION = "confidence@1"

# Oracle verdicts that mean "the oracle ruled on this citation" — the verifiable subset. UNVERIFIABLE
# citations (no oracle verdict) belong to the judge, not here.
_VERIFIABLE = (CitationVerdict.VERIFIED, CitationVerdict.HALLUCINATED)


def _verifiable_point(trace: Trace) -> dict[str, Any] | None:
    """One `(confidence, correct)` point from a trace, or None if the oracle couldn't rule on it.

    `correct` = every oracle-checked citation VERIFIED — a single hallucinated citation makes the draft
    wrong. Per-check verdicts are recorded so the frozen `correct` is re-derivable, never merely
    trusted (the replay guard recomputes it)."""
    checked = [c for c in trace.checks if c.verdict in _VERIFIABLE]
    if not checked:
        return None  # incomplete / judgment finding — the judge owns it, not the oracle
    if trace.confidence is None:
        return None  # defensive: a drafted, oracle-checked finding always carries a confidence
    return {
        "finding_id": trace.finding_id,
        "confidence": trace.confidence,
        "correct": all(c.verdict is CitationVerdict.VERIFIED for c in checked),
        "checks": [{"sc_id": c.sc_id, "verdict": c.verdict.value} for c in checked],
    }


def build_confidence_set() -> dict[str, Any]:
    """Run the live forward path over the verifiable set and harvest its confidence points. Uses an
    explicitly-built retriever so `corpus_version` is recorded on the artifact; everything else
    (drafter, oracle, store) is `run_set`'s production default."""
    manifest = json.loads(_MANIFEST.read_text())
    targets = [str(_FIXTURES / page["path"]) for page in manifest["pages"]]
    retriever = build_default_retriever()

    result = run_set(targets, eval_set_id=manifest["eval_set_id"], retrieve=retriever.retrieve)
    report = result.report

    points: list[dict[str, Any]] = []
    for trace in result.traces:
        point = _verifiable_point(trace)
        if point is not None:
            points.append(point)
    drafter_model = result.traces[0].model if result.traces else ""

    return {
        "set_id": "confidence-calibration",
        "version": 1,
        "confidence_version": _CONFIDENCE_VERSION,
        "eval_set_id": report.eval_set_id,
        "run_id": report.run_id,
        "config_id": report.config_id,
        "drafter_model": drafter_model,
        "corpus_version": retriever.corpus_version,
        "oracle_regime": report.oracle_regime.value,
        "oracle_version": report.oracle_version,
        "created_at": report.created_at.isoformat(),
        "points": points,
    }


def _print_summary(artifact: dict[str, Any]) -> None:
    points = artifact["points"]
    correct = sum(1 for p in points if p["correct"])
    print(f"verifiable points: {len(points)}  ({correct} correct / {len(points) - correct} incorrect)")
    for p in points:
        mark = "ok " if p["correct"] else "BAD"
        scs = ",".join(c["sc_id"] for c in p["checks"])
        print(f"  [{mark}] conf={p['confidence']:.2f}  {p['finding_id']}  {scs}")


def main() -> None:
    artifact = build_confidence_set()
    _ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {_ARTIFACT.relative_to(Path.cwd())} — {len(artifact['points'])} verifiable points")
    _print_summary(artifact)


if __name__ == "__main__":
    main()
