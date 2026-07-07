"""M0 retriever STUB — canned `Citation[]` per axe rule. No RAG (that arrives in M1).

Returns the *correct* citation for each known fixture rule, so the drafter has real-shaped
input to draft from. Real `Citation` objects, canned content. Unknown rules -> [].
"""

from __future__ import annotations

from clearway.schemas.models import Citation, ConformanceLevel, Finding

# axe rule_id -> the correct citation(s) a real retriever should surface for the M0 fixtures.
_CANNED_CITATIONS: dict[str, list[Citation]] = {
    "image-alt": [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A, source="WCAG-SC")],
    "html-has-lang": [Citation(sc_id="3.1.1", title="Language of Page", level=ConformanceLevel.A, source="WCAG-SC")],
    "label": [Citation(sc_id="4.1.2", title="Name, Role, Value", level=ConformanceLevel.A, source="WCAG-SC")],
}


def retrieve(finding: Finding) -> list[Citation]:
    """STUB: return canned correct citations for a finding's axe rule (no retrieval)."""
    return [c.model_copy() for c in _CANNED_CITATIONS.get(finding.rule_id, [])]
