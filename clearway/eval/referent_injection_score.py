"""Freeze and score one acceptance run: determinism assertion, the paired thesis, per-class mechanism.

Pure — no model, no network, no clock. It replays one run's frozen pass artifacts and the frozen baseline
(`verdict_vector.json` + `drafter_kappa_baseline.json`) into that run's result. Three things are produced:

1. **Determinism.** Per-class κ must be identical across the run's passes (`_assert_deterministic`, reused
   from the baseline freeze). Each prompt change lengthens the prompt the earlier baseline verified, so this
   check keeps testing something it could not before. A drift here means pass 1 is not canonical and no
   paired claim may be made.
2. **The paired thesis.** The run's per-case verdict vector set beside the baseline's, keyed by
   `act_testcase_id` → the pooled primary endpoint and the per-class secondary tests (`paired.pair_verdicts`).
3. **Per-class mechanism** (reported for every class, certified or not): distinct prompts before/after, the
   `constant_classifier` state, the 2×2, and which specific reachable errors moved — the evidence that
   survives when significance does not, and the only evidence `document-title` can offer.

**Which run is scored is an explicit argument.** Passes are selected by run label rather than by globbing a
shared prefix (`run_artifacts.frozen_pass_paths`): two runs swept into one determinism check would be
compared against each other, and the prompt change that distinguishes them — the very thing under test —
would surface as a determinism drift. Every artifact read and written is likewise label-scoped, so scoring
one run cannot overwrite another's frozen record.

The judge appears in no number here, exactly as the pre-registration requires. `document-title` is reported
on mechanism only and can never read as "certified"; that invariant is asserted before the result is written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.eval.drafter_kappa import class_ceilings, class_kappa_cis, class_kappas
from clearway.eval.drafter_kappa_baseline import _assert_deterministic
from clearway.eval.drafter_score import score_drafter
from clearway.eval.offline import _drafted_cases
from clearway.eval.paired import attribute_against_prior, pair_verdicts
from clearway.eval.verdict_vector import build_verdict_vector
from clearway.schemas.models import TechniqueMatch, VerdictVector

# The distinct-prompt counts BEFORE injection, as pre-registered in the spec / frozen baseline (assembled
# `_user_prompt` over the minting cases). Reported beside the after-injection counts as a secondary, gold-free
# mechanism diagnostic — never an acceptance criterion.
_DISTINCT_PROMPTS_BEFORE = {"label": 6, "document-title": 1, "link-name": 13, "empty-heading": 9}


def _mechanism(
    run_a: dict[str, Any], baseline_reachable: dict[str, list[str]], distinct_after: dict[str, int]
) -> list[dict[str, Any]]:
    """Per-class mechanism evidence from Run A: 2×2, κ (both readings), constant-classifier state, distinct
    prompts before/after, and the reachable errors that moved."""
    kappas = {c.axe_rule: c for c in class_kappas(run_a)}
    kappas_pf_false = {c.axe_rule: c for c in class_kappas(run_a, partial_flags=False)}
    cis = {c.axe_rule: c for c in class_kappa_cis(run_a)}
    ceilings = {c.axe_rule: c for c in class_ceilings(run_a)}
    rows: list[dict[str, Any]] = []
    for axe_rule in sorted(kappas):
        k, ci, ceil = kappas[axe_rule], cis[axe_rule], ceilings[axe_rule]
        rows.append(
            {
                "axe_rule": axe_rule,
                "kappa": k.kappa,
                "kappa_partial_false": kappas_pf_false[axe_rule].kappa,
                "raw_agreement": k.raw_agreement,
                "tp": k.tp,
                "fp": k.fp,
                "fn": k.fn,
                "tn": k.tn,
                "constant_classifier": ci.constant_classifier,
                "distinct_prompts_before": _DISTINCT_PROMPTS_BEFORE.get(axe_rule),
                "distinct_prompts_after": distinct_after.get(axe_rule),
                "errors": ceil.errors,
                "reachable_errors_remaining": ceil.reachable_errors,
                "baseline_reachable_error_ids": baseline_reachable.get(axe_rule, []),
            }
        )
    return rows


def _score_predictions(
    predictions: list[dict[str, Any]], improved: set[str], regressed: set[str]
) -> list[dict[str, Any]]:
    """The objective movement of each pre-registered prediction's named cases — fixed / regressed / not
    moved — recorded so the two predictions are scored from the data, not narrated. Both referent-injection
    predictions are failure predictions (the case will NOT be fixed), so `held_mechanically` = none fixed.
    The interpretation is left to a reviewer other than the ticket author (exit criterion 8)."""
    rows: list[dict[str, Any]] = []
    for p in predictions:
        ids = p["act_testcase_ids"]
        per_id = {
            tid: ("fixed" if tid in improved else "regressed" if tid in regressed else "not_moved") for tid in ids
        }
        rows.append(
            {
                "prediction_id": p["prediction_id"],
                "act_testcase_ids": ids,
                "per_case_movement": per_id,
                "held_mechanically": not any(v == "fixed" for v in per_id.values()),
            }
        )
    return rows


def score_run(
    runs: list[dict[str, Any]],
    baseline_vec: VerdictVector,
    baseline_reachable: dict[str, list[str]],
    distinct_after: dict[str, int],
    predictions: list[dict[str, Any]] | None = None,
    prior_vec: VerdictVector | None = None,
    technique_match: TechniqueMatch | None = None,
) -> tuple[VerdictVector, dict[str, Any]]:
    """One run's frozen passes + the frozen baseline → (that run's verdict vector, the result dict).

    All passes must belong to the SAME run: determinism is asserted across them, so passes from two runs
    would be read as one drifting run. Asserts determinism first (pass 1 is canonical only if they agree),
    builds the verdict vector from pass 1, pairs it against the baseline, and assembles the paired thesis +
    per-class mechanism. `document-title` reported as certified is a spec violation, asserted before
    returning.

    `prior_vec` is the preceding run's frozen vector, where one exists. It answers a question the baseline
    pairing cannot: whether this run's further prompt change gave back what the previous run bought. The
    caller decides whether it is required — see `run_artifacts.prior_label`.

    `technique_match` is the remediation fix-direction measurement, which needs its own classification pass
    over this run's drafted text and so is passed in rather than derived here. Absent, it stays `None` and
    the notes say why — an unmeasured direction must never render as a zero."""
    if len(runs) < 2:
        raise ValueError("determinism needs at least two passes of the same run to compare")
    _assert_deterministic(runs)
    run_vec = build_verdict_vector(runs[0])
    paired = pair_verdicts(baseline_vec, run_vec)

    for cls in paired.classes:
        if cls.axe_rule == "document-title" and cls.verdict == "certified":
            raise AssertionError("document-title reported as certified — a spec violation (ceiling p = 0.125)")

    # Cross-reference which of each class's pre-registered reachable errors Run A actually moved.
    moved = {cls.axe_rule: set(cls.improved_ids) for cls in paired.classes}
    reachable_moved = {
        axe_rule: sorted(set(ids) & moved.get(axe_rule, set())) for axe_rule, ids in baseline_reachable.items()
    }
    all_improved = {tid for cls in paired.classes for tid in cls.improved_ids}
    all_regressed = {tid for cls in paired.classes for tid in cls.regressed_ids}

    # The drafter-side rates, off the same frozen artifact — a pure function of it, no second model pass.
    # A drafter-only run cannot go through the judge-inclusive scorecard, and these are the numbers the
    # written read reports beside the paired thesis, so they are scored here rather than left unreported.
    drafter_scoring = score_drafter(_drafted_cases(runs[0]), technique_match=technique_match)

    result = {
        "pooled": paired.pooled.to_dict(),
        "classes": [c.to_dict() for c in paired.classes],
        "reachable_errors_moved": reachable_moved,
        "predictions_scored": _score_predictions(predictions or [], all_improved, all_regressed),
        "mechanism": _mechanism(runs[0], baseline_reachable, distinct_after),
        "drafter_score": drafter_scoring.score.model_dump(mode="json"),
        "drafter_score_notes": drafter_scoring.sensitivity_notes,
        "determinism": {"passes": len(runs), "per_class_kappa_identical": True},
        "run_ids": [rid for r in runs for rid in r["run_ids"]],
        "baseline_run_ids": list(baseline_vec.run_ids),
        "held_out_model_run_count": len(runs),
        "judge_absent": True,
    }
    if prior_vec is not None:
        result["attribution"] = attribute_against_prior(baseline_vec, prior_vec, run_vec).to_dict()
    return run_vec, result


def _print_read(result: dict[str, Any], label: str) -> None:
    pooled = result["pooled"]
    print(f"\n=== {label} — paired against the frozen baseline ===")
    print(
        f"POOLED (primary): label+link-name  b={pooled['improved']} c={pooled['regressed']}  "
        f"p={pooled['p_value']:.4f}  → THESIS {pooled['thesis'].upper()}"
    )
    for c in result["classes"]:
        moved = result["reachable_errors_moved"].get(c["axe_rule"], [])
        print(
            f"  {c['axe_rule']:<15} b={c['improved']} c={c['regressed']} p={c['p_value']:.4f} "
            f"→ {c['verdict']}   reachable-moved={len(moved)}"
        )
    print("mechanism (distinct prompts before→after, constant_classifier, 2x2):")
    for m in result["mechanism"]:
        print(
            f"  {m['axe_rule']:<15} prompts {m['distinct_prompts_before']}→{m['distinct_prompts_after']}  "
            f"const={m['constant_classifier']}  2x2 tp/fp/fn/tn={m['tp']}/{m['fp']}/{m['fn']}/{m['tn']}  "
            f"κ={m['kappa']:+.3f}"
        )
    attribution = result.get("attribution")
    if attribution is not None:
        verdict = "EATS THE PRIOR RUN" if attribution["eats_prior_run"] else "prior run intact"
        print(f"attribution vs the prior run ({', '.join(attribution['prior_run_ids'])}): {verdict}")
        for a in attribution["classes"]:
            lost = a["prior_gains_lost"]
            print(
                f"  {a['axe_rule']:<15} b={a['improved']} c={a['regressed']}  "
                f"prior gains lost={len(lost)}{' ' + str(lost) if lost else ''}"
            )
    print("pre-registered predictions (mechanical outcome; interpretation is a reviewer's):")
    for p in result.get("predictions_scored", []):
        print(f"  {p['prediction_id']:<24} held={p['held_mechanically']}  {p['per_case_movement']}")
    print(f"held-out model-run count: {result['held_out_model_run_count']}  |  judge absent: {result['judge_absent']}")


def main() -> None:
    import argparse

    from clearway.eval.offline_build import _REPORTS_DIR, _RUNS_DIR
    from clearway.eval.run_artifacts import (
        RUN_LABELS,
        dry_gate_path,
        frozen_pass_paths,
        prior_label,
        result_path,
        technique_match_path,
        verdict_vector_path,
    )

    parser = argparse.ArgumentParser(description="score one frozen acceptance run against the frozen baseline")
    parser.add_argument(
        "--run",
        required=True,
        choices=RUN_LABELS,
        help="which run to score — required, never defaulted, because passes of different runs must "
        "never be swept into one determinism check",
    )
    args = parser.parse_args()

    paths = frozen_pass_paths(args.run)
    if not paths:
        raise SystemExit(
            f"no {args.run} passes found under {_RUNS_DIR} — build them first with "
            f"`referent_injection_build --run {args.run} <pass>`"
        )
    runs = [json.loads(p.read_text()) for p in paths]

    baseline_vec = VerdictVector.model_validate_json((_REPORTS_DIR / "verdict_vector.json").read_text())
    baseline_kappa = json.loads((_REPORTS_DIR / "drafter_kappa_baseline.json").read_text())
    baseline_reachable = {c["axe_rule"]: c.get("reachable_error_ids", []) for c in baseline_kappa["classes"]}

    # Distinct prompts after the change: recomputed live by this run's dry gate; read its last diagnostic if
    # present, else fall back to an empty map (the counts are a diagnostic, not a gate).
    distinct_after: dict[str, int] = {}
    dg = dry_gate_path(args.run)
    if dg.exists():
        distinct_after = json.loads(dg.read_text()).get("distinct_prompts_by_class", {})

    # A run with a predecessor MUST be attributed against it — a missing attribution reads exactly like a
    # clean one, so its absence is refused rather than tolerated.
    prior_vec: VerdictVector | None = None
    prior = prior_label(args.run)
    if prior is not None:
        prior_path = verdict_vector_path(prior)
        if not prior_path.exists():
            raise SystemExit(
                f"{args.run} has to be attributed against {prior}, whose verdict vector is not frozen at "
                f"{prior_path}. Without it there is no way to tell whether this run gave back what {prior} "
                f"bought, and an absent attribution is indistinguishable from a clean one. Score {prior} "
                "first."
            )
        prior_vec = VerdictVector.model_validate_json(prior_path.read_text())

    # The fix-direction pass calls a classifier, so it is run separately and its frozen result read back
    # here. Absent, the metric stays None and says so — never a zero standing in for an unmeasured thing.
    technique_match: TechniqueMatch | None = None
    tm_path = technique_match_path(args.run)
    if tm_path.exists():
        payload = json.loads(tm_path.read_text())
        if payload.get("is_reported_metric"):
            technique_match = TechniqueMatch.model_validate(payload["metric"])
        else:
            print(f"skipping {tm_path.name}: stamped {payload.get('status')!r}, not the reported metric")

    run_vec, result = score_run(
        runs,
        baseline_vec,
        baseline_reachable,
        distinct_after,
        predictions=baseline_kappa.get("predictions", []),
        prior_vec=prior_vec,
        technique_match=technique_match,
    )
    verdict_vector_path(args.run).write_text(run_vec.model_dump_json(indent=2) + "\n")
    result_path(args.run).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    _print_read(result, args.run)
    print(f"\nwrote {result_path(args.run).relative_to(Path.cwd())}  ({len(paths)} passes, {args.run})")


if __name__ == "__main__":
    main()
