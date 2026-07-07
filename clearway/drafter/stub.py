"""M0 drafter STUB — assembles a `DraftRow` from a Finding + retrieved Citations. No LLM (M1).

It **deliberately** cites a wrong SC for two fixture rules so that eval has known citation
hallucinations to measure (see `fixtures/` and T8). These are intentional planted test faults,
not bugs — they are what makes `citation_hallucination_rate` move off zero.
"""

from __future__ import annotations

from clearway.schemas.models import Citation, Conformance, DraftRow, Finding

_STUB_CONFIDENCE = 0.9

# INTENTIONAL planted citation faults: axe rule_id -> the wrong sc_id the stub cites instead.
#   html-has-lang -> "1.1.1": a real SC but the wrong one (truth is 3.1.1) -> fails L1 (oracle mismatch)
#   label         -> "9.9.9": a nonexistent SC                            -> fails L0 (not a real SC)
_PLANTED_WRONG_SC: dict[str, str] = {
    "html-has-lang": "1.1.1",
    "label": "9.9.9",
}


def draft(finding: Finding, citations: list[Citation]) -> DraftRow:
    """STUB: canned `DraftRow`. For a planted rule the retrieved citation is replaced by a wrong SC."""
    wrong_sc = _PLANTED_WRONG_SC.get(finding.rule_id)
    if wrong_sc is not None:
        cited = [Citation(sc_id=wrong_sc, source="STUB-PLANTED")]
    else:
        cited = [c.model_copy() for c in citations]
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=cited,
        remediation=f"STUB draft for rule '{finding.rule_id}'.",
        severity=finding.impact,
        confidence=_STUB_CONFIDENCE,
    )
