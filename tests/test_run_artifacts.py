"""Artifact namespacing: two acceptance runs must never share a filename, and a frozen pass is never
overwritten in place. Both failures are silent when they happen, which is what these tests exist to stop."""

from __future__ import annotations

from pathlib import Path

import pytest

from clearway.eval.run_artifacts import (
    CITATION_GROUNDING,
    REFERENT_INJECTION,
    RUN_LABELS,
    FrozenRunExists,
    UnknownRunLabel,
    dry_gate_path,
    partial_path,
    passes_in,
    refuse_to_overwrite,
    require_label,
    result_path,
    run_path,
    verdict_vector_path,
)


def test_referent_injection_label_reproduces_the_already_frozen_filenames() -> None:
    """Labelling must not rename anything already frozen. These five names are the artifacts the
    referent-injection run committed; if a label change moved one, the frozen record would be orphaned
    and every reference to it in the repo would dangle."""
    assert run_path(REFERENT_INJECTION, 1).name == "referent_injection_run_1.json"
    assert run_path(REFERENT_INJECTION, 3).name == "referent_injection_run_3.json"
    assert dry_gate_path(REFERENT_INJECTION).name == "referent_injection_dry_gate.json"
    assert result_path(REFERENT_INJECTION).name == "referent_injection_result.json"
    assert verdict_vector_path(REFERENT_INJECTION).name == "referent_injection_verdict_vector.json"


def test_the_two_labels_collide_on_no_artifact_path() -> None:
    """The whole point of the label. A shared path means the second run silently overwrites the first,
    and the first is the comparison the second is measured against."""
    for builder in (dry_gate_path, result_path, verdict_vector_path):
        assert builder(REFERENT_INJECTION) != builder(CITATION_GROUNDING)
    for pass_n in (1, 2, 3):
        assert run_path(REFERENT_INJECTION, pass_n) != run_path(CITATION_GROUNDING, pass_n)
        assert partial_path(REFERENT_INJECTION, pass_n) != partial_path(CITATION_GROUNDING, pass_n)


def test_a_partial_never_lands_beside_a_frozen_pass() -> None:
    """The checkpoint is gitignored working state; the pass artifact is the frozen record. Keeping them
    in separate directories is what lets `passes_in` glob without excluding the checkpoints by name."""
    assert partial_path(REFERENT_INJECTION, 1).parent != run_path(REFERENT_INJECTION, 1).parent


def test_passes_in_returns_only_its_own_labels_passes(tmp_path: Path) -> None:
    """The glob-mixing bug: sweeping both runs' passes into one determinism check would compare the two
    runs against each other and report the intended prompt change as a determinism drift."""
    for name in (
        "referent_injection_run_1.json",
        "referent_injection_run_2.json",
        "citation_grounding_run_1.json",
        "citation_grounding_run_2.json",
        "citation_grounding_run_3.json",
    ):
        (tmp_path / name).write_text("{}")

    assert [p.name for p in passes_in(tmp_path, REFERENT_INJECTION)] == [
        "referent_injection_run_1.json",
        "referent_injection_run_2.json",
    ]
    assert [p.name for p in passes_in(tmp_path, CITATION_GROUNDING)] == [
        "citation_grounding_run_1.json",
        "citation_grounding_run_2.json",
        "citation_grounding_run_3.json",
    ]


def test_passes_in_orders_numerically_not_lexically(tmp_path: Path) -> None:
    """Pass 1 is canonical, so the order the passes are read in decides which artifact the verdict vector
    is built from. A lexical sort puts pass 10 before pass 2."""
    for n in (1, 2, 3, 10):
        (tmp_path / f"referent_injection_run_{n}.json").write_text("{}")
    assert [p.name for p in passes_in(tmp_path, REFERENT_INJECTION)] == [
        "referent_injection_run_1.json",
        "referent_injection_run_2.json",
        "referent_injection_run_3.json",
        "referent_injection_run_10.json",
    ]


def test_passes_in_ignores_files_that_are_not_a_numbered_pass(tmp_path: Path) -> None:
    """A checkpoint or a hand-named experiment sitting in the directory must not be read as a pass and
    fed into the determinism sweep."""
    for name in (
        "referent_injection_run_1.json",
        "referent_injection_run_1.partial.json",
        "referent_injection_run_draft.json",
        "referent_injection_result.json",
    ):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in passes_in(tmp_path, REFERENT_INJECTION)] == ["referent_injection_run_1.json"]


def test_passes_in_is_empty_when_the_run_has_not_been_built(tmp_path: Path) -> None:
    assert passes_in(tmp_path, CITATION_GROUNDING) == []


@pytest.mark.parametrize("label", RUN_LABELS)
def test_every_declared_label_is_accepted(label: str) -> None:
    assert require_label(label) == label


def test_an_unknown_label_is_refused_rather_than_opening_a_new_namespace() -> None:
    """A typo must not quietly create a third set of files that no scorer will ever look for."""
    with pytest.raises(UnknownRunLabel, match="unknown run label"):
        run_path("referent-injection", 1)


def test_refuse_to_overwrite_raises_on_an_existing_frozen_pass(tmp_path: Path) -> None:
    """The guard that makes the separation hold even if a label is passed wrong: a frozen pass is
    superseded by deleting it deliberately, never by a build silently writing over it."""
    frozen = tmp_path / "referent_injection_run_1.json"
    frozen.write_text("{}")
    with pytest.raises(FrozenRunExists, match="delete"):
        refuse_to_overwrite(frozen)


def test_refuse_to_overwrite_passes_when_nothing_is_frozen_there(tmp_path: Path) -> None:
    refuse_to_overwrite(tmp_path / "citation_grounding_run_1.json")


# Artifact filenames belong to `run_artifacts` and nowhere else. A harness module that rebuilds one from
# a string literal is how the namespacing gets bypassed: it keeps working for the run whose name happens
# to be baked in, and silently reads or writes that run's files for every other. Grepped rather than
# argued, because the failure reappears one call site at a time.
_HARNESS_DIR = Path(__file__).resolve().parents[1] / "clearway" / "eval"
_ARTIFACT_LITERALS = ("_run_1.json", "_run_2.json", "_run_3.json", "_dry_gate.json", "_verdict_vector.json")


def test_no_harness_module_rebuilds_an_artifact_filename_from_a_literal() -> None:
    offenders: list[str] = []
    for path in sorted(_HARNESS_DIR.glob("*.py")):
        if path.name == "run_artifacts.py":
            continue
        body = path.read_text()
        for literal in _ARTIFACT_LITERALS:
            if literal in body:
                offenders.append(f"{path.name} hardcodes {literal!r}")
    assert offenders == [], (
        "these modules build a run artifact's filename themselves instead of asking `run_artifacts` for "
        f"it, which bypasses the label and can read or write the wrong run's frozen files: {offenders}"
    )
