"""T7 acceptance: the validator grades cited SCs via L0 (enum) + L1 (oracle)."""

from __future__ import annotations

from stubs import canned_retrieve

from clearway.drafter import draft
from clearway.oracle import AxeCoreOracle
from clearway.schemas.models import (
    Citation,
    CitationVerdict,
    Conformance,
    DraftRow,
    Finding,
    L1Status,
)
from clearway.validator import validate

ORACLE = AxeCoreOracle()


def _finding(rule_id: str, axe_tags: list[str]) -> Finding:
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://home.html",
        rule_id=rule_id,
        axe_tags=axe_tags,
        target="x",
    )


def _draft(finding: Finding, *sc_ids: str) -> DraftRow:
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=[Citation(sc_id=sc) for sc in sc_ids],
        confidence=0.9,
    )


# --- the three acceptance cases from the ticket -------------------------------


def test_correct_sc_matching_oracle_is_verified() -> None:
    finding = _finding("image-alt", ["wcag2a", "wcag111"])
    (check,) = validate(_draft(finding, "1.1.1"), finding, ORACLE)
    assert check.l0_valid is True
    assert check.l1_status is L1Status.MATCH
    assert check.verdict is CitationVerdict.VERIFIED


def test_nonexistent_sc_is_hallucinated() -> None:
    finding = _finding("label", ["wcag2a", "wcag412"])
    (check,) = validate(_draft(finding, "9.9.9"), finding, ORACLE)
    assert check.l0_valid is False
    assert check.verdict is CitationVerdict.HALLUCINATED


def test_valid_sc_without_oracle_verdict_is_unverifiable() -> None:
    # No wcag SC tag -> AxeCoreOracle returns None -> nothing to check L1 against.
    finding = _finding("region", ["cat.keyboard", "best-practice"])
    (check,) = validate(_draft(finding, "1.1.1"), finding, ORACLE)
    assert check.l0_valid is True
    assert check.l1_status is L1Status.NO_ORACLE
    assert check.verdict is CitationVerdict.UNVERIFIABLE


# --- real-but-wrong SC (L0 passes, L1 contradicts) ----------------------------


def test_real_but_wrong_sc_is_hallucinated_via_mismatch() -> None:
    finding = _finding("html-has-lang", ["wcag2a", "wcag311"])
    (check,) = validate(_draft(finding, "1.1.1"), finding, ORACLE)
    assert check.l0_valid is True
    assert check.l1_status is L1Status.MISMATCH
    assert check.verdict is CitationVerdict.HALLUCINATED


# --- shape: one CitationCheck per cited SC, order preserved -------------------


def test_one_check_per_citation_in_order() -> None:
    finding = _finding("image-alt", ["wcag111"])
    checks = validate(_draft(finding, "1.1.1", "9.9.9"), finding, ORACLE)
    assert [c.sc_id for c in checks] == ["1.1.1", "9.9.9"]
    assert [c.verdict for c in checks] == [
        CitationVerdict.VERIFIED,
        CitationVerdict.HALLUCINATED,
    ]


def test_empty_citations_produce_no_checks() -> None:
    finding = _finding("image-alt", ["wcag111"])
    assert validate(_draft(finding), finding, ORACLE) == []


# --- end-to-end on the fixture rules: retrieve -> draft -> validate -----------
# Exercises the planted faults from T5 and pins the 2/3 shape T8 will compute.

_FIXTURE_TAGS = {
    "image-alt": ["wcag2a", "wcag111"],
    "html-has-lang": ["wcag2a", "wcag311"],
    "label": ["wcag2a", "wcag412"],
}
_EXPECTED_VERDICT = {
    "image-alt": CitationVerdict.VERIFIED,
    "html-has-lang": CitationVerdict.HALLUCINATED,  # planted real-but-wrong 1.1.1 -> L1 mismatch
    "label": CitationVerdict.HALLUCINATED,  # planted fake 9.9.9 -> L0 fail
}


def test_fixture_pipeline_yields_expected_verdicts() -> None:
    hallucinated = 0
    total = 0
    for rule_id, tags in _FIXTURE_TAGS.items():
        finding = _finding(rule_id, tags)
        row = draft(finding, canned_retrieve(finding))
        for check in validate(row, finding, ORACLE):
            total += 1
            if check.verdict is CitationVerdict.HALLUCINATED:
                hallucinated += 1
        # each fixture rule drafts exactly one citation
        (check,) = validate(row, finding, ORACLE)
        assert check.verdict is _EXPECTED_VERDICT[rule_id]

    assert (hallucinated, total) == (2, 3)  # citation_hallucination_rate = 2/3
