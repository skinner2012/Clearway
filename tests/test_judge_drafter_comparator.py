"""The drafter comparator the judge's side-by-side is set against — recomputed, never read off the
frozen pre-referent baseline.

Two properties carry the weight. First, **κ is re-derived from each row's own 2×2 by the textbook
formula**, not by calling the same function the record calls: a test that re-runs the builder can only
prove the builder is deterministic, which is a different claim from the numbers being right. Second, the
record is pinned to the committed file by a full rebuild — it is a deterministic function of its two
sources, `created_at` included, so a rebuild is byte-identical and an edit in place fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clearway.eval.judge_drafter_comparator import (
    SUPERSEDED_BASELINE,
    build_record,
    per_class_rows,
    report_path,
)

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"
_BASELINE = _REPO / "benchmark" / "reports" / SUPERSEDED_BASELINE


def _record() -> dict:
    return build_record(replay_path=_REPLAY, baseline_path=_BASELINE)


def _kappa_from_cells(tp: int, fp: int, fn: int, tn: int) -> float:
    """Cohen's κ from a 2×2, written out here rather than imported.

    Importing the repo's own `cohen_kappa` would check the record against the arithmetic that produced
    it. This is the independent statement of the same quantity: observed agreement against the agreement
    the two raters' marginals would produce by chance.
    """
    n = tp + fp + fn + tn
    observed = (tp + tn) / n
    chance = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n**2
    return (observed - chance) / (1 - chance)


def test_every_class_kappa_re_derives_from_its_own_two_by_two() -> None:
    for row in per_class_rows(json.loads(_REPLAY.read_text())):
        expected = _kappa_from_cells(row["tp"], row["fp"], row["fn"], row["tn"])
        assert row["kappa"] == pytest.approx(expected, abs=5e-5), row["axe_rule"]
        cells = row["tp"] + row["fp"] + row["fn"] + row["tn"]
        assert cells == row["drafter_units"], f"{row['axe_rule']}: the 2×2 must exhaust the class"
        assert row["failed"] + row["passed"] == row["drafter_units"]
        assert row["raw_agreement"] == pytest.approx((row["tp"] + row["tn"]) / row["drafter_units"], abs=5e-5)


def test_the_two_denominators_are_on_every_row_and_reconcile_to_the_totals() -> None:
    """The judge can never hold a case that minted no finding, so the two raters' n differ by design."""
    record = _record()
    rows, totals = record["per_class"], record["totals"]
    for row in rows:
        assert row["judge_visible_units"] + row["unit_gap"] == row["drafter_units"]
        assert row["gap_rows_whose_gold_is_failed"] <= row["unit_gap"]
    assert totals["drafter_units"] == sum(r["drafter_units"] for r in rows)
    assert totals["judge_visible_units"] == sum(r["judge_visible_units"] for r in rows)
    assert totals["drafter_units"] - totals["judge_visible_units"] == totals["unit_gap"]


def test_the_gap_is_exactly_the_cases_that_minted_nothing() -> None:
    """Named to their ids and checked against the artifact, so the gap cannot be a rounding story."""
    artifact = json.loads(_REPLAY.read_text())
    honest_misses = {m["act_testcase_id"] for m in artifact["honest_misses"]}
    minting = {c["act_testcase_id"] for c in artifact["cases"]}
    gap_ids = {i for row in _record()["per_class"] for i in row["gap_row_ids"]}
    assert gap_ids <= honest_misses
    assert gap_ids.isdisjoint(minting)


def test_the_frozen_baseline_is_a_different_drafter_and_the_record_names_which_classes() -> None:
    """The whole reason this module exists: the substitution is invisible on the shapes.

    Both sources agree on their case and finding counts, so nothing about reading the frozen file
    instead would look wrong — and the per-class κ disagrees. The moved classes are recomputed here from
    the two files rather than taken from the record's own field.
    """
    record = _record()
    superseded = {r["axe_rule"]: r["kappa"] for r in record["superseded_baseline"]["per_class"]}
    current = {r["axe_rule"]: r["kappa"] for r in record["per_class"]}
    assert superseded.keys() == current.keys()
    moved = sorted(k for k in current if current[k] != superseded[k])
    assert moved, "if nothing moved, this record would be redundant — check the source pass"
    assert record["superseded_baseline"]["classes_whose_kappa_moved"] == moved
    assert record["superseded_baseline"]["historical_only"] is True

    baseline = json.loads(_BASELINE.read_text())
    assert baseline["denominators"]["findings"] == record["totals"]["findings"]
    assert baseline["denominators"]["cases"] == record["totals"]["drafter_units"]
    assert all(rid.startswith("acceptance-") for rid in baseline["run_ids"])
    assert not any(rid.startswith("acceptance-") for rid in record["source"]["run_ids"])


def test_the_record_carries_no_clock_and_rebuilds_byte_identical() -> None:
    artifact = json.loads(_REPLAY.read_text())
    first, second = _record(), _record()
    assert first == second
    assert first["created_at"] == artifact["created_at"]
    assert first["model_calls_spent"] == 0


def test_the_committed_record_is_the_one_a_rebuild_produces() -> None:
    """Deterministic given its sources, so the freeze is pinned by comparison rather than by a digest
    computed from the file's own bytes — which any edit that recomputes it would pass."""
    on_disk = json.loads(report_path().read_text())
    assert on_disk == _record()
