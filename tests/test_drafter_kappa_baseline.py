"""The frozen per-class drafter-κ baseline — the reference every future drafter claim is measured against.

Every number is a deterministic replay of a checked-in run artifact — no model, no network, no clock. The
anchors pinned here (κ per class under both readings, the 2×2 error rows, the bootstrap bounds, the ceiling
verdicts) are the same pre-registered numbers the per-class κ tests fix, read here through the assembled
baseline so the baseline and the underlying functions cannot drift apart. The honesty guards are asserted,
not just present: document-title's zero-width interval carries the constant-classifier flag and a 1.0
degenerate share, and its ceiling is NOT certifiable at any fix quality.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from clearway.eval.drafter_kappa_baseline import (
    build_drafter_kappa_baseline,
    freeze_drafter_kappa_baseline,
)
from clearway.schemas.models import DrafterKappaBaseline

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"
_REPORTS = Path(__file__).resolve().parent.parent / "benchmark" / "reports"


def _artifact(name: str = "run_1.json") -> dict:
    return json.loads((_RUNS / name).read_text())


def _baseline(name: str = "run_1.json") -> DrafterKappaBaseline:
    return build_drafter_kappa_baseline(_artifact(name))


def _row(baseline: DrafterKappaBaseline, axe_rule: str):
    return next(c for c in baseline.classes if c.axe_rule == axe_rule)


def test_four_fix_unit_classes_sorted_by_axe_rule() -> None:
    baseline = _baseline()
    assert [c.axe_rule for c in baseline.classes] == ["document-title", "empty-heading", "label", "link-name"]


def test_kappa_anchors_reproduce_headline_reading() -> None:
    # The pre-registered sanity anchors: the constant classifier at ≈0, the control clearly positive.
    baseline = _baseline()
    assert _row(baseline, "document-title").kappa == pytest.approx(0.0, abs=1e-9)
    assert _row(baseline, "empty-heading").kappa == pytest.approx(0.675, abs=5e-3)
    assert _row(baseline, "label").kappa == pytest.approx(0.127, abs=5e-3)
    assert _row(baseline, "link-name").kappa == pytest.approx(0.250, abs=5e-3)


def test_second_reading_moves_only_link() -> None:
    # partial_flags=False is robust: only link-name moves (κ 0.250→0.408, errors 9→7); no verdict flips.
    baseline = _baseline()
    for axe in ("document-title", "empty-heading", "label"):
        row = _row(baseline, axe)
        assert row.kappa_partial_false == pytest.approx(row.kappa, abs=1e-9)
        assert row.errors_partial_false == row.errors
    link = _row(baseline, "link-name")
    assert link.kappa_partial_false == pytest.approx(0.408, abs=5e-3)
    assert link.errors_partial_false == 7
    assert link.errors == 9


def test_2x2_and_splits_match_known_rows() -> None:
    baseline = _baseline()
    dt = _row(baseline, "document-title")
    assert (dt.n, dt.failed, dt.passed) == (5, 2, 3)
    assert (dt.fp, dt.fn) == (3, 0)
    eh = _row(baseline, "empty-heading")
    assert (eh.n, eh.failed, eh.passed) == (13, 5, 8)
    assert (eh.fp, eh.fn) == (1, 1)


def test_document_title_is_flagged_a_constant_classifier() -> None:
    # zero-width interval = no variance because no signal; the share is 1.0; it must not read as precision.
    dt = _row(_baseline(), "document-title")
    assert (dt.ci_low, dt.ci_high) == (0.0, 0.0)
    assert dt.constant_classifier is True
    assert dt.degenerate_share == pytest.approx(1.0)


def test_ceiling_verdicts_and_alpha() -> None:
    baseline = _baseline()
    assert baseline.alpha == 0.05
    assert _row(baseline, "link-name").certifiable is True
    assert _row(baseline, "label").certifiable is True
    assert _row(baseline, "document-title").certifiable is False  # unprovable at any fix quality — n=5
    # p = 0.5^errors
    assert _row(baseline, "document-title").p_value == pytest.approx(0.125)
    assert _row(baseline, "link-name").p_value == pytest.approx(0.5**9)


def test_preregistration_and_bootstrap_params_travel_on_the_artifact() -> None:
    baseline = _baseline()
    assert "one-sided" in baseline.preregistration.lower()
    assert baseline.bootstrap_seed == 0
    assert baseline.bootstrap_resamples == 10_000
    assert baseline.headline_partial_flags is True


def test_provenance_is_complete() -> None:
    baseline = _baseline()
    assert baseline.config_id
    assert baseline.eval_set_id
    assert baseline.corpus_version
    assert baseline.drafter_model_digest
    assert baseline.axe_core_version
    assert baseline.act_export_hash
    assert isinstance(baseline.created_at, datetime)


def test_committed_artifact_loads_validates_and_is_frozen() -> None:
    # the checked-in baseline round-trips through the schema AND equals a fresh freeze of the sweep.
    loaded = DrafterKappaBaseline.model_validate(json.loads((_REPORTS / "drafter_kappa_baseline.json").read_text()))
    runs = [_artifact(n) for n in ("run_1.json", "run_2.json", "run_3.json")]
    assert loaded == freeze_drafter_kappa_baseline(runs)


def test_pure_same_artifact_yields_identical_baseline() -> None:
    a = _artifact()
    assert build_drafter_kappa_baseline(a) == build_drafter_kappa_baseline(a)


def test_freeze_records_the_full_verified_sweep() -> None:
    # run_1 is canonical (drafter deterministic), but the freeze records every run id it was checked
    # against — the numbers are run_1's, the provenance is the whole sweep.
    runs = [_artifact(n) for n in ("run_1.json", "run_2.json", "run_3.json")]
    frozen = freeze_drafter_kappa_baseline(runs)
    assert frozen.classes == build_drafter_kappa_baseline(runs[0]).classes
    assert frozen.run_ids == [rid for run in runs for rid in run["run_ids"]]
    assert len(frozen.run_ids) == 3


def test_freeze_asserts_determinism_and_refuses_a_drifted_run() -> None:
    # if a run's per-class κ diverged, freezing run_1 as canonical would be a lie — fail loud instead.
    good = _artifact()
    drifted = _artifact()
    drifted["cases"][0]["expected"] = "failed" if drifted["cases"][0]["expected"] == "passed" else "passed"
    with pytest.raises(ValueError, match="drifted"):
        freeze_drafter_kappa_baseline([good, drifted])


def test_all_three_frozen_runs_yield_identical_per_class_kappa() -> None:
    # the drafter is deterministic — per-class κ is bit-identical across the three frozen runs.
    def kappas(name: str) -> dict[str, float]:
        return {c.axe_rule: c.kappa for c in _baseline(name).classes}

    assert kappas("run_1.json") == kappas("run_2.json") == kappas("run_3.json")
