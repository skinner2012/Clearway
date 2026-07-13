"""Replay guard for the frozen calibration set: recompute κ OFFLINE from the checked-in artifact and
re-derive the trust decision, so the calibration number is reproducible without any model call.

Skips until the artifact exists (the live build in `clearway.eval.calibration_build` writes it); once
committed, it runs on every suite — `calibration_set.json` is a data contract, like the gold manifest.
The verdicts are RECOMPUTED from raw and compared to the stored ones, so the frozen data is proven
self-consistent, never merely trusted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.kappa import KAPPA_THRESHOLD, agreements_from_artifact, build_report, human_verdict
from clearway.judge import verdict_from
from clearway.schemas.models import Citation, Conformance, DraftRow, GoldLabel

_ARTIFACT = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "calibration_set.json"

pytestmark = pytest.mark.skipif(
    not _ARTIFACT.exists(),
    reason="calibration_set.json not built yet — run `python -m clearway.eval.calibration_build`",
)


def _artifact() -> dict[str, Any]:
    return json.loads(_ARTIFACT.read_text())


def test_artifact_is_well_formed_and_records_provenance() -> None:
    a = _artifact()
    assert a["calibration_version"] == "calibration@1"
    assert a["gold_version"] == "quality-gold@1"
    assert a["drafter_model"] != a["judge_model"]  # judge != drafter, recorded on the artifact
    assert a["kappa_threshold"] == KAPPA_THRESHOLD
    assert a["drafts"]


def test_natural_pass_covers_every_gold_finding_once() -> None:
    rows = _artifact()["drafts"]
    natural_ids = [r["finding_id"] for r in rows if r["lever"] == "natural"]
    assert len(natural_ids) == 27  # one faithful draft per gold finding
    assert len(set(natural_ids)) == 27  # all distinct
    negatives = [r for r in rows if r["lever"] != "natural"]
    assert negatives, "the balanced set needs authentic negatives, else κ is degenerate"
    assert {r["finding_id"] for r in negatives} <= set(natural_ids)  # every negative pairs to a finding


def test_both_verdict_polarities_present_so_kappa_is_not_degenerate() -> None:
    verdicts = {r["human_verdict"] for r in _artifact()["drafts"]}
    assert "correct" in verdicts
    assert verdicts - {"correct"}  # at least one not-correct → the human stream actually varies


def test_frozen_verdicts_match_a_fresh_recompute() -> None:
    """Self-checking: stored 3-way verdicts equal a fresh recompute from raw (draft vs gold for the
    human; the two booleans for the judge). A divergence means the frozen artifact is stale."""
    for row in _artifact()["drafts"]:
        draft = DraftRow(
            finding_id=row["finding_id"],
            conformance=Conformance(row["draft"]["conformance"]),
            citations=[Citation(sc_id=sc) for sc in row["draft"]["cited_sc_ids"]],
            confidence=row["draft"]["confidence"],
        )
        gold = GoldLabel(
            finding_id=row["finding_id"],
            gold_success_criteria=row["gold"]["gold_success_criteria"],
            gold_conformance=Conformance(row["gold"]["gold_conformance"]),
            labeller="(replay)",
            gold_version="(replay)",
        )
        assert human_verdict(draft, gold).value == row["human_verdict"]
        j = row["judge"]
        assert verdict_from(j["citation_correct"], j["conformance_correct"]).value == j["verdict"]


def test_kappa_replays_and_the_judge_clears_the_bar() -> None:
    a = _artifact()
    balanced, natural = agreements_from_artifact(a)
    assert balanced.n == len(a["drafts"])
    assert natural.n == 27
    assert -1.0 <= balanced.kappa <= 1.0
    assert sum(balanced.human_counts.values()) == balanced.n  # per-class counts partition n
    report = build_report(balanced, natural, created_at=datetime(2026, 7, 13, tzinfo=timezone.utc))
    assert report.judge_trusted == (balanced.kappa >= KAPPA_THRESHOLD)
    assert report.judge_trusted is True  # the frozen set represents a calibrated, TRUSTED judge
    assert report.confidence_bins == []  # T4 fills the curve
