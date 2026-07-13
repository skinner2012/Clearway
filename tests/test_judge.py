"""The LLM-as-judge — offline mechanics + a gated live path, mirroring the other client seams.

- **offline** (default): verdict derivation across all four boolean combinations, the judge≠drafter
  guard, recorded provenance, and raise-not-fabricate on unparseable output.
- **gated** (`openai_up`): the real cloud judge grades a judgment item, and a face-validity smoke
  confirms it calls obvious right/wrong drafts correctly. Skips when OPENAI_API_KEY is absent.
"""

from __future__ import annotations

import os

import pytest

from clearway.judge import Judge, JudgeError, verdict_from
from clearway.llm import CloudLLMClient, FakeLLMClient
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
    assert verdict_from(cit, conf) is want


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


# --- gated integration: the real cloud judge ---------------------------------

openai_up = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set in the environment")


@openai_up
def test_real_judge_returns_wellformed_result_for_a_judgment_item() -> None:
    """The real cloud judge grades a judgment item into a schema-valid JudgeResult whose model is
    the cloud model (not the drafter) and whose reproducibility provenance is recorded."""
    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = Judge(CloudLLMClient(), drafter_model=_DRAFTER_MODEL)
    result = judge.judge(finding, draft, run_id="live-1")
    assert result.judge_model != _DRAFTER_MODEL
    assert result.verdict in (JudgeVerdict.CORRECT, JudgeVerdict.PARTIAL, JudgeVerdict.INCORRECT)
    assert result.rationale
    assert "rubric=" in result.judge_version


@openai_up
def test_face_validity_obvious_correct_and_incorrect_drafts() -> None:
    """Face-validity sanity eyeball, NOT a κ measurement: on an obvious garbage-alt item the judge
    must call a right draft correct and a doubly-wrong draft incorrect. If it cannot get blatant
    cases right, the instrument is broken and there is no point calibrating it."""
    finding = _finding()  # alt="DSC_0042.jpg" — a clear 1.1.1 failure
    judge = Judge(CloudLLMClient(), drafter_model=_DRAFTER_MODEL)
    good = judge.judge(finding, _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1"), run_id="fv-good")
    bad = judge.judge(finding, _draft(finding, Conformance.SUPPORTS, "1.4.3"), run_id="fv-bad")
    assert good.verdict is JudgeVerdict.CORRECT  # right verdict + right SC
    assert bad.verdict is JudgeVerdict.INCORRECT  # wrong verdict (supports) + irrelevant SC (contrast)
