"""Expert edit-distance — how much a human changed a drafted row (ARCHITECTURE §4.5, M2 T4).

The HITL gate (orchestrator/, T3) lets a reviewer approve, edit, or reject a flagged `DraftRow`.
An *edit* is the only human-correction signal the pipeline produces, so it is the raw material for
`EvalMetrics.expert_edit_distance`: the mean, over a run's edited reviews, of how far the human
moved the draft. The trend should fall over time as retrieval/drafting improve.

M2 keeps this deliberately simple and stdlib-only (`difflib`) — no `rapidfuzz`, no semantic/LLM
scoring (that is M5 judge territory, per the T4 ticket). The distance is a normalized `[0, 1]`
ratio over the `remediation` text (the primary human-edited free-text field); a separate categorical
`conformance_changed` flag captures the other thing a human commonly changes. The two are kept
distinct on purpose — the scalar stays cleanly in `[0, 1]`; the conformance flag rides alongside as
a metric attribute rather than being folded into the number (M2 keeps it a single aggregate scalar;
a per-field / semantic breakdown is M5).
"""

from __future__ import annotations

from difflib import SequenceMatcher

from clearway.schemas.models import DraftRow, NeedsReview, ReviewStatus


def expert_edit_distance(original: DraftRow, edited: DraftRow) -> float:
    """Normalized `[0, 1]` distance between the drafted and human-edited `remediation` text.

    `0.0` = identical text (an approve-without-edit), `1.0` = no shared subsequence at all.
    `1 - SequenceMatcher.ratio()`: the complement of difflib's similarity ratio.
    """
    ratio = SequenceMatcher(None, original.remediation, edited.remediation).ratio()
    return 1.0 - ratio


def conformance_changed(original: DraftRow, edited: DraftRow) -> bool:
    """Whether the human changed the conformance verdict — the categorical companion to the
    text distance, tracked separately (not folded into the `[0, 1]` scalar)."""
    return original.conformance is not edited.conformance


def mean_expert_edit_distance(reviews: list[NeedsReview]) -> float:
    """Run mean of `expert_edit_distance` over the *edited* reviews in `reviews`.

    Only `status == EDITED` records carry an `edited_draft` to measure against; approvals and
    rejections contribute nothing. With no edits the mean is `0.0` (an honest "no corrections
    needed", matching an unedited approval scoring 0).
    """
    edited = [r for r in reviews if r.status is ReviewStatus.EDITED and r.edited_draft is not None]
    if not edited:
        return 0.0
    total = sum(expert_edit_distance(r.draft, r.edited_draft) for r in edited if r.edited_draft is not None)
    return total / len(edited)
