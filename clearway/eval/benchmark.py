"""Assemble a `BenchmarkReport` from a frozen acceptance-run artifact — pure, no LLM, no network.

The live builder runs the pipeline over the held-out ACT set ONCE and freezes a raw artifact (drafts +
judge booleans + provenance); this module replays that artifact into the scored, reproducible report.
The split is the same one the κ replay uses: the non-deterministic models are called once, and every
number is re-derivable from the checked-in file, never by re-invoking a cloud model.

Both subjects are scored here by deterministic comparison against ACT gold — the drafter per case (with
the honest-misses carried in as drafts-less cases so recall isn't overstated) and the judge on the
conformance axis. The artifact's `injected` and `tier_b` sections are optional: a first plain run has
neither, an injection pass fills `injected`, and the realistic-page pass fills `tier_b` — the assembly
reads whatever is present, so the same builder grows the report without a schema change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clearway.eval.drafter_score import DraftedCase, DraftedFinding, score_drafter
from clearway.eval.judge_score import InjectedResult, JudgedDraft, score_judge
from clearway.eval.stats import COLLAPSE_RULE, is_flag
from clearway.schemas.models import (
    AcceptanceScorecard,
    BenchmarkReport,
    Conformance,
    NotMeasuredItem,
    TierBSmoke,
)

# The explicit out-of-scope list — stated, never hidden. Static: these are properties of the method,
# not of any one run.
NOT_MEASURED: list[NotMeasuredItem] = [
    NotMeasuredItem(
        what="Expert-minutes-per-finding, and whether a drafted remediation is genuinely useful to an implementer",
        why="both need a real accessibility specialist's time — the one resource unavailable; the benchmark "
        "checks only alignment with the canonical technique (direction), which is a proxy, not efficacy.",
    ),
    NotMeasuredItem(
        what="Recall / missed findings — how much the system failed to raise",
        why="a Finding exists only when axe emits something; what axe cannot see (reading order, motion) is "
        "invisible to the pipeline too, so total miss volume cannot be measured here.",
    ),
    NotMeasuredItem(
        what="Image alt-text quality",
        why="raised via passes[] but not validatable — the ACT filename leaks the answer, so a DOM-only pipeline "
        "would score filename-matching, not image-text-correspondence judgment; needs a multimodal drafter.",
    ),
    NotMeasuredItem(
        what="The judge's own ceiling",
        why="judgment-item scores in production are the judge's, so no judgment-item number can be trusted beyond "
        "judge_kappa — the judge's accuracy is their upper bound.",
    ),
]


def _drafted_finding(d: dict[str, Any]) -> DraftedFinding:
    return DraftedFinding(
        conformance=Conformance(d["conformance"]),
        cited_sc_ids=tuple(d["cited_sc_ids"]),
        confidence=d["confidence"],
    )


def _drafted_cases(artifact: dict[str, Any]) -> list[DraftedCase]:
    """Minting cases (with their per-finding drafts) plus the honest-misses as drafts-less cases —
    a failed honest-miss is then an automatic recall miss, a passed one trivially clean."""
    cases = [
        DraftedCase(
            act_testcase_id=c["act_testcase_id"],
            rule_name=c["rule_name"],
            expected=c["expected"],
            gold_success_criteria=tuple(c["gold_success_criteria"]),
            drafts=tuple(_drafted_finding(d) for d in c["drafts"]),
        )
        for c in artifact["cases"]
    ]
    misses = [
        DraftedCase(
            act_testcase_id=m["act_testcase_id"],
            rule_name=m["rule_name"],
            expected=m["expected"],
            gold_success_criteria=tuple(m["gold_success_criteria"]),
            drafts=(),
        )
        for m in artifact.get("honest_misses", [])
    ]
    return cases + misses


def _judged_drafts(artifact: dict[str, Any]) -> list[JudgedDraft]:
    """One judged draft per minted finding: its deterministic conformance-correctness vs gold paired
    with the judge's own `conformance_correct` boolean (the conformance-axis measurement)."""
    drafts: list[JudgedDraft] = []
    for c in artifact["cases"]:
        should_flag = c["expected"] == "failed"
        for d in c["drafts"]:
            drafts.append(
                JudgedDraft(
                    rule_name=c["rule_name"],
                    act_correct=is_flag(Conformance(d["conformance"])) == should_flag,
                    judge_pass=d["judge_conformance_correct"],
                )
            )
    return drafts


def _injected(artifact: dict[str, Any], key: str) -> list[InjectedResult]:
    """The injected known-wrong drafts of one mutation, if the artifact has an injection pass — else
    empty (a plain run reports the detection rates as no-data)."""
    return [
        InjectedResult(rule_name=r["rule_name"], caught=r["caught"]) for r in artifact.get("injected", {}).get(key, [])
    ]


def _tier_b(artifact: dict[str, Any]) -> TierBSmoke | None:
    """The realistic-page smoke test, if the artifact has a Tier-B pass — always illustrative (n=2),
    never a headline number. Absent on a plain Tier-A run."""
    tb = artifact.get("tier_b")
    if tb is None:
        return None
    return TierBSmoke(
        n=tb.get("n", len(tb.get("instance_ids", []))),
        instance_ids=list(tb.get("instance_ids", [])),
        clean_vs_noisy_note=tb.get("clean_vs_noisy_note", ""),
        method_and_limits=tb["method_and_limits"],
    )


def build_scorecard(artifact: dict[str, Any]) -> AcceptanceScorecard:
    """Score both subjects off the frozen artifact → the metrics payload. `noise_floor` stays None —
    it needs the repeat runs a single artifact does not carry."""
    drafter_scoring = score_drafter(_drafted_cases(artifact))
    judge = score_judge(
        _judged_drafts(artifact),
        conformance_flip=_injected(artifact, "conformance_flip"),
        sc_swap=_injected(artifact, "sc_swap"),
        rationale_note=artifact.get("injected", {}).get("rationale_note", ""),
    )
    return AcceptanceScorecard(
        drafter=drafter_scoring.score,
        judge=judge,
        noise_floor=None,
        tier_b=_tier_b(artifact),
        not_measured=NOT_MEASURED,
        conformance_collapse_rule=COLLAPSE_RULE,
        notes=drafter_scoring.sensitivity_notes,
    )


def build_report(artifact: dict[str, Any]) -> BenchmarkReport:
    """The frozen artifact → the reproducible `BenchmarkReport`. Provenance (config / corpus versions,
    model digests, axe version, ACT export hash) is read straight off the artifact — the builder is
    responsible for freezing it by content hash, not by a mutable name."""
    return BenchmarkReport(
        run_ids=list(artifact["run_ids"]),
        config_id=artifact["config_id"],
        eval_set_id=artifact["eval_set_id"],
        corpus_version=artifact["corpus_version"],
        drafter_model=artifact["drafter_model"],
        drafter_model_digest=artifact["drafter_model_digest"],
        judge_model=artifact["judge_model"],
        judge_model_digest=artifact["judge_model_digest"],
        judge_version=artifact["judge_version"],
        axe_core_version=artifact["axe_core_version"],
        act_export_hash=artifact["act_export_hash"],
        created_at=datetime.fromisoformat(artifact["created_at"]),
        scorecard=build_scorecard(artifact),
    )
