"""Guard for the quality-review terminology sweep: renaming prose changed no model input.

The sweep touched comments, docstrings, Pydantic field descriptions and markdown only — never a
string that reaches the model. This file *pins* that instead of asserting it. The drafter prompt is
a pure function (`clearway.drafter.llm._system_prompt` / `_user_prompt`), so the exact assembled
system and user prompt is frozen here as a literal for the four `passes`-bucket classes the
acceptance benchmark measures.

Two properties make the freeze meaningful rather than circular:

- the finding's `help` is read from the **live** `QUALITY_REVIEW_RULES`, so a reworded rule help
  fails the comparison instead of quietly redefining the expected prompt;
- the expected value is a whole-prompt literal, so an edit to the `AxeBucket.PASSES` framing, the
  candidate-citation block, or the field order fails too.

A failure here does not mean "update the literal" — it means a prose-only change reached the model
input, and the numbers frozen under the old prompt no longer describe the new one.
"""

from __future__ import annotations

import pytest

from clearway.drafter.llm import _system_prompt, _user_prompt
from clearway.normalizer.quality_review import QUALITY_REVIEW_RULES
from clearway.schemas.models import AxeBucket, Citation, Finding

# One retrieved candidate, so the citation block is exercised rather than rendering "(none retrieved)".
_CITATION = Citation(sc_id="2.4.4", url="https://example/2.4.4", source="WCAG-SC")

_EXPECTED_SYSTEM = (
    "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. Output ONLY a single JSON "
    "object matching the schema — no prose, no markdown, no code fences.\n"
    "Rules:\n"
    "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
    "- cited_sc_ids: only WCAG SC ids from the provided candidates that genuinely apply (may be empty)\n"
    "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
    "- remediation: one concrete sentence on how to fix it\n"
    'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"Add a descriptive alt '
    'attribute.","confidence":0.9}'
)

# The four classes measured against ACT gold. Each value is the whole user prompt, byte for byte.
_EXPECTED_USER: dict[str, str] = {
    "document-title": (
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge whether it is "
        "meaningful — assess the CONTENT's quality; present-but-inadequate is does_not_support or partially_supports,"
        " never supports): axe rule 'document-title' — The page has a non-empty <title> — judge whether it DESCRIBES "
        "the page's topic or purpose for WCAG 2.4.2; a generic 'Untitled' / 'Home' / boilerplate title does NOT.\n"
        "Target element: x\n"
        "HTML: <x/>\n"
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://example/2.4.4)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    ),
    "empty-heading": (
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge whether it is "
        "meaningful — assess the CONTENT's quality; present-but-inadequate is does_not_support or partially_supports,"
        " never supports): axe rule 'empty-heading' — The heading has non-empty text — judge whether it DESCRIBES the"
        " section's topic for WCAG 2.4.6; a generic or off-topic heading (e.g. 'Weather' over opening hours) does "
        "NOT.\n"
        "Target element: x\n"
        "HTML: <x/>\n"
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://example/2.4.4)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    ),
    "label": (
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge whether it is "
        "meaningful — assess the CONTENT's quality; present-but-inadequate is does_not_support or partially_supports,"
        " never supports): axe rule 'label' — The form field has a programmatic label — judge whether it clearly "
        "identifies the field's PURPOSE for WCAG 1.3.1 / 3.3.2; a placeholder-as-label or a vague label does NOT.\n"
        "Target element: x\n"
        "HTML: <x/>\n"
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://example/2.4.4)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    ),
    "link-name": (
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge whether it is "
        "meaningful — assess the CONTENT's quality; present-but-inadequate is does_not_support or partially_supports,"
        " never supports): axe rule 'link-name' — The link has an accessible name — judge whether it describes the "
        "link's PURPOSE in context for WCAG 2.4.4; 'click here', 'read more', or a bare URL does NOT.\n"
        "Target element: x\n"
        "HTML: <x/>\n"
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://example/2.4.4)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    ),
}


def _passes_finding(rule_id: str) -> Finding:
    """A `passes`-bucket finding carrying the live quality-review help — the shape the normalizer
    mints for an existence-only rule. `target` / `html` are fixed placeholders: they are the
    per-element part of the prompt, and pinning them keeps the comparison about the rule help and
    the bucket framing, which are what the sweep touched."""
    return Finding(
        id=f"f:{rule_id}",
        source_url="file://p.html",
        rule_id=rule_id,
        target="x",
        help=QUALITY_REVIEW_RULES[rule_id],
        html="<x/>",
        source_bucket=AxeBucket.PASSES,
    )


def test_measured_classes_are_all_still_quality_review_rules() -> None:
    """The freeze only covers a class while that class is still minted. If a rule left the rule set,
    its frozen prompt would silently stop being checked."""
    assert set(_EXPECTED_USER) <= set(QUALITY_REVIEW_RULES)


def test_system_prompt_is_byte_identical() -> None:
    assert _system_prompt() == _EXPECTED_SYSTEM


@pytest.mark.parametrize("rule_id", sorted(_EXPECTED_USER))
def test_passes_bucket_prompt_is_byte_identical(rule_id: str) -> None:
    assert _user_prompt(_passes_finding(rule_id), [_CITATION]) == _EXPECTED_USER[rule_id]
