"""The validator grades cited SCs via L0 (enum) + L1 (oracle), on both stub and real paths.

Two layers, mirroring the drafter/retriever seams:
- **offline** (default): grade hand-built and canned `DraftRow`s to prove the decision table —
  VERIFIED, HALLUCINATED (L0 fail or L1 mismatch), UNVERIFIABLE (no oracle), order, empty.
- **gated** (`ollama_up`): the real path — a live `gemma4:31b` draft graded by `validate()` — proves
  a confirmed violation resolves VERIFIED and a judgment (incomplete-bucket) item resolves
  UNVERIFIABLE. Skips when Ollama is down. (HALLUCINATED stays offline-only: the real model is too
  accurate to force a hallucination deterministically.)
"""

from __future__ import annotations

import urllib.request

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.drafter import Drafter
from clearway.llm import LocalLLMClient
from clearway.oracle import AxeCoreOracle
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    CitationVerdict,
    Conformance,
    ConformanceLevel,
    DraftRow,
    Finding,
    L1Status,
    Severity,
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
        row = canned_draft(finding, canned_retrieve(finding))
        for check in validate(row, finding, ORACLE):
            total += 1
            if check.verdict is CitationVerdict.HALLUCINATED:
                hallucinated += 1
        # each fixture rule drafts exactly one citation
        (check,) = validate(row, finding, ORACLE)
        assert check.verdict is _EXPECTED_VERDICT[rule_id]

    assert (hallucinated, total) == (2, 3)  # citation_hallucination_rate = 2/3


# --- gated integration: real Ollama draft → real validate() -------------------


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


ollama_up = pytest.mark.skipif(not _ollama_up(), reason="Ollama not running (need `ollama serve` + gemma4:31b)")


@ollama_up
def test_real_violation_draft_grades_verified() -> None:
    """A confirmed violation (image-alt → oracle grounds 1.1.1): the real drafter cites 1.1.1 and
    the validator grades it VERIFIED against the axe oracle. Asserts the verdict, not the wording."""
    finding = Finding(
        id="h:image-alt",
        source_url="file://home.html",
        rule_id="image-alt",
        axe_tags=["cat.text-alternatives", "wcag2a", "wcag111"],
        target="img",
        html='<img src="logo.png">',
        impact=Severity.CRITICAL,
        help="Images must have alternate text",
        source_bucket=AxeBucket.VIOLATIONS,
    )
    citations = [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A, source="WCAG-SC")]
    row = Drafter(LocalLLMClient()).draft(finding, citations)
    checks = {c.sc_id: c for c in validate(row, finding, AxeCoreOracle())}
    assert "1.1.1" in checks, f"real drafter did not cite the retrieved SC; cited {list(checks)}"
    check = checks["1.1.1"]
    assert check.l0_valid is True
    assert check.l1_status is L1Status.MATCH
    assert check.verdict is CitationVerdict.VERIFIED


@ollama_up
def test_real_judgment_draft_grades_unverifiable() -> None:
    """A judgment item (color-contrast in the `incomplete` bucket): the oracle can't ground-truth it,
    so however the real drafter cites, the validator must resolve UNVERIFIABLE — the honest 'can't
    self-check yet' verdict that becomes M1's unverifiable_share."""
    finding = Finding(
        id="h:color-contrast",
        source_url="file://home.html",
        rule_id="color-contrast",
        axe_tags=["cat.color", "wcag2aa", "wcag143"],
        target="p.faint",
        html='<p class="faint">hard to read</p>',
        impact=Severity.SERIOUS,
        help="Elements must meet minimum color contrast ratio thresholds",
        source_bucket=AxeBucket.INCOMPLETE,
    )
    citations = [Citation(sc_id="1.4.3", title="Contrast (Minimum)", level=ConformanceLevel.AA, source="WCAG-SC")]
    row = Drafter(LocalLLMClient()).draft(finding, citations)
    checks = validate(row, finding, AxeCoreOracle())
    assert checks, "real drafter cited nothing, so there is no citation to grade"
    for check in checks:
        assert check.l1_status is L1Status.NO_ORACLE
        assert check.verdict is CitationVerdict.UNVERIFIABLE
