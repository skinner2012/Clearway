"""The `document-title` referent injection: the resolved <title> the drafter has never seen, plus
the page-topic signal it is judged against, appended to that class's user prompt — and to no other.

Four properties, each a way the injection could go wrong:

1. the resolved title lands in the prompt VERBATIM and the topic signal names the tier it came from;
2. a finding with no referent yields the pre-injection prompt exactly (the gate is what keeps the
   injection out of a prompt that has nothing to inject);
3. the field injected is `document_title`, never `accessible_name` — on a `document-title` finding the
   target is `html`, so the accname is a page dump (axe's correct-but-useless answer), and injecting it
   would defeat the point;
4. the helper is empty for every OTHER class (disjoint by class), and the never-injected `empty-heading`
   control is byte-identical even with a full referent — which is what lets one run attribute a movement
   to this class and no other. (The sibling injected classes change via their own blocks, not this one.)

Referents are built directly here (no browser): the injection is a pure function of `Finding.referent`.
"""

from __future__ import annotations

import pytest

from clearway.drafter.llm import _document_title_referent_block, _user_prompt
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

# One retrieved candidate, so the base prompt's citation block renders rather than "(none retrieved)".
_CITATION = Citation(sc_id="2.4.2", url="https://example/2.4.2", source="WCAG-SC")


def _excerpt(text: str, source: ReferentSource) -> ReferentExcerpt:
    return ReferentExcerpt(text=text, source=source)


def _finding(referent: NodeReferent | None, *, rule_id: str = "document-title", target: str = "html") -> Finding:
    return Finding(
        id=f"f:{rule_id}",
        source_url="file://p.html",
        rule_id=rule_id,
        target=target,
        help="quality-review help (irrelevant to the injection delta)",
        html='<html lang="en">',
        source_bucket=AxeBucket.PASSES,
        referent=referent,
    )


def test_resolved_title_is_verbatim_and_the_topic_tier_is_named() -> None:
    ref = NodeReferent(
        document_title=_excerpt("Apple harvesting season", ReferentSource.DOCUMENT_TITLE),
        page_topic=_excerpt("When to pick apples in the Northeast", ReferentSource.H1),
    )
    prompt = _user_prompt(_finding(ref), [_CITATION])
    assert 'Resolved page title: "Apple harvesting season"' in prompt
    assert "When to pick apples in the Northeast" in prompt
    assert "source: h1" in prompt  # the tier is recorded, so a result is never read without knowing it


def test_no_referent_yields_the_pre_injection_prompt_exactly() -> None:
    ref = NodeReferent(
        document_title=_excerpt("Apple harvesting season", ReferentSource.DOCUMENT_TITLE),
        page_topic=_excerpt("When to pick apples in the Northeast", ReferentSource.H1),
    )
    base = _user_prompt(_finding(None), [_CITATION])
    injected = _user_prompt(_finding(ref), [_CITATION])

    assert "Resolved page title" not in base  # gating: nothing is appended without a referent
    expected_block = (
        '\nResolved page title: "Apple harvesting season"'
        '\nPage topic signal (source: h1): "When to pick apples in the Northeast"'
    )
    assert injected == base + expected_block  # the block is the ONLY delta, and base is the old prompt


def test_injects_document_title_not_the_accessible_name_dump() -> None:
    # On a `document-title` finding the target is `html`, so axe's accessible name is the whole page
    # concatenated — correct but useless. The primary referent is the resolved <title>.
    page_dump = "Skip to content Home About Products Blog Contact Sign in " * 12
    ref = NodeReferent(
        accessible_name=_excerpt(page_dump, ReferentSource.ACCESSIBLE_NAME),
        document_title=_excerpt("Clementine harvesting guide", ReferentSource.DOCUMENT_TITLE),
        page_topic=_excerpt("How to harvest clementines", ReferentSource.MAIN),
    )
    prompt = _user_prompt(_finding(ref), [_CITATION])
    assert 'Resolved page title: "Clementine harvesting guide"' in prompt
    assert page_dump not in prompt  # the accname page dump must never reach the prompt
    assert "source: main" in prompt


def test_topic_signal_is_never_injected_without_the_title() -> None:
    # The title is load-bearing: a topic signal alone cannot decide this class, so it is never
    # injected on its own. An absent resolved title gates the whole block out.
    ref = NodeReferent(page_topic=_excerpt("How to harvest clementines", ReferentSource.MAIN))
    assert _document_title_referent_block(_finding(ref)) == ""
    assert _user_prompt(_finding(ref), [_CITATION]) == _user_prompt(_finding(None), [_CITATION])


@pytest.mark.parametrize("rule_id", ["label", "link-name", "empty-heading"])
def test_other_classes_are_byte_identical_even_with_a_full_referent(rule_id: str) -> None:
    full = NodeReferent(
        accessible_name=_excerpt("First name:", ReferentSource.ACCESSIBLE_NAME),
        document_title=_excerpt("Should not leak into another class", ReferentSource.DOCUMENT_TITLE),
        page_topic=_excerpt("Nor should this", ReferentSource.H1),
        section_heading=_excerpt("Shipping", ReferentSource.NEAREST_SECTION_HEADING),
        surrounding_context=_excerpt("Download Ulysses in EPUB", ReferentSource.ANCESTOR_TEXT),
    )
    with_ref = _finding(full, rule_id=rule_id, target="#x")
    without_ref = _finding(None, rule_id=rule_id, target="#x")

    assert _document_title_referent_block(with_ref) == ""  # disjoint by class
    assert "Resolved page title" not in _user_prompt(with_ref, [_CITATION])
    # the sibling injected classes change via their OWN blocks; only the never-injected control is
    # byte-identical at the whole-prompt level.
    if rule_id == "empty-heading":
        assert _user_prompt(with_ref, [_CITATION]) == _user_prompt(without_ref, [_CITATION])
