"""Replay guard for the frozen verifiable confidence set: prove the checked-in artifact is well-formed
and self-consistent, so the confidence curve is reproducible OFFLINE without re-running the drafter.

Skips until the artifact exists (the live build in `clearway.eval.confidence_build` writes it); once
committed it runs on every suite — `confidence_calibration.json` is a data contract, like the κ set.
Each point's `correct` flag is RECOMPUTED from its raw per-check verdicts and compared to the stored
one, so the frozen data is proven self-checking, never merely trusted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_ARTIFACT = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "confidence_calibration.json"

pytestmark = pytest.mark.skipif(
    not _ARTIFACT.exists(),
    reason="confidence_calibration.json not built yet — run `python -m clearway.eval.confidence_build`",
)

_VERIFIABLE_VERDICTS = {"verified", "hallucinated"}


def _artifact() -> dict[str, Any]:
    return json.loads(_ARTIFACT.read_text())


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
