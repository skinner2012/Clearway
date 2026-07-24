"""Run A scoring: determinism gate, paired thesis, mechanism, and the document-title certified-guard."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clearway.eval.referent_injection_score import score_run_a
from clearway.schemas.models import CaseVerdict, VerdictVector


def _artifact(cases: list[dict], created_at: str = "2026-07-24T00:00:00+00:00") -> dict:
    return {
        "run_ids": [f"run-a-{created_at}"],
        "config_id": "m1-single@1",
        "eval_set_id": "act-acceptance@1",
        "corpus_version": "corpus@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "deadbeef",
        "axe_core_version": "4.12.1",
        "act_export_hash": "abc",
        "created_at": created_at,
        "cases": cases,
        "honest_misses": [],
    }


def _case(tid: str, rule: str, axe_rule: str, expected: str, conformance: str) -> dict:
    return {
        "act_testcase_id": tid,
        "rule_name": rule,
        "axe_rule": axe_rule,
        "expected": expected,
        "gold_success_criteria": ["2.4.4"],
        "drafts": [
            {"finding_id": f"f-{tid}", "target": "x", "conformance": conformance, "cited_sc_ids": [], "confidence": 0.9}
        ],
    }


def _baseline_vector(cases: list[CaseVerdict]) -> VerdictVector:
    return VerdictVector(
        partial_flags=True,
        cases=cases,
        run_ids=["baseline-1"],
        config_id="m1-single@1",
        eval_set_id="act-acceptance@1",
        corpus_version="corpus@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        axe_core_version="4.12.1",
        act_export_hash="abc",
        created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        rationale="test",
    )


# Two label cases both gold-failed; baseline drafter was CLEAN on both (wrong), Run A flags both (right).
_LABEL_CASES = [
    _case("k1", "Link in context is descriptive", "link-name", "failed", "does_not_support"),
    _case("k2", "Link in context is descriptive", "link-name", "failed", "does_not_support"),
]


def test_determinism_needs_two_passes() -> None:
    with pytest.raises(ValueError, match="at least two passes"):
        score_run_a([_artifact(_LABEL_CASES)], _baseline_vector([]), {}, {})


def test_paired_improvement_scored() -> None:
    run = _artifact(_LABEL_CASES)
    base_vec = _baseline_vector(
        [
            CaseVerdict(
                act_testcase_id="k1",
                axe_rule="link-name",
                drafter_flag=False,
                gold_flag=True,
                conformances=["supports"],
            ),
            CaseVerdict(
                act_testcase_id="k2",
                axe_rule="link-name",
                drafter_flag=False,
                gold_flag=True,
                conformances=["supports"],
            ),
        ]
    )
    _vec, result = score_run_a([run, run, run], base_vec, {"link-name": ["k1", "k2"]}, {"link-name": 2})
    kln = next(c for c in result["classes"] if c["axe_rule"] == "link-name")
    assert (kln["improved"], kln["regressed"]) == (2, 0)
    assert result["determinism"]["passes"] == 3
    assert result["reachable_errors_moved"]["link-name"] == ["k1", "k2"]
    assert result["held_out_model_run_count"] == 3
    mech = next(m for m in result["mechanism"] if m["axe_rule"] == "link-name")
    assert mech["distinct_prompts_after"] == 2


def test_determinism_drift_raises() -> None:
    # mixed gold so κ is non-degenerate: one failed + one passed case.
    good = _artifact(
        [
            _case("k1", "Link in context is descriptive", "link-name", "failed", "does_not_support"),  # tp
            _case("p1", "Link in context is descriptive", "link-name", "passed", "supports"),  # tn → κ = 1.0
        ]
    )
    # a pass where the passed case is now flagged (fp) → per-class κ differs → determinism gate fires
    drifted = _artifact(
        [
            _case("k1", "Link in context is descriptive", "link-name", "failed", "does_not_support"),
            _case("p1", "Link in context is descriptive", "link-name", "passed", "does_not_support"),  # fp
        ]
    )
    with pytest.raises(ValueError, match="drifted"):
        score_run_a([good, drifted], _baseline_vector([]), {}, {})
