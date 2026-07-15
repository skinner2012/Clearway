"""The noise-floor math: run-to-run SD of the headline metrics, the binomial-vs-jitter dominance call,
and the per-stratum McNemar discordance floor. Replays hand-built run artifacts with a KNOWN jitter so
every number is exact — this decides whether a future change is progress or noise, so it must not drift.
"""

from __future__ import annotations

import pytest

from clearway.eval.noise_floor import binomial_sd, build_noise_floor, stddev


def _draft(conformance: str) -> dict:
    return {
        "finding_id": f"x-{conformance}",
        "conformance": conformance,
        "cited_sc_ids": ["2.4.6"],
        "confidence": 0.8,
        "judge_conformance_correct": True,
    }


def _run(created_at: str, cases: list[tuple[str, str, str]]) -> dict:
    """A minimal run artifact: `cases` are (act_testcase_id, expected, conformance) triples."""
    return {
        "run_ids": [f"r-{created_at}"],
        "config_id": "m1-single@1",
        "eval_set_id": "act-acceptance@1",
        "corpus_version": "c@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "d",
        "judge_model": "j",
        "judge_model_digest": "jd",
        "judge_version": "v",
        "axe_core_version": "4.12.1",
        "act_export_hash": "h",
        "created_at": created_at,
        "cases": [
            {
                "act_testcase_id": aid,
                "rule_name": "Heading is descriptive",
                "axe_rule": "empty-heading",
                "expected": exp,
                "gold_success_criteria": ["2.4.6"],
                "drafts": [_draft(conf)],
            }
            for aid, exp, conf in cases
        ],
        "honest_misses": [],
        "injected": {"conformance_flip": [], "sc_swap": [], "rationale_note": ""},
    }


# Run A and B differ only in TN case p1 (clean in A, cried-wolf in B) → a controlled jitter in the FP rate.
_RUN_A = _run(
    "2026-07-15T00:00:00+00:00",
    [("p1", "passed", "supports"), ("p2", "passed", "supports"), ("f1", "failed", "does_not_support")],
)
_RUN_B = _run(
    "2026-07-15T01:00:00+00:00",
    [("p1", "passed", "does_not_support"), ("p2", "passed", "supports"), ("f1", "failed", "does_not_support")],
)


def test_stddev_and_binomial_helpers() -> None:
    assert stddev([0.0, 0.5]) == pytest.approx(0.35355, abs=1e-4)
    assert stddev([0.4]) == 0.0  # a single run has no variance
    assert binomial_sd(0.25, 2) == pytest.approx(0.30619, abs=1e-4)
    assert binomial_sd(0.5, 0) == 0.0


def test_sd_is_over_the_headline_metrics() -> None:
    """recall is identical across the two runs (SD 0); FP jitters 0.0 → 0.5 (SD 0.3536)."""
    nf = build_noise_floor([_RUN_A, _RUN_B])
    assert nf.runs == 2
    assert nf.per_metric_sd["recall"] == pytest.approx(0.0)
    assert nf.per_metric_sd["false_positive_rate"] == pytest.approx(0.35355, abs=1e-4)


def test_mdi_is_the_noisier_headline_metric() -> None:
    nf = build_noise_floor([_RUN_A, _RUN_B])
    assert nf.min_detectable_improvement == pytest.approx(0.35355, abs=1e-4)


def test_dominant_source_is_jitter_when_it_exceeds_the_binomial_floor() -> None:
    """Observed FP jitter (0.354) exceeds the binomial SD at p=0.25,n=2 (0.306) → jitter dominates."""
    assert build_noise_floor([_RUN_A, _RUN_B]).dominant_source == "llm-jitter"


def test_paired_discordance_counts_flips_per_stratum() -> None:
    """Only the TN case p1 flips between the runs → 1 TN→FP flip, 0 TP→miss flips, never pooled."""
    note = build_noise_floor([_RUN_A, _RUN_B]).paired_mdi_note
    assert "TN→FP flips max 1" in note
    assert "TP→miss flips max 0" in note


def test_identical_runs_are_floored_by_binomial_sampling() -> None:
    """Three identical runs → zero observed jitter, so the floor is finite-sample binomial noise, not
    the model (the temperature-0 case the spec warns to report, not assume)."""
    run = _run(
        "2026-07-15T00:00:00+00:00",
        [("f1", "failed", "does_not_support"), ("f2", "failed", "supports"), ("p1", "passed", "supports")],
    )
    nf = build_noise_floor([run, run, run])
    assert nf.min_detectable_improvement == pytest.approx(0.0)
    assert nf.dominant_source == "binomial-sampling"
    assert "TP→miss flips max 0" in nf.paired_mdi_note


def test_single_run_has_no_noise_floor() -> None:
    with pytest.raises(ValueError, match="at least two runs"):
        build_noise_floor([_RUN_A])


def test_missing_honest_misses_is_rejected() -> None:
    """The noise floor replays run artifacts; a missing honest_misses must raise, never default — the
    same silent recall-denominator skew the report loader guards against."""
    run = _run("2026-07-15T00:00:00+00:00", [("f1", "failed", "does_not_support")])
    del run["honest_misses"]
    with pytest.raises(KeyError, match="honest_misses"):
        build_noise_floor([run, run])
