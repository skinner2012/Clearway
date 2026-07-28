"""Self-reported confidence is a calibration receipt, never a trust signal.

The drafter's `confidence` is measured to carry no usable signal — one populated bin, values pinned
high regardless of correctness (over-confidence gap +0.39). So nothing may READ it to decide how far
an output is trusted; trust comes from verification state (the per-row label in `cli.py`) and from the
per-class κ prior (`FINDING_CLASS_TRUST`), neither of which touches it.

"Nothing reads it" is not assertable by testing behaviour alone — a reader that happens not to change
today's fixtures would pass. So this is a STATIC audit: every read of the field anywhere in the
package is enumerated by parsing the source, and each one is pinned with the reason it is allowed. A
new read fails here until someone classifies it, which is the point.

That the receipt itself still computes is guarded where it lives — `test_confidence.py` (the math)
and `test_confidence_replay.py` (the frozen curve, ECE and gap replayed offline).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_PACKAGE = _REPO / "clearway"

# Every module that reads the field, and why that read is not a trust decision. Only two kinds are
# allowed: the ECE receipt (and the frozen artifacts feeding it), and plumbing that carries the
# number without interpreting it.
_ALLOWED_READS: dict[str, str] = {
    "drafter/llm.py": (
        "produces the field from the model's JSON, and detects the parse-failure fallback by its exact "
        "sentinel (0.0 AND the fixed remediation) — an equality check on a sentinel, not a trust ranking"
    ),
    "orchestrator/machine.py": "copies it onto the Trace so the receipt can be computed offline; never compared",
    "eval/confidence.py": "the ECE receipt itself — bins, ECE, over-confidence gap",
    "eval/confidence_build.py": "freezes the oracle-scored half of the receipt's curve",
    "eval/calibration_build.py": "freezes the judge-scored half of the receipt's curve",
    "eval/offline_build.py": "freezes drafts into the offline artifact, receipt included",
    "eval/referent_injection_build.py": "freezes drafts into the run artifact, receipt included",
    "eval/image_pass.py": (
        "freezes drafts into an image condition's pass artifact, receipt included — recorded beside "
        "the verdict and never read back: the difference and the endpoint are scored on the "
        "conformance collapse against gold, and nothing there weights or thresholds by confidence"
    ),
    "eval/image_score.py": (
        "prints it beside each row of the absence endpoint's two controls — reported for both and "
        "gated on by neither, which is how the controls were pre-registered. It appears in the "
        "artifact and in no predicate: A counts `visual_evidence` values, and both controls are "
        "equalities on that field"
    ),
    "eval/offline.py": "reads the frozen artifact back",
    "eval/kappa.py": "replays frozen drafts into receipt points",
    "eval/drafter_score.py": "the benchmark's receipt — ECE and over-confidence gap per run",
}

# Surfaces a reader actually meets. None of them may read the field at all: a client-facing signal
# sourced from it would launder a broken number into an assurance.
_READER_FACING = ("cli.py", "mcp_server/server.py", "normalizer/quality_review.py", "validator/check.py")


def _reads_confidence(module: Path) -> bool:
    """True iff the module READS a `confidence` field — `x.confidence` or `x["confidence"]` in a load
    position. Construction (`confidence=...`), field declarations and prose are not reads."""
    for node in ast.walk(ast.parse(module.read_text())):
        if isinstance(node, ast.Attribute) and node.attr == "confidence" and isinstance(node.ctx, ast.Load):
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "confidence"
            and isinstance(node.ctx, ast.Load)
        ):
            return True
    return False


def _readers() -> set[str]:
    return {str(p.relative_to(_PACKAGE)) for p in sorted(_PACKAGE.rglob("*.py")) if _reads_confidence(p)}


def test_every_confidence_read_is_a_receipt_or_plumbing() -> None:
    """⚠️ The acceptance criterion. The enumerated readers are exactly the pinned ones — a new read
    anywhere in the package fails until it is classified here."""
    assert _readers() == set(_ALLOWED_READS)


def test_no_reader_facing_surface_reads_confidence() -> None:
    """The report renderer, the retrieval server, the trust-tier table and the citation validator all
    decide what a reader is told to trust. None of them may source it from the self-report."""
    assert not (_readers() & set(_READER_FACING))
