"""The LLM-as-judge — offline mechanics + a gated live path, mirroring the other client seams.

- **offline** (default): verdict derivation across all four boolean combinations, the judge≠drafter
  guard, recorded provenance, raise-not-fabricate on unparseable output, and the **user-prompt
  template** — pinned as a whole-prompt literal, and separately as what `judge_version` reaches.
- **gated** (`openai_up`): the real cloud judge grades a judgment item, and a face-validity smoke
  confirms it calls obvious right/wrong drafts correctly. Skips when OPENAI_API_KEY is absent.
"""

from __future__ import annotations

import os

import pytest

from clearway.drafter.llm import candidate_lines, referent_blocks
from clearway.judge import (
    CANDIDATE_HEADING,
    BlindAnswer,
    BlindJudge,
    FindingInput,
    Judge,
    JudgeError,
    blind_user_prompt,
    citations_agree,
    conformance_agrees,
    finding_input,
    verdict_from,
)
from clearway.judge import judge as judge_module
from clearway.judge.judge import _BLIND_SYSTEM, _RUBRIC_SYSTEM, blind_version_prompts, version_prompts
from clearway.llm import CloudLLMClient, FakeLLMClient
from clearway.schemas.models import (
    Citation,
    Conformance,
    ConformanceLevel,
    DraftRow,
    Finding,
    JudgeVerdict,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

_JUDGE_MODEL = "cloud-judge"
_DRAFTER_MODEL = "gemma4:31b"

_CANDIDATE = Citation(
    sc_id="1.1.1",
    title="Non-text Content",
    level=ConformanceLevel.A,
    source="WCAG-SC",
    url="https://www.w3.org/TR/WCAG22/#non-text-content",
    text="All non-text content has a text alternative.",
)


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
    result = _judge(_resp(True, True, "right SC and verdict")).judge(
        finding, draft, run_id="run-1", citations=[_CANDIDATE]
    )
    assert result.verdict is JudgeVerdict.CORRECT
    assert result.citation_correct is True
    assert result.conformance_correct is True
    assert result.finding_id == finding.id  # identity from code, never the model
    assert result.run_id == "run-1"
    assert result.judge_model == _JUDGE_MODEL
    assert "prompt=" in result.judge_version  # whole-prompt provenance recorded
    assert result.rationale == "right SC and verdict"


def test_partial_when_exactly_one_dimension_is_wrong() -> None:
    finding = _finding()
    draft = _draft(finding, Conformance.SUPPORTS, "1.1.1")  # over-flagged a poor alt as supports
    result = _judge(_resp(True, False)).judge(finding, draft, run_id="r", citations=[_CANDIDATE])
    assert result.verdict is JudgeVerdict.PARTIAL


def test_judge_must_differ_from_drafter_model() -> None:
    with pytest.raises(ValueError, match="must differ from the drafter model"):
        Judge(FakeLLMClient(model=_DRAFTER_MODEL), drafter_model=_DRAFTER_MODEL)


def test_raises_rather_than_fabricating_on_unparseable_output() -> None:
    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = _judge("not json", "still not json")  # every attempt unparseable → JudgeError
    with pytest.raises(JudgeError):
        judge.judge(finding, draft, run_id="r", citations=[_CANDIDATE])


def test_reasoning_effort_is_folded_into_judge_version() -> None:
    """A client exposing reasoning_effort (like the cloud client) records it in the version pin."""

    class _EffortClient(FakeLLMClient):
        reasoning_effort = "high"

    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = Judge(_EffortClient(_resp(True, True), model=_JUDGE_MODEL), drafter_model=_DRAFTER_MODEL)
    result = judge.judge(finding, draft, run_id="r", citations=[_CANDIDATE])
    assert "effort=high" in result.judge_version


# --- the user prompt: what the judge is shown ---------------------------------

_SENTINEL_CANDIDATE = Citation(
    sc_id="2.4.4",
    title="Link Purpose (In Context)",
    level=ConformanceLevel.A,
    source="WCAG-SC",
    url="https://www.w3.org/TR/WCAG22/#link-purpose-in-context",
    text="The purpose of each link can be determined from the link text alone.",
)


def _sentinel_finding() -> Finding:
    return Finding(
        id="h:link-name",
        source_url="file://q.html",
        rule_id="link-name",
        target="a",
        html='<a href="/x">EPUB</a>',
        help="The link has an accessible name — judge whether it describes the link's purpose.",
        referent=NodeReferent(
            accessible_name=ReferentExcerpt(text="EPUB", source=ReferentSource.ACCESSIBLE_NAME),
            surrounding_context=ReferentExcerpt(
                text="Download Ulysses EPUB", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
            ),
        ),
    )


# The whole user prompt, byte for byte, for a referent-carrying class with one grounded candidate.
#
# ⚠️ A failure here is not a literal to retype — it means the judge's input changed, so any measurement
# taken under the old template (the calibration κ, a frozen baseline) describes an instrument that no
# longer exists. `judge_version` now moves with it, which is a second signal and not a replacement: the
# version string says THAT the prompt moved, this literal says WHAT moved, and only the second is
# readable in a diff.
_EXPECTED_USER_PROMPT = (
    "FINDING\n"
    "- axe rule: link-name\n"
    "- task: The link has an accessible name — judge whether it describes the link's purpose.\n"
    "- target element: a\n"
    '- HTML: <a href="/x">EPUB</a>\n'
    "Referent (captured deterministically at scan time, not by a model):\n"
    'Resolved accessible name: "EPUB"\n'
    "Surrounding context (ancestor depth 2, bounded to at most 3 ancestor levels and 500 characters): "
    '"Download Ulysses EPUB"\n'
    "Link destination: not available — the surrounding context is a proxy for it, not the destination; "
    "judge the link's purpose from the accessible name and surrounding context only, and do not invent "
    "a target URL.\n"
    "Candidate WCAG success criteria retrieved for this finding:\n"
    "- 2.4.4 (https://www.w3.org/TR/WCAG22/#link-purpose-in-context)\n"
    "  What it requires: The purpose of each link can be determined from the link text alone.\n"
    "\n"
    "DRAFTED ROW (grade this)\n"
    "- conformance: does_not_support\n"
    "- cited WCAG SC(s): 2.4.4\n"
    "\n"
    "Grade citation_correct and conformance_correct for this finding."
)


def test_the_whole_user_prompt_is_pinned_line_by_line() -> None:
    finding = _sentinel_finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "2.4.4")
    client = FakeLLMClient(_resp(True, True), model=_JUDGE_MODEL)
    Judge(client, drafter_model=_DRAFTER_MODEL).judge(finding, draft, "r", citations=[_SENTINEL_CANDIDATE])
    assert client.requests[0].user == _EXPECTED_USER_PROMPT, (
        "the judge's user prompt moved. `judge_version` moves with it, so every result taken under the "
        "previous template is now dated — re-read what the change does to any baseline measured under "
        "it, and re-record the pre-flight, before updating this literal"
    )


def test_the_version_hash_reaches_every_prompt_surface_a_judged_finding_can_take() -> None:
    """`judge_version` is provenance only if it covers what actually varies.

    Asserted on the surfaces rather than on the digest: a pin on the hash alone stays green if a
    sentinel silently stops rendering a block, which is the failure that put the referent and the
    candidate list outside the string in the first place. One sentinel cannot do this — the referent
    block is gated by class, so a single rule id leaves two of the three builders unreached.
    """
    surfaces = version_prompts()
    assert surfaces[0] == _RUBRIC_SYSTEM  # the system half is still in there
    joined = "\n".join(surfaces)
    for rule in ("label", "document-title", "link-name", "empty-heading"):
        assert f"- axe rule: {rule}\n" in joined, f"no sentinel renders {rule}"
    for marker in (
        'Resolved accessible name: "',  # label + link-name referent builders
        "Nearest section heading: ",
        'Resolved page title: "',  # document-title referent builder
        "Page topic signal (source: ",
        "Surrounding context (ancestor depth ",
        CANDIDATE_HEADING,  # the candidate block and both of its shapes
        "  What it requires: ",
        "- (none retrieved)",
        "(normative text truncated at ",
        "DRAFTED ROW (grade this)",  # the draft presentation, cited and not
        "- cited WCAG SC(s): (none)",
    ):
        assert marker in joined, f"the version hash does not reach {marker!r}"


def test_the_version_string_moves_when_the_judges_prompt_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property the whole decision rests on: an edit to the user template re-dates every result.

    Exercised through the candidate heading, which lives in the finding side and is exactly the kind of
    wording change the rubric-only hash used to swallow.
    """
    before = Judge(FakeLLMClient(model=_JUDGE_MODEL), drafter_model=_DRAFTER_MODEL).judge_version
    monkeypatch.setattr(judge_module, "CANDIDATE_HEADING", "Some other heading:")
    after = Judge(FakeLLMClient(model=_JUDGE_MODEL), drafter_model=_DRAFTER_MODEL).judge_version
    assert after != before
    assert after.startswith("prompt=")


def test_the_referent_and_the_candidates_are_the_drafters_own_sentences() -> None:
    """Not similar wording — the same wording, produced by the same functions.

    A second reader is only answering the same question if it was given the same facts in the same
    words; a copy of these renderers in the judge would drift one edit later, and a difference between
    the two readers could then be a difference in phrasing rather than in judgment.
    """
    finding = _sentinel_finding()
    block = finding_input(finding, [_SENTINEL_CANDIDATE]).block
    assert referent_blocks(finding) in block
    assert candidate_lines([_SENTINEL_CANDIDATE]) in block
    assert CANDIDATE_HEADING in block


def test_a_class_with_no_referent_injection_contributes_no_referent_line() -> None:
    """The asymmetry between the classes is inherited from the drafter, not introduced here."""
    finding = _finding("empty-heading")
    assert referent_blocks(finding) == ""
    block = finding_input(finding, [_CANDIDATE]).block
    assert "Resolved accessible name" not in block
    assert block.endswith(candidate_lines([_CANDIDATE]))


def test_only_the_draft_presentation_differs_between_two_asks_over_one_finding() -> None:
    """The finding side is one value; a configuration may vary what it appends after it and nothing else.

    Asserted here on two drafts of one finding — the same property the frozen finding-side artifact
    asserts across the two configurations, at the level of the assembly rather than of the file.
    """
    finding = _sentinel_finding()
    prepared = finding_input(finding, [_SENTINEL_CANDIDATE])
    client = FakeLLMClient(_resp(True, True), _resp(False, False), model=_JUDGE_MODEL)
    judge = Judge(client, drafter_model=_DRAFTER_MODEL)
    judge.judge_prepared(prepared, _draft(finding, Conformance.DOES_NOT_SUPPORT, "2.4.4"), "r")
    judge.judge_prepared(prepared, _draft(finding, Conformance.SUPPORTS), "r")
    first, second = client.requests[0].user, client.requests[1].user
    assert first != second, "two different drafts must produce two different asks"
    # The finding side is identical because it is the same bytes, and the whole of the difference sits
    # after it: strip that one prefix off both and what is left is the draft presentation alone.
    assert first.removeprefix(prepared.block) != second.removeprefix(prepared.block)
    assert len(first.removeprefix(prepared.block)) < len(first)  # the prefix was really there
    assert "DRAFTED ROW" not in prepared.block


def test_a_prepared_finding_side_is_sent_verbatim_and_never_re_rendered() -> None:
    """The entry point a two-configuration comparison uses: the frozen bytes are the bytes sent.

    `finding_id` comes off the prepared value rather than a `Finding`, so the assembled result is still
    keyed by code and a caller holding only the frozen block can produce a well-formed `JudgeResult`.
    """
    prepared = FindingInput(finding_id="frozen-1", block="FROZEN FINDING SIDE")
    client = FakeLLMClient(_resp(True, True), model=_JUDGE_MODEL)
    result = Judge(client, drafter_model=_DRAFTER_MODEL).judge_prepared(
        prepared, _draft(_finding(), Conformance.SUPPORTS), "r"
    )
    assert client.requests[0].user.startswith("FROZEN FINDING SIDE\n\nDRAFTED ROW (grade this)")
    assert result.finding_id == "frozen-1"


def test_an_empty_candidate_list_is_rendered_rather_than_omitted() -> None:
    """A caller that retrieved nothing has to be visible in the prompt, not silently equal to one that
    retrieved something — which is also why `citations` has no default."""
    assert "- (none retrieved)" in finding_input(_finding(), []).block


# --- the blind configuration: it answers, and code compares -------------------


def _blind_resp(conformance: str, *sc_ids: str, rationale: str = "because") -> str:
    cited = ", ".join(f'"{s}"' for s in sc_ids)
    return f'{{"conformance":"{conformance}","cited_sc_ids":[{cited}],"rationale":"{rationale}"}}'


def _blind(*responses: str) -> tuple[BlindJudge, FakeLLMClient]:
    client = FakeLLMClient(*responses, model=_JUDGE_MODEL)
    return BlindJudge(client, drafter_model=_DRAFTER_MODEL), client


def _answer(conformance: Conformance, *sc_ids: str) -> BlindAnswer:
    return BlindAnswer(finding_id="f", conformance=conformance, cited_sc_ids=sc_ids, rationale="r")


def test_the_blind_ask_is_the_frozen_finding_side_alone() -> None:
    """The whole of the blinding, asserted on the bytes: nothing is appended to the frozen block."""
    prepared = FindingInput(finding_id="frozen-1", block="FROZEN FINDING SIDE")
    judge, client = _blind(_blind_resp("supports"))
    judge.answer(prepared)
    assert client.requests[0].user == "FROZEN FINDING SIDE"
    assert blind_user_prompt(prepared) == prepared.block


def test_the_blind_judge_is_never_shown_the_draft() -> None:
    """The draft's verdict and its citation appear in neither half of the ask.

    Structural rather than incidental — `answer` takes no draft at all, so there is nothing in scope
    to leak — and asserted anyway on the recorded request, because a rubric could name a draft in
    prose without any caller passing one.
    """
    prepared = FindingInput(finding_id="frozen-1", block="FROZEN FINDING SIDE")
    judge, client = _blind(_blind_resp("does_not_support", "1.1.1"))
    answer = judge.answer(prepared)
    judge.compare(answer, _draft(_finding(), Conformance.PARTIALLY_SUPPORTS, "9.9.9"), "r")
    sent = client.requests[0].system + client.requests[0].user
    assert "9.9.9" not in sent  # the drafted citation
    assert "- conformance: partially_supports" not in sent  # the drafted verdict, as it would be shown
    assert "DRAFTED ROW" not in sent
    assert "- cited WCAG SC(s):" not in sent
    assert len(client.requests) == 1, "comparing a draft must not cost a second call"


@pytest.mark.parametrize(
    "judge_conformance,draft_conformance,agree",
    [
        (Conformance.SUPPORTS, Conformance.SUPPORTS, True),
        (Conformance.PARTIALLY_SUPPORTS, Conformance.DOES_NOT_SUPPORT, False),
        (Conformance.DOES_NOT_SUPPORT, Conformance.PARTIALLY_SUPPORTS, False),
        (Conformance.NOT_APPLICABLE, Conformance.SUPPORTS, False),
    ],
)
def test_conformance_is_compared_raw_and_four_valued(
    judge_conformance: Conformance, draft_conformance: Conformance, agree: bool
) -> None:
    """`partially_supports` != `does_not_support`. The FLAG/CLEAN collapse governs scoring against
    gold, never the comparison of two raters' answers — both emit the same enum, so both are read."""
    finding = _finding()
    assert conformance_agrees(_answer(judge_conformance), _draft(finding, draft_conformance)) is agree


@pytest.mark.parametrize(
    "judge_ids,draft_ids,agree",
    [
        ((), (), True),  # both silent on a clean row — the drafter's own convention
        (("1.1.1",), ("1.1.1",), True),
        (("1.1.1", "1.3.1"), ("1.3.1", "1.1.1"), True),  # a set, so order is not a difference
        ((), ("1.1.1",), False),  # the judge named nothing where the drafter named one
        (("1.1.1",), (), False),  # and the mirror, which is the artefact the spec warns about
        (("1.1.1",), ("1.1.1", "1.3.1"), False),  # a subset is not a match
    ],
)
def test_citations_are_compared_as_exact_sets(
    judge_ids: tuple[str, ...], draft_ids: tuple[str, ...], agree: bool
) -> None:
    finding = _finding()
    answer = _answer(Conformance.SUPPORTS, *judge_ids)
    assert citations_agree(answer, _draft(finding, Conformance.SUPPORTS, *draft_ids)) is agree


def test_the_result_carries_code_derived_booleans_and_this_configurations_provenance() -> None:
    finding = _finding()
    judge, client = _blind(_blind_resp("does_not_support", "1.1.1", rationale="the alt is a filename"))
    result = judge.compare(
        judge.answer(FindingInput(finding_id=finding.id, block="B")),
        _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1"),
        "blind-1",
    )
    assert result.verdict is JudgeVerdict.CORRECT  # both axes agree → the same derivation as anchored
    assert result.citation_correct is True
    assert result.conformance_correct is True
    assert result.finding_id == finding.id
    assert result.run_id == "blind-1"
    assert result.judge_model == _JUDGE_MODEL
    assert result.judge_version.startswith("prompt=")
    assert result.rationale == "the alt is a filename"
    assert len(client.requests) == 1


def test_one_axis_agreeing_is_a_partial_verdict_here_too() -> None:
    finding = _finding()
    judge, _ = _blind(_blind_resp("supports", "1.1.1"))
    result = judge.compare(
        judge.answer(FindingInput(finding_id=finding.id, block="B")),
        _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1"),
        "r",
    )
    assert result.verdict is JudgeVerdict.PARTIAL
    assert (result.citation_correct, result.conformance_correct) == (True, False)


def test_blind_raises_rather_than_fabricating_an_answer() -> None:
    judge, _ = _blind("not json", "still not json")
    with pytest.raises(JudgeError):
        judge.answer(FindingInput(finding_id="f", block="B"))


def test_blind_judge_must_differ_from_the_drafter_model() -> None:
    with pytest.raises(ValueError, match="must differ from the drafter model"):
        BlindJudge(FakeLLMClient(model=_DRAFTER_MODEL), drafter_model=_DRAFTER_MODEL)


def test_the_rubric_carries_the_drafters_citation_convention_and_its_quality_review_stance() -> None:
    """Both are frozen before the run, and neither may be repaired afterwards.

    The convention is the drafter's unwritten habit — cite the criterion you decided against, cite
    nothing when there is no failure — which nobody had ever told a judge; the quality-review stance is
    the framing sentence the drafter's own prompt carries, without which a present-but-inadequate value
    reads as conformant.
    """
    assert "Name NOTHING when you find no failure." in _BLIND_SYSTEM
    assert "the SINGLE most applicable one" in _BLIND_SYSTEM
    assert "present-but-inadequate value is does_not_support or partially_supports, never supports" in _BLIND_SYSTEM
    assert "No other rater's answer is shown to you" in _BLIND_SYSTEM


def test_the_blind_version_hash_reaches_every_finding_side_surface_and_no_draft() -> None:
    """The same surface assertion the anchored configuration carries, minus the half it does not send.

    The draft presentation must be absent: if it reached this hash, a reworded draft block would
    re-date a configuration whose asks it cannot enter.
    """
    surfaces = blind_version_prompts()
    assert surfaces[0] == _BLIND_SYSTEM
    joined = "\n".join(surfaces)
    for rule in ("label", "document-title", "link-name", "empty-heading"):
        assert f"- axe rule: {rule}\n" in joined, f"no sentinel renders {rule}"
    for marker in (
        'Resolved accessible name: "',
        "Nearest section heading: ",
        'Resolved page title: "',
        "Page topic signal (source: ",
        "Surrounding context (ancestor depth ",
        CANDIDATE_HEADING,
        "  What it requires: ",
        "- (none retrieved)",
        "(normative text truncated at ",
    ):
        assert marker in joined, f"the blind version hash does not reach {marker!r}"
    assert "DRAFTED ROW (grade this)" not in joined


def test_the_two_configurations_carry_different_version_strings() -> None:
    """Two prompts, two strings. One string over both would date neither run to what it was sent."""
    client = FakeLLMClient(model=_JUDGE_MODEL)
    anchored = Judge(client, drafter_model=_DRAFTER_MODEL).judge_version
    blind = BlindJudge(client, drafter_model=_DRAFTER_MODEL).judge_version
    assert anchored != blind
    assert anchored.startswith("prompt=") and blind.startswith("prompt=")


def test_the_anchored_string_cannot_be_moved_by_the_blind_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the decision, and the one that protects an already-frozen measurement.

    An edit to the blind rubric must move the blind string and leave the anchored one exactly where it
    was, because the anchored ask it cannot reach is byte-identical either way. The converse is
    already asserted above for the shared finding side, which moves both.
    """
    client = FakeLLMClient(model=_JUDGE_MODEL)
    anchored_before = Judge(client, drafter_model=_DRAFTER_MODEL).judge_version
    blind_before = BlindJudge(client, drafter_model=_DRAFTER_MODEL).judge_version
    monkeypatch.setattr(judge_module, "_BLIND_SYSTEM", "a different blind rubric")
    assert Judge(client, drafter_model=_DRAFTER_MODEL).judge_version == anchored_before
    assert BlindJudge(client, drafter_model=_DRAFTER_MODEL).judge_version != blind_before


def test_the_shared_finding_side_moves_both_configurations(monkeypatch: pytest.MonkeyPatch) -> None:
    """One file feeds both asks, so a reworded line there re-dates both — which is what makes the two
    strings comparable as provenance rather than merely different."""
    client = FakeLLMClient(model=_JUDGE_MODEL)
    before = (
        Judge(client, drafter_model=_DRAFTER_MODEL).judge_version,
        BlindJudge(client, drafter_model=_DRAFTER_MODEL).judge_version,
    )
    monkeypatch.setattr(judge_module, "CANDIDATE_HEADING", "Some other heading:")
    after = (
        Judge(client, drafter_model=_DRAFTER_MODEL).judge_version,
        BlindJudge(client, drafter_model=_DRAFTER_MODEL).judge_version,
    )
    assert after[0] != before[0]
    assert after[1] != before[1]


# --- gated integration: the real cloud judge ---------------------------------

openai_up = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set in the environment")


@openai_up
def test_real_judge_returns_wellformed_result_for_a_judgment_item() -> None:
    """The real cloud judge grades a judgment item into a schema-valid JudgeResult whose model is
    the cloud model (not the drafter) and whose reproducibility provenance is recorded."""
    finding = _finding()
    draft = _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1")
    judge = Judge(CloudLLMClient(), drafter_model=_DRAFTER_MODEL)
    result = judge.judge(finding, draft, run_id="live-1", citations=[_CANDIDATE])
    assert result.judge_model != _DRAFTER_MODEL
    assert result.verdict in (JudgeVerdict.CORRECT, JudgeVerdict.PARTIAL, JudgeVerdict.INCORRECT)
    assert result.rationale
    assert "prompt=" in result.judge_version


@openai_up
def test_face_validity_obvious_correct_and_incorrect_drafts() -> None:
    """Face-validity sanity eyeball, NOT a κ measurement: on an obvious garbage-alt item the judge
    must call a right draft correct and a doubly-wrong draft incorrect. If it cannot get blatant
    cases right, the instrument is broken and there is no point calibrating it."""
    finding = _finding()  # alt="DSC_0042.jpg" — a clear 1.1.1 failure
    judge = Judge(CloudLLMClient(), drafter_model=_DRAFTER_MODEL)
    good = judge.judge(
        finding, _draft(finding, Conformance.DOES_NOT_SUPPORT, "1.1.1"), run_id="fv-good", citations=[_CANDIDATE]
    )
    bad = judge.judge(finding, _draft(finding, Conformance.SUPPORTS, "1.4.3"), run_id="fv-bad", citations=[_CANDIDATE])
    assert good.verdict is JudgeVerdict.CORRECT  # right verdict + right SC
    assert bad.verdict is JudgeVerdict.INCORRECT  # wrong verdict (supports) + irrelevant SC (contrast)
