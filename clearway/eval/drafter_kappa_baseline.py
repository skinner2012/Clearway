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
"robust to the second reading" claim is checkable from the artifact rather than taken on faith: only the link
class moves under `partial_flags=False`, and no certifiability verdict flips.

**The pre-registration is part of the artifact, not commentary about it.** Alongside the per-class rows the
freeze carries the POOLED endpoint that is the primary result (per-class certification is zero-margin at
these n, so resting the answer on it would report failure for a fix that worked), the scope correction with
both of the arithmetic side-effects it causes, the named falsifiable predictions a later run scores, and the
denominators that keep a later run's pooled rates like-for-like. All of it is fixed here, before the run that
could be tempted to choose it.

**The superseded reading is preserved as a declared field** (`scope_correction.superseded`), not as a second
artifact file beside the current one — a parallel file is exactly the stale surface the correction exists to
remove. κ across the correction is NOT comparable (the class has a different n); the paired per-case
comparison is, on the surviving cases, and that is what a later run uses.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import rule_success_criteria
from clearway.eval.drafter_kappa import (
    _BOOTSTRAP_SEED,
    _RESAMPLES,
    CEILING_PREREGISTRATION,
    ONE_SIDED,
    _grouped,
    class_ceilings,
    class_kappa_cis,
    class_kappas,
    minimum_wins,
    sign_test_p,
    tolerated_regressions,
)
from clearway.eval.drafter_score import DraftedCase
from clearway.schemas.models import (
    ConformanceLevel,
    DrafterKappaBaseline,
    DrafterKappaClass,
    ExclusionSideEffect,
    PooledEndpoint,
    PreregisteredPrediction,
    ScopeCorrection,
    ScopedDenominators,
    SupersededClassReading,
    UnreachableError,
    UnreachableErrorKind,
)

_HEADLINE_PARTIAL_FLAGS = True

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "act-gold" / "html"

# WCAG levels for the criteria the scoping turns on — the conformance ground, stated once.
_SC_LEVEL = {"2.4.4": ConformanceLevel.A, "2.4.9": ConformanceLevel.AAA}

_EXCLUDED_RULE = "Link is descriptive"
_RETAINED_RULE = "Link in context is descriptive"
_CONFORMANCE_TARGET = "WCAG 2.2 Level A/AA — the target a VPAT/ACR row is drafted against"

_SCOPE_RATIONALE = (
    "'Link is descriptive' maps to SC 2.4.9 only, which is Level AAA, and every conformance row Clearway "
    "drafts is scored against a Level A/AA target; its sibling 'Link in context is descriptive' carries the "
    "Level A criterion 2.4.4 and stays scored, so the link judgment is not dropped, only narrowed to the "
    "level being claimed. This ground existed before any fixed run and does not depend on how one turns "
    "out, which is what makes the correction a pre-registration rather than a choice made after seeing a "
    "result."
)
_SCOPE_CONSEQUENCE = (
    "It also removes a contradiction the pipeline cannot represent: two of the excluded rule's fixtures are "
    "byte-identical to retained ones while carrying the opposite ACT outcome, so one member of each pair was "
    "permanently wrong under a one-Finding-per-element design. That is a consequence of the scoping, NOT its "
    "reason — unlike the other exclusions, which each hold for a rule in isolation, this contradiction "
    "dissolves under a different grouping key and so cannot carry an exclusion on its own."
)

# The two cases the correction moves, each named with the byte-identical twin on the other side of the scope.
_MANUFACTURED_WIN_ID = "6566c139dc811b5a566a8e58c85d1f7f3c550d04"
_UNSCORED_REGRESSION_ID = "48cbc84f4c020393cfb56fd53337827278b2d528"

_MANUFACTURED_WIN_EFFECT = (
    "Retained, and currently a false positive. Before the correction it was unwinnable: its byte-identical "
    "twin carries the opposite gold, so any input change that fixed one broke the other. With the twin out "
    "of scope it becomes one of the five wins the class now needs — an error converted to winnable by the "
    "scoping itself, not by any fix."
)
_UNSCORED_REGRESSION_EFFECT = (
    "Dropped, and currently CORRECT. Fixing its byte-identical twin flips this case from correct to wrong, "
    "because both receive the same input — and that regression is no longer scored anywhere. One "
    "manufactured win and one hidden regression: a reader who cannot see this pair cannot audit the "
    "improvement the class reports."
)

_POOLED_AXE_RULES = ("label", "link-name")
_POOLED_HYPOTHESIS = (
    "Accuracy on the classes whose deciding fact is absent from the drafter's input is governed by whether "
    "that fact is PRESENT, not by model strength — same model, same weights, same temperature. The claim is "
    "about referent presence rather than about either class, so the estimand is the pool of both classes' "
    "reachable errors and the per-class tests are secondary. Per-class certification requires a perfect run "
    "twice over (tolerated_regressions = 0 on each), which is a property of the gold set's size; resting "
    "the answer there would report failure for a fix that worked."
)
_POOLED_FAILURE_DEFINITION = (
    "Pooled improvements b <= 2, with the referent verifiably present in every prompt, the control class "
    "byte-identical and determinism holding, is reported as THESIS NOT SUPPORTED — in those words. It is a "
    "publishable result, not a setback to be reframed. If instead the referent is not verifiably present, "
    "the thesis was never tested and the run says nothing about it."
)

_PREDICTIONS = (
    PreregisteredPrediction(
        prediction_id="accname-trailing-colon",
        axe_rule="label",
        act_testcase_ids=[
            "e419548ab0986f9d71f073253193a66178191536",
            "5d11716ba4bcb2c9804cbea517e2382b51d89217",
        ],
        claim=(
            "Supplying the resolved accessible name will NOT separate these two cases: the drafter will "
            "either leave the gold-passed one wrong, or fix it by breaking the gold-failed one."
        ),
        reasoning=(
            "Their accessible names differ only by a trailing colon ('Name'/'Street' against "
            "'Name:'/'Street:') while their gold outcomes are opposite, so the accname alone cannot "
            "distinguish them for any rater that treats a trailing colon as immaterial."
        ),
        epistemic_status="argued",
        consequence_if_held=(
            "The class lands at 4 of 5 reachable errors fixed (p = 0.0625) or 5 fixed with 1 broken "
            "(p = 0.109) — neither clears alpha. The consequence is arithmetic; the antecedent is a claim "
            "about model behaviour, and models distinguish on a trailing colon routinely."
        ),
    ),
    PreregisteredPrediction(
        prediction_id="destination-outside-dom",
        axe_rule="link-name",
        act_testcase_ids=["3bb1986371e1ad785428f87c89a1dd7071604ee0"],
        claim="Surrounding-context injection will not fix this case, and may move it the wrong way.",
        reasoning=(
            "Its gold turns on the link's DESTINATION — the linked resource is a report, not the workshop "
            "the link text names — and the destination lies outside a single-page DOM. The surrounding "
            "paragraph describes the workshop, so injected context makes the existing link text look MORE "
            "justified, not less."
        ),
        epistemic_status="argued",
        consequence_if_held=(
            "The class lands at 4 of 5 and is not certified. It stays INSIDE the reachable count: "
            "subtracting a predicted failure from the denominator is how a ceiling becomes unfalsifiable, "
            "and a confirmed prediction of failure is still an error not fixed."
        ),
    ),
)


def _cases(artifact: dict[str, Any], *, scoped: bool) -> list[DraftedCase]:
    """The flat case stream under one scope reading — the denominator every pooled rate runs on."""
    return [case for group in _grouped(artifact, scoped=scoped).values() for case in group]


def _shared_fixture_digest(*act_testcase_ids: str) -> str:
    """The sha256 the named cases' fixture files share. Raises if they have drifted apart — the pair being
    byte-identical is the whole argument, so it is verified at freeze time, never asserted in prose."""
    digests = {hashlib.sha256((_FIXTURES / f"{tid}.html").read_bytes()).hexdigest() for tid in act_testcase_ids}
    if len(digests) != 1:
        raise ValueError(f"{act_testcase_ids} are no longer byte-identical — the exclusion arithmetic does not hold")
    return digests.pop()


def _pooled_endpoint(classes: list[DrafterKappaClass], *, alpha: float) -> PooledEndpoint:
    """The primary endpoint: one hypothesis, tested once, over the pooled reachable errors of the classes a
    fix treats. Pure arithmetic over the rows already computed."""
    reachable = sum(c.reachable_errors for c in classes if c.axe_rule in _POOLED_AXE_RULES)
    p_value = sign_test_p(reachable, 0)
    return PooledEndpoint(
        axe_rules=list(_POOLED_AXE_RULES),
        hypothesis=_POOLED_HYPOTHESIS,
        reachable_errors=reachable,
        p_value=p_value,
        certifiable=p_value <= alpha,
        minimum_wins=minimum_wins(alpha),
        tolerated_regressions=tolerated_regressions(reachable, alpha),
        failure_definition=_POOLED_FAILURE_DEFINITION,
    )


def _superseded(artifact: dict[str, Any]) -> list[SupersededClassReading]:
    """The classes the scope correction changed, as they read before it. Derived by scoring the same frozen
    artifact unscoped and keeping only the rows that actually moved — so an unchanged class never appears."""
    scoped = {c.axe_rule: c for c in class_kappas(artifact, partial_flags=_HEADLINE_PARTIAL_FLAGS)}
    rows: list[SupersededClassReading] = []
    for k in class_kappas(artifact, partial_flags=_HEADLINE_PARTIAL_FLAGS, scoped=False):
        if k.axe_rule in scoped and scoped[k.axe_rule].n == k.n:
            continue
        rows.append(
            SupersededClassReading(
                axe_rule=k.axe_rule,
                rule_names=list(k.rule_names),
                n=k.n,
                failed=k.failed,
                passed=k.passed,
                tp=k.tp,
                fp=k.fp,
                fn=k.fn,
                tn=k.tn,
                kappa=k.kappa,
                errors=k.fp + k.fn,
                p_value=sign_test_p(k.fp + k.fn, 0),
                note=(
                    f"This class pooled {len(k.rule_names)} ACT rules over {k.n} cases before the scoping, and its "
                    f"ceiling was read off all {k.fp + k.fn} of its errors — optimistic on both counts. Its kappa is "
                    "NOT comparable to the current one: the class has a different n and a different membership. What "
                    "survives the correction is the PAIRED per-case comparison on the surviving act_testcase_ids, "
                    "which is what a later run is scored on."
                ),
            )
        )
    return rows


def _scope_correction(artifact: dict[str, Any]) -> ScopeCorrection:
    """The recorded narrowing: its conformance-level ground, the contradiction it also removes (a
    consequence, not the reason), both arithmetic side-effects, and the superseded reading."""
    excluded_scs = rule_success_criteria(_EXCLUDED_RULE)
    retained_scs = rule_success_criteria(_RETAINED_RULE)
    digest = _shared_fixture_digest(_MANUFACTURED_WIN_ID, _UNSCORED_REGRESSION_ID)
    return ScopeCorrection(
        excluded_rule=_EXCLUDED_RULE,
        excluded_rule_success_criteria=excluded_scs,
        excluded_rule_levels=[_SC_LEVEL[sc] for sc in excluded_scs],
        retained_rule=_RETAINED_RULE,
        retained_rule_success_criteria=retained_scs,
        retained_rule_levels=[_SC_LEVEL[sc] for sc in retained_scs],
        conformance_target=_CONFORMANCE_TARGET,
        rationale=_SCOPE_RATIONALE,
        consequence=_SCOPE_CONSEQUENCE,
        cases_before=len(_cases(artifact, scoped=False)),
        cases_after=len(_cases(artifact, scoped=True)),
        manufactured_win=ExclusionSideEffect(
            act_testcase_id=_MANUFACTURED_WIN_ID,
            twin_act_testcase_id=_UNSCORED_REGRESSION_ID,
            content_sha256=digest,
            effect=_MANUFACTURED_WIN_EFFECT,
        ),
        unscored_regression=ExclusionSideEffect(
            act_testcase_id=_UNSCORED_REGRESSION_ID,
            twin_act_testcase_id=_MANUFACTURED_WIN_ID,
            content_sha256=digest,
            effect=_UNSCORED_REGRESSION_EFFECT,
        ),
        superseded=_superseded(artifact),
    )


def _denominators(artifact: dict[str, Any]) -> ScopedDenominators:
    """The denominators every pooled rate runs on, beside the ones they replace — so a later run's recall,
    false-positive rate, SC-match and ECE can be read like-for-like against the earlier ones."""
    scoped = _cases(artifact, scoped=True)
    unscoped = _cases(artifact, scoped=False)
    return ScopedDenominators(
        cases=len(scoped),
        minting_cases=sum(1 for c in scoped if c.drafts),
        honest_misses=sum(1 for c in scoped if not c.drafts),
        failed_cases=sum(1 for c in scoped if c.expected == "failed"),
        passed_cases=sum(1 for c in scoped if c.expected == "passed"),
        findings=sum(len(c.drafts) for c in scoped),
        superseded_cases=len(unscoped),
        superseded_findings=sum(len(c.drafts) for c in unscoped),
    )


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
                unreachable=[
                    UnreachableError(
                        act_testcase_id=u.act_testcase_id,
                        kind=UnreachableErrorKind(u.kind),
                        reason=u.reason,
                    )
                    for u in ceil.unreachable
                ],
                honest_miss_errors=sum(1 for u in ceil.unreachable if u.kind == UnreachableErrorKind.HONEST_MISS),
                contradictory_gold_errors=sum(
                    1 for u in ceil.unreachable if u.kind == UnreachableErrorKind.CONTRADICTORY_GOLD
                ),
                reachable_errors=ceil.reachable_errors,
                reachable_error_ids=list(ceil.reachable_error_ids),
                reachable_p_value=ceil.reachable_p_value,
                reachable_certifiable=ceil.reachable_certifiable,
                tolerated_regressions=ceil.tolerated_regressions,
            )
        )

    alpha = ceilings[classes[0].axe_rule].alpha
    return DrafterKappaBaseline(
        classes=classes,
        headline_partial_flags=_HEADLINE_PARTIAL_FLAGS,
        alpha=alpha,
        one_sided=ONE_SIDED,
        preregistration=CEILING_PREREGISTRATION,
        pooled_endpoint=_pooled_endpoint(classes, alpha=alpha),
        scope_correction=_scope_correction(artifact),
        predictions=list(_PREDICTIONS),
        denominators=_denominators(artifact),
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
