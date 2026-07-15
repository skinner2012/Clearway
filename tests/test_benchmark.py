"""The pure artifact → `BenchmarkReport` assembly: replays a frozen acceptance run into the scored,
reproducible report. A tiny hand-built artifact with known outcomes so the wiring (drafter per case,
judge on the conformance axis, provenance passthrough, optional injected/Tier-B sections) is exact.
"""

from __future__ import annotations

import pytest

from clearway.eval.benchmark import NOT_MEASURED, build_report
from clearway.schemas.models import BenchmarkReport


def _draft(conformance: str, sc: list[str], *, conf: float, judge_ok: bool) -> dict:
    return {
        "finding_id": f"f-{conformance}",
        "conformance": conformance,
        "cited_sc_ids": sc,
        "confidence": conf,
        "judge_conformance_correct": judge_ok,
    }


def _artifact(**overrides) -> dict:
    base = {
        "run_ids": ["acceptance-test"],
        "config_id": "m5-acceptance@1",
        "eval_set_id": "act-acceptance@1",
        "corpus_version": "corpus@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "sha256:aaa",
        "judge_model": "gpt-5.6-luna",
        "judge_model_digest": "cloud-snapshot:gpt-5.6-luna",
        "judge_version": "rubric=abc123",
        "axe_core_version": "4.12.1",
        "act_export_hash": "a805d865d61ae2418e56a6a9d303fe60c85089c792b897eb9472ea5513156293",
        "created_at": "2026-07-14T00:00:00+00:00",
        "cases": [
            {  # a failed case correctly flagged (recall hit; judge correctly passes it)
                "act_testcase_id": "t1",
                "rule_name": "Heading is descriptive",
                "expected": "failed",
                "gold_success_criteria": ["2.4.6"],
                "drafts": [_draft("does_not_support", ["2.4.6"], conf=0.9, judge_ok=True)],
            },
            {  # a passed case correctly clean (no cry wolf)
                "act_testcase_id": "t2",
                "rule_name": "Form field label is descriptive",
                "expected": "passed",
                "gold_success_criteria": ["2.4.6"],
                "drafts": [_draft("supports", ["2.4.6"], conf=0.8, judge_ok=True)],
            },
        ],
        "honest_misses": [
            {  # a failed case that minted nothing → an automatic recall miss
                "act_testcase_id": "t3",
                "rule_name": "Link is descriptive",
                "expected": "failed",
                "gold_success_criteria": ["2.4.9"],
            }
        ],
    }
    base.update(overrides)
    return base


def test_build_report_produces_a_valid_benchmark_report() -> None:
    report = build_report(_artifact())
    assert isinstance(report, BenchmarkReport)
    # round-trips through validation → the artifact is a faithful, reproducible freeze
    assert BenchmarkReport.model_validate(report.model_dump()) == report


def test_provenance_is_passed_through_verbatim() -> None:
    report = build_report(_artifact())
    assert report.run_ids == ["acceptance-test"]
    assert report.axe_core_version == "4.12.1"
    assert report.act_export_hash.startswith("a805d865")
    assert report.drafter_model_digest == "sha256:aaa"


def test_drafter_recall_counts_the_honest_miss_as_a_miss() -> None:
    """2 failed cases (t1 flagged, t3 honest-miss) → recall 1/2; the passed case is clean → FP 0/1."""
    d = build_report(_artifact()).scorecard.drafter
    assert (d.recall.value, d.recall.n) == (pytest.approx(0.5), 2)
    assert (d.false_positive_rate.value, d.false_positive_rate.n) == (pytest.approx(0.0), 1)


def test_judge_confusion_is_on_the_conformance_axis() -> None:
    """Both judged drafts are conformance-correct and the judge passes both → 2 correct releases, no
    misses; the injected rates are no-data on a plain run."""
    j = build_report(_artifact()).scorecard.judge
    assert (j.correct_release, j.missed_error, j.false_alarm, j.correct_catch) == (2, 0, 0, 0)
    assert j.injected_conformance_flip.n == 0
    assert j.injected_sc_swap.n == 0


def test_plain_run_has_no_noise_floor_or_tier_b() -> None:
    sc = build_report(_artifact()).scorecard
    assert sc.noise_floor is None
    assert sc.tier_b is None
    assert len(sc.not_measured) == len(NOT_MEASURED) == 4
    assert sc.notes  # the sensitivity notes travel on the scorecard
    assert "does_not_support" in sc.conformance_collapse_rule


def test_injected_section_is_read_when_present() -> None:
    """An injection pass fills the detection rates: 2 of 3 flip-drafts caught, 1 of 1 swap caught."""
    art = _artifact(
        injected={
            "conformance_flip": [
                {"rule_name": "Heading is descriptive", "caught": True},
                {"rule_name": "Link is descriptive", "caught": True},
                {"rule_name": "Form field label is descriptive", "caught": False},
            ],
            "sc_swap": [{"rule_name": "Heading is descriptive", "caught": True}],
            "rationale_note": "regenerated to argue the flip",
        }
    )
    j = build_report(art).scorecard.judge
    assert (j.injected_conformance_flip.value, j.injected_conformance_flip.n) == (pytest.approx(2 / 3), 3)
    assert (j.injected_sc_swap.value, j.injected_sc_swap.n) == (pytest.approx(1.0), 1)
    assert j.rationale_coherence_note == "regenerated to argue the flip"


def test_tier_b_section_is_read_when_present() -> None:
    art = _artifact(
        tier_b={
            "instance_ids": ["page-a-title", "page-b-label"],
            "clean_vs_noisy_note": "no verdict changed under noise",
            "method_and_limits": "intact embedding into hybrid noise; n=2 illustrative, not a rate",
        }
    )
    tb = build_report(art).scorecard.tier_b
    assert tb is not None
    assert tb.n == 2
    assert tb.instance_ids == ["page-a-title", "page-b-label"]
    assert "illustrative" in tb.method_and_limits
