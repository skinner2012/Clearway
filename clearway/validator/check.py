"""Citation validator — L0 (enum) + L1 (oracle cross-check). No LLM, no RAG.

Grades each SC cited by a `DraftRow` against two deterministic, free oracles
(ARCHITECTURE §4.8). This is where "measured trust" first becomes a number:
the eval harness (T8) counts these verdicts into `citation_hallucination_rate`.

Ground truth is read **only** through the `Oracle` protocol (never axe internals).
L0 uses the static WCAG 2.2 SC set — a WCAG fact, not oracle ground truth.
"""

from __future__ import annotations

from clearway.oracle import VALID_SC_IDS
from clearway.schemas.models import (
    CitationCheck,
    CitationVerdict,
    DraftRow,
    Finding,
    L1Status,
    Oracle,
    OracleVerdict,
)


def _l1_status(sc_id: str, verdict: OracleVerdict | None) -> L1Status:
    """L1: does the cited SC agree with the oracle's verdict for this finding?"""
    if verdict is None:
        return L1Status.NO_ORACLE
    return L1Status.MATCH if sc_id in verdict.success_criteria else L1Status.MISMATCH


def _verdict(l0_valid: bool, l1_status: L1Status) -> CitationVerdict:
    """Combine L0 + L1 into the graded trust verdict (decision table, §4.8)."""
    if not l0_valid:
        return CitationVerdict.HALLUCINATED  # not a real SC — L0 dominates
    if l1_status is L1Status.MATCH:
        return CitationVerdict.VERIFIED
    if l1_status is L1Status.MISMATCH:
        return CitationVerdict.HALLUCINATED  # real SC, but contradicted by the oracle
    return CitationVerdict.UNVERIFIABLE  # valid SC, no oracle verdict to check against


def check_sc(sc_id: str, verdict: OracleVerdict | None) -> CitationCheck:
    """Validate a single cited SC against a pre-fetched oracle verdict."""
    l0_valid = sc_id in VALID_SC_IDS
    l1_status = _l1_status(sc_id, verdict)
    return CitationCheck(
        sc_id=sc_id,
        l0_valid=l0_valid,
        l1_status=l1_status,
        verdict=_verdict(l0_valid, l1_status),
    )


def validate(draft: DraftRow, finding: Finding, oracle: Oracle) -> list[CitationCheck]:
    """Grade every SC cited by `draft`. One `CitationCheck` per cited citation.

    The oracle is consulted once per finding (its verdict is shared across the
    row's citations), and only via the `Oracle` protocol.
    """
    verdict = oracle.verdict_for(finding)
    return [check_sc(citation.sc_id, verdict) for citation in draft.citations]
