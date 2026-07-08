"""T5 acceptance: the drafter stub produces valid DraftRows and plants the intended faults."""

from __future__ import annotations

from stubs import canned_retrieve

from clearway.drafter import draft
from clearway.schemas.models import Citation, Conformance, Finding


def _finding(rule_id: str) -> Finding:
    return Finding(id=f"h:{rule_id}", source_url="file://home.html", rule_id=rule_id, target="x", impact=None)


def test_clean_finding_keeps_retrieved_citation() -> None:
    finding = _finding("image-alt")
    row = draft(finding, canned_retrieve(finding))
    assert row.finding_id == finding.id
    assert row.conformance == Conformance.DOES_NOT_SUPPORT
    assert row.confidence == 0.9
    assert [c.sc_id for c in row.citations] == ["1.1.1"]  # correct -> will verify


def test_planted_l1_fault_cites_real_but_wrong_sc() -> None:
    finding = _finding("html-has-lang")
    row = draft(finding, canned_retrieve(finding))
    # truth is 3.1.1; the stub cites 1.1.1 (real SC, wrong one) -> fails L1
    assert [c.sc_id for c in row.citations] == ["1.1.1"]


def test_planted_l0_fault_cites_nonexistent_sc() -> None:
    finding = _finding("label")
    row = draft(finding, canned_retrieve(finding))
    # nonexistent SC -> fails L0
    assert [c.sc_id for c in row.citations] == ["9.9.9"]


def test_planted_fault_overrides_any_input_citation() -> None:
    # even if handed a correct citation, a planted rule still emits the wrong one.
    finding = _finding("label")
    row = draft(finding, [Citation(sc_id="4.1.2")])
    assert [c.sc_id for c in row.citations] == ["9.9.9"]


def test_fixture_rules_yield_expected_cited_scs() -> None:
    cited = {}
    for rule_id in ("image-alt", "html-has-lang", "label"):
        finding = _finding(rule_id)
        row = draft(finding, canned_retrieve(finding))
        cited[rule_id] = [c.sc_id for c in row.citations]
    assert cited == {"image-alt": ["1.1.1"], "html-has-lang": ["1.1.1"], "label": ["9.9.9"]}
