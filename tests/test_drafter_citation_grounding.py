"""The candidate criteria reach the drafter with their normative text, and the drafter is told to
spend its citations narrowly.

The text was already being retrieved and then thrown away: `CorpusChunk` carried it, `Citation` did
not, so the prompt named ids and left the model to supply their meaning from memory. These tests hold
down the four things that changing that can break, in order of what a failure would cost:

1. **The text actually arrives, verbatim and bounded.** A budget nobody enforces is a comment, and an
   excerpt that does not say it is one is a lie to the model.
2. **Nothing moves where there is no text.** The block is presence-gated exactly like the referent
   blocks, so a bare `Citation` renders the pre-grounding prompt byte-for-byte — which is what keeps
   the referent injections' own pinned prompts, and the control's, still meaningful.
3. **The drafted row is unchanged.** Corpus prose is a drafting input; letting it ride into
   `DraftRow.citations` would copy the same paragraph into every persisted checkpoint and frozen
   artifact.
4. **The citation budget is in the system prompt, and only there.** It is the one instruction change,
   so its blast radius is pinned rather than described.

No browser, no model, no network — `Finding` / `Citation` are constructed directly.
"""

from __future__ import annotations

import hashlib

import pytest

from clearway.drafter.llm import (
    NORMATIVE_TEXT_CHARS,
    _candidate_lines,
    _document_title_referent_block,
    _label_referent_block,
    _link_name_referent_block,
    _resolve_citations,
    _system_prompt,
    _user_prompt,
)
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    ConformanceLevel,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

# WCAG 2.2's own wording for 2.4.4, as the corpus stores it ("<handle>. <normative text>"), at its
# real length (252 characters) — comfortably inside the budget, so it renders whole.
_SC_2_4_4 = (
    "Link Purpose (In Context). The purpose of each link can be determined from the link text alone "
    "or from the link text together with its programmatically determined link context, except where "
    "the purpose of the link would be ambiguous to users in general"
)

_GROUNDED = Citation(
    sc_id="2.4.4",
    title="Link Purpose (In Context)",
    level=ConformanceLevel.A,
    source="WCAG-SC",
    url="https://www.w3.org/TR/WCAG22/#link-purpose-in-context",
    text=_SC_2_4_4,
)

# The same criterion as retrieval used to hand it over: an id and a url, and nothing about what it
# requires. This is also the shape `_resolve_citations` mints for an SC that was never retrieved.
_BARE = Citation(
    sc_id="2.4.4",
    title="Link Purpose (In Context)",
    level=ConformanceLevel.A,
    source="WCAG-SC",
    url="https://www.w3.org/TR/WCAG22/#link-purpose-in-context",
)


def _finding(rule_id: str = "link-name", referent: NodeReferent | None = None) -> Finding:
    return Finding(
        id=f"f:{rule_id}",
        source_url="file://p.html",
        rule_id=rule_id,
        target="a",
        html='<a href="/d">More</a>',
        help="judge whether the link name describes its purpose",
        source_bucket=AxeBucket.PASSES,
        referent=referent,
    )


# ---------------------------------------------------------------------------
# 1. The text arrives, verbatim and bounded
# ---------------------------------------------------------------------------


def test_the_candidate_block_carries_the_normative_text_verbatim() -> None:
    """The point of the whole change: the model is shown what the criterion requires, not just its
    number. Pinned as whole bytes — an indented line under the id/url line it already had."""
    assert _candidate_lines([_GROUNDED]) == (
        f"- 2.4.4 (https://www.w3.org/TR/WCAG22/#link-purpose-in-context)\n  What it requires: {_SC_2_4_4}"
    )


def test_a_long_criterion_is_prefix_truncated_at_the_pinned_budget_and_says_so() -> None:
    """The budget is enforced, the cut is a PREFIX (WCAG states the requirement first and its
    exceptions after, so a suffix cut would keep the footnotes and lose the rule), and the excerpt
    announces itself — an unmarked excerpt would read as the whole criterion."""
    long_text = "REQUIREMENT. " + "x" * NORMATIVE_TEXT_CHARS + " EXCEPTION-TAIL"
    line = _candidate_lines([_GROUNDED.model_copy(update={"text": long_text})]).splitlines()[1]

    body = line.removeprefix("  What it requires: ")
    assert body.startswith("REQUIREMENT. ")
    assert "EXCEPTION-TAIL" not in body
    assert body.endswith(f" (normative text truncated at {NORMATIVE_TEXT_CHARS} characters)")
    excerpt = body.removesuffix(f" (normative text truncated at {NORMATIVE_TEXT_CHARS} characters)")
    assert excerpt == long_text[:NORMATIVE_TEXT_CHARS]


def test_a_criterion_exactly_at_the_budget_is_whole_and_unmarked() -> None:
    """The boundary: the note claims text was dropped, so it must not appear when none was."""
    exact = "y" * NORMATIVE_TEXT_CHARS
    line = _candidate_lines([_GROUNDED.model_copy(update={"text": exact})]).splitlines()[1]
    assert line == f"  What it requires: {exact}"


def test_the_budget_is_a_pinned_positive_constant() -> None:
    """Pinned like the scanner's referent budgets: a named number that a review can argue with, not a
    magic literal buried in a format string."""
    assert isinstance(NORMATIVE_TEXT_CHARS, int) and NORMATIVE_TEXT_CHARS == 400


def test_the_candidate_block_is_bounded_whatever_retrieval_returns() -> None:
    """The property the budget exists for: five pathological candidates cannot blow up the prompt.
    The bound is per candidate, so what grounding adds is bounded by k and the budget, never by the
    corpus — five 5,000-character criteria add the same as five 400-character ones would."""
    huge = [_GROUNDED.model_copy(update={"sc_id": f"1.1.{i}", "text": "z" * 5_000}) for i in range(5)]
    ungrounded = [c.model_copy(update={"text": ""}) for c in huge]

    added = len(_candidate_lines(huge)) - len(_candidate_lines(ungrounded))
    per_line = (
        len("\n  What it requires: ")
        + NORMATIVE_TEXT_CHARS
        + len(f" (normative text truncated at {NORMATIVE_TEXT_CHARS} characters)")
    )
    assert added == 5 * per_line == 2_330


def test_the_whole_grounded_prompt_is_byte_identical() -> None:
    """The assembled user prompt with a grounded candidate, pinned whole. The pins in
    test_terminology_sweep / test_report_trust_label / test_scanner_referent all use text-less
    citations and so no longer see this block; this is where it is held down."""
    assert _user_prompt(_finding(), [_GROUNDED]) == (
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
        "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
        "does_not_support or partially_supports, never supports): axe rule 'link-name' — judge whether "
        "the link name describes its purpose\n"
        "Target element: a\n"
        'HTML: <a href="/d">More</a>\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://www.w3.org/TR/WCAG22/#link-purpose-in-context)\n"
        f"  What it requires: {_SC_2_4_4}\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )


# ---------------------------------------------------------------------------
# 2. Presence-gated: no text, no change
# ---------------------------------------------------------------------------


def test_a_citation_without_text_renders_the_pre_grounding_line() -> None:
    """Gating, at the block level. `''` is "no grounding chunk supplied one", and the honest render of
    that is silence — an empty `What it requires:` line would assert the criterion requires nothing."""
    assert _candidate_lines([_BARE]) == "- 2.4.4 (https://www.w3.org/TR/WCAG22/#link-purpose-in-context)"


def test_no_candidates_still_renders_the_none_retrieved_marker() -> None:
    assert _candidate_lines([]) == "- (none retrieved)"


@pytest.mark.parametrize("rule_id", ["document-title", "empty-heading", "label", "link-name"])
def test_the_prompt_is_byte_identical_to_the_pre_grounding_prompt_without_text(rule_id: str) -> None:
    """Whole-prompt gating on every measured class, including the control. This is what lets the
    frozen numbers keep describing the prompts that produced them wherever a citation carries no
    text, and it is the same discipline the referent blocks are held to."""
    grounded_off = _user_prompt(_finding(rule_id), [_BARE])
    assert "What it requires:" not in grounded_off
    assert grounded_off.endswith("and your confidence.")


def test_grounding_is_appended_before_the_referent_blocks_not_through_them() -> None:
    """The referent injections are a frozen, already-measured experiment. Grounding lands inside the
    candidate block — ahead of them in the prompt body — and their own bytes are untouched, so the two
    changes compose instead of one rewriting the other."""
    referent = NodeReferent(
        accessible_name=ReferentExcerpt(text="More", source=ReferentSource.ACCESSIBLE_NAME),
        surrounding_context=ReferentExcerpt(
            text="Download Ulysses in HTML", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
        ),
    )
    finding = _finding("link-name", referent)
    prompt = _user_prompt(finding, [_GROUNDED])
    block = _link_name_referent_block(finding)

    assert prompt.endswith(block), "the referent block is still the last thing appended"
    assert prompt.index("What it requires:") < prompt.index("Referent (captured deterministically")
    # the three injections are untouched by grounding: each still keys on class + referent alone
    assert _label_referent_block(finding) == ""
    assert _document_title_referent_block(finding) == ""
    assert _user_prompt(finding, [_BARE]) == _user_prompt(finding, [_BARE.model_copy()])


# ---------------------------------------------------------------------------
# 3. The drafted row stays a reference
# ---------------------------------------------------------------------------


def test_the_resolved_row_citation_drops_the_normative_text() -> None:
    """A drafted row is a reference (id, title, level, url), not a copy of the corpus. Everything else
    survives the resolve, so the row is exactly what it was before grounding existed."""
    (resolved,) = _resolve_citations([_GROUNDED], ["2.4.4"])
    assert resolved.text == ""
    assert resolved == _BARE
    assert _GROUNDED.text == _SC_2_4_4, "the retrieved citation itself must not be mutated"


def test_an_unretrieved_citation_still_resolves_to_a_bare_reference() -> None:
    """The hallucination path is unchanged: an id the corpus never supported still ships, still
    without a url, so the validator and oracle keep catching it."""
    (resolved,) = _resolve_citations([_GROUNDED], ["9.9.9"])
    assert resolved == Citation(sc_id="9.9.9")


def test_a_citation_written_before_the_field_existed_still_validates() -> None:
    """Why `text` is Optional-with-default rather than required. `Citation` is `extra="forbid"` and
    citations are persisted inside `DraftRow`s by orchestrator checkpoints, review records and frozen
    run artifacts written before this field existed. A payload with no `text` key must still load, and
    must load as "no grounding chunk supplied one" rather than fail."""
    payload = _BARE.model_dump()
    del payload["text"]
    assert Citation.model_validate(payload).text == ""
    with pytest.raises(ValueError):
        Citation(sc_id="1.1.1", normative_text="oops")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 4. The citation budget, and where it lives
# ---------------------------------------------------------------------------


def test_the_system_prompt_carries_the_citation_budget() -> None:
    """The budget instructs a narrow citation set with an explicit escape in both directions — a
    second id where the finding independently fails it, and none where none applies — so it cannot be
    read as "always cite exactly one"."""
    assert _system_prompt() == (
        "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
        "- cited_sc_ids: only WCAG SC ids from the provided candidates, and cite the SINGLE most "
        "applicable one — the criterion this finding most directly fails. Add a second only if the "
        "finding independently fails that one too; cite none if none of the candidates applies\n"
        "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
        "- remediation: one concrete sentence on how to fix it\n"
        'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
        '"remediation":"Add a descriptive alt attribute.","confidence":0.9}'
    )
    assert (
        hashlib.sha256(_system_prompt().encode()).hexdigest()
        == "0df2d394e8b79713aea0c42629435287e465c6967ea47b16ed99ecf85cc14b9e"
    )


def test_the_budget_is_the_only_instruction_change_and_it_is_not_in_the_user_prompt() -> None:
    """Blast radius. The budget is a rule about an output field, so it belongs with the other field
    rules; putting it in the user prompt too would restate one instruction in two places that can
    drift apart, and would move every user-prompt pin for a reason unrelated to grounding."""
    user = _user_prompt(_finding(), [_GROUNDED])
    assert "SINGLE most applicable" not in user
    assert "SINGLE most applicable" in _system_prompt()
