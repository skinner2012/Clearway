"""Assemble the frozen per-class drafter-κ baseline — the reference every future drafter claim is measured against.

The per-class functions in `drafter_kappa.py` each answer one question — κ (`class_kappas`), its bootstrap
interval (`class_kappa_cis`), the detectable-improvement ceiling (`class_ceilings`). This module joins them,
per fix-unit class, into one committed artifact so a reader (or a future run) has every number in one place,
grounded and pointable: κ under BOTH `partial_flags` readings, the 2×2, the interval with its honesty guards,
and the pre-registered ceiling verdict, plus the drafter-side provenance that makes the freeze reproducible.

Pure — no LLM, no network, no clock. Every number replays from the frozen offline-eval run artifact, and
even `created_at` is READ off it, never generated, so the baseline is a deterministic function of its source
run. It scores against ACT gold only; the judge appears in no number here (it sits at chance, so scoring
against it optimises against noise).

`freeze_drafter_kappa_baseline` / `main` freeze the committed artifact from the run sweep: run_1 is canonical
because the drafter is deterministic, and `_assert_deterministic` fails loud if any run's per-class κ diverged
rather than silently freezing run_1. Invoke `uv run python -m clearway.eval.drafter_kappa_baseline` to
regenerate — the same offline-freeze pattern the acceptance scorecard uses.

The headline reading is `partial_flags=True` — the convention every other rate uses — and the 2×2, interval
and ceiling are computed under it. Each row also carries `kappa_partial_false` + `errors_partial_false` so the
"robust to the second reading" claim is checkable from the artifact rather than taken on faith: only the two
pooled link rules move under `partial_flags=False`, and no certifiability verdict flips.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clearway.eval.drafter_kappa import (
    _BOOTSTRAP_SEED,
    _RESAMPLES,
    CEILING_PREREGISTRATION,
    class_ceilings,
    class_kappa_cis,
    class_kappas,
)
from clearway.schemas.models import DrafterKappaBaseline, DrafterKappaClass

_HEADLINE_PARTIAL_FLAGS = True


def build_drafter_kappa_baseline(artifact: dict[str, Any], *, run_ids: list[str] | None = None) -> DrafterKappaBaseline:
    """Frozen offline-eval run artifact → the per-class `DrafterKappaBaseline`, scored against ACT gold.

    Pure: no model, no network, no clock — a deterministic replay of the checked-in artifact, `created_at`
    included (read off the artifact, never generated). Joins `class_kappas` (both readings), `class_kappa_cis`
    and `class_ceilings` by `axe_rule` into one row per fix-unit class, sorted by `axe_rule`. The 2×2, the
    interval and the ceiling are the headline reading (`partial_flags=True`); `kappa_partial_false` and
    `errors_partial_false` carry the second reading so its robustness is checkable from the artifact alone.
    `run_ids` defaults to this artifact's own; `freeze` overrides it with the full verified sweep.
    """
    headline = {c.axe_rule: c for c in class_kappas(artifact, partial_flags=_HEADLINE_PARTIAL_FLAGS)}
    alternate = {c.axe_rule: c for c in class_kappas(artifact, partial_flags=not _HEADLINE_PARTIAL_FLAGS)}
    cis = {c.axe_rule: c for c in class_kappa_cis(artifact, partial_flags=_HEADLINE_PARTIAL_FLAGS)}
    ceilings = {c.axe_rule: c for c in class_ceilings(artifact, partial_flags=_HEADLINE_PARTIAL_FLAGS)}

    classes: list[DrafterKappaClass] = []
    for axe_rule in sorted(headline):
        k, alt, ci, ceil = headline[axe_rule], alternate[axe_rule], cis[axe_rule], ceilings[axe_rule]
        classes.append(
            DrafterKappaClass(
                axe_rule=axe_rule,
                rule_names=list(k.rule_names),
                n=k.n,
                failed=k.failed,
                passed=k.passed,
                tp=k.tp,
                fp=k.fp,
                fn=k.fn,
                tn=k.tn,
                raw_agreement=k.raw_agreement,
                kappa=k.kappa,
                kappa_partial_false=alt.kappa,
                ci_low=ci.ci_low,
                ci_high=ci.ci_high,
                degenerate_share=ci.degenerate_share,
                constant_classifier=ci.constant_classifier,
                errors=ceil.errors,
                errors_partial_false=alt.fp + alt.fn,
                p_value=ceil.p_value,
                certifiable=ceil.certifiable,
            )
        )

    return DrafterKappaBaseline(
        classes=classes,
        headline_partial_flags=_HEADLINE_PARTIAL_FLAGS,
        alpha=ceilings[classes[0].axe_rule].alpha,
        preregistration=CEILING_PREREGISTRATION,
        bootstrap_seed=_BOOTSTRAP_SEED,
        bootstrap_resamples=_RESAMPLES,
        run_ids=run_ids if run_ids is not None else artifact["run_ids"],
        config_id=artifact["config_id"],
        eval_set_id=artifact["eval_set_id"],
        corpus_version=artifact["corpus_version"],
        drafter_model=artifact["drafter_model"],
        drafter_model_digest=artifact["drafter_model_digest"],
        axe_core_version=artifact["axe_core_version"],
        act_export_hash=artifact["act_export_hash"],
        created_at=datetime.fromisoformat(artifact["created_at"]),
    )


def _per_class_kappa(artifact: dict[str, Any]) -> tuple[tuple[tuple[str, float], ...], ...]:
    """A run's per-class κ under both readings — the determinism key `freeze` compares runs on."""
    return tuple(
        tuple(sorted((c.axe_rule, c.kappa) for c in class_kappas(artifact, partial_flags=pf))) for pf in (True, False)
    )


def _assert_deterministic(runs: list[dict[str, Any]]) -> None:
    """Per-class κ must be identical across the sweep — the determinism that makes run_1 canonical. If a
    run diverged, freezing run_1 as the baseline would be a lie, so fail loud and make the human decide."""
    base = _per_class_kappa(runs[0])
    for i, run in enumerate(runs[1:], start=2):
        if _per_class_kappa(run) != base:
            raise ValueError(
                f"run_{i} per-class κ drifted from run_1 — the drafter is expected to be deterministic, so "
                "run_1 cannot be taken as the canonical baseline. Re-examine the sweep before freezing."
            )


def freeze_drafter_kappa_baseline(runs: list[dict[str, Any]]) -> DrafterKappaBaseline:
    """Compose the frozen baseline: run_1's per-class numbers (canonical, since the drafter is deterministic),
    with every verified run's id recorded as provenance. Asserts determinism across the sweep first."""
    if not runs:
        raise ValueError("freeze_drafter_kappa_baseline needs at least one run artifact")
    _assert_deterministic(runs)
    run_ids = [rid for run in runs for rid in run["run_ids"]]
    return build_drafter_kappa_baseline(runs[0], run_ids=run_ids)


def main() -> None:
    """Freeze the per-class drafter-κ baseline from the checked-in run sweep. Pure and offline — it replays
    the frozen run artifacts, never re-invoking a model.
    Invoke: `uv run python -m clearway.eval.drafter_kappa_baseline`."""
    import json

    from clearway.eval.offline_build import _REPORTS_DIR, _RUNS_DIR

    paths = sorted(_RUNS_DIR.glob("run_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    if not paths:
        raise SystemExit(f"no runs found under {_RUNS_DIR} — run the acceptance sweep first")
    runs = [json.loads(p.read_text()) for p in paths]
    baseline = freeze_drafter_kappa_baseline(runs)
    artifact_path = _REPORTS_DIR / "drafter_kappa_baseline.json"
    artifact_path.write_text(baseline.model_dump_json(indent=2) + "\n")

    print(f"froze {len(runs)} run(s) → {artifact_path.relative_to(_REPORTS_DIR.parent.parent)}")
    for c in baseline.classes:
        flag = "  (constant classifier)" if c.constant_classifier else ""
        cert = "certifiable" if c.certifiable else "not certifiable"
        print(f"  {c.axe_rule:<15} κ {c.kappa:+.3f}  CI [{c.ci_low:+.3f}, {c.ci_high:+.3f}]  {cert}{flag}")


if __name__ == "__main__":
    main()
