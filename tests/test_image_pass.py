"""One condition's frozen pass: is it the run it says it is?

A pass artifact is the only record that a condition ran. Everything downstream — the descriptive
difference, the null replicates, the endpoint — reads it and cannot re-derive it, so the failures that
matter are the ones that leave a *complete-looking* artifact: a condition short of a sample, a sample
short of a finding, samples that are not actually repeats of the same ask, a text-only condition that
attached a picture.

Every check here is proven to fire by mutating a real pass, built offline through the real drafter
with a canned client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clearway.drafter import Drafter
from clearway.eval.image_conditions import (
    CONDITIONS,
    LEAKY_NO_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_WITH_IMAGE,
    Condition,
)
from clearway.eval.image_pass import (
    build_pass,
    canonical_rows,
    condition_slug,
    partial_path,
    pass_failures,
    pass_path,
    receipt_rows,
)
from clearway.llm import FakeLLMClient

_CANNED = '{"conformance":"supports","cited_sc_ids":["1.1.1"],"remediation":"add a description","confidence":0.7}'


def _build(condition: Condition, tmp_path: Path) -> dict[str, Any]:
    return build_pass(
        condition,
        Drafter(FakeLLMClient(_CANNED)),
        created_at="2026-07-28T00:00:00+00:00",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        checkpoint=tmp_path / "partial.json",
    )


@pytest.fixture(scope="module")
def opaque_pass(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _build(OPAQUE_NO_IMAGE, tmp_path_factory.mktemp("opaque"))


@pytest.fixture(scope="module")
def leaky_pass(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _build(LEAKY_NO_IMAGE, tmp_path_factory.mktemp("leaky"))


# --- the pass is the run it claims to be ------------------------------------


def test_a_pass_carries_every_pre_registered_sample_over_every_pool_finding(opaque_pass: dict[str, Any]) -> None:
    assert [s["sample"] for s in opaque_pass["samples"]] == [1, 2, 3]
    assert [len(s["rows"]) for s in opaque_pass["samples"]] == [7, 7, 7]
    assert pass_failures(opaque_pass) == []


def test_a_pass_records_the_drafted_verdict_and_what_was_sent_on_every_row(opaque_pass: dict[str, Any]) -> None:
    for row in canonical_rows(opaque_pass):
        assert row["draft"]["conformance"] == "supports"
        assert row["draft"]["cited_sc_ids"] == ["1.1.1"]
        assert row["draft"]["confidence"] == 0.7
        assert row["draft"]["remediation"] == "add a description"
        assert row["gold"]["expected"] in {"passed", "failed"}
        assert row["gold"]["gold_success_criteria"] == ["1.1.1"]
        assert row["receipt"]["image_sha256"] is None
        assert len(row["receipt"]["prompt_sha256"]) == 64


def test_the_samples_of_one_condition_are_repeats_of_the_identical_ask(opaque_pass: dict[str, Any]) -> None:
    """What makes three samples *null replicates* rather than three different questions. If the ask
    moved between samples, a disagreement between them would measure the prompt, not the stack."""
    asks: dict[str, set[tuple[str, str]]] = {}
    for sample in opaque_pass["samples"]:
        for row in sample["rows"]:
            key = row["receipt"]["finding_id"]
            asks.setdefault(key, set()).add((row["receipt"]["prompt_sha256"], row["receipt"]["payload_sha256"]))
    assert len(asks) == 7
    assert all(len(seen) == 1 for seen in asks.values())


def test_a_pass_stamps_its_own_condition_s_identity_and_never_another_s(
    opaque_pass: dict[str, Any], leaky_pass: dict[str, Any]
) -> None:
    assert opaque_pass["eval_set_id"] == "act-image-opaque@1"
    assert leaky_pass["eval_set_id"] == "act-image-leaky@1"
    assert {opaque_pass["config_id"], leaky_pass["config_id"]} == {"single-multimodal@1"}
    assert opaque_pass["condition"]["condition"] == OPAQUE_NO_IMAGE.condition_id
    assert leaky_pass["condition"]["samples"] == 1


def test_a_pass_declares_that_its_candidate_criteria_were_pinned_and_not_retrieved(
    opaque_pass: dict[str, Any],
) -> None:
    """The one input a reader cannot recover from the hashes. A run drafted against a pinned candidate
    block and one drafted against live retrieval are different measurements, and the artifact has to
    say which it is."""
    assert opaque_pass["citations"]["source"] == "pinned"
    assert opaque_pass["citations"]["sc_ids"] == ["1.1.1"]
    assert opaque_pass["corpus_version"].startswith("pinned:image-alt@")


def test_the_receipt_rows_are_the_shape_the_cross_condition_check_reads(opaque_pass: dict[str, Any]) -> None:
    """The receipt projection carries the receipt and nothing else, so the claim it supports is about
    what was sent — never about what came back. The endpoint's cross-condition assertion reads these
    rows by name, so the key set is the contract."""
    rows = receipt_rows(opaque_pass)
    assert len(rows) == 21
    assert all(set(row) == set(rows[0]) for row in rows)
    assert set(rows[0]) == {
        "condition",
        "scope",
        "act_testcase_id",
        "finding_id",
        "target",
        "image_sha256",
        "media_type",
        "prompt_sha256",
        "payload_sha256",
    }


# --- every completeness check is proven to fire ------------------------------


def _mutated(artifact: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(json.dumps(artifact)))


def test_a_pass_short_a_sample_fails(opaque_pass: dict[str, Any]) -> None:
    artifact = _mutated(opaque_pass)
    artifact["samples"] = artifact["samples"][:1]
    assert any("1 samples for a condition pre-registered at 3" in f for f in pass_failures(artifact))


def test_a_pass_that_also_rewrote_its_own_declared_sample_count_still_fails(opaque_pass: dict[str, Any]) -> None:
    """The count is taken from the pre-registration, never from the artifact's own claim about itself —
    otherwise a short run that declared itself short would read as complete."""
    artifact = _mutated(opaque_pass)
    artifact["samples"] = artifact["samples"][:1]
    artifact["condition"]["samples"] = 1
    failures = pass_failures(artifact)
    assert any("1 samples for a condition pre-registered at 3" in f for f in failures)
    assert any("declares 1 samples" in f for f in failures)


def test_a_sample_short_a_finding_fails(opaque_pass: dict[str, Any]) -> None:
    artifact = _mutated(opaque_pass)
    artifact["samples"][0]["rows"].pop()
    assert any("sample 1 drafted 6 of 7" in f for f in pass_failures(artifact))


def test_a_sample_that_drafted_one_finding_twice_fails(opaque_pass: dict[str, Any]) -> None:
    """The count check alone would pass: seven rows, one of them a duplicate and one finding absent."""
    artifact = _mutated(opaque_pass)
    artifact["samples"][0]["rows"][1] = _mutated(artifact["samples"][0]["rows"][0])
    assert any("drafted the same finding twice" in f for f in pass_failures(artifact))


def test_samples_drafted_under_different_asks_fail(opaque_pass: dict[str, Any]) -> None:
    artifact = _mutated(opaque_pass)
    artifact["samples"][1]["rows"][0]["receipt"]["prompt_sha256"] = "0" * 64
    assert any("was asked 2 different things across the samples" in f for f in pass_failures(artifact))


def test_the_canonical_sample_is_pass_one(opaque_pass: dict[str, Any]) -> None:
    assert opaque_pass["canonical_sample"] == 1
    assert canonical_rows(opaque_pass) == opaque_pass["samples"][0]["rows"]


def test_a_text_only_condition_that_attached_a_picture_fails(opaque_pass: dict[str, Any]) -> None:
    artifact = _mutated(opaque_pass)
    artifact["samples"][0]["rows"][0]["receipt"]["image_sha256"] = "1" * 64
    assert any("attached a picture and must not" in f for f in pass_failures(artifact))


def test_a_row_belonging_to_another_condition_fails(opaque_pass: dict[str, Any]) -> None:
    artifact = _mutated(opaque_pass)
    artifact["samples"][0]["rows"][0]["receipt"]["condition"] = LEAKY_NO_IMAGE.condition_id
    assert any("carries rows of" in f for f in pass_failures(artifact))


def test_a_fallback_draft_is_never_frozen(tmp_path: Path) -> None:
    """A fallback ships as `does_not_support`@0.0 and would score as a phantom flag — a silent drafter
    failure has to abort the condition rather than freeze one."""
    with pytest.raises(RuntimeError, match="fell back"):
        build_pass(
            LEAKY_NO_IMAGE,
            Drafter(FakeLLMClient("not json at all"), retries=0),
            created_at="2026-07-28T00:00:00+00:00",
            drafter_model="gemma4:31b",
            drafter_model_digest="deadbeef",
            checkpoint=tmp_path / "partial.json",
        )


# --- where a pass lives ------------------------------------------------------


def test_every_condition_has_its_own_file_and_none_shares_a_name() -> None:
    """The namespacing failure this closes is silent in both directions: one condition overwriting
    another's frozen pass, or a scorer sweeping two conditions into one."""
    paths = {condition_slug(c) for c in CONDITIONS}
    assert paths == {"leaky_no_image", "opaque_no_image", "opaque_with_image", "opaque_mismatched_image"}
    assert len({pass_path(c) for c in CONDITIONS}) == 4
    assert pass_path(OPAQUE_WITH_IMAGE).name == "image_opaque_with_image.json"
    assert pass_path(OPAQUE_WITH_IMAGE).parent.name == "runs"


def test_the_checkpoint_is_kept_out_of_the_runs_directory() -> None:
    """A half-written pass in `runs/` would be picked up as a frozen one by anything that globs."""
    assert partial_path(OPAQUE_NO_IMAGE).parent != pass_path(OPAQUE_NO_IMAGE).parent
    assert partial_path(OPAQUE_NO_IMAGE).suffixes == [".partial", ".json"]


def test_a_completed_pass_leaves_no_checkpoint_behind(tmp_path: Path) -> None:
    checkpoint = tmp_path / "partial.json"
    build_pass(
        LEAKY_NO_IMAGE,
        Drafter(FakeLLMClient(_CANNED)),
        created_at="2026-07-28T00:00:00+00:00",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        checkpoint=checkpoint,
    )
    assert not checkpoint.exists()


def test_a_pass_resumes_from_a_checkpoint_instead_of_re_drafting(opaque_pass: dict[str, Any], tmp_path: Path) -> None:
    """A resumed pass keeps the original run identity — a resume that re-stamped `created_at` would
    freeze one measurement under two names — and never re-drafts a sample it already has."""
    checkpoint = tmp_path / "partial.json"
    done = _mutated(opaque_pass)["samples"][:2]
    checkpoint.write_text(json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "samples": done}))

    resumed = build_pass(
        OPAQUE_NO_IMAGE,
        Drafter(
            FakeLLMClient('{"conformance":"does_not_support","cited_sc_ids":[],"remediation":"z","confidence":0.1}')
        ),
        created_at="2026-07-28T00:00:00+00:00",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        checkpoint=checkpoint,
    )

    assert resumed["created_at"] == "2026-01-01T00:00:00+00:00"
    assert resumed["samples"][:2] == done  # kept verbatim, not re-drafted under the new canned answer
    assert resumed["samples"][2]["rows"][0]["draft"]["conformance"] == "does_not_support"
    assert not checkpoint.exists()
