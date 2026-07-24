"""Freeze and score Run A: determinism assertion, the paired thesis, per-class mechanism, the honest read.

Pure — no model, no network, no clock. It replays the frozen Run A pass artifacts
(`referent_injection_run_1..3.json`) and the frozen baseline (`verdict_vector.json` +
`drafter_kappa_baseline.json`) into the referent-injection result. Three things are produced:

1. **Determinism.** Per-class κ must be identical across the three passes (`_assert_deterministic`, reused
   from the baseline freeze). The injected prompt is longer than the one the earlier baseline verified, and
   injection splits the previously-degenerate prompts, so this check now tests something it could not before.
   A drift here means pass 1 is not canonical and no paired claim may be made.
2. **The paired thesis.** Run A's per-case verdict vector set beside the baseline's, keyed by
   `act_testcase_id` → the pooled primary endpoint and the per-class secondary tests (`paired.pair_verdicts`).
3. **Per-class mechanism** (reported for every class, certified or not): distinct prompts before/after, the
   `constant_classifier` state, the 2×2, and which specific reachable errors moved — the evidence that
   survives when significance does not, and the only evidence `document-title` can offer.

The judge appears in no number here, exactly as the pre-registration requires. `document-title` is reported
on mechanism only and can never read as "certified"; that invariant is asserted before the result is written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.eval.drafter_kappa import class_ceilings, class_kappa_cis, class_kappas
from clearway.eval.drafter_kappa_baseline import _assert_deterministic
from clearway.eval.paired import pair_verdicts
from clearway.eval.verdict_vector import build_verdict_vector
from clearway.schemas.models import VerdictVector

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


def score_run_a(
    runs: list[dict[str, Any]],
    baseline_vec: VerdictVector,
    baseline_reachable: dict[str, list[str]],
    distinct_after: dict[str, int],
    predictions: list[dict[str, Any]] | None = None,
) -> tuple[VerdictVector, dict[str, Any]]:
    """The three frozen Run A passes + the frozen baseline → (Run A verdict vector, the result dict).

    Asserts determinism across the passes first (run_A_1 is canonical only if they agree), builds Run A's
    verdict vector from pass 1, pairs it against the baseline, and assembles the paired thesis + per-class
    mechanism. `document-title` reported as certified is a spec violation, asserted here before returning."""
    if len(runs) < 2:
        raise ValueError("Run A determinism needs at least two passes to compare")
    _assert_deterministic(runs)
    run_a_vec = build_verdict_vector(runs[0])
    paired = pair_verdicts(baseline_vec, run_a_vec)

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

    result = {
        "pooled": paired.pooled.to_dict(),
        "classes": [c.to_dict() for c in paired.classes],
        "reachable_errors_moved": reachable_moved,
        "predictions_scored": _score_predictions(predictions or [], all_improved, all_regressed),
        "mechanism": _mechanism(runs[0], baseline_reachable, distinct_after),
        "determinism": {"passes": len(runs), "per_class_kappa_identical": True},
        "referent_injection_run_ids": [rid for r in runs for rid in r["run_ids"]],
        "baseline_run_ids": list(baseline_vec.run_ids),
        "held_out_model_run_count": len(runs),
        "judge_absent": True,
    }
    return run_a_vec, result


def _print_read(result: dict[str, Any]) -> None:
    pooled = result["pooled"]
    print("\n=== Run A — the referent-injection experiment ===")
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
    print("pre-registered predictions (mechanical outcome; interpretation is a reviewer's):")
    for p in result.get("predictions_scored", []):
        print(f"  {p['prediction_id']:<24} held={p['held_mechanically']}  {p['per_case_movement']}")
    print(f"held-out model-run count: {result['held_out_model_run_count']}  |  judge absent: {result['judge_absent']}")


def main() -> None:
    from clearway.eval.offline_build import _REPORTS_DIR, _RUNS_DIR

    paths = sorted(_RUNS_DIR.glob("referent_injection_run_*.json"), key=lambda p: int(p.stem.split("_")[-1]))
    if not paths:
        raise SystemExit(f"no Run A passes found under {_RUNS_DIR} — run referent_injection_build first")
    runs = [json.loads(p.read_text()) for p in paths]

    baseline_vec = VerdictVector.model_validate_json((_REPORTS_DIR / "verdict_vector.json").read_text())
    baseline_kappa = json.loads((_REPORTS_DIR / "drafter_kappa_baseline.json").read_text())
    baseline_reachable = {c["axe_rule"]: c.get("reachable_error_ids", []) for c in baseline_kappa["classes"]}

    # After-injection distinct prompts: recomputed live by the dry gate; read its last diagnostic if present,
    # else fall back to an empty map (the counts are a diagnostic, not a gate).
    distinct_after: dict[str, int] = {}
    dg = _REPORTS_DIR / "referent_injection_dry_gate.json"
    if dg.exists():
        distinct_after = json.loads(dg.read_text()).get("distinct_prompts_by_class", {})

    run_a_vec, result = score_run_a(
        runs, baseline_vec, baseline_reachable, distinct_after, predictions=baseline_kappa.get("predictions", [])
    )
    (_REPORTS_DIR / "referent_injection_verdict_vector.json").write_text(run_a_vec.model_dump_json(indent=2) + "\n")
    (_REPORTS_DIR / "referent_injection_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    _print_read(result)
    print(f"\nwrote {(_REPORTS_DIR / 'referent_injection_result.json').relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
