"""Mutate correct drafts into KNOWN-wrong ones so the judge's miss-catching can be measured directly.

The drafter is accurate, so it produces too few naturally-wrong drafts to measure the judge's miss
rate (the statistical trap). The fix is mutation testing: manufacture controlled errors and see how
many the judge catches. Two independent mutations, each a pure transform of a `DraftRow`:

  - **conformance flip** — flip the verdict, making a conformance-correct draft wrong.
  - **SC swap** — replace the cited SC with a clearly-unrelated real one, a wrong *citation*.

Both are PURE — no LLM. The conformance flip in particular needs NO rationale regeneration: the judge
rubric grades conformance from the finding + cited SC only and never reads the draft's remediation
prose (see `judge._judge_user_prompt`), so a flipped verdict is not self-contradictory to the judge —
the strawman effect the calibration lesson warns of cannot arise here, and no LLM re-authorship (hence
no authorship bias) is introduced. Each mutation's detection rate is an UPPER BOUND on real
miss-catching (a manufactured error is cleaner, so more catchable, than a natural one).
"""

from __future__ import annotations

from collections.abc import Iterable

from clearway.schemas.models import Citation, Conformance, DraftRow

# Real WCAG 2.2 SCs used as clearly-wrong decoy citations. None overlaps the ACT gold SCs the
# acceptance set uses (2.4.2 / 2.4.4 / 2.4.6 / 2.4.9), so a swap always introduces a genuine error the
# judge should recognise (a contrast/keyboard SC on a link/heading/label finding is plainly irrelevant).
_DECOY_SCS: tuple[str, ...] = ("1.4.3", "2.1.1", "1.4.1")

_FLIP: dict[Conformance, Conformance] = {
    Conformance.DOES_NOT_SUPPORT: Conformance.SUPPORTS,
    Conformance.PARTIALLY_SUPPORTS: Conformance.SUPPORTS,
    Conformance.SUPPORTS: Conformance.DOES_NOT_SUPPORT,
    Conformance.NOT_APPLICABLE: Conformance.DOES_NOT_SUPPORT,
}

RATIONALE_NOTE = (
    "Conformance flip is a pure mutation — no rationale regeneration. The judge rubric grades "
    "conformance from the finding and cited SC only and does not read the draft's remediation prose, so "
    "a flipped verdict is coherent to the judge (not a self-contradictory strawman); no LLM re-authorship "
    "was introduced, avoiding that authorship bias entirely."
)


def flip_conformance(conformance: Conformance) -> Conformance:
    """Flip a verdict across the FLAGS/CLEAN boundary: the two alarm verdicts → `supports`, the two
    clean verdicts → `does_not_support`. A conformance-correct draft becomes conformance-wrong."""
    return _FLIP[conformance]


def decoy_sc(avoid: Iterable[str]) -> str:
    """The first decoy SC not in `avoid` (the gold SCs + the draft's own citations) — a real SC that is
    wrong for the finding. Raises if every decoy is excluded (never happens with the acceptance gold)."""
    blocked = set(avoid)
    for sc in _DECOY_SCS:
        if sc not in blocked:
            return sc
    raise ValueError(f"no decoy SC outside {sorted(blocked)} — widen _DECOY_SCS")


def conformance_flip(draft: DraftRow) -> DraftRow:
    """Flip only the verdict (citations, remediation, confidence untouched) → a known-wrong draft. Apply
    ONLY to a conformance-correct draft, or the flip could accidentally make a wrong draft right."""
    return draft.model_copy(update={"conformance": flip_conformance(draft.conformance)})


def sc_swap(draft: DraftRow, gold_scs: Iterable[str]) -> DraftRow:
    """Replace the cited SC(s) with one clearly-unrelated decoy → a known-wrong citation (the verdict is
    untouched). Avoids the gold SCs and the draft's own SCs so the swap always introduces a real error."""
    avoid = set(gold_scs) | {c.sc_id for c in draft.citations}
    return draft.model_copy(update={"citations": [Citation(sc_id=decoy_sc(avoid))]})
