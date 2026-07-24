"""The `label` referent block is injected into the `label` prompt — and ONLY there.

Three properties, each a separate risk:

1. Injection carries the resolved accessible name and the nearest section heading (with its
   accessibility-tree note) into the `label` prompt, verbatim — the referent the element snippet
   alone cannot carry.
2. Gating: a `label` finding with no referent produces the pre-injection prompt byte-for-byte, so
   a missing referent can never silently reword the prompt the frozen numbers were measured under.
3. Attribution/control: `document-title`, `link-name` and `empty-heading` findings that DO carry a
   full referent are left byte-identical — the injection is `label`-only, and the experiment's
   control (`empty-heading`) is provably untouched.

`Finding` / `NodeReferent` / `ReferentExcerpt` are constructed directly — no browser, no model.
"""

from __future__ import annotations

from clearway.drafter.llm import _label_referent_block, _user_prompt
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)

# One retrieved candidate so the citation block renders rather than "(none retrieved)".
_CITATION = Citation(sc_id="3.3.2", url="https://example/3.3.2", source="WCAG-SC")

# A full referent — both a resolved accessible name and a section heading in the accessibility
# tree — reused across the control cases to prove they ignore it.
_FULL_REFERENT = NodeReferent(
    accessible_name=ReferentExcerpt(text="Menu", source=ReferentSource.ACCESSIBLE_NAME),
    section_heading=ReferentExcerpt(
        text="Main navigation",
        source=ReferentSource.NEAREST_SECTION_HEADING,
        in_accessibility_tree=True,
    ),
)


def _finding(rule_id: str, referent: NodeReferent | None) -> Finding:
    """A `passes`-bucket quality-review finding of `rule_id`, optionally carrying a referent."""
    return Finding(
        id=f"f:{rule_id}",
        source_url="file://p.html",
        rule_id=rule_id,
        target="#field",
        help="judge whether the label identifies the field's purpose",
        html='<input id="field" type="text">',
        source_bucket=AxeBucket.PASSES,
        referent=referent,
    )


def test_label_prompt_carries_accname_and_heading_verbatim() -> None:
    """The decisive hidden-referent accname (`88a1646138` → "First name:") and a section heading
    with its in-tree note both appear verbatim in the assembled `label` prompt."""
    referent = NodeReferent(
        accessible_name=ReferentExcerpt(text="First name:", source=ReferentSource.ACCESSIBLE_NAME),
        section_heading=ReferentExcerpt(
            text="Shipping address",
            source=ReferentSource.NEAREST_SECTION_HEADING,
            in_accessibility_tree=True,
        ),
    )
    prompt = _user_prompt(_finding("label", referent), [_CITATION])

    assert "First name:" in prompt  # accname verbatim (a trailing colon must survive)
    assert "Shipping address" in prompt  # heading text verbatim
    assert "in accessibility tree: yes" in prompt  # the in-tree note is recorded


def test_label_prompt_records_a_heading_outside_the_accessibility_tree() -> None:
    """`in_accessibility_tree=False` is carried as `no`, not dropped — the flag is a fact even when
    the heading is hidden from screen readers."""
    referent = NodeReferent(
        section_heading=ReferentExcerpt(
            text="Billing",
            source=ReferentSource.NEAREST_SECTION_HEADING,
            in_accessibility_tree=False,
        ),
    )
    prompt = _user_prompt(_finding("label", referent), [_CITATION])
    assert 'Nearest section heading: "Billing" (in accessibility tree: no)' in prompt


def test_label_prompt_without_referent_is_unchanged() -> None:
    """Gating: no referent, no change. The injected block is exactly appended, so the no-referent
    prompt is the with-referent prompt minus the block — and carries none of its markers."""
    referent = NodeReferent(
        accessible_name=ReferentExcerpt(text="First name:", source=ReferentSource.ACCESSIBLE_NAME),
        section_heading=ReferentExcerpt(
            text="Shipping address",
            source=ReferentSource.NEAREST_SECTION_HEADING,
            in_accessibility_tree=True,
        ),
    )
    without = _user_prompt(_finding("label", None), [_CITATION])
    with_ref = _user_prompt(_finding("label", referent), [_CITATION])

    assert "Resolved accessible name:" not in without
    assert "Nearest section heading:" not in without
    assert without.endswith("and your confidence.")  # the original final line, nothing after it
    assert with_ref == without + _label_referent_block(_finding("label", referent))


def test_present_but_empty_accname_is_carried_not_skipped() -> None:
    """An accname source that exists but resolved to '' is a different fact from an absent one, and
    is rendered as empty quotes rather than omitted."""
    referent = NodeReferent(
        accessible_name=ReferentExcerpt(text="", source=ReferentSource.ACCESSIBLE_NAME),
    )
    prompt = _user_prompt(_finding("label", referent), [_CITATION])
    assert 'Resolved accessible name: ""' in prompt


def test_injection_is_label_only_control_classes_untouched() -> None:
    """Attribution: the `label` block is empty for every non-`label` class — asserted at the block
    level for `document-title`, `link-name` and the `empty-heading` control — so a `label`-class
    movement is never this block leaking elsewhere. The sibling injected classes DO change their own
    prompt, but via their OWN blocks (see their tests); the control `empty-heading`, which no ticket
    injects, is byte-identical at the whole-prompt level with and without a full referent."""
    for rule_id in ("document-title", "link-name", "empty-heading"):
        assert _label_referent_block(_finding(rule_id, _FULL_REFERENT)) == "", rule_id
    control_with_ref = _user_prompt(_finding("empty-heading", _FULL_REFERENT), [_CITATION])
    control_without = _user_prompt(_finding("empty-heading", None), [_CITATION])
    assert control_with_ref == control_without
    assert "Resolved accessible name:" not in control_with_ref


def test_helper_returns_empty_when_referent_present_but_holds_no_named_source() -> None:
    """A referent with neither an accessible name nor a section heading (only, say, surrounding
    context) has nothing this block injects, so it stays empty rather than emitting a bare newline."""
    referent = NodeReferent(
        surrounding_context=ReferentExcerpt(text="some neighbourhood text", source=ReferentSource.ANCESTOR_TEXT),
    )
    assert _label_referent_block(_finding("label", referent)) == ""
