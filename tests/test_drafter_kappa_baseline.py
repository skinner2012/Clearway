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
    assert _row(baseline, "link-name").kappa == pytest.approx(0.211, abs=5e-3)


def test_second_reading_moves_only_link() -> None:
    # partial_flags=False is robust: only link-name moves (κ 0.211→0.324, errors 6→5); no verdict flips.
    baseline = _baseline()
    for axe in ("document-title", "empty-heading", "label"):
        row = _row(baseline, axe)
        assert row.kappa_partial_false == pytest.approx(row.kappa, abs=1e-9)
        assert row.errors_partial_false == row.errors
    link = _row(baseline, "link-name")
    assert link.kappa_partial_false == pytest.approx(0.324, abs=5e-3)
    assert link.errors_partial_false == 5
    assert link.errors == 6


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
    assert _row(baseline, "link-name").p_value == pytest.approx(0.5**6)


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


# --- the pre-registration carried on the artifact ---------------------------------------------------


def test_pooled_endpoint_is_the_primary_and_has_real_margin() -> None:
    """The pooled thesis test: 10 reachable errors across the two classes a fix treats. Unlike either
    class alone it tolerates a regression, which is why the milestone rests here and not per class."""
    pooled = _baseline().pooled_endpoint
    assert pooled.axe_rules == ["label", "link-name"]
    assert pooled.reachable_errors == 10
    assert pooled.p_value == pytest.approx(0.5**10)
    assert pooled.certifiable is True
    assert pooled.minimum_wins == 5
    assert pooled.tolerated_regressions == 3


def test_per_class_certification_is_zero_margin_by_construction() -> None:
    # Both certifiable classes need 5 fixed and 0 broken. That is the gold set's size, not the fix.
    baseline = _baseline()
    for axe in ("label", "link-name"):
        row = _row(baseline, axe)
        assert row.reachable_errors == 5
        assert row.reachable_certifiable is True
        assert row.tolerated_regressions == 0


def test_the_failure_outcome_is_pre_committed_numerically() -> None:
    # "Thesis not supported" has a number attached before the run, so it cannot be reframed after it.
    text = _baseline().pooled_endpoint.failure_definition.lower()
    assert "b <= 2" in text
    assert "not supported" in text


def test_reachable_ledger_rides_on_every_row() -> None:
    baseline = _baseline()
    expected = {"link-name": 5, "label": 5, "document-title": 3, "empty-heading": 1}
    for axe, reachable in expected.items():
        row = _row(baseline, axe)
        assert row.reachable_errors == reachable
        assert len(row.reachable_error_ids) == reachable
        assert row.errors - row.honest_miss_errors - row.contradictory_gold_errors == row.reachable_errors
        assert len(row.unreachable) == row.honest_miss_errors + row.contradictory_gold_errors


def test_contradictory_gold_term_is_present_and_zero() -> None:
    # Kept in the formula so the ledger reads the same before and after the scoping that emptied it.
    assert all(c.contradictory_gold_errors == 0 for c in _baseline().classes)


def test_scope_correction_states_the_conformance_ground() -> None:
    sc = _baseline().scope_correction
    assert sc.excluded_rule == "Link is descriptive"
    assert sc.excluded_rule_success_criteria == ["2.4.9"]
    assert [lv.value for lv in sc.excluded_rule_levels] == ["AAA"]
    assert sc.retained_rule == "Link in context is descriptive"
    assert "2.4.4" in sc.retained_rule_success_criteria
    assert "A" in [lv.value for lv in sc.retained_rule_levels]
    assert (sc.cases_before, sc.cases_after) == (53, 44)
    # the reason is conformance level; the contradiction it also removes is a consequence, not the reason
    assert "aaa" in sc.rationale.lower() and "level" in sc.rationale.lower()
    assert "consequence" in sc.consequence.lower()


def test_both_arithmetic_side_effects_are_disclosed_on_the_artifact() -> None:
    """The correction converts one unwinnable error into a win and stops scoring one predictable
    regression. A reader who cannot see this pair cannot audit the improvement."""
    sc = _baseline().scope_correction
    assert sc.manufactured_win.act_testcase_id.startswith("6566c139dc")
    assert sc.unscored_regression.act_testcase_id.startswith("48cbc84f4c")
    # they are each other's twin, and the twinning is a byte-identity, verified at freeze time
    assert sc.manufactured_win.twin_act_testcase_id == sc.unscored_regression.act_testcase_id
    assert sc.unscored_regression.twin_act_testcase_id == sc.manufactured_win.act_testcase_id
    assert sc.manufactured_win.content_sha256 == sc.unscored_regression.content_sha256
    # and the manufactured win really is one of the wins the class now needs
    assert sc.manufactured_win.act_testcase_id in _row(_baseline(), "link-name").reachable_error_ids


def test_superseded_reading_is_preserved_for_the_changed_class_only() -> None:
    superseded = _baseline().scope_correction.superseded
    assert [s.axe_rule for s in superseded] == ["link-name"]
    prior = superseded[0]
    assert (prior.n, prior.errors) == (24, 9)
    assert prior.kappa == pytest.approx(0.250, abs=5e-3)
    assert prior.p_value == pytest.approx(0.5**9)
    assert "not comparable" in prior.note.lower()


def test_both_predictions_are_recorded_before_the_run_that_scores_them() -> None:
    predictions = _baseline().predictions
    assert [p.prediction_id for p in predictions] == ["accname-trailing-colon", "destination-outside-dom"]
    for p in predictions:
        assert p.epistemic_status == "argued"  # both rest on a claim about model behaviour
        assert p.claim and p.reasoning and p.consequence_if_held
        assert p.act_testcase_ids


def test_predicted_failures_are_not_subtracted_from_any_ceiling() -> None:
    # Every case a prediction names that is currently an error stays inside its class's reachable count.
    baseline = _baseline()
    named = {tid for p in baseline.predictions for tid in p.act_testcase_ids}
    unreachable = {u.act_testcase_id for c in baseline.classes for u in c.unreachable}
    assert not named & unreachable


def test_denominators_are_stated_beside_the_ones_they_replace() -> None:
    # Without both, a later run's pooled recall / FP / SC-match / ECE are not like-for-like.
    d = _baseline().denominators
    assert (d.cases, d.minting_cases, d.honest_misses) == (44, 40, 4)
    assert (d.failed_cases, d.passed_cases) == (18, 26)
    assert d.findings == 54
    assert (d.superseded_cases, d.superseded_findings) == (53, 63)


def test_direction_is_pre_registered_as_one_sided() -> None:
    assert _baseline().one_sided is True


# --- no live surface still reports the superseded ceiling as current --------------------------------

_REPO = Path(__file__).resolve().parent.parent

# Live surfaces a reader inherits numbers from. `specs/` and the dated analysis reports under `docs/`
# are deliberately excluded: they are historical records of what was measured at the time, and each
# carries its own superseded banner. A frozen number left standing where the NEXT reader takes it as
# current is the failure this test exists to catch.
_LIVE_SURFACES = (
    _REPO / "CONTRACTS.md",
    _REPO / "ARCHITECTURE.md",
    _REPO / "README.md",
    _REPO / "docs" / "drafter-kappa-baseline.md",
    _REPO / "docs" / "act-feasibility.md",
    _REPO / "benchmark" / "reports" / "verdict_vector.json",
    *sorted((_REPO / "clearway").rglob("*.py")),
)

# The literals the superseded reading was published under. A test cannot judge prose, so it greps.
_SUPERSEDED_LITERALS = (
    "0.001953125",  # the old link-name ceiling p
    "p = 0.002",  # its rounded form in prose
    "24 (11/13)",  # the old class size and gold split
    "two link rules pool",  # the pooling claim itself
    "the two link rules",
    "pooled ×2",
    "five ACT",  # the rule count before the scoping
)


def _live_text(path: Path) -> str:
    """A surface's CURRENT content. The contract's change log is history by convention — every row
    records what a change moved — so it is read out before grepping, not exempted wholesale."""
    text = path.read_text()
    return text.split("## 6. Change log")[0] if path.name == "CONTRACTS.md" else text


def test_no_live_surface_reports_the_superseded_ceiling() -> None:
    hits = [
        f"{path.relative_to(_REPO)}: {literal!r}"
        for path in _LIVE_SURFACES
        for literal in _SUPERSEDED_LITERALS
        if literal in _live_text(path)
    ]
    assert not hits, "superseded numbers still live on a current surface:\n  " + "\n  ".join(hits)


def test_the_frozen_artifact_carries_the_old_ceiling_only_as_the_superseded_reading() -> None:
    """The superseded p-value survives in exactly one place — the labelled `scope_correction.superseded`
    row — and in none of the current class rows. Preserved and quarantined, not left standing."""
    raw = json.loads((_REPORTS / "drafter_kappa_baseline.json").read_text())
    assert all(c["p_value"] != 0.001953125 for c in raw["classes"])
    assert [s["p_value"] for s in raw["scope_correction"]["superseded"]] == [0.001953125]
