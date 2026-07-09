"""Expert edit-distance: how far a human moved a drafted row (M2 T4).

The distance is a normalized `[0, 1]` ratio over the `remediation` text (`0` = unedited approval,
higher = more rewriting); `conformance_changed` is the separate categorical companion. The run mean
folds only the `EDITED` reviews — approvals/rejections contribute nothing.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clearway.eval import (
    conformance_changed,
    expert_edit_distance,
    mean_expert_edit_distance,
)
from clearway.schemas.models import (
    Conformance,
    DraftRow,
    NeedsReview,
    ReviewReason,
    ReviewStatus,
)

_AT = datetime(2026, 7, 9, 12, 0, 0)


def _draft(
    *,
    remediation: str,
    conformance: Conformance = Conformance.PARTIALLY_SUPPORTS,
    finding_id: str = "f1",
) -> DraftRow:
    return DraftRow(
        finding_id=finding_id,
        conformance=conformance,
        remediation=remediation,
        confidence=1.0,
    )


def _review(
    draft: DraftRow,
    *,
    status: ReviewStatus,
    edited_draft: DraftRow | None = None,
    run_id: str = "run-1",
) -> NeedsReview:
    return NeedsReview(
        finding_id=draft.finding_id,
        run_id=run_id,
        draft=draft,
        reason=ReviewReason.UNVERIFIABLE_JUDGMENT,
        status=status,
        edited_draft=edited_draft,
        created_at=_AT,
        updated_at=_AT,
    )


# --- expert_edit_distance -----------------------------------------------------


def test_identical_remediation_is_zero_distance() -> None:
    d = _draft(remediation="Add an alt attribute to the image.")
    assert expert_edit_distance(d, d) == 0.0


def test_disjoint_remediation_is_max_distance() -> None:
    original = _draft(remediation="aaaaaa")
    edited = _draft(remediation="ZZZZZZ")
    assert expert_edit_distance(original, edited) == pytest.approx(1.0)


def test_partial_edit_lands_between_zero_and_one() -> None:
    original = _draft(remediation="Add an alt attribute to the image.")
    edited = _draft(remediation="Add a descriptive alt attribute to the image.")
    dist = expert_edit_distance(original, edited)
    assert 0.0 < dist < 1.0
    # complement of difflib's ratio, so it is deterministic and reproducible
    from difflib import SequenceMatcher

    expected = 1.0 - SequenceMatcher(None, original.remediation, edited.remediation).ratio()
    assert dist == pytest.approx(expected)


def test_distance_ignores_conformance_and_other_fields() -> None:
    # Same remediation text, different conformance → text distance is still 0 (the flag tracks that).
    original = _draft(remediation="Same text.", conformance=Conformance.SUPPORTS)
    edited = _draft(remediation="Same text.", conformance=Conformance.DOES_NOT_SUPPORT)
    assert expert_edit_distance(original, edited) == 0.0


# --- conformance_changed ------------------------------------------------------


def test_conformance_changed_detects_a_flip() -> None:
    original = _draft(remediation="x", conformance=Conformance.SUPPORTS)
    edited = _draft(remediation="x", conformance=Conformance.PARTIALLY_SUPPORTS)
    assert conformance_changed(original, edited) is True


def test_conformance_unchanged_when_verdict_kept() -> None:
    original = _draft(remediation="x", conformance=Conformance.SUPPORTS)
    edited = _draft(remediation="y", conformance=Conformance.SUPPORTS)
    assert conformance_changed(original, edited) is False


# --- mean_expert_edit_distance ------------------------------------------------


def test_mean_is_zero_with_no_reviews() -> None:
    assert mean_expert_edit_distance([]) == 0.0


def test_mean_ignores_non_edited_reviews() -> None:
    approved = _review(_draft(remediation="x"), status=ReviewStatus.APPROVED)
    rejected = _review(_draft(remediation="y"), status=ReviewStatus.REJECTED)
    pending = _review(_draft(remediation="z"), status=ReviewStatus.PENDING)
    assert mean_expert_edit_distance([approved, rejected, pending]) == 0.0


def test_mean_averages_only_edited_reviews() -> None:
    unchanged = _draft(remediation="aaaaaa")
    edited_zero = _review(unchanged, status=ReviewStatus.EDITED, edited_draft=unchanged)  # distance 0
    original = _draft(remediation="aaaaaa", finding_id="f2")
    rewritten = _draft(remediation="ZZZZZZ", finding_id="f2")
    edited_one = _review(original, status=ReviewStatus.EDITED, edited_draft=rewritten)  # distance ~1
    # an APPROVED review must not dilute the mean
    approved = _review(_draft(remediation="q", finding_id="f3"), status=ReviewStatus.APPROVED)
    assert mean_expert_edit_distance([edited_zero, edited_one, approved]) == pytest.approx(0.5)
