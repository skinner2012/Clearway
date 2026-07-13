"""Replay guard for the frozen verifiable confidence set: prove the checked-in artifact is well-formed
and self-consistent, so the confidence curve is reproducible OFFLINE without re-running the drafter.

Skips until the artifact exists (the live build in `clearway.eval.confidence_build` writes it); once
committed it runs on every suite — `confidence_calibration.json` is a data contract, like the κ set.
Each point's `correct` flag is RECOMPUTED from its raw per-check verdicts and compared to the stored
one, so the frozen data is proven self-checking, never merely trusted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.confidence import build_curve, judgment_points, verifiable_points
from clearway.eval.kappa import agreements_from_artifact, build_report

_FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
_ARTIFACT = _FIXTURES / "confidence_calibration.json"
_CALIBRATION = _FIXTURES / "calibration_set.json"

pytestmark = pytest.mark.skipif(
    not (_ARTIFACT.exists() and _CALIBRATION.exists()),
    reason="calibration artifacts not built yet — run the confidence_build / calibration_build modules",
)

_VERIFIABLE_VERDICTS = {"verified", "hallucinated"}


def _artifact() -> dict[str, Any]:
    return json.loads(_ARTIFACT.read_text())


def _calibration() -> dict[str, Any]:
    return json.loads(_CALIBRATION.read_text())


def test_artifact_is_well_formed_and_records_provenance() -> None:
    a = _artifact()
    assert a["confidence_version"] == "confidence@1"
    assert a["eval_set_id"] == "m1-core@1"
    assert a["drafter_model"]  # the non-deterministic model is recorded on the artifact
    assert a["oracle_version"]  # the oracle that scored the verifiable citations
    assert a["corpus_version"]
    assert a["points"], "the verifiable half of the curve needs at least one oracle-scored point"


def test_points_are_bounded_and_oracle_scored() -> None:
    for p in _artifact()["points"]:
        assert 0.0 <= p["confidence"] <= 1.0
        assert isinstance(p["correct"], bool)
        assert p["checks"], "a verifiable point must carry the oracle checks that decided it"
        assert all(c["verdict"] in _VERIFIABLE_VERDICTS for c in p["checks"])  # oracle ruled on every check


def test_correct_flag_matches_a_fresh_recompute_from_raw_verdicts() -> None:
    """Self-checking: stored `correct` equals `every checked citation VERIFIED`. A divergence means the
    frozen artifact is stale — the flag was written from the run, this re-derives it from the verdicts."""
    for p in _artifact()["points"]:
        recomputed = all(c["verdict"] == "verified" for c in p["checks"])
        assert p["correct"] is recomputed


# --- the combined curve, replayed offline from both frozen artifacts ---------------------------------


def test_both_streams_read_back_with_their_known_splits() -> None:
    judgment = judgment_points(_calibration())
    verifiable = verifiable_points(_artifact())
    # Judgment = the 27 NATURAL drafts (the 16 elicited negatives are excluded), judge-scored.
    assert (len(judgment), sum(p.correct for p in judgment)) == (27, 15)
    assert (len(verifiable), sum(p.correct for p in verifiable)) == (3, 2)


def test_curve_is_a_single_over_confident_bin() -> None:
    """The finding, replayed: every draft's confidence lands in [0.8, 1.0], so the curve collapses to
    one bin — confidence never drops. And within it the drafter is right ~57% while ~96% confident:
    systematically over-confident. A flat, over-confident curve IS the deliverable, counts included."""
    curve = build_curve(judgment_points(_calibration()), verifiable_points(_artifact()))
    assert curve.n == 30  # 27 judgment + 3 verifiable
    (only_bin,) = curve.bins  # degenerate: a single populated bin
    assert (only_bin.lower, only_bin.upper) == (0.8, 1.0)
    assert (only_bin.n, only_bin.correct_n) == (30, 17)
    assert only_bin.mean_confidence == pytest.approx(0.9583, abs=1e-4)
    assert only_bin.correctness_rate == pytest.approx(0.5667, abs=1e-4)


def test_scalars_report_the_over_confidence_honestly() -> None:
    curve = build_curve(judgment_points(_calibration()), verifiable_points(_artifact()))
    # Single bin → ECE equals the signed gap; both ≈ +0.39 (confident far above correct = over-confident).
    assert curve.ece == pytest.approx(0.3917, abs=1e-4)
    assert curve.overconfidence_gap == pytest.approx(0.3917, abs=1e-4)
    assert curve.overconfidence_gap > 0  # positive = systematically over-confident, the predicted mode
    assert curve.judgment_correctness_rate == pytest.approx(15 / 27)


def test_build_report_carries_the_curve_when_supplied() -> None:
    curve = build_curve(judgment_points(_calibration()), verifiable_points(_artifact()))
    balanced, natural = agreements_from_artifact(_calibration())
    report = build_report(
        balanced, natural, created_at=datetime(2026, 7, 13, tzinfo=timezone.utc), confidence_bins=curve.bins
    )
    assert report.confidence_bins == curve.bins  # the curve rides on the CalibrationReport, its only home
