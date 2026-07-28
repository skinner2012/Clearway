"""The baseline nobody's judgment moved, and the blast radius of the two things that ship.

What is asserted here:

* the detector **catches** a row that reports the absence — the measurement can move, so a zero is a
  result rather than a rule that matches nothing;
* run over every frozen image-condition row it finds **0 of 28** blind rows reporting it, which is
  the number a later measurement of the same question moves from;
* the marking and the contradiction guard are counted over the **whole scoped corpus**, not over the
  seven cases they were designed for;
* and **no frozen artifact of the image experiment moved** — asserted as a diff over the bytes on
  disk, because "the suite is green" is a claim about code and this one is a claim about files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.blind_judgment import DETECTOR_PHRASES, REPORT, build_report, matched_phrase
from clearway.eval.drafter_payload import BASELINE
from clearway.eval.image_conditions import (
    LEAKY_NO_IMAGE,
    OPAQUE_MISMATCHED_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_WITH_IMAGE,
    RECEIPT,
)
from clearway.eval.image_pass import pass_path

# Every artifact of the image experiment that existed before the marking was built, with the digest
# it carried then. The four condition passes cannot be rebuilt — they cost model calls — so a diff
# over their bytes is the only check there is; the other two also have rebuild tests of their own,
# and this is the second direction on the same claim.
FROZEN_BEFORE_THE_MARKING: dict[Path, str] = {
    pass_path(LEAKY_NO_IMAGE): "d5c2c097d11544817ce691e6b461b96914a7bd435ea014c7f1047303f9c314eb",
    pass_path(OPAQUE_NO_IMAGE): "591651eac9079f56714e8781b03468abd60056a5a5742b0e2d13c6d676875f58",
    pass_path(OPAQUE_WITH_IMAGE): "7a3bc574e61b80e705060ed82a8c87b442b15715f06101517f13d566e0e0de06",
    pass_path(OPAQUE_MISMATCHED_IMAGE): "5a313a00560098b6c83239fdcf94b64337568462cc9f368f9cc42e86b624c6ad",
    BASELINE: "ef97ee34a0c56806847ebca0b4170eb22860b207f6bcffb1a834d28f69a024eb",
    RECEIPT: "6eedd358e0be4ac23c5be4e5a01bf569783f8ed1ee04a071378ed5b2d8101758",
}


@pytest.fixture(scope="module")
def frozen() -> dict[str, Any]:
    return dict(json.loads(REPORT.read_text()))


@pytest.fixture(scope="module")
def rebuilt() -> dict[str, Any]:
    """One re-derivation for every comparison below. The blast radius re-scans every scoped case, so
    a fixture per assertion would pay for the same sweep three times over."""
    return build_report()


# --- the rule, before the rows -----------------------------------------------


@pytest.mark.parametrize("phrase", DETECTOR_PHRASES)
def test_every_pinned_phrase_is_caught_in_a_sentence_a_drafter_would_write(phrase: str) -> None:
    """The measurement can move. A rule that matched nothing would report the same zero as a drafter
    that never reports an absence, and only one of those is a finding."""
    assert matched_phrase(f"I {phrase} the image, so add an alt attribute describing it.") == phrase


def test_the_match_is_case_folded() -> None:
    assert matched_phrase("CANNOT SEE the picture") == "cannot see"


def test_a_remediation_that_reports_nothing_matches_nothing() -> None:
    """The shape of every row in the frozen conditions: it speaks of the image in the abstract and
    never says it was unavailable."""
    assert matched_phrase("Replace the alt text so it conveys the image's actual meaning.") is None


# --- the baseline ------------------------------------------------------------


def test_no_blind_row_this_project_has_frozen_reports_the_absence(frozen: dict[str, Any]) -> None:
    measured = frozen["baseline"]
    assert (measured["rows"], measured["blind_rows"]) == (70, 28)
    assert measured["blind_rows_signalling"] == 0
    assert measured["signalling"] == []


def test_the_blind_denominator_is_the_two_conditions_that_attach_nothing(frozen: dict[str, Any]) -> None:
    """28 is 7 + 21, and it is those two conditions rather than whichever rows happen to carry no
    digest — the set's boundary, not the data's surface."""
    blind = {row["condition"] for row in frozen["baseline"]["conditions"] if row["blind"]}
    assert blind == {"leaky/no-image", "opaque/no-image"}


def test_the_baseline_re_derives_from_the_frozen_conditions(frozen: dict[str, Any], rebuilt: dict[str, Any]) -> None:
    assert rebuilt["baseline"] == frozen["baseline"]


# --- the blast radius --------------------------------------------------------


def test_the_marking_is_counted_over_every_scope_and_not_over_the_image_cases(frozen: dict[str, Any]) -> None:
    radius = frozen["blast_radius"]
    assert [scope["scope"] for scope in radius["scopes"]] == ["acceptance", "image-leaky", "image-opaque"]
    assert radius["findings"] == 68  # 54 text findings the marking must not touch, plus the 14 image ones
    assert radius["marking"]["visually_verified_false"] == 14
    assert radius["marking"]["visually_verified_none"] == 54


def test_the_guard_refuses_nothing_as_shipped_and_only_blind_image_rows_when_announced(
    frozen: dict[str, Any],
) -> None:
    """Its zero is structural — the shipped schema carries no field for a claim — and its upper bound
    is what flipping the announcement on would cost against a model that claimed `seen` everywhere."""
    guard = frozen["blast_radius"]["contradiction_guard"]
    assert guard["degraded_as_shipped"] == 0
    assert guard["degraded_when_claiming_seen"] == 14
    assert len(guard["degraded_cases"]) == 7  # the same seven cases, in both image sets


def test_the_blast_radius_re_derives_over_the_live_corpus(frozen: dict[str, Any], rebuilt: dict[str, Any]) -> None:
    """Re-scans every scoped case and re-drafts it through the real drafter with a canned client, so a
    corpus that grew or a rule that joined `PIXEL_DECIDED_RULES` shows up as a moved count rather than
    as a frozen number nobody re-checked."""
    assert rebuilt["blast_radius"] == frozen["blast_radius"]


# --- nothing that was frozen moved -------------------------------------------


@pytest.mark.parametrize("path", FROZEN_BEFORE_THE_MARKING)
def test_no_frozen_artifact_of_the_image_experiment_moved(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == FROZEN_BEFORE_THE_MARKING[path], (
        f"{path.name} changed. The four condition passes are model calls that cannot be re-spent, and "
        "the other two are the controls a prompt change is measured against — a moved one is a "
        "declared change with its own entry in CONTRACTS.md §6, never a test updated to match."
    )
