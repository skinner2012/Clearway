"""T4 acceptance: the retriever stub returns valid, correct canned citations per rule."""

from __future__ import annotations

from clearway.retriever import retrieve
from clearway.schemas.models import Citation, ConformanceLevel, Finding


def _finding(rule_id: str) -> Finding:
    return Finding(id=f"h:{rule_id}", source_url="file://home.html", rule_id=rule_id, target="x")


def test_returns_correct_citation_per_fixture_rule() -> None:
    expected = {"image-alt": "1.1.1", "html-has-lang": "3.1.1", "label": "4.1.2"}
    for rule_id, sc_id in expected.items():
        citations = retrieve(_finding(rule_id))
        assert [c.sc_id for c in citations] == [sc_id]
        assert all(isinstance(c, Citation) for c in citations)


def test_citations_are_populated() -> None:
    (citation,) = retrieve(_finding("image-alt"))
    assert citation.title == "Non-text Content"
    assert citation.level == ConformanceLevel.A
    assert citation.source == "WCAG-SC"


def test_unknown_rule_returns_empty() -> None:
    assert retrieve(_finding("color-contrast")) == []
