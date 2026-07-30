"""The drafter's per-class κ against ACT gold, recomputed from the pass the judge comparison replays.

The judge's side-by-side against the drafter — *when the two disagree, which of them is more often
right, and on which classes* — needs a drafter number at the same unit. One already exists on disk,
frozen, per class, per case, with a bootstrap interval: `benchmark/reports/drafter_kappa_baseline.json`.
**It is the wrong drafter**, and this module exists because that is not visible from the file.

⚠️ Why the frozen baseline cannot supply it
--------------------------------------------
That baseline was built from the acceptance sweep — its `run_ids` are `acceptance-2026-07-15…` — so it
is the drafter as it was **before** the referent reached its prompt. The pass this comparison replays is
two prompt revisions later. Both carry 54 findings and the baseline's `denominators.findings` is 54 as
well, so the substitution looks sound on inspection and its per-class rows still parse; what moves is
the numbers, and it moves on exactly the two classes the referent work repaired. Reading the drafter's
side off that file would place the judge beside a stale rater and get *which of them is right* wrong on
two classes out of four.

So the comparator is recomputed here from the replay pass, by the same `class_kappas` the baseline
itself uses — new source, not new arithmetic — and the superseded reading is carried in the record
beside it rather than left for a reader to discover.

What the record carries, and the one thing it deliberately does not
--------------------------------------------------------------------
Per class: the 2×2, raw agreement, κ, and **two denominators**. The drafter's stream carries the cases
that minted no finding (a failed one is the automatic recall miss it is); the judge can never hold those
rows, because a case that mints nothing produces no `Finding` to judge. The gap is class-structured
rather than spread, so both counts sit on every row and the record states which rows the gap is made of.

**It does not choose between them.** Quoting the judge over its 40 and the drafter over its 44 keeps two
honest numbers; restricting the drafter to the 40 buys one denominator at the price of dropping real
errors from its count, which flatters it, and it means republishing a frozen number. That choice belongs
to the stage that publishes the side-by-side table; this record's job is to make either one derivable
and neither one accidental.

Pure — no model, no network, no clock. `created_at` is read off the replay pass, so the record is a
deterministic function of its sources and a rebuild is byte-identical.

Invoke: `uv run python -m clearway.eval.judge_drafter_comparator`
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from clearway.eval.drafter_kappa import _grouped, class_kappas
from clearway.eval.drafter_score import FAILED, DraftedCase
from clearway.eval.judge_observation_unit import (
    OBSERVATION_UNIT,
    WITHIN_CASE_AGGREGATION,
)
from clearway.eval.stats import COLLAPSE_RULE

# The unit key every row is joined on. The drafter's κ exists ONLY per case, so this is the only key at
# which the two raters can be set beside each other at all.
UNIT_KEY = "act_testcase_id"

SUPERSEDED_BASELINE = "drafter_kappa_baseline.json"

WHY_THE_FROZEN_BASELINE_IS_NOT_THE_COMPARATOR = (
    "The frozen per-class drafter baseline was built from the acceptance sweep (run_ids "
    "acceptance-2026-07-15…), which is the drafter BEFORE the referent reached its prompt. This "
    "comparison replays a pass two prompt revisions later. The two agree on their finding count (54) "
    "and on their case count (44), so a substitution is invisible on inspection — and the per-class "
    "kappa is materially different on the two classes the referent work repaired. The frozen file "
    "remains correct as the record of the run it was built from, and it is historical: it is not this "
    "drafter, and it must not be read as the comparator the judge is set beside."
)

DENOMINATOR_IS_NOT_DECIDED_HERE = (
    "Two denominators are recorded per class and neither is chosen. The drafter's stream carries the "
    "cases that minted no finding, because a failed one is an automatic recall miss and dropping it "
    "would overstate recall; the judge's stream cannot hold them, because a case that mints nothing "
    "produces no finding to judge. Quoting each rater on its own denominator keeps two honest numbers "
    "and forbids arithmetic that subtracts one from the other; restricting the drafter to the "
    "judge-visible cases buys one denominator at the cost of dropping real errors from the drafter's "
    "count, which flatters it. The stage that publishes the side-by-side table declares which; this "
    "record makes both derivable and neither accidental."
)


def _minting(cases: list[DraftedCase]) -> list[DraftedCase]:
    return [c for c in cases if c.drafts]


def per_class_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per fix-unit class: the drafter's 2×2 and κ, with both denominators and the gap named."""
    groups = _grouped(artifact)
    rows: list[dict[str, Any]] = []
    for kappa in class_kappas(artifact):
        group = groups[kappa.axe_rule]
        non_minting = [c for c in group if not c.drafts]
        rows.append(
            {
                "axe_rule": kappa.axe_rule,
                "rule_names": list(kappa.rule_names),
                "drafter_units": kappa.n,
                "judge_visible_units": len(_minting(group)),
                "unit_gap": len(non_minting),
                "gap_rows_whose_gold_is_failed": sum(1 for c in non_minting if c.expected == FAILED),
                "gap_row_ids": sorted(c.act_testcase_id for c in non_minting),
                "findings": sum(len(c.drafts) for c in group),
                "failed": kappa.failed,
                "passed": kappa.passed,
                "tp": kappa.tp,
                "fp": kappa.fp,
                "fn": kappa.fn,
                "tn": kappa.tn,
                "kappa": round(kappa.kappa, 4),
                "raw_agreement": round(kappa.raw_agreement, 4),
            }
        )
    return rows


def superseded_rows(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """The frozen baseline's per-class κ, read off the file — the reading this record replaces."""
    return [{"axe_rule": c["axe_rule"], "n": c["n"], "kappa": round(c["kappa"], 4)} for c in baseline["classes"]]


def _provenance(path: Path, artifact: dict[str, Any], *, fields: tuple[str, ...]) -> dict[str, Any]:
    known = {f: artifact[f] for f in fields if f in artifact}
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **known}


def build_record(*, replay_path: Path, baseline_path: Path) -> dict[str, Any]:
    """Assemble the comparator record. Pure given the two files, so the whole shape is testable."""
    artifact = json.loads(replay_path.read_text())
    baseline = json.loads(baseline_path.read_text())
    rows = per_class_rows(artifact)
    superseded = superseded_rows(baseline)
    moved = sorted(
        row["axe_rule"]
        for row in rows
        for old in superseded
        if old["axe_rule"] == row["axe_rule"] and old["kappa"] != row["kappa"]
    )
    return {
        "artifact": "the drafter's per-class kappa against ACT gold, on the pass the judge comparison replays",
        "version": 1,
        "model_calls_spent": 0,
        "created_at": artifact["created_at"],
        "unit": {
            "observation_unit": OBSERVATION_UNIT,
            "unit_key": UNIT_KEY,
            "within_case_aggregation": WITHIN_CASE_AGGREGATION,
            "conformance_collapse_rule": COLLAPSE_RULE,
            "note": (
                "The drafter's kappa exists only per case, which is what makes the case the only unit "
                "at which the two raters can be set beside each other."
            ),
        },
        "source": _provenance(
            replay_path,
            artifact,
            fields=(
                "run_ids",
                "config_id",
                "eval_set_id",
                "corpus_version",
                "drafter_model",
                "drafter_model_digest",
                "axe_core_version",
                "act_export_hash",
                "created_at",
            ),
        ),
        "per_class": rows,
        "totals": {
            "drafter_units": sum(r["drafter_units"] for r in rows),
            "judge_visible_units": sum(r["judge_visible_units"] for r in rows),
            "unit_gap": sum(r["unit_gap"] for r in rows),
            "gap_rows_whose_gold_is_failed": sum(r["gap_rows_whose_gold_is_failed"] for r in rows),
            "findings": sum(r["findings"] for r in rows),
        },
        "denominators": DENOMINATOR_IS_NOT_DECIDED_HERE,
        "superseded_baseline": {
            **_provenance(baseline_path, baseline, fields=("run_ids", "config_id", "eval_set_id", "created_at")),
            "per_class": superseded,
            "classes_whose_kappa_moved": moved,
            "historical_only": True,
            "why": WHY_THE_FROZEN_BASELINE_IS_NOT_THE_COMPARATOR,
        },
    }


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_drafter_comparator.json"


def main() -> None:
    from clearway.eval.offline_build import _REPORTS_DIR
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path

    record = build_record(
        replay_path=run_path(CITATION_GROUNDING, 1),
        baseline_path=_REPORTS_DIR / SUPERSEDED_BASELINE,
    )
    print(f"drafter comparator over {record['source']['path']} — 0 model calls")
    for row in record["per_class"]:
        old = next(o["kappa"] for o in record["superseded_baseline"]["per_class"] if o["axe_rule"] == row["axe_rule"])
        moved = " ← MOVED" if old != row["kappa"] else ""
        print(
            f"  {row['axe_rule']:15s} kappa {row['kappa']:+.4f} (superseded {old:+.4f}){moved}"
            f"  n drafter {row['drafter_units']} / judge-visible {row['judge_visible_units']}"
        )
    totals = record["totals"]
    print(f"  totals: drafter {totals['drafter_units']} / judge-visible {totals['judge_visible_units']} units")

    path = report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
