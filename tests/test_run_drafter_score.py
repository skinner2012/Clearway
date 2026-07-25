"""The drafter-side numbers a drafter-only run has to carry: recall, false-positive rate, the SC-citation
pair, and the remediation fix-direction.

A run built without the judge cannot go through the judge-inclusive scorecard, and the reason it must go
somewhere is that these are the numbers the written read reports beside the paired thesis. Scoring them off
the same frozen artifact keeps them a pure function of it, with no second model pass.
"""

from __future__ import annotations

from datetime import datetime, timezone

from clearway.eval.referent_injection_score import score_run
from clearway.schemas.models import CaseVerdict, TechniqueMatch, VerdictVector


def _artifact(cases: list[dict]) -> dict:
    return {
        "run_ids": ["citation-grounding-pass1-2026-07-25T00:00:00+00:00"],
        "config_id": "m1-single@1",
        "eval_set_id": "act-acceptance@1",
        "corpus_version": "corpus@1",
        "drafter_model": "gemma4:31b",
        "drafter_model_digest": "deadbeef",
        "axe_core_version": "4.12.1",
        "act_export_hash": "abc",
        "created_at": "2026-07-25T00:00:00+00:00",
        "cases": cases,
        "honest_misses": [],
    }


def _case(tid: str, expected: str, conformance: str, *, cited: list[str] | None = None) -> dict:
    return {
        "act_testcase_id": tid,
        "rule_name": "Link in context is descriptive",
        "axe_rule": "link-name",
        "expected": expected,
        "gold_success_criteria": ["2.4.4"],
        "drafts": [
            {
                "finding_id": f"f-{tid}",
                "target": "x",
                "conformance": conformance,
                "cited_sc_ids": ["2.4.4"] if cited is None else cited,
                "confidence": 0.9,
                "remediation": "Give the link text that describes where it goes.",
            }
        ],
    }


_CASES = [
    _case("k1", "failed", "does_not_support"),
    _case("k2", "failed", "does_not_support"),
    _case("k3", "passed", "supports"),
]


def _vector() -> VerdictVector:
    return VerdictVector(
        partial_flags=True,
        cases=[
            CaseVerdict(
                act_testcase_id=c["act_testcase_id"],
                axe_rule="link-name",
                drafter_flag=c["expected"] == "failed",
                gold_flag=c["expected"] == "failed",
                conformances=["supports"],
            )
            for c in _CASES
        ],
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


def _score(technique_match: TechniqueMatch | None = None) -> dict:
    run = _artifact(_CASES)
    _vec, result = score_run([run, run], _vector(), {}, {}, technique_match=technique_match)
    return result


def _technique_match() -> TechniqueMatch:
    return TechniqueMatch(
        kappa=0.42,
        ci_low=0.1,
        ci_high=0.8,
        n=16,
        raw_agreement=0.688,
        degenerate_share=0.5,
        constant_classifier=False,
        covered_classes=["label", "document-title"],
        uncovered_classes=["link-name", "empty-heading"],
        classifier_model="classifier-model",
        seed=0,
        resamples=10000,
    )


def test_a_drafter_only_run_still_carries_recall_and_false_positive_rate() -> None:
    """These come from the drafter half alone, so the judge's absence is no reason for the read to go
    without them."""
    drafter = _score()["drafter_score"]
    assert drafter["recall"]["value"] == 1.0
    assert drafter["false_positive_rate"]["value"] == 0.0


def test_both_sides_of_the_sc_citation_read_are_reported() -> None:
    """The case-level hit rate alone can only fall when citations narrow, and precision alone rewards
    citing nothing. Reporting one without the other misreads a citation change in whichever direction
    the reader is already leaning."""
    result = _score()
    assert "sc_citation_match" in result["drafter_score"]
    assert "precision" in result["drafter_score_notes"].lower()


def test_the_fix_direction_metric_rides_through_when_its_pass_has_run() -> None:
    result = _score(_technique_match())
    match = result["drafter_score"]["remediation_technique_match"]
    assert match["kappa"] == 0.42
    assert match["covered_classes"] == ["label", "document-title"]


def test_the_fix_direction_metric_is_null_and_says_so_when_its_pass_has_not_run() -> None:
    """Absent is not zero. A missing measurement that renders as a number is the failure this whole
    metric was added to close."""
    result = _score()
    assert result["drafter_score"]["remediation_technique_match"] is None
    assert "None" in result["drafter_score_notes"]


def test_the_fix_direction_metric_is_reported_chance_corrected_never_as_raw_match() -> None:
    """Technique gold is rule-level, so a constant classifier scores ~0.69 raw. The note has to lead with
    the chance-corrected number or the raw one gets quoted."""
    notes = _score(_technique_match())["drafter_score_notes"]
    assert "CHANCE-CORRECTED" in notes
    assert "2 of 4" in notes
