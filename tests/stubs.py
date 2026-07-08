"""Shared test stubs — canned stand-ins for real components, kept out of `clearway/`.

`canned_retrieve` is the retired canned retriever: canned, *correct* `Citation`s per fixture
rule. It lives here (not in `clearway/`) because it is test-only — the production spine uses the
real RAG `Retriever`. Two jobs across the suite:
- the orchestrator/CLI spine tests inject it so the exit-criterion metrics run offline (they need
  canned-correct citations, which a hash-based `FakeEmbedder` cannot produce);
- the drafter/validator/eval unit tests use it as a convenient source of real-shaped citations.
"""

from __future__ import annotations

from clearway.schemas.models import Citation, ConformanceLevel, Finding

# axe rule_id -> the correct citation(s) a real retriever should surface for the fixtures.
_CANNED_CITATIONS: dict[str, list[Citation]] = {
    "image-alt": [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A, source="WCAG-SC")],
    "html-has-lang": [Citation(sc_id="3.1.1", title="Language of Page", level=ConformanceLevel.A, source="WCAG-SC")],
    "label": [Citation(sc_id="4.1.2", title="Name, Role, Value", level=ConformanceLevel.A, source="WCAG-SC")],
}


def canned_retrieve(finding: Finding) -> list[Citation]:
    """Return canned correct citations for a finding's axe rule (no retrieval). Unknown rules -> []."""
    return [c.model_copy() for c in _CANNED_CITATIONS.get(finding.rule_id, [])]
