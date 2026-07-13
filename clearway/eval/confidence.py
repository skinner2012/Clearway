"""Confidence-vs-correctness calibration — the honest boundary the milestone draws and hands forward.

The question: does the drafter know when it doesn't know? We bin drafts by their self-reported
confidence and measure correctness per bin — the trusted judge scores judgment items, the oracle
scores verifiable ones — so a *calibrated* drafter would keep its wrong answers in the low-confidence
bins. The earlier reads predict the opposite: confidence pinned at 0.9-1.0, uninformative. This
module therefore reports the curve WITH per-bin counts instead of dressing a flat line up — a single
populated bin *is* the finding, and it only reads that way if the counts ship beside it.

Pure: no LLM, no network. It takes `(confidence, correct)` points — built live and frozen elsewhere,
exactly like the κ streams — and returns the binned curve plus its two summary scalars: the ECE
(unsigned magnitude of miscalibration) and the signed over-confidence gap (positive = the drafter is
systematically more confident than it is right). Kept pure so the curve replays from a checked-in
artifact, never re-derived by calling the non-deterministic drafter. Named apart from `kappa.py`
(judge calibration) and `calibration_build.py` (which builds the κ set) — this is confidence only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clearway.schemas.models import ConfidenceBin

# Equal-width 0.2 bins over the whole confidence range. The width matches the milestone's own
# `bin="0.6-0.8"` example, and it is deliberately coarse: if every draft's confidence lands in the
# top bin, the curve collapses to a single point — which is exactly the degenerate result the earlier
# reads predict, made visible rather than smoothed away by fine bins.
DEFAULT_BIN_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


@dataclass(frozen=True)
class ConfidencePoint:
    """One draft on the calibration curve: the drafter's self-reported confidence paired with whether
    the draft was actually correct (oracle verdict for verifiable items, trusted judge for judgment
    items). The two streams meet on this one shape so the combined curve compares like with like."""

    confidence: float
    correct: bool


def _bin_index(confidence: float, edges: Sequence[float]) -> int:
    """Index of the bin `confidence` falls in: half-open `[lo, hi)` bins, with the TOP bin closed so a
    perfect 1.0 has a home. An interior edge value (e.g. 0.8) belongs to the upper bin it opens."""
    if not (edges[0] <= confidence <= edges[-1]):
        raise ValueError(f"confidence {confidence} outside the bin range [{edges[0]}, {edges[-1]}]")
    for i in range(len(edges) - 1):
        if confidence < edges[i + 1]:
            return i
    return len(edges) - 2  # confidence == edges[-1] → the closed top bin


def bin_points(points: Sequence[ConfidencePoint], edges: Sequence[float] = DEFAULT_BIN_EDGES) -> list[ConfidenceBin]:
    """Group points into their confidence bins → the calibration curve, ascending. ONLY populated bins
    are emitted: an empty bin has no honest `mean_confidence`, and its absence is itself informative —
    the missing low-confidence bins are how "confidence never drops" shows on the curve."""
    buckets: dict[int, list[ConfidencePoint]] = {}
    for p in points:
        buckets.setdefault(_bin_index(p.confidence, edges), []).append(p)
    curve: list[ConfidenceBin] = []
    for i in sorted(buckets):
        members = buckets[i]
        n = len(members)
        correct_n = sum(1 for p in members if p.correct)
        curve.append(
            ConfidenceBin(
                lower=edges[i],
                upper=edges[i + 1],
                n=n,
                mean_confidence=sum(p.confidence for p in members) / n,
                correctness_rate=correct_n / n,
                correct_n=correct_n,
            )
        )
    return curve


def expected_calibration_error(bins: Sequence[ConfidenceBin]) -> float:
    """ECE — the count-weighted average gap between confidence and correctness across bins, in `[0, 1]`.

    ECE = Σ (n_bin / N) · |mean_confidence − correctness_rate|. Unsigned: it measures *how far off* the
    confidence is, in either direction. Raises on an empty curve rather than return a misleading 0.0
    (which would read as "perfectly calibrated" when it means "no data")."""
    total = sum(b.n for b in bins)
    if total == 0:
        raise ValueError("cannot compute ECE over an empty curve")
    return sum((b.n / total) * abs(b.mean_confidence - b.correctness_rate) for b in bins)


def overconfidence_gap(points: Sequence[ConfidencePoint]) -> float:
    """Signed miscalibration: mean confidence − mean correctness, in `[-1, 1]`. Positive = the drafter
    is systematically MORE confident than it is right (over-confident — the predicted failure mode);
    negative = under-confident. The sign ECE throws away, kept because the direction is the finding."""
    if not points:
        raise ValueError("cannot compute the over-confidence gap over no points")
    mean_confidence = sum(p.confidence for p in points) / len(points)
    mean_correct = sum(1 for p in points if p.correct) / len(points)
    return mean_confidence - mean_correct
