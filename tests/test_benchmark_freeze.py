"""The freeze step composes the regression baseline from the sweep: run_1's score, the noise floor
bundled in, every run's id — and it refuses to freeze a drafter that drifted between runs (freezing
run_1 as canonical would then be a lie the noise floor's SD-0 claim cannot back)."""

from __future__ import annotations

import pytest

from clearway.eval.benchmark_freeze import freeze_report
from clearway.schemas.models import NoiseFloor


def _draft(conformance: str, sc: list[str], *, judge_ok: bool = True) -> dict:
    return {
        "finding_id": f"f-{conformance}",
        "conformance": conformance,
        "cited_sc_ids": sc,
        "confidence": 0.8,
        "judge_conformance_correct": judge_ok,
    }


def _run(run_id: str, *, flagged_failed: bool = True) -> dict:
    """A minimal run artifact with one failed case (flagged or not) and one clean passed case."""
    return {
        "run_ids": [run_id],
        "config_id": "m1-single@1",
        "eval_set_id": "act-acceptance@1",
        "corpus_version": "corpus@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "sha256:aaa",
        "judge_model": "gpt-5.6-luna",
        "judge_model_digest": "cloud-snapshot:gpt-5.6-luna",
        "judge_version": "rubric=abc123",
        "axe_core_version": "4.12.1",
        "act_export_hash": "a805d865",
        "created_at": "2026-07-14T00:00:00+00:00",
        "cases": [
            {
                "act_testcase_id": "t1",
                "rule_name": "Heading is descriptive",
                "expected": "failed",
                "gold_success_criteria": ["2.4.6"],
                # flagged → recall hit; clean → recall miss (drifts the drafter's headline rate)
                "drafts": [_draft("does_not_support" if flagged_failed else "supports", ["2.4.6"])],
            },
            {
                "act_testcase_id": "t2",
                "rule_name": "Form field label is descriptive",
                "expected": "passed",
                "gold_success_criteria": ["2.4.6"],
                "drafts": [_draft("supports", ["2.4.6"])],
            },
        ],
        "honest_misses": [],
    }


def _noise_floor() -> NoiseFloor:
    return NoiseFloor(
        runs=3,
        per_metric_sd={"recall": 0.0, "false_positive_rate": 0.0, "judge_kappa": 0.16},
        min_detectable_improvement=0.0,
        dominant_source="binomial-sampling",
    )


def test_freeze_bundles_noise_floor_and_every_run_id() -> None:
    runs = [_run("run-1"), _run("run-2"), _run("run-3")]
    report = freeze_report(runs, _noise_floor())
    assert report.run_ids == ["run-1", "run-2", "run-3"]
    assert report.scorecard.noise_floor is not None
    assert report.scorecard.noise_floor.runs == 3
    # numbers are run_1's (deterministic drafter): the one failed case is flagged → recall 1/1
    assert report.scorecard.drafter.recall.value == pytest.approx(1.0)


def test_freeze_fails_loud_when_the_drafter_drifts() -> None:
    """run_2 mis-flags the failed case → its recall differs from run_1 → the guard raises rather than
    silently freezing run_1."""
    runs = [_run("run-1", flagged_failed=True), _run("run-2", flagged_failed=False)]
    with pytest.raises(ValueError, match="drifted from run_1"):
        freeze_report(runs, _noise_floor())


def test_freeze_needs_at_least_one_run() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        freeze_report([], _noise_floor())
