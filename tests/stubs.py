"""Shared test stubs — canned stand-ins for real components, kept out of `clearway/`.

These are the retired M0 pipeline stubs; production now runs the real RAG `Retriever` + LLM
`Drafter`. They live here (not in `clearway/`) because they are test-only. Two jobs across the
suite: the orchestrator/CLI spine tests inject them so the exit-criterion metric runs offline and
deterministically (which the real, network-bound components can't), and the drafter/validator/eval
unit tests use them as a convenient source of real-shaped citations and rows.
"""

from __future__ import annotations

from clearway.schemas.models import Citation, Conformance, ConformanceLevel, DraftRow, Finding

# axe rule_id -> the correct citation(s) a real retriever should surface for the fixtures.
# The first three are the verifiable `violations` (m0-core@1); the last two are the M1
# `incomplete`-bucket rules — canned here so the offline set run can exercise the UNVERIFIABLE
# path (a real retriever would surface these too; the oracle then returns NO_ORACLE for them).
_CANNED_CITATIONS: dict[str, list[Citation]] = {
    "image-alt": [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A, source="WCAG-SC")],
    "html-has-lang": [Citation(sc_id="3.1.1", title="Language of Page", level=ConformanceLevel.A, source="WCAG-SC")],
    "label": [Citation(sc_id="4.1.2", title="Name, Role, Value", level=ConformanceLevel.A, source="WCAG-SC")],
    "color-contrast": [
        Citation(sc_id="1.4.3", title="Contrast (Minimum)", level=ConformanceLevel.AA, source="WCAG-SC")
    ],
    "video-caption": [
        Citation(sc_id="1.2.2", title="Captions (Prerecorded)", level=ConformanceLevel.A, source="WCAG-SC")
    ],
}

# axe rule_id -> a deliberately WRONG sc_id the canned drafter cites, so eval has known citation
# hallucinations to measure: html-has-lang -> a real-but-wrong SC (fails L1); label -> a
# nonexistent SC (fails L0). The real drafter has no such planting — this is a test device only.
_PLANTED_WRONG_SC: dict[str, str] = {"html-has-lang": "1.1.1", "label": "9.9.9"}
_CANNED_CONFIDENCE = 0.9


def canned_retrieve(finding: Finding) -> list[Citation]:
    """Return canned correct citations for a finding's axe rule (no retrieval). Unknown rules -> []."""
    return [c.model_copy() for c in _CANNED_CITATIONS.get(finding.rule_id, [])]


def canned_draft(finding: Finding, citations: list[Citation]) -> DraftRow:
    """Assemble a deterministic `DraftRow`: cite the retrieved citations, except for the two planted
    fixture rules where it cites a known-wrong SC — giving the spine/eval/validator tests a fixed,
    assertable citation_hallucination_rate offline."""
    wrong_sc = _PLANTED_WRONG_SC.get(finding.rule_id)
    cited = [Citation(sc_id=wrong_sc, source="STUB-PLANTED")] if wrong_sc else [c.model_copy() for c in citations]
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=cited,
        remediation=f"canned draft for rule '{finding.rule_id}'.",
        severity=finding.impact,
        confidence=_CANNED_CONFIDENCE,
    )
