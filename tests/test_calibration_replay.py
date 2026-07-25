"""Replay guard for the frozen calibration set: recompute κ OFFLINE from the checked-in artifact and
re-derive the trust decision, so the calibration number is reproducible without any model call.

Skips until the artifact exists (the live build in `clearway.eval.calibration_build` writes it); once
committed, it runs on every suite — `calibration_set.json` is a data contract, like the gold manifest.
The verdicts are RECOMPUTED from raw and compared to the stored ones, so the frozen data is proven
self-consistent, never merely trusted.

The last section pins something different: not that the artifact replays, but that a *rebuild* of it
cannot quietly answer a different question under the same filename.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.calibration_build import (
    SYSTEM_PROMPT_SHA256_KEY,
    IncomparableRebuild,
    assert_rebuild_is_comparable,
    provenance_pin,
    system_prompt_sha256,
)
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
    assert report.confidence_bins == []  # κ-only build leaves the curve empty; the confidence assembly supplies it


# ---------------------------------------------------------------------------
# The rebuild guard: a re-run cannot quietly replace this artifact with an
# incomparable one
# ---------------------------------------------------------------------------
#
# κ here was measured on drafts written under a particular drafter system prompt. The build script
# reads that prompt but does not own it, so a prompt change elsewhere in the repo could have a re-run
# months from now overwrite the frozen number with one that answers a different question — under the
# same filename, with the same apparent authority. These pin the guard that stops it.


def _frozen(tmp_path: Path, **fields: Any) -> Path:
    """A stand-in frozen artifact carrying only what the guard reads."""
    path = tmp_path / "calibration_set.json"
    path.write_text(json.dumps({"set_id": "calibration", **fields}))
    return path


def test_a_first_build_proceeds_because_there_is_nothing_to_be_incomparable_with(tmp_path: Path) -> None:
    """No frozen artifact, nothing to overwrite — the guard must not block the build that creates the
    very thing it protects."""
    assert assert_rebuild_is_comparable(tmp_path / "calibration_set.json") is None


def test_a_matching_prompt_hash_proceeds(tmp_path: Path) -> None:
    """The artifact names the prompt it was built under and the prompt still hashes to it — the
    rebuild answers the same question, so it is allowed."""
    path = _frozen(tmp_path, **{SYSTEM_PROMPT_SHA256_KEY: system_prompt_sha256()})
    assert assert_rebuild_is_comparable(path) is None


def test_a_changed_prompt_refuses_loudly_and_names_both_hashes(tmp_path: Path) -> None:
    """The failure the guard exists for. It must name what moved and what to do — an error that only
    says "mismatch" gets overridden by whoever hits it."""
    path = _frozen(tmp_path, **{SYSTEM_PROMPT_SHA256_KEY: "0" * 64})
    with pytest.raises(IncomparableRebuild) as excinfo:
        assert_rebuild_is_comparable(path)
    message = str(excinfo.value)
    assert "0" * 64 in message and system_prompt_sha256() in message
    assert "delete" in message  # the deliberate, reviewable way to supersede a frozen measurement


def test_a_missing_prompt_hash_is_its_own_case_and_is_not_read_as_a_match(tmp_path: Path) -> None:
    """⚠️ The case that must never default to "fine". An artifact predating the pin cannot state
    which prompt produced it; that is an unanswerable question, not agreement, and answering it by
    omission is the silent inheritance the guard exists to prevent."""
    path = _frozen(tmp_path, drafter_model="gemma")
    with pytest.raises(IncomparableRebuild) as excinfo:
        assert_rebuild_is_comparable(path)
    message = str(excinfo.value)
    assert "predates" in message
    assert SYSTEM_PROMPT_SHA256_KEY in message
    assert "0" * 64 not in message, "a missing hash must not be reported as a mismatch against a value"


def test_what_a_build_stamps_is_exactly_what_the_guard_reads(tmp_path: Path) -> None:
    """The loop closes: a build stamps its prompt onto the artifact, and the next build is checked
    against that stamp. Proven by writing the stamp the build writes and handing it to the guard —
    a mechanism where the two halves agreed only by coincidence would pass a source-grep and fail
    here."""
    pin = provenance_pin()
    assert len(pin[SYSTEM_PROMPT_SHA256_KEY]) == 64
    assert assert_rebuild_is_comparable(_frozen(tmp_path, **pin)) is None


def test_the_shipped_artifact_either_states_its_prompt_or_cannot_be_rebuilt_over() -> None:
    """The invariant, on the real file: there is no third state in which a reader silently inherits a
    κ whose prompt nobody can name. Today the shipped artifact predates the pin and takes the second
    branch — that is a disclosure, not a defect, and it is deliberately visible here rather than left
    in a comment. A rebuilt artifact records its pin and takes the first branch instead."""
    if SYSTEM_PROMPT_SHA256_KEY in _artifact():
        assert len(_artifact()[SYSTEM_PROMPT_SHA256_KEY]) == 64
    else:
        with pytest.raises(IncomparableRebuild):
            assert_rebuild_is_comparable(_ARTIFACT)
