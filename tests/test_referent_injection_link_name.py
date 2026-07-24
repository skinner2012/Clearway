"""The `link-name` referent injection: the already-extracted context (and the resolved accessible
name where that is the gap) is placed into the `link-name` drafter prompt, and nowhere else.

This class is INSUFFICIENCY, not degeneracy: every `link-name` case already gets its own prompt, but
none of those prompts carries the deciding fact — what the link is *for*. So the test here is that the
referent is PRESENT in the prompt (verbatim), that it is gated to `link-name` alone, and that a
no-referent finding is byte-for-byte the pre-injection prompt. It is deliberately NOT a test that the
number of distinct prompts rises — for this class that is already maximal and cannot.

No model, no browser: `Finding` / `NodeReferent` / `ReferentExcerpt` are built directly, so this is a
pure-function test of `_user_prompt` and its `_link_name_referent_block` helper.
"""

from __future__ import annotations

from clearway.drafter.llm import _link_name_referent_block, _user_prompt
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

_CITE = Citation(sc_id="2.4.4", url="https://example/2.4.4", source="WCAG-SC")

_DESTINATION_LINE = "Link destination: not available"


def _link_finding(referent: NodeReferent | None) -> Finding:
    """A `link-name` quality-review finding (the PASSES-bucket shape the normalizer mints), optionally
    carrying referent material. Bucket/help are irrelevant to the injected block — the helper gates on
    `rule_id` alone — so they are fixed and the test stays about the referent."""
    return Finding(
        id="f:link-name",
        source_url="file://p.html",
        rule_id="link-name",
        target="#l",
        help="The link has an accessible name — judge whether it describes the link's PURPOSE.",
        html='<a href="#">EPUB</a>',
        source_bucket=AxeBucket.PASSES,
        referent=referent,
    )


def _full_referent() -> NodeReferent:
    """Every per-node field populated — the strongest control input: a non-`link-name` finding must be
    untouched even when it carries the exact accname/context a `link-name` finding would be injected
    with, proving the gate is on `rule_id`, not on which referent fields exist."""
    return NodeReferent(
        accessible_name=ReferentExcerpt(text="Go to the main content.", source=ReferentSource.ACCESSIBLE_NAME),
        document_title=ReferentExcerpt(text="Download page", source=ReferentSource.DOCUMENT_TITLE),
        page_topic=ReferentExcerpt(text="Books to download", source=ReferentSource.H1),
        section_heading=ReferentExcerpt(text="Ulysses", source=ReferentSource.NEAREST_SECTION_HEADING),
        surrounding_context=ReferentExcerpt(
            text="Download Ulysses in EPUB", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
        ),
    )


def test_surrounding_context_is_injected_verbatim_with_its_depth() -> None:
    """A context-gap case: the link text is present but ambiguous, so the neighbourhood decides it.
    The bounded ancestor text must appear verbatim, its depth must be named, and the prompt must be
    honest that the destination is unavailable so the model does not invent one."""
    finding = _link_finding(
        NodeReferent(
            surrounding_context=ReferentExcerpt(
                text="Download Ulysses in EPUB", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
            )
        )
    )
    prompt = _user_prompt(finding, [_CITE])
    expected_context_line = (
        "Surrounding context (ancestor depth 2, bounded to at most 3 ancestor levels and 500 "
        'characters): "Download Ulysses in EPUB"'
    )
    assert "Download Ulysses in EPUB" in prompt  # the extracted context, verbatim
    assert expected_context_line in prompt  # verbatim context + its depth, in one line
    assert _DESTINATION_LINE in prompt  # honest: the model is told not to invent a target
    assert "Resolved accessible name" not in prompt  # accname absent -> its line is omitted, not blank


def test_accessible_name_is_injected_when_it_is_the_gap() -> None:
    """The `aria-labelledby` case (`<a href="#main" aria-labelledby="instructions">`): no link text at
    all, so the referent is the resolved accessible name, computed elsewhere in the DOM."""
    finding = _link_finding(
        NodeReferent(
            accessible_name=ReferentExcerpt(text="Go to the main content.", source=ReferentSource.ACCESSIBLE_NAME)
        )
    )
    prompt = _user_prompt(finding, [_CITE])
    assert 'Resolved accessible name: "Go to the main content."' in prompt  # verbatim accname
    assert _DESTINATION_LINE in prompt
    assert "Surrounding context" not in prompt  # context absent -> its line is omitted


def test_both_present_are_both_injected() -> None:
    """Where both the accname and the surrounding context are available, both are placed in the prompt."""
    finding = _link_finding(_full_referent())
    prompt = _user_prompt(finding, [_CITE])
    assert 'Resolved accessible name: "Go to the main content."' in prompt
    assert "Download Ulysses in EPUB" in prompt


def test_no_referent_prompt_is_byte_identical_to_pre_injection() -> None:
    """Gating: a `link-name` finding with no referent gets exactly the pre-injection prompt — the base
    carries no injection markers — and an injected prompt is precisely that base plus the block. This
    is what keeps the terminology-sweep freeze (which uses no-referent findings) green."""
    with_ref = _link_finding(_full_referent())
    without_ref = with_ref.model_copy(update={"referent": None})

    base = _user_prompt(without_ref, [_CITE])
    assert _DESTINATION_LINE not in base
    assert "Resolved accessible name" not in base
    assert "Surrounding context" not in base

    assert _link_name_referent_block(without_ref) == ""
    assert _user_prompt(with_ref, [_CITE]) == base + _link_name_referent_block(with_ref)


def test_present_but_empty_excerpt_is_kept_distinct_from_absent() -> None:
    """T4's convention, carried through to the prompt: `None` is 'the source was not there' and drops
    the line; a `ReferentExcerpt(text="")` is 'the source was there and blank' and keeps its line. The
    two are different facts and must not be collapsed, so an empty surrounding context still injects."""
    finding = _link_finding(
        NodeReferent(
            surrounding_context=ReferentExcerpt(text="", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=1)
        )
    )
    block = _link_name_referent_block(finding)
    assert (
        'Surrounding context (ancestor depth 1, bounded to at most 3 ancestor levels and 500 characters): ""' in block
    )
    assert _DESTINATION_LINE in block  # a present-but-empty referent is still a referent


def test_link_name_referent_with_no_relevant_excerpts_injects_nothing() -> None:
    """A referent that carries only page-level material (title/topic/heading) but neither the accname
    nor the surrounding context has nothing this class can use, so the block is empty."""
    finding = _link_finding(
        NodeReferent(document_title=ReferentExcerpt(text="Some page", source=ReferentSource.DOCUMENT_TITLE))
    )
    assert _link_name_referent_block(finding) == ""
    assert _DESTINATION_LINE not in _user_prompt(finding, [_CITE])


def test_other_classes_are_unchanged_even_with_a_full_referent() -> None:
    """ATTRIBUTION/CONTROL: the `link-name` block is '' for every non-`link-name` class — asserted for
    `label`, `document-title` and the `empty-heading` control, the disjoint-by-class guarantee the run
    rests on. The sibling injected classes change via their OWN blocks; the control `empty-heading`,
    injected by no block, is additionally byte-identical at the whole-prompt level with and without a
    full referent."""
    for rule_id in ("label", "document-title", "empty-heading"):
        with_ref = Finding(
            id=f"f:{rule_id}",
            source_url="file://p.html",
            rule_id=rule_id,
            target="#x",
            help=f"quality-review help for {rule_id}",
            html="<x/>",
            source_bucket=AxeBucket.PASSES,
            referent=_full_referent(),
        )
        assert _link_name_referent_block(with_ref) == ""
        # the sibling injected classes change via their OWN blocks; only the never-injected control is
        # byte-identical at the whole-prompt level.
        if rule_id == "empty-heading":
            without_ref = with_ref.model_copy(update={"referent": None})
            assert _user_prompt(with_ref, [_CITE]) == _user_prompt(without_ref, [_CITE])
