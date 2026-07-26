"""The payload control: the drafter's requests still hash to what they hashed before the image
channel existed.

The frozen artifact was measured against the drafter as it stood at the commit named in it, so what
is asserted here is not "the builder agrees with itself" but "the prompt this code builds today is
byte-for-byte the prompt the frozen runs were built over". The image classes are covered because the
endpoint needs their text-only condition to be the same text; the one `label` row is the cross-class
check, and it is the class carrying the most recently changed prompt path.

Live scans, not fixtures: a payload is only worth freezing if it is the one a run would actually
send, and that means the same Playwright + axe + normalizer path a run takes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clearway.eval.drafter_payload import (
    BASELINE,
    PINNED_CITATIONS,
    TEXT_CROSS_CHECK_RULE,
    baseline_failures,
    build_baseline,
    citations_for,
    load_baseline,
    payload_for,
    rows_for_scope,
)
from clearway.eval.run_scope import IMAGE_LEAKY, IMAGE_OPAQUE, OutOfScope, cases_for
from clearway.schemas.models import AxeBucket, Finding, Severity

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rebuilt() -> dict[str, Any]:
    """One live rebuild of every controlled payload, shared by the assertions below (15 scans)."""
    return build_baseline()


def test_the_frozen_control_reproduces_through_the_current_prompt_builders(rebuilt: dict[str, Any]) -> None:
    """THE control (M8 Control 6). A single moved byte in any prompt this repo builds fails here,
    naming the case and the two hashes — before a model call is spent on a prompt nobody meant to
    change."""
    failures = baseline_failures(rebuilt["payloads"], load_baseline())
    assert failures == [], "; ".join(failures)


def test_the_control_covers_both_image_sets_and_one_text_class(rebuilt: dict[str, Any]) -> None:
    rows = rebuilt["payloads"]
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_scope.setdefault(row["scope"], []).append(row)
    assert len(by_scope["image-leaky"]) == 7
    assert len(by_scope["image-opaque"]) == 7
    assert [r["axe_rule"] for r in by_scope["acceptance"]] == [TEXT_CROSS_CHECK_RULE]
    assert len(rows) == 15


def test_every_controlled_payload_is_the_no_image_condition(rebuilt: dict[str, Any]) -> None:
    """The control is over the text-only condition — that is what makes it comparable with runs
    frozen before any picture could be attached."""
    assert {row["condition"] for row in rebuilt["payloads"]} == {"no-image"}
    assert {row["image_ref"] for row in rebuilt["payloads"]} == {None}


def test_the_seven_opaque_payloads_are_pairwise_distinct(rebuilt: dict[str, Any]) -> None:
    """Two pool cases whose text-only prompts were identical would be a forced constant classifier on
    the text-only condition, which is the exclusion rule the set was admitted under. Asserted here on
    the *payload*, which is the object the model actually receives."""
    opaque = [row["payload_sha256"] for row in rebuilt["payloads"] if row["scope"] == "image-opaque"]
    assert len(set(opaque)) == len(opaque) == 7


def test_the_ablation_reaches_the_prompt_on_every_case(rebuilt: dict[str, Any]) -> None:
    """Leaky and opaque are the same seven cases with the path cues removed. If any case's two
    payloads hashed the same, the ablation never reached the text the model reads."""
    by_case: dict[str, dict[str, str]] = {}
    for row in rebuilt["payloads"]:
        by_case.setdefault(row["act_testcase_id"], {})[row["scope"]] = row["payload_sha256"]
    paired = {tid: h for tid, h in by_case.items() if len(h) == 2}
    assert len(paired) == 7
    assert all(h["image-leaky"] != h["image-opaque"] for h in paired.values())


def test_no_payload_depends_on_where_this_repository_sits_on_disk() -> None:
    """Why rows are keyed by the case id and not by `finding_id`: the id hashes the case's `file://`
    URL, so it moves with a clone. The payload must not — no prompt carries the URL."""
    case = cases_for(IMAGE_OPAQUE)[0]
    (finding,) = IMAGE_OPAQUE.minting_findings(IMAGE_OPAQUE.root / case["path"], case["axe_rule"])
    request = payload_for(finding, citations_for(case["axe_rule"]))
    everything = request.system + request.user
    assert "file://" not in everything
    assert str(_REPO) not in everything


def test_a_moved_a_missing_and_an_added_payload_all_fail(rebuilt: dict[str, Any]) -> None:
    """The comparison is proven to fire in all three directions, because a control that only catches
    changed values passes happily over a class that stopped minting findings."""
    frozen = load_baseline()
    rows = rebuilt["payloads"]

    moved = [dict(rows[0], payload_sha256="0" * 64), *rows[1:]]
    assert any("payload moved" in f for f in baseline_failures(moved, frozen))

    assert any("was not re-derived" in f for f in baseline_failures(rows[1:], frozen))

    added = [*rows, dict(rows[0], act_testcase_id="never-measured")]
    assert any("not in the frozen control" in f for f in baseline_failures(added, frozen))


def test_an_assembled_path_finding_is_refused_rather_than_hashed() -> None:
    """A confirmed violation whose tags decode to criteria drafts a different prompt under a different
    schema. Hashing it here would freeze a number nothing compares against."""
    violation = Finding(
        id="v1",
        source_url="file:///x.html",
        rule_id="image-alt",
        target="img",
        html='<img src="x.png">',
        impact=Severity.SERIOUS,
        axe_tags=["wcag2a", "wcag111"],
        source_bucket=AxeBucket.VIOLATIONS,
    )
    with pytest.raises(OutOfScope, match="assembled path"):
        payload_for(violation, citations_for("image-alt"))


def test_an_unpinned_class_is_refused_rather_than_drafted_with_no_candidates() -> None:
    assert set(PINNED_CITATIONS) == {"image-alt", TEXT_CROSS_CHECK_RULE}
    with pytest.raises(OutOfScope, match="no pinned citations"):
        citations_for("document-title")


def test_the_rows_come_from_the_scope_and_nothing_else() -> None:
    """The work list is the scope's, so a payload can never be controlled over a case set the scope
    does not cover (the whole reason `RunScope` exists)."""
    rows = rows_for_scope(IMAGE_LEAKY)
    assert {row["scope"] for row in rows} == {"image-leaky"}
    assert [row["act_testcase_id"] for row in rows] == [c["act_testcase_id"] for c in cases_for(IMAGE_LEAKY)]
    assert BASELINE.name == "drafter_payload_baseline.json"
