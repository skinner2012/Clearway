"""The pure draft mutations that give the judge a controlled set of known-wrong drafts to catch:
a conformance flip (wrong verdict) and an SC swap (wrong citation). Both are pure transforms — no
LLM — so they are asserted exactly here; the live judging of the mutants lives in the builder.
"""

from __future__ import annotations

import pytest

from clearway.eval.offline_inject import (
    conformance_flip,
    decoy_sc,
    flip_conformance,
    sc_swap,
)
from clearway.schemas.models import Citation, Conformance, DraftRow


def _draft(conformance: Conformance, *sc: str) -> DraftRow:
    return DraftRow(
        finding_id="f1",
        conformance=conformance,
        citations=[Citation(sc_id=s) for s in sc],
        remediation="original rationale",
        confidence=0.9,
    )


def test_flip_crosses_the_flags_clean_boundary() -> None:
    assert flip_conformance(Conformance.DOES_NOT_SUPPORT) is Conformance.SUPPORTS
    assert flip_conformance(Conformance.PARTIALLY_SUPPORTS) is Conformance.SUPPORTS
    assert flip_conformance(Conformance.SUPPORTS) is Conformance.DOES_NOT_SUPPORT
    assert flip_conformance(Conformance.NOT_APPLICABLE) is Conformance.DOES_NOT_SUPPORT


def test_conformance_flip_changes_only_the_verdict() -> None:
    """A does_not_support draft flips to supports; citations, remediation, confidence are untouched —
    the wrongness is purely the verdict, and nothing an LLM had to re-author."""
    flipped = conformance_flip(_draft(Conformance.DOES_NOT_SUPPORT, "2.4.6"))
    assert flipped.conformance is Conformance.SUPPORTS
    assert [c.sc_id for c in flipped.citations] == ["2.4.6"]
    assert flipped.remediation == "original rationale"
    assert flipped.confidence == 0.9


def test_sc_swap_replaces_citation_with_an_unrelated_decoy() -> None:
    """The cited 2.4.6 becomes a single decoy SC outside the gold and outside the original citation —
    a wrong citation, while the verdict stays put."""
    swapped = sc_swap(_draft(Conformance.DOES_NOT_SUPPORT, "2.4.6"), gold_scs=["2.4.6"])
    cited = [c.sc_id for c in swapped.citations]
    assert cited == ["1.4.3"]  # first decoy not in {2.4.6}
    assert "2.4.6" not in cited
    assert swapped.conformance is Conformance.DOES_NOT_SUPPORT


def test_sc_swap_avoids_both_gold_and_the_drafts_own_citation() -> None:
    """If a decoy happens to be the gold SC or already cited, the swap skips it — the result is always
    a genuinely wrong citation, never an accidental match."""
    swapped = sc_swap(_draft(Conformance.DOES_NOT_SUPPORT, "1.4.3"), gold_scs=["2.1.1"])
    cited = [c.sc_id for c in swapped.citations]
    assert cited == ["1.4.1"]  # 1.4.3 (own) and 2.1.1 (gold) both skipped


def test_decoy_sc_raises_when_all_decoys_excluded() -> None:
    with pytest.raises(ValueError, match="no decoy SC"):
        decoy_sc({"1.4.3", "2.1.1", "1.4.1"})
