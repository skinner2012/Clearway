"""Freeze the drafter's per-case verdict vector — the reference a future run pairs against, case by case.

The per-class κ baseline is a scalar per fix unit, and a scalar cannot be PAIRED against: comparing two
κ numbers tells you they differ, never WHICH cases moved, so it throws away the very structure the most
sensitive regression test needs. This module freezes the missing structure — one FLAG/CLEAN verdict per
ACT case, keyed by `act_testcase_id` — so a future drafter run can be set beside this one case-by-case
(a McNemar / exact sign test on the discordant pairs) without re-deriving which case is which. The κ
baseline says *how well the drafter judges each class today*; this vector is what lets a later run prove
it got BETTER, on the same cases, rather than merely different.

Pure — no LLM, no network, no clock. Every verdict replays from the frozen offline-eval run artifact
(the same discipline `drafter_kappa.py` and `offline.py` follow); even `created_at` is READ off the
artifact, never generated, so the vector is a deterministic function of its source run.

**The verdict is the scorer's own**, reused rather than re-derived: `_grouped` supplies the exact case
stream κ measures — grouped by fix unit (`axe_rule`), scoped to the ACT rules the gold currently scores,
with the honest-misses carried in as drafts-less cases — and `_flagged` (flag-if-any) supplies the identical
FLAG/CLEAN collapse every other rate uses. So a case's `drafter_flag` here is bit-identical to the value
that entered its class κ, and an honest miss (no conformances) is CLEAN exactly as it is a recall miss.

**The provenance travels with the vector** so the freeze is reproducible: the drafter-side slice of the
offline report — model DIGEST (the immutable freeze key, not the mutable tag), corpus / axe-core /
config / eval-set versions, the vendored ACT export hash, the run ids and the source timestamp. The
judge-side provenance is deliberately absent: no judge number enters this vector, so its digest would be
dead weight.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clearway.eval.drafter_kappa import _grouped
from clearway.eval.drafter_score import FAILED, _flagged
from clearway.schemas.models import CaseVerdict, VerdictVector

# Recorded on the artifact so it reads without cross-referencing the spec: the one reason this vector is
# frozen at all — a per-class κ scalar has no case-level structure to pair a future run against.
_RATIONALE = (
    "A kappa scalar cannot be paired against: keyed by act_testcase_id, this per-case FLAG/CLEAN vector "
    "is what lets a future drafter run be compared case-by-case (a McNemar / exact sign test on the "
    "discordant pairs) to prove it improved on the same cases rather than merely changed — the most "
    "sensitive regression test available here, and one a per-class kappa number cannot support."
)


def build_verdict_vector(artifact: dict[str, Any], *, partial_flags: bool = True) -> VerdictVector:
    """Frozen offline-eval run artifact → the drafter's per-case `VerdictVector`, keyed by `act_testcase_id`.

    Pure: no model, no network, no clock — a deterministic replay of the checked-in artifact, `created_at`
    included (read off the artifact, never generated). Reuses the scorer's own grouped case stream
    (`_grouped`, so honest-misses ride in and only the currently-scored ACT rules do) and `_flagged`
    (flag-if-any), so each case's `drafter_flag` is bit-identical to the value that entered its class κ.
    One `CaseVerdict` per ACT case — minting cases and honest misses alike — sorted by fix unit then by
    the group's own order. Computed under one `partial_flags` reading; call twice to freeze both.
    """
    cases: list[CaseVerdict] = []
    for axe_rule, group in sorted(_grouped(artifact).items()):
        for case in group:
            cases.append(
                CaseVerdict(
                    act_testcase_id=case.act_testcase_id,
                    axe_rule=axe_rule,
                    drafter_flag=_flagged(case, partial_flags=partial_flags),
                    gold_flag=(case.expected == FAILED),
                    conformances=[d.conformance for d in case.drafts],
                )
            )
    return VerdictVector(
        partial_flags=partial_flags,
        cases=cases,
        run_ids=artifact["run_ids"],
        config_id=artifact["config_id"],
        eval_set_id=artifact["eval_set_id"],
        corpus_version=artifact["corpus_version"],
        drafter_model=artifact["drafter_model"],
        drafter_model_digest=artifact["drafter_model_digest"],
        axe_core_version=artifact["axe_core_version"],
        act_export_hash=artifact["act_export_hash"],
        created_at=datetime.fromisoformat(artifact["created_at"]),
        rationale=_RATIONALE,
    )
