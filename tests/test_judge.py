"""The LLM-as-judge — offline mechanics with FakeLLMClient; the gated live path lives elsewhere.

Proven here (no network): verdict derivation across all four boolean combinations, the judge≠drafter
guard, recorded provenance, and raise-not-fabricate on unparseable output.
"""

from __future__ import annotations

import pytest

from clearway.judge import Judge, JudgeError
from clearway.judge.judge import _verdict_from
from clearway.llm import FakeLLMClient
from clearway.schemas.models import Citation, Conformance, DraftRow, Finding, JudgeVerdict

_JUDGE_MODEL = "cloud-judge"
_DRAFTER_MODEL = "gemma4:31b"


def _finding(rule_id: str = "image-alt") -> Finding:
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://q.html",
        rule_id=rule_id,
        target="img",
        html='<img alt="DSC_0042.jpg">',
        help="alt PRESENT — assess meaningfulness for 1.1.1",
    )


def _draft(finding: Finding, conformance: Conformance, *sc_ids: str) -> DraftRow:
    return DraftRow(
        finding_id=finding.id,
        conformance=conformance,
        citations=[Citation(sc_id=s) for s in sc_ids],
        confidence=0.9,
    )


def _resp(citation_correct: bool, conformance_correct: bool, rationale: str = "because") -> str:
    return (
        f'{{"citation_correct":{str(citation_correct).lower()},'
        f'"conformance_correct":{str(conformance_correct).lower()},'
        f'"rationale":"{rationale}"}}'
    )


def _judge(*responses: str) -> Judge:
    return Judge(FakeLLMClient(*responses, model=_JUDGE_MODEL), drafter_model=_DRAFTER_MODEL)


# --- verdict derivation (pure) ------------------------------------------------


@pytest.mark.parametrize(
    "cit,conf,want",
    [
        (True, True, JudgeVerdict.CORRECT),
        (False, False, JudgeVerdict.INCORRECT),
        (True, False, JudgeVerdict.PARTIAL),
        (False, True, JudgeVerdict.PARTIAL),
    ],
)
def test_verdict_is_derived_from_the_two_booleans(cit: bool, conf: bool, want: JudgeVerdict) -> None:
    assert _verdict_from(cit, conf) is want


# --- Judge mechanics (offline: FakeLLMClient) --------------------------------


def test_assembles_result_with_derived_verdict_and_provenance() -> None:
    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    result = _judge(_resp(True, True, "right SC and verdict")).judge(finding, draft, run_id="run-1")
    assert result.verdict is JudgeVerdict.CORRECT
    assert result.citation_correct is True
    assert result.conformance_correct is True
    assert result.finding_id == finding.id  # identity from code, never the model
    assert result.run_id == "run-1"
    assert result.judge_model == _JUDGE_MODEL
    assert "rubric=" in result.judge_version  # rubric-hash provenance recorded
    assert result.rationale == "right SC and verdict"


def test_partial_when_exactly_one_dimension_is_wrong() -> None:
    finding = _finding()
    draft = _draft(finding, Conformance.SUPPORTS, "1.1.1")  # over-flagged a poor alt as supports
    result = _judge(_resp(True, False)).judge(finding, draft, run_id="r")
    assert result.verdict is JudgeVerdict.PARTIAL


def test_judge_must_differ_from_drafter_model() -> None:
    with pytest.raises(ValueError, match="must differ from the drafter model"):
        Judge(FakeLLMClient(model=_DRAFTER_MODEL), drafter_model=_DRAFTER_MODEL)


def test_raises_rather_than_fabricating_on_unparseable_output() -> None:
    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = _judge("not json", "still not json")  # every attempt unparseable → JudgeError
    with pytest.raises(JudgeError):
        judge.judge(finding, draft, run_id="r")


def test_reasoning_effort_is_folded_into_judge_version() -> None:
    """A client exposing reasoning_effort (like the cloud client) records it in the version pin."""

    class _EffortClient(FakeLLMClient):
        reasoning_effort = "high"

    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = Judge(_EffortClient(_resp(True, True), model=_JUDGE_MODEL), drafter_model=_DRAFTER_MODEL)
    result = judge.judge(finding, draft, run_id="r")
    assert "effort=high" in result.judge_version
