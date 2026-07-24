"""The violations bucket drafts remediation only — and the judgment buckets are provably untouched.

Two halves, and the first one is the reason the second is allowed to exist:

- **The guard.** A confirmed axe violation no longer asks the model for conformance or citations, so
  the drafter now dispatches on `source_bucket`. That is shared prompt code, and the acceptance
  measurement runs entirely on `AxeBucket.PASSES` findings. So every `passes` prompt — system *and*
  user — is pinned here against an exact expected string literal, captured through the real
  `Drafter` dispatch (not by calling the prompt builders directly), for the four rules the
  measurement scores, using the real `QUALITY_REVIEW_RULES` help text. `INCOMPLETE` is pinned the
  same way. A single changed byte on those paths fails here, loudly, before it can reach a number.
- **The behaviour.** SC ids and conformance for a confirmed violation are assembled in code from
  axe's own tags; the model writes one field.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from clearway.drafter import Drafter, is_fallback_draft
from clearway.drafter.llm import confirmed_violation_sc_ids
from clearway.llm import Completion, LLMUsage
from clearway.normalizer.quality_review import QUALITY_REVIEW_RULES
from clearway.oracle import AxeCoreOracle
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    CitationVerdict,
    Conformance,
    Finding,
    Severity,
)
from clearway.validator import validate


class _RecordingClient:
    """An `LLMClient` that records every (system, user, schema) it is handed and replays canned
    responses. The byte-identity guard asserts on what the drafter *actually sent*, so a change to
    the dispatch is caught as surely as a change to the prompt text."""

    def __init__(self, *responses: str, model: str = "recording-llm") -> None:
        self._responses = list(responses) or ['{"remediation":"x"}']
        self._model = model
        self._i = 0
        self.calls: list[tuple[str, str, type[BaseModel]]] = []

    @property
    def model(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> Completion:
        self.calls.append((system, user, schema))
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return Completion(response, LLMUsage())


def _cite(sc_id: str, url: str) -> Citation:
    return Citation(sc_id=sc_id, url=url, source="WCAG-SC")


def _sent(finding: Finding, citations: list[Citation], *responses: str) -> tuple[str, str, type[BaseModel]]:
    """Drive the real `Drafter` and return the single (system, user, schema) it sent."""
    client = _RecordingClient(*responses)
    Drafter(client).draft(finding, citations)
    (call,) = client.calls
    return call


# --- the guard: judgment-bucket prompts are byte-identical -------------------
#
# Expected literals are written out in full, deliberately. A template computed from the code under
# test would pass whatever the code did; a literal is the only form that can disagree with it.

_JUDGMENT_SYSTEM_PROMPT = (
    "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
    "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
    "Rules:\n"
    "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
    "- cited_sc_ids: only WCAG SC ids from the provided candidates that genuinely apply (may be empty)\n"
    "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
    "- remediation: one concrete sentence on how to fix it\n"
    'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
    '"remediation":"Add a descriptive alt attribute.","confidence":0.9}'
)

_JUDGMENT_RESPONSE = (
    '{"conformance":"does_not_support","cited_sc_ids":["2.4.4"],"remediation":"Rename the link.","confidence":0.9}'
)

# (rule_id, target, html, sc_id, url, expected user prompt) — the four classes the held-out
# acceptance set scores, each with the real quality-review help text.
_PASSES_CASES: list[tuple[str, str, str, str, str, str]] = [
    (
        "link-name",
        'a[href="#desc"]',
        '<a href="#desc">More</a>',
        "2.4.4",
        "https://www.w3.org/TR/WCAG22/#link-purpose-in-context",
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
        "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
        "does_not_support or partially_supports, never supports): axe rule 'link-name' — "
        "The link has an accessible name — judge whether it describes the link's PURPOSE in "
        "context for WCAG 2.4.4; 'click here', 'read more', or a bare URL does NOT.\n"
        'Target element: a[href="#desc"]\n'
        'HTML: <a href="#desc">More</a>\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://www.w3.org/TR/WCAG22/#link-purpose-in-context)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence.",
    ),
    (
        "label",
        "#q",
        '<input id="q" type="text" placeholder="Search">',
        "3.3.2",
        "https://www.w3.org/TR/WCAG22/#labels-or-instructions",
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
        "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
        "does_not_support or partially_supports, never supports): axe rule 'label' — "
        "The form field has a programmatic label — judge whether it clearly identifies the "
        "field's PURPOSE for WCAG 1.3.1 / 3.3.2; a placeholder-as-label or a vague label does NOT.\n"
        "Target element: #q\n"
        'HTML: <input id="q" type="text" placeholder="Search">\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 3.3.2 (https://www.w3.org/TR/WCAG22/#labels-or-instructions)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence.",
    ),
    (
        "document-title",
        "html",
        '<html lang="en">',
        "2.4.2",
        "https://www.w3.org/TR/WCAG22/#page-titled",
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
        "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
        "does_not_support or partially_supports, never supports): axe rule 'document-title' — "
        "The page has a non-empty <title> — judge whether it DESCRIBES the page's topic or purpose "
        "for WCAG 2.4.2; a generic 'Untitled' / 'Home' / boilerplate title does NOT.\n"
        "Target element: html\n"
        'HTML: <html lang="en">\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.2 (https://www.w3.org/TR/WCAG22/#page-titled)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence.",
    ),
    (
        "empty-heading",
        "h2",
        "<h2>Weather</h2>",
        "2.4.6",
        "https://www.w3.org/TR/WCAG22/#headings-and-labels",
        "Finding (a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
        "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
        "does_not_support or partially_supports, never supports): axe rule 'empty-heading' — "
        "The heading has non-empty text — judge whether it DESCRIBES the section's topic for "
        "WCAG 2.4.6; a generic or off-topic heading (e.g. 'Weather' over opening hours) does NOT.\n"
        "Target element: h2\n"
        "HTML: <h2>Weather</h2>\n"
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.6 (https://www.w3.org/TR/WCAG22/#headings-and-labels)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence.",
    ),
]


def _passes_finding(rule_id: str, target: str, html: str) -> Finding:
    """A quality-review finding exactly as the normalizer mints it: the PASSES bucket, carrying the
    reframed `QUALITY_REVIEW_RULES` help — and the WCAG tags axe puts on every rule, so the guard
    proves the tags alone do NOT divert a `passes` finding onto the violations path."""
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://page.html",
        rule_id=rule_id,
        axe_tags=["cat.name-role-value", "wcag2a", "wcag412", "wcag244"],
        target=target,
        html=html,
        help=QUALITY_REVIEW_RULES[rule_id],
        source_bucket=AxeBucket.PASSES,
    )


@pytest.mark.parametrize(
    ("rule_id", "target", "html", "sc_id", "url", "expected"),
    _PASSES_CASES,
    ids=[case[0] for case in _PASSES_CASES],  # the rule id alone — the prompts are far too long for one
)
def test_passes_bucket_prompt_is_byte_identical(
    rule_id: str, target: str, html: str, sc_id: str, url: str, expected: str
) -> None:
    """The acceptance set is drawn entirely from the `passes` bucket, so a violations-only change is
    only safe if it provably cannot reach a `passes` prompt. This is that proof, byte for byte."""
    system, user, schema = _sent(_passes_finding(rule_id, target, html), [_cite(sc_id, url)], _JUDGMENT_RESPONSE)
    assert system == _JUDGMENT_SYSTEM_PROMPT
    assert user == expected
    assert [f for f in schema.model_fields] == ["conformance", "cited_sc_ids", "remediation", "confidence"]


def test_incomplete_bucket_prompt_is_byte_identical() -> None:
    """The needs-review branch is not the subject of this change either, and is pinned the same way."""
    finding = _passes_finding("link-name", 'a[href="#desc"]', '<a href="#desc">More</a>').model_copy(
        update={"source_bucket": AxeBucket.INCOMPLETE}
    )
    system, user, _ = _sent(finding, [_cite("2.4.4", "https://example/2.4.4")], _JUDGMENT_RESPONSE)
    assert system == _JUDGMENT_SYSTEM_PROMPT
    assert user == (
        "Finding (a NEEDS-REVIEW item the scanner could not decide): axe rule 'link-name' — "
        "The link has an accessible name — judge whether it describes the link's PURPOSE in "
        "context for WCAG 2.4.4; 'click here', 'read more', or a bare URL does NOT.\n"
        'Target element: a[href="#desc"]\n'
        'HTML: <a href="#desc">More</a>\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://example/2.4.4)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )


# --- the behaviour: a confirmed violation drafts remediation only ------------


def _violation(rule_id: str = "image-alt", tags: list[str] | None = None, impact: Severity | None = None) -> Finding:
    return Finding(
        id=f"v:{rule_id}",
        source_url="file://page.html",
        rule_id=rule_id,
        axe_tags=["cat.text-alternatives", "wcag2a", "wcag111"] if tags is None else tags,
        target="img",
        html='<img src="cat.png">',
        help="Images must have alternate text",
        impact=impact,
        source_bucket=AxeBucket.VIOLATIONS,
    )


_REMEDIATION = '{"remediation":"Add an alt attribute describing the cat."}'


def test_confirmed_violation_sc_ids_come_from_axe_tags_only_for_the_violations_bucket() -> None:
    assert confirmed_violation_sc_ids(_violation(tags=["wcag2a", "wcag111", "wcag412"])) == ["1.1.1", "4.1.2"]
    assert confirmed_violation_sc_ids(_violation(tags=["cat.structure", "best-practice"])) == []
    # a PASSES finding carries WCAG tags too, but axe confirmed nothing — no derivation applies.
    assert confirmed_violation_sc_ids(_passes_finding("link-name", "a", "<a>x</a>")) == []


def test_violation_conformance_and_citations_are_assembled_from_tags_not_the_model() -> None:
    row = Drafter(_RecordingClient(_REMEDIATION)).draft(
        _violation(impact=Severity.CRITICAL), [_cite("1.1.1", "https://www.w3.org/TR/WCAG22/#non-text-content")]
    )
    assert row.conformance == Conformance.DOES_NOT_SUPPORT  # axe confirmed the failure; code says so
    assert [c.sc_id for c in row.citations] == ["1.1.1"]  # from wcag111, not from the model
    assert row.citations[0].url == "https://www.w3.org/TR/WCAG22/#non-text-content"  # corpus-grounded
    assert row.remediation == "Add an alt attribute describing the cat."  # the model's one field
    assert row.severity == Severity.CRITICAL
    assert row.confidence == 1.0


def test_violation_prompt_states_the_confirmed_criteria_and_asks_only_for_remediation() -> None:
    system, user, schema = _sent(_violation(tags=["wcag2a", "wcag111", "wcag412"]), [], _REMEDIATION)
    assert [f for f in schema.model_fields] == ["remediation"]  # the model cannot return a verdict
    assert "conformance" not in system  # nothing left to judge
    assert "cited_sc_ids" not in system
    assert "1.1.1, 4.1.2" in user  # the fix is written against the criteria axe actually named
    assert "Candidate WCAG success criteria" not in user  # not candidates — settled


def test_violation_sc_ids_are_untouched_by_what_the_model_returns() -> None:
    """Stray keys are ignored, so a model that keeps emitting the old shape cannot smuggle a verdict
    or a citation back in."""
    stray = '{"conformance":"supports","cited_sc_ids":["9.9.9"],"remediation":"Fix it.","confidence":0.1}'
    row = Drafter(_RecordingClient(stray)).draft(_violation(), [])
    assert row.conformance == Conformance.DOES_NOT_SUPPORT
    assert [c.sc_id for c in row.citations] == ["1.1.1"]
    assert row.confidence == 1.0


def test_violation_citation_not_retrieved_is_still_carried_bare() -> None:
    row = Drafter(_RecordingClient(_REMEDIATION)).draft(_violation(), [_cite("4.1.2", "https://example/4.1.2")])
    (citation,) = row.citations
    assert citation.sc_id == "1.1.1"
    assert citation.url == ""  # retrieval missed it; the tag-derived SC still ships


def test_violation_without_recognizable_wcag_tags_keeps_the_judgment_path() -> None:
    """axe's best-practice rules (`region`, `landmark-*`, …) are confirmed violations that map to NO
    success criterion, so there is nothing to assemble. They keep the judgment prompt — which is also
    what keeps `AxeCoreOracle` returning None for them, so their citations stay UNVERIFIABLE and the
    orchestrator's human-review gate still fires. Shipping a citation-less row instead would have
    silently removed that gate."""
    finding = _violation(rule_id="region", tags=["cat.keyboard", "best-practice"])
    system, user, schema = _sent(finding, [_cite("1.3.1", "https://example/1.3.1")], _JUDGMENT_RESPONSE)
    assert system == _JUDGMENT_SYSTEM_PROMPT
    assert "Finding (a CONFIRMED failure): axe rule 'region'" in user
    assert [f for f in schema.model_fields] == ["conformance", "cited_sc_ids", "remediation", "confidence"]


def test_violation_with_no_usable_remediation_retries_then_falls_back() -> None:
    """`remediation` is the only field left, so an empty or missing one is an empty draft, not a
    draft. It must fail validation and degrade — otherwise a blank row would ship looking complete."""
    for bad in ('{"remediation":""}', "{}", "sorry, here is your fix:"):
        row = Drafter(_RecordingClient(bad, bad)).draft(_violation(), [])
        assert is_fallback_draft(row) is True, bad
        assert row.confidence == 0.0
        assert row.citations == []


def test_violation_retries_once_then_succeeds() -> None:
    row = Drafter(_RecordingClient("not json", _REMEDIATION)).draft(_violation(), [])
    assert is_fallback_draft(row) is False
    assert row.remediation == "Add an alt attribute describing the cat."


def test_assembled_violation_citations_verify_against_the_oracle_by_construction() -> None:
    """The honest cost of assembling SC from tags: the drafter and `AxeCoreOracle` now read the same
    tags through the same function, so L1 on a violation can no longer disagree. Every such citation
    is VERIFIED by construction — `citation_hallucination_rate` measures nothing on this bucket any
    more, because the guess it used to grade is gone. Pinned so the tautology is a stated property,
    not a surprise in a later report."""
    finding = _violation(tags=["wcag2a", "wcag111", "wcag412"])
    row = Drafter(_RecordingClient(_REMEDIATION)).draft(finding, [])
    checks = validate(row, finding, AxeCoreOracle())
    assert [c.verdict for c in checks] == [CitationVerdict.VERIFIED, CitationVerdict.VERIFIED]
