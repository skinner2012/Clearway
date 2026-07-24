"""The frozen per-case drafter verdict vector — the reference a future run pairs against.

Every number is a deterministic replay of a checked-in run artifact — no model, no network, no clock.
The counts (44 cases, per-class sizes, the 2×2 error rows) are the same pre-registered anchors the
per-class κ tests pin, read here through the verdict vector so the vector and the κ baseline cannot
drift apart. The final test proves the vector's whole reason to exist: a case-by-case paired comparison
against a hypothetical future run, keyed by `act_testcase_id`, that a κ scalar could not support.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from clearway.eval.drafter_kappa import _grouped
from clearway.eval.drafter_score import FAILED, _flagged
from clearway.eval.verdict_vector import build_verdict_vector
from clearway.schemas.models import Conformance, VerdictVector

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"
_REPORTS = Path(__file__).resolve().parent.parent / "benchmark" / "reports"


def _artifact(name: str = "run_1.json") -> dict:
    return json.loads((_RUNS / name).read_text())


def _vector(name: str = "run_1.json", *, partial_flags: bool = True) -> VerdictVector:
    return build_verdict_vector(_artifact(name), partial_flags=partial_flags)


def test_builds_44_cases_all_ids_unique() -> None:
    # 40 minting cases + 4 honest misses = 44; the misses are carried in exactly as κ carries them.
    vv = _vector()
    assert len(vv.cases) == 44
    ids = [c.act_testcase_id for c in vv.cases]
    assert len(set(ids)) == len(ids)


def test_per_class_case_counts() -> None:
    vv = _vector()
    counts = {axe: sum(1 for c in vv.cases if c.axe_rule == axe) for axe in {c.axe_rule for c in vv.cases}}
    assert counts == {"document-title": 5, "empty-heading": 13, "label": 11, "link-name": 15}


def _error_split(vv: VerdictVector, axe: str) -> tuple[int, int]:
    grp = [c for c in vv.cases if c.axe_rule == axe]
    fp = sum(1 for c in grp if c.drafter_flag and not c.gold_flag)
    miss = sum(1 for c in grp if not c.drafter_flag and c.gold_flag)
    return fp, miss


def test_error_rows_match_the_known_2x2() -> None:
    vv = _vector()
    assert _error_split(vv, "link-name") == (4, 2)
    assert _error_split(vv, "document-title") == (3, 0)
    assert _error_split(vv, "label") == (4, 1)
    assert _error_split(vv, "empty-heading") == (1, 1)


def test_empty_conformances_are_always_clean() -> None:
    # An honest miss mints no finding, so it carries no conformance and can never have flagged.
    vv = _vector()
    empties = [c for c in vv.cases if not c.conformances]
    assert len(empties) == 4
    assert all(c.drafter_flag is False for c in empties)


def test_provenance_is_complete() -> None:
    vv = _vector()
    assert vv.config_id
    assert vv.eval_set_id
    assert vv.corpus_version
    assert vv.drafter_model_digest
    assert vv.axe_core_version
    assert vv.act_export_hash
    assert isinstance(vv.created_at, datetime)
    assert vv.rationale  # a κ scalar cannot be paired against — stated on the artifact
    assert vv.partial_flags is True


def test_conformances_are_typed_verdicts() -> None:
    # the underlying draft verdicts survive as Conformance enums, not bare strings
    vv = _vector()
    flagged = next(c for c in vv.cases if c.conformances)
    assert all(isinstance(x, Conformance) for x in flagged.conformances)


def test_committed_artifact_loads_validates_and_is_frozen() -> None:
    # the checked-in vector round-trips through the schema AND equals a fresh build — reproducible/frozen.
    loaded = VerdictVector.model_validate(json.loads((_REPORTS / "verdict_vector.json").read_text()))
    assert loaded == build_verdict_vector(_artifact())


def test_pure_same_artifact_yields_identical_vector() -> None:
    a = _artifact()
    assert build_verdict_vector(a) == build_verdict_vector(a)


def test_paired_comparison_is_demonstrable_from_the_vector_alone() -> None:
    """The vector's raison d'être: a future run pairs case-to-case, keyed by `act_testcase_id`, with no
    re-derivation of alignment — the sensitive test a per-class κ scalar cannot support."""
    vv = _vector()
    current = {c.act_testcase_id: c.drafter_flag for c in vv.cases}
    gold = {c.act_testcase_id: c.gold_flag for c in vv.cases}

    # every case the drafter currently gets wrong (FP or miss), by id
    errors = {cid for cid, flag in current.items() if flag != gold[cid]}
    assert len(errors) == 16  # 6 link-name + 5 label + 3 document-title + 2 empty-heading

    # a hypothetical perfect-fix run: flip every current error (FP→CLEAN, miss→FLAG), leave the rest.
    # Built as an id-keyed map in arbitrary order to prove the pairing is by KEY, not by position.
    hypothetical = {cid: (not flag if cid in errors else flag) for cid, flag in sorted(current.items())}

    # McNemar discordant count, joined on act_testcase_id — no positional alignment anywhere
    discordant = sum(1 for cid in current if current[cid] != hypothetical[cid])
    assert discordant == len(errors)  # every discordant pair is a fixed error — pairing works from the vector alone


def test_scoping_left_every_surviving_verdict_bit_identical() -> None:
    """The scope correction removed cases; it must not have perturbed a single one that remains.

    This is what makes the paired comparison survive the correction: a later run pairs on the surviving
    `act_testcase_id`s, and each of those carries exactly the verdict it carried before."""
    scoped = build_verdict_vector(_artifact())
    before = {
        case.act_testcase_id: (_flagged(case), case.expected == FAILED)
        for group in _grouped(_artifact(), scoped=False).values()
        for case in group
    }
    assert len(before) == 53
    for row in scoped.cases:
        assert (row.drafter_flag, row.gold_flag) == before[row.act_testcase_id], row.act_testcase_id
