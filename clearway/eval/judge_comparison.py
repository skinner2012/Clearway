"""The two comparisons this milestone owes, computed off the frozen runs and kept apart.

They share one run and several metric names, and blurring them is the easiest mistake available here.

* **Comparison 1 — judge vs judge.** Did removing the anchor make the ROUTING DECISION better? The two
  sides are the anchored and blind configurations; ACT gold is the oracle; the unit is the **case**; and
  it is the only thing in this milestone that carries a statistical test.
* **Comparison 2 — judge vs drafter.** What does the second reader look like, and is it worth having?
  The two sides are the blind judge and the frozen drafter. The disagreement rate is per **finding**;
  *which of them is more often right* is per class, per case, against gold. **No p-value anywhere.**

**The less useful comparison is the testable one.** Comparison 2 is what says whether the signal is
worth wiring into anything, and it carries no significance verdict whatsoever.

Zero model calls, zero network, no clock
----------------------------------------
Everything is read from files that already exist: the frozen replay drafts, both configurations'
measured baselines, and the drafter comparator. `created_at` is taken off the replay pass, so the record
is a deterministic function of its four sources and a rebuild is byte-identical — which is what lets the
freeze be pinned by comparison rather than by a digest computed from the file's own bytes.

What is reused rather than re-implemented, and why it matters here
-----------------------------------------------------------------
* **The sign test is `null_routing_sign_test`**, the same function the floor bar was measured with. The
  bar this stage runs at was derived from that function's `improved`/`regressed` columns on
  same-configuration pass-pairs; counting the real contrast any other way would compare a number against
  a bar measured on a different definition. Its name says *null* because the null is what it was written
  for — the arithmetic is the paired sign test, and passing it two configurations rather than two passes
  is the whole difference.
* **Both configurations' routing decisions are replayed through their own harnesses**
  (`results_from_rows` + `natural_majority`; `outcomes_from_rows` + `releases`), which refuse outright if
  the frozen rows are not those asks. Nothing is lifted from a summary field.
* **The threshold is `judge_threshold.threshold`**, plugged with the floor bar frozen in the anchored
  baseline. This stage measures nothing about the floor and re-derives none of it.

⚠️ Two streams come out of the blind configuration and they are NOT the same quantity
------------------------------------------------------------------------------------
The **routing decision** is *does the judge agree with the draft* — the thing Comparison 1 scores. The
**rater verdict** is *does the judge think this content fails* — the judge answering the question itself,
which is what puts it beside the drafter in Comparison 2's side-by-side. Only a blind judge has the
second one at all; an anchored judge emits a grade of a draft, never a verdict of its own.

Invoke: `uv run python -m clearway.eval.judge_comparison`
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from clearway.eval.judge_anchored import anchored_asks, natural_majority
from clearway.eval.judge_anchored_baseline import (
    case_act_wrong,
    finding_act_wrong,
    results_from_rows,
    scoring_block,
    spread,
)
from clearway.eval.judge_anchored_baseline import report_path as anchored_report_path
from clearway.eval.judge_blind import blind_asks, conformance_majorities, releases, score_blind
from clearway.eval.judge_blind_baseline import outcomes_from_rows
from clearway.eval.judge_blind_baseline import report_path as blind_report_path
from clearway.eval.judge_drafter_comparator import report_path as comparator_report_path
from clearway.eval.judge_observation_unit import (
    AGGREGATION_ORDER,
    DISAGREEMENT_RATE_UNIT,
    OBSERVATION_UNIT,
    aggregation_divergence,
    majority_stream,
    null_routing_sign_test,
)
from clearway.eval.judge_threshold import ALPHA, threshold
from clearway.eval.kappa import cohen_kappa, raw_agreement
from clearway.eval.stats import COLLAPSE_RULE, is_flag

COMPARISON_1 = (
    "COMPARISON 1 — judge vs judge. Did removing the anchor make the ROUTING DECISION better? The two "
    "sides are the anchored configuration and the blind one; the oracle is ACT gold, scored into the "
    "four routing cells; the unit is the CASE (40); and this is the only comparison in the milestone "
    "that is statistically tested. ⚠️ It is also the LESS USEFUL of the two: at best it establishes that "
    "blind routes better than a mechanism this project had already judged broken."
)

COMPARISON_2 = (
    "COMPARISON 2 — the blind judge vs the frozen drafter. What does the second reader actually look "
    "like, and is it worth having? The disagreement rate is per FINDING (54) and is the milestone's "
    "primary deliverable; *which of them is more often right* is per class, per case, against ACT gold. "
    "⚠️ DESCRIPTIVE BY CONSTRUCTION — no p-value anywhere, because per-class n did not grow. It does not "
    "exist under the anchored configuration at all: a judge that grades a draft emits no verdict of its "
    "own to set beside the drafter's."
)

# ⚠️ The declaration the comparison stage owes, which the drafter comparator deliberately left open.
DENOMINATOR_DECLARATION = (
    "DECLARED HERE, because the two raters do not share a per-class n even at the pinned unit. THE JUDGE "
    "IS QUOTED OVER ITS OWN 40 JUDGE-VISIBLE CASES AND THE DRAFTER OVER ITS 44, both n printed on every "
    "row, and no arithmetic anywhere subtracts one from the other. The gap is the 4 cases that minted no "
    "finding: a case that mints nothing produces no finding to judge, while the drafter's stream carries "
    "it because a failed one is the automatic recall miss it is. The alternative — restricting the "
    "drafter to the 40 minting cases — buys one denominator at the price of dropping 2 real errors from "
    "the drafter's count, which flatters it, and it would mean republishing a frozen number. The gap is "
    "class-structured rather than spread (empty-heading 2, link-name 2, the other two classes 0), so a "
    "per-class kappa difference on either of those classes is PARTLY A DIFFERENCE OF DENOMINATOR and is "
    "never read as a difference of rater."
)

FOUR_CONDITIONS = (
    "1. VARIANCE IS NOT SHARED. The drafter's frozen passes are bit-identical, so its kappa is a point "
    "estimate; a cloud judge is not bit-reproducible even at a fixed effort, so its kappa is a draw. The "
    "judge's side is therefore the MAJORITY VERDICT across its passes, with the per-pass values and "
    "their SD printed beside it — never one pass placed beside a deterministic number. "
    "2. MODEL AND ROLE ARE CONFOUNDED. The judge is a cloud reasoning model and the drafter a local one, "
    "so a kappa difference is a different model AND a different role. That is enough for the product "
    "question — is a second reader worth having — and is not enough for any statement about what either "
    "model can do. "
    "3. FRAMING IS A LIVE CONFOUND. Both models follow prompt framing over page content. The judge's "
    "finding side reuses the drafter's own referent and candidate sentences, but two differences "
    "survive: the drafter states each finding's provenance bucket and the finding side does not, and the "
    "ORDER of the shared material differs (drafter: candidates then referent; finding side: referent "
    "then candidates). Position is framing, so a per-class difference may be the framing rather than the "
    "rater. "
    "4. PER-CLASS N DID NOT GROW, so no per-class number is tested and every row carries BOTH n. The "
    "smallest class cannot be certified at any effect size, and 3 of its 5 observations are the same "
    "question asked three times — see the duplicate-ask caveat."
)

DUPLICATE_ASK_CAVEAT = (
    "⚠️ The 54 findings render only 45 distinct finding-side blocks, in 8 duplicate groups, and not one "
    "group lies inside a single case — so two clusters can be sent a byte-identical question and their "
    "answers are correlated by a route no within-case statistic sees and the case collapse cannot "
    "absorb. It lands hardest on the smallest class: 3 of document-title's 5 observations are one "
    "question asked three times, so EVERY document-title figure carries this caveat, a zero included. "
    "The blind ask is the block alone, so its duplication cannot be lower than the anchored side's; "
    "measured, it is the same 17 findings."
)

# The historical figures the injected-versus-real gap is read against — the acceptance sweep's, the only
# prior that exists. Held as scalars so the guard's arithmetic has something typed to compare against;
# quoted with their denominators because they were measured on a DIFFERENT draft set, which is the whole
# difficulty in reading them.
HISTORICAL_SC_SWAP_DETECTION = 1.00
HISTORICAL_CONFORMANCE_FLIP_DETECTION = 0.82
HISTORICAL_REAL_DETECTION = 0.33

HISTORICAL_INJECTED_BASELINE: dict[str, Any] = {
    "injected_sc_swap_detection": HISTORICAL_SC_SWAP_DETECTION,
    "injected_sc_swap_n": 63,
    "injected_conformance_flip_detection": HISTORICAL_CONFORMANCE_FLIP_DETECTION,
    "injected_conformance_flip_n": 39,
    "real_detection": HISTORICAL_REAL_DETECTION,
    "real_detection_n": 24,
    "real_detection_unit": "finding",
    "gap": "threefold — injected detection at 1.00 and 0.82 against real detection at 0.33",
    "⚠️": (
        "MEASURED ON A DIFFERENT DRAFT SET — 63 drafted findings from the acceptance sweep, of which 24 "
        "were act-wrong. This milestone replays 54 findings over 40 cases with 15 act-wrong, so no "
        "figure here shares a denominator with anything below and a difference between the two is a "
        "difference of set as much as of judge. It is the only prior that exists, so it is quoted; it is "
        "not a paired comparator and nothing is subtracted from it."
    ),
}

# The pre-committed reporting rules, as outcome names. Fixed before the comparison ran; the selection is
# mechanical and the predicate that chose is recorded beside the answer.
VERDICT_SUPPORTED = "SUPPORTED — blind cleared the pre-registered bar; anchoring was the dominant cause"
VERDICT_DIRECTIONAL = (
    "WORKED BUT UNCERTIFIABLE — blind won on more cases than it lost on, and not by enough to clear the "
    "pre-registered bar"
)
VERDICT_NO_MOVEMENT = (
    "ANCHORING WAS NOT THE DOMINANT CAUSE — blind did not win on more cases than it lost on. The "
    "milestone's own falsification condition, and a result rather than a failure: the remaining "
    "correlation lives somewhere this milestone did not touch"
)
VERDICT_UNCERTIFIABLE_AT_N = (
    "UNCERTIFIABLE AT THIS N — no win count available at this many discordant pairs could have "
    "constituted a result, so the comparison was never in a position to certify. ⚠️ This is NOT a bar the "
    "evidence missed, and must not be written up as one"
)


# ---------------------------------------------------------------------------------------------
# The two configurations' streams, replayed through their own harnesses
# ---------------------------------------------------------------------------------------------


def anchored_releases(artifact: dict[str, Any], frozen: dict[str, Any]) -> dict[str, bool]:
    """`finding_id → the anchored judge released it`, majority across its passes.

    Replayed through the anchored harness' own `results_from_rows`, which refuses if the frozen rows are
    not those asks — so a record that no longer describes these drafts fails to load rather than
    producing a well-formed comparison of something else.
    """
    asks = anchored_asks(artifact)
    passes = [
        results_from_rows(
            asks,
            block["results"],
            judge_model=frozen["judge_model"],
            judge_version=frozen["judge_version"],
            run_id=f"anchored-pass-{index + 1}",
        )
        for index, block in enumerate(frozen["pass_results"])
    ]
    return natural_majority(asks, passes)


def blind_passes(artifact: dict[str, Any], frozen: dict[str, Any]) -> list[list[Any]]:
    """The blind configuration's outcomes, per pass, replayed from its frozen answers."""
    asks = blind_asks(artifact)
    return [
        outcomes_from_rows(
            asks,
            block["results"],
            judge_model=frozen["judge_model"],
            judge_version=frozen["judge_version"],
            run_id=f"blind-pass-{index + 1}",
        )
        for index, block in enumerate(frozen["pass_results"])
    ]


def flag_stream(artifact: dict[str, Any], released: dict[str, bool]) -> list[list[bool]]:
    """`[case][finding]` — did this configuration raise its hand, in the artifact's own case order.

    No collapse here: the sign test applies flag-if-any itself, and it must be the one doing it so the
    real contrast is counted by exactly the function the floor bar was measured with.
    """
    return [[not released[d["finding_id"]] for d in case["drafts"]] for case in artifact["cases"]]


# ---------------------------------------------------------------------------------------------
# Comparison 1 — the paired routing test
# ---------------------------------------------------------------------------------------------


def paired_case_rows(
    artifact: dict[str, Any], anchored: dict[str, bool], blind: dict[str, bool]
) -> list[dict[str, Any]]:
    """Every case where the two configurations' routing CORRECTNESS differs, named to its id.

    A case is a discordant pair when one configuration routes it right and the other routes it wrong.
    Because gold is fixed per case, a flip of the collapsed decision is always a flip of correctness, so
    this is the same event the sign test counts — the rows exist so a reader can see which cases carried
    the result rather than take a pair of integers on trust.
    """
    wrong = case_act_wrong(artifact)
    left, right = flag_stream(artifact, anchored), flag_stream(artifact, blind)
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(artifact["cases"]):
        anchored_flag, blind_flag = any(left[index]), any(right[index])
        anchored_ok, blind_ok = anchored_flag == wrong[index], blind_flag == wrong[index]
        if anchored_ok == blind_ok:
            continue
        rows.append(
            {
                "act_testcase_id": case["act_testcase_id"],
                "axe_rule": case["axe_rule"],
                "findings_on_the_case": len(case["drafts"]),
                "drafted_answer_is_act_wrong": wrong[index],
                "anchored_raised_its_hand": anchored_flag,
                "blind_raised_its_hand": blind_flag,
                "winner": "blind" if blind_ok else "anchored",
            }
        )
    return rows


def paired_test(artifact: dict[str, Any], anchored: dict[str, bool], blind: dict[str, bool]) -> dict[str, Any]:
    """The one-sided exact sign test, at the pinned unit, at the bar frozen before this stage ran.

    The pre-registered direction is *blind improves on anchored*, so anchored is the left-hand stream and
    `improved` is blind's win count. The per-finding row rides along and **does not govern** — a
    threshold counted per finding cannot be applied to a test scored per case.
    """
    left, right = flag_stream(artifact, anchored), flag_stream(artifact, blind)
    case_row = null_routing_sign_test([left, right], case_act_wrong(artifact))[0]
    finding_row = null_routing_sign_test(
        [[[flag] for cluster in left for flag in cluster], [[flag] for cluster in right for flag in cluster]],
        finding_act_wrong(artifact),
    )[0]
    return {
        "per_case": {
            "unit": OBSERVATION_UNIT,
            "observations": len(artifact["cases"]),
            "discordant_pairs": case_row["discordant"],
            "blind_wins": case_row["improved"],
            "anchored_wins": case_row["regressed"],
            "one_sided_p": case_row["one_sided_p"],
        },
        "per_finding_does_not_govern": {
            "unit": "finding",
            "observations": sum(len(cluster) for cluster in left),
            "discordant_pairs": finding_row["discordant"],
            "blind_wins": finding_row["improved"],
            "anchored_wins": finding_row["regressed"],
            "one_sided_p": finding_row["one_sided_p"],
            "note": (
                "Reported beside the test and never instead of it. A threshold counted per finding "
                "cannot govern a test scored per case, and the pinned unit was fixed before any run."
            ),
        },
        "direction": (
            "One-sided, and the direction was pre-registered: `blind_wins` counts cases the blind "
            "configuration routes correctly and the anchored one does not. `anchored_wins` is the same "
            "event pointing back, and it is reported rather than folded into the p-value."
        ),
    }


def verdict_for(*, wins: int, losses: int, required_wins: int | None) -> str:
    """The pre-committed reporting rule this result falls under. Mechanical, in a fixed order.

    Unattainability is read FIRST, because a bar no win count at this `n` could have met is a different
    outcome from an effect that failed to reach one — filing the first as the second reports a comparison
    that was never in a position to certify as a mechanism that did not work.
    """
    if required_wins is None:
        return VERDICT_UNCERTIFIABLE_AT_N
    if wins >= required_wins:
        return VERDICT_SUPPORTED
    if wins > losses:
        return VERDICT_DIRECTIONAL
    return VERDICT_NO_MOVEMENT


def injected_versus_real(anchored_frozen: dict[str, Any]) -> dict[str, Any]:
    """The injected-versus-real gap, on the ANCHORED configuration, and the guard it can trip.

    ⚠️ **Read on anchored only.** Both mutations edit the draft, and a blind ask is byte-identical
    whatever the draft says, so under blind an SC swap is caught 1.000 by construction and a conformance
    flip is caught exactly when the judge already agreed. Neither figure contains one bit of judge
    behaviour, so the blind numbers are algebra and are not eligible to trip this guard — running them
    into it would report the milestone failed for a reason that is not about the judge.

    Two readings are emitted and neither is folded into the other. The **within-run gap** needs no
    cross-set comparison at all: injected detection against real detection on this run's own drafts. The
    **movement against the historical baseline** is the pre-committed guard's own wording — *injected
    detection rises while real detection does not* — and it crosses draft sets, which is stated on the
    block rather than left for a reader to notice.
    """
    measured = anchored_frozen["injected_versus_real"]
    swap = measured["injected_sc_swap_detection"]
    flip = measured["injected_conformance_flip_detection"]
    real_finding = measured["real_detection_per_finding"]
    real_case = measured["real_detection_per_case"]
    injected_rose = swap > HISTORICAL_SC_SWAP_DETECTION or flip > HISTORICAL_CONFORMANCE_FLIP_DETECTION
    real_rose = real_finding > HISTORICAL_REAL_DETECTION
    return {
        "configuration": "anchored",
        "read_on_anchored_only": (
            "Both mutations edit the DRAFT and a blind ask never contains one, so under blind an SC swap "
            "is caught 1.000 by construction and a conformance flip is caught exactly when the judge "
            "already agreed. Those are restatements of arithmetic, not measurements of a judge, and they "
            "are NOT eligible to trip the guard below."
        ),
        "measured": {
            "injected_sc_swap_detection": swap,
            "injected_sc_swap_n": measured["injected_sc_swap_n"],
            "injected_conformance_flip_detection": flip,
            "injected_conformance_flip_n": measured["injected_conformance_flip_n"],
            "real_detection_per_finding": real_finding,
            "real_detection_per_case": real_case,
            "denominators": measured["denominators"],
            "read_the_swap_knowing_this": measured["read_the_swap_knowing_this"],
        },
        "historical_baseline": HISTORICAL_INJECTED_BASELINE,
        "within_run_gap": {
            "injected_over_real_per_finding_sc_swap": round(swap / real_finding, 2),
            "injected_over_real_per_finding_conformance_flip": round(flip / real_finding, 2),
            "injected_over_real_per_case_sc_swap": round(swap / real_case, 2),
            "injected_over_real_per_case_conformance_flip": round(flip / real_case, 2),
            "note": (
                "The gap on this run's own drafts, needing no comparison to any other set. The "
                "historical gap was threefold; this one is of the same order at the finding and somewhat "
                "narrower at the case, which is the unit change and not the judge. IT HAS NOT CLOSED."
            ),
        },
        "guard_against_the_historical_baseline": {
            "predicate": (
                "The pre-committed guard reads: injected detection RISES while real detection DOES NOT. "
                "Evaluated at the historical figures' own unit — real detection per FINDING, because the "
                "0.33 it is compared against was 8 catches over 24 act-wrong findings."
            ),
            "injected_detection_rose": injected_rose,
            "sc_swap_moved": round(swap - HISTORICAL_SC_SWAP_DETECTION, 4),
            "conformance_flip_moved": round(flip - HISTORICAL_CONFORMANCE_FLIP_DETECTION, 4),
            "real_detection_rose": real_rose,
            "real_detection_moved_per_finding": round(real_finding - HISTORICAL_REAL_DETECTION, 4),
            "trips": injected_rose and not real_rose,
            "consequence_if_it_trips": (
                "EFFECTIVE ONLY ON CLEAN SIGNAL — DOES NOT TRANSFER. Success may not be claimed on the "
                "strength of an injected figure. ⚠️ Nothing in this milestone claims success in the first "
                "place unless Comparison 1's verdict is SUPPORTED, so read the two together rather than "
                "either alone."
            ),
            "⚠️": (
                "THE COMPARISON CROSSES DRAFT SETS. The historical figures were measured on 63 drafted "
                "findings with 24 act-wrong; these are 54 findings with 15. Both movements are therefore "
                "movements of the set as much as of the judge, and the guard is evaluated because it was "
                "pre-committed, not because the two are like-for-like. The within-run gap above needs no "
                "such comparison and is the sturdier of the two readings."
            ),
        },
    }


# ---------------------------------------------------------------------------------------------
# Comparison 2 — the blind judge beside the drafter
# ---------------------------------------------------------------------------------------------


def judge_rater_flags(artifact: dict[str, Any], passes: Sequence[Sequence[Any]]) -> dict[str, bool]:
    """`finding_id → the blind judge's OWN verdict, collapsed to FLAG/CLEAN, majority across passes.

    ⚠️ This is not the routing decision. The routing decision is *the judge agrees with the draft*; this
    is *the judge thinks the content fails*, which is the only stream that can be scored against gold as
    a rater — and only a blind judge has it.

    The four-value verdict is collapsed BEFORE the majority is taken, deliberately: every gold-scored
    number in this project runs through `is_flag`, and a boolean always has a strict majority over an odd
    pass count while a four-valued field does not. Taking the majority first would make a gold-scored
    figure undefined on any finding where three passes returned three verdicts.
    """
    asks = blind_asks(artifact)
    per_pass = [[[is_flag(outcome.answer.conformance)] for outcome in outcomes] for outcomes in passes]
    winners = majority_stream(per_pass)
    return {ask.finding_id: bool(row[0]) for ask, row in zip(asks, winners, strict=True)}


def _class_cells(judge: Sequence[str], gold: Sequence[str]) -> dict[str, int]:
    return {
        "tp": sum(1 for j, g in zip(judge, gold, strict=True) if j == "FLAG" and g == "FLAG"),
        "fp": sum(1 for j, g in zip(judge, gold, strict=True) if j == "FLAG" and g == "CLEAN"),
        "fn": sum(1 for j, g in zip(judge, gold, strict=True) if j == "CLEAN" and g == "FLAG"),
        "tn": sum(1 for j, g in zip(judge, gold, strict=True) if j == "CLEAN" and g == "CLEAN"),
    }


def _judge_class_streams(cases: Sequence[dict[str, Any]], flags: dict[str, bool]) -> tuple[list[str], list[str]]:
    judge = ["FLAG" if any(flags[d["finding_id"]] for d in c["drafts"]) else "CLEAN" for c in cases]
    gold = ["FLAG" if c["expected"] == "failed" else "CLEAN" for c in cases]
    return judge, gold


def rater_side_by_side(
    artifact: dict[str, Any], passes: Sequence[Sequence[Any]], comparator: dict[str, Any]
) -> dict[str, Any]:
    """Each rater's own kappa against ACT gold, per finding-class, side by side — Comparison 2's only
    gold-scored metric, and the one that says whether following the disagreement signal pays.

    The judge's side is computed here from its own verdicts, collapsed by `is_flag` and flag-if-any
    within the case, exactly as the drafter's is. The drafter's side is READ from the frozen comparator —
    recomputed there from this same replay pass, never from the pre-referent baseline.

    Both n sit on every row and nothing subtracts one from the other; see `DENOMINATOR_DECLARATION`.
    """
    drafter = {row["axe_rule"]: row for row in comparator["per_class"]}
    flags = judge_rater_flags(artifact, passes)
    by_class: dict[str, list[dict[str, Any]]] = {}
    for case in artifact["cases"]:
        by_class.setdefault(case["axe_rule"], []).append(case)

    rows: list[dict[str, Any]] = []
    for axe_rule, cases in sorted(by_class.items()):
        judge_stream, gold_stream = _judge_class_streams(cases, flags)
        per_pass = []
        for outcomes in passes:
            single = judge_rater_flags(artifact, [outcomes])
            single_stream, _ = _judge_class_streams(cases, single)
            per_pass.append(cohen_kappa(single_stream, gold_stream))
        rows.append(
            {
                "axe_rule": axe_rule,
                "judge_units": len(cases),
                "drafter_units": drafter[axe_rule]["drafter_units"],
                "judge_kappa": round(cohen_kappa(judge_stream, gold_stream), 4),
                "drafter_kappa": drafter[axe_rule]["kappa"],
                "judge_raw_agreement": round(raw_agreement(judge_stream, gold_stream), 4),
                "drafter_raw_agreement": drafter[axe_rule]["raw_agreement"],
                "judge_cells": _class_cells(judge_stream, gold_stream),
                "drafter_cells": {k: drafter[axe_rule][k] for k in ("tp", "fp", "fn", "tn")},
                "judge_kappa_per_pass": spread(per_pass),
                "more_often_right": (
                    "judge"
                    if round(cohen_kappa(judge_stream, gold_stream), 4) > drafter[axe_rule]["kappa"]
                    else (
                        "drafter"
                        if round(cohen_kappa(judge_stream, gold_stream), 4) < drafter[axe_rule]["kappa"]
                        else "tied"
                    )
                ),
                "unit_gap": drafter[axe_rule]["unit_gap"],
            }
        )

    overall_judge, overall_gold = _judge_class_streams(artifact["cases"], flags)
    return {
        "asks": (
            "When the two readers disagree, which of them is more often right, and on which classes? "
            "Neither Group A metric can answer this, and without it the disagreement rate is a number "
            "with no consequence attached: you know how many people to send, not what they will find."
        ),
        "unit": OBSERVATION_UNIT,
        "join_key": "act_testcase_id",
        "denominator_declaration": DENOMINATOR_DECLARATION,
        "four_conditions": FOUR_CONDITIONS,
        "duplicate_ask_caveat": DUPLICATE_ASK_CAVEAT,
        "drafter_side_source": {
            "path": comparator_report_path().name,
            "why": (
                "Recomputed from this same replay pass. The frozen per-class drafter baseline is the "
                "PRE-REFERENT drafter and would get *which of them is right* wrong on two classes."
            ),
        },
        "per_class": rows,
        "all_classes_pooled": {
            "judge_units": len(overall_judge),
            "drafter_units": comparator["totals"]["drafter_units"],
            "judge_kappa": round(cohen_kappa(overall_judge, overall_gold), 4),
            "judge_raw_agreement": round(raw_agreement(overall_judge, overall_gold), 4),
            "note": (
                "⚠️ Pooled across classes and NOT tested. It is quoted because a per-class table with no "
                "total invites a reader to add the rows up, and the drafter's pooled kappa is not "
                "recomputed here at all — the comparator freezes the drafter per class, and pooling two "
                "raters over different denominators is exactly the arithmetic the declaration forbids."
            ),
        },
        "judge_stream": (
            "The judge's OWN four-value verdict, collapsed to FLAG/CLEAN by the project's standard rule "
            "and then flag-if-any within the case — the same two collapses the drafter's side runs "
            "through. It is NOT the routing decision, which is whether the judge agreed with the draft."
        ),
    }


def drafter_judge_kappa(artifact: dict[str, Any], passes: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """Agreement between the two raters — Group A, blind only, per FINDING.

    ⚠️ **Descriptive, and it must never become a target.** Raising it means moving the drafter toward the
    judge, which is optimising against the judge. It is reported because it characterises the pair.

    The scale is the RAW FOUR-VALUE conformance, matching the rule code compares the two answers on:
    `partially_supports` is not `does_not_support`, and a difference of degree is a real difference of
    opinion. That makes this the chance-corrected form of the disagreement rate's conformance axis, and
    it is deliberately NOT the FLAG/CLEAN collapse, which exists only because ACT gold is binary — no
    gold is involved here.

    The unit is the finding, because that is where the two raters' answers pair one-to-one with no
    aggregation at all. It is therefore NOT on the same unit as the per-class kappa against gold above.
    """
    asks = blind_asks(artifact)
    verdicts = conformance_majorities(asks, passes)
    # ⚠️ Refused rather than dropped. Three passes of a four-valued field can return three distinct
    # verdicts, and a rater stream assembled over the findings that happened to settle would be a kappa
    # on a subset silently chosen by the judge's own indecision.
    undecided = sorted(fid for fid, verdict in verdicts.items() if verdict is None)
    if undecided:
        raise ValueError(
            f"{len(undecided)} finding(s) have no strict majority for the judge's own four-value verdict, "
            f"so a paired rating stream cannot be assembled over them. First few: {undecided[:3]}"
        )
    drafted = {d["finding_id"]: str(d["conformance"]) for case in artifact["cases"] for d in case["drafts"]}
    judge_stream: list[str] = []
    draft_stream: list[str] = []
    for ask in asks:
        verdict = verdicts[ask.finding_id]
        assert verdict is not None  # noqa: S101 — the refusal above is the real guard
        judge_stream.append(verdict.value)
        draft_stream.append(drafted[ask.finding_id])
    return {
        "unit": DISAGREEMENT_RATE_UNIT,
        "observations": len(asks),
        "scale": "raw four-value conformance — the rule code compares the two answers on",
        "kappa": round(cohen_kappa(judge_stream, draft_stream), 4),
        "raw_agreement": round(raw_agreement(judge_stream, draft_stream), 4),
        "judge_verdict_counts": {
            value: judge_stream.count(value) for value in sorted(set(judge_stream) | set(draft_stream))
        },
        "drafted_verdict_counts": {
            value: draft_stream.count(value) for value in sorted(set(judge_stream) | set(draft_stream))
        },
        "descriptive_only": (
            "⚠️ NEVER A TARGET. Raising it means moving the drafter toward the judge — optimising against "
            "the judge, which is the Goodhart failure this comparison exists to avoid. And no interval on "
            "it is read as tight: the measured within-case correlation puts its effective n near 40, not "
            f"{len(asks)}."
        ),
        "not_the_same_unit_as_the_gold_kappa": (
            "This is per FINDING; the per-class kappa against gold is per CASE. Two kappas with the same "
            "word in their name on two denominators, and each is labelled wherever it appears."
        ),
    }


ARTEFACT_FREE_RULE = (
    "The ARTEFACT-FREE rate counts only findings carrying a CONFORMANCE-axis disagreement, and it is "
    "reported BESIDE the headline rather than instead of it — both numbers are true and each answers a "
    "different question. The headline is *how many findings the two answers differ on at all*, which is "
    "the queue as it would actually be walked. The artefact-free figure is *how many of those visits can "
    "carry a difference of opinion*, and it is the honest price in people-visits: a finding whose only "
    "disagreement is an SC mismatch forced by the citation convention is a guaranteed dead end. The rule "
    "is the conformance axis rather than a per-configuration subtraction because the axis is well-defined "
    "on both sides and needs no predicate chosen after seeing the rows — and `set_identity` below is what "
    "says whether dropping the SC-only rows is honest on that side or merely convenient."
)


def _artefact_free(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The disagreements that can carry an opinion: the conformance-axis ones, with their case count."""
    conformance = [row for row in rows if row["conformance_disagreement"]]
    return {
        "findings": len(rows),
        "artefact_free_disagreements": len(conformance),
        "artefact_free_rate": round(len(conformance) / len(rows), 4) if rows else 0.0,
        "distinct_cases_touched": len({row["act_testcase_id"] for row in conformance}),
    }


def _set_identity(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """⚠️ Whether the SC-only disagreements ARE the drafter's inconsistent rows, as a set — not as a count.

    Two counts that happen to be equal are not the same fact as two sets that coincide, and only the
    second licenses reading an SC-only disagreement as a formatting artefact rather than as an opinion.
    Both candidate predicates are tested on both configurations, because the artefact runs the opposite
    way on the two sides and a symmetry assumed rather than measured is how one of them ends up
    mislabelled.
    """
    sc_only = {row["finding_id"] for row in rows if row["sc_disagreement"] and not row["conformance_disagreement"]}
    clean_citing = {row["finding_id"] for row in rows if row["drafter_cites_on_a_clean_row"]}
    citing_nothing = {row["finding_id"] for row in rows if row["drafter_cites_nothing"]}
    return {
        "sc_only_disagreements": len(sc_only),
        "drafter_rows_that_cite_while_clean": len(clean_citing),
        "drafter_rows_that_cite_nothing": len(citing_nothing),
        "sc_only_set_is_exactly_the_clean_citing_rows": sc_only == clean_citing,
        "sc_only_set_is_exactly_the_cite_nothing_rows": sc_only == citing_nothing,
        "note": (
            "⚠️ A SET IDENTITY, not a coincidence of counts. Where it holds, every SC-only disagreement on "
            "that side is a row the drafter's citation convention does not cover, so the mismatch is "
            "forced by the convention rather than reached by judgment — which is what makes the "
            "artefact-free rate a fair second figure. Where it does NOT hold, the counts may still match "
            "while the sets differ, and no row may be written off on the strength of the total alone."
        ),
    }


def disagreement_side_by_side(anchored_frozen: dict[str, Any], blind_frozen: dict[str, Any]) -> dict[str, Any]:
    """The milestone's primary deliverable, both configurations, read off the frozen records.

    ⚠️ **Never averaged, never differenced.** The two rates count different events — anchored's is *the
    judge graded the draft incorrect*, blind's is *the judge's own answer differs* — and the SC axis in
    particular answers two different questions on the two sides (grading a citation it was shown against
    naming its own). They sit beside each other and nothing arithmetic runs between them.

    ⚠️ **And each rate is published in two forms.** The headline counts a disagreement on either axis; the
    artefact-free figure counts only the conformance axis, because part of the SC axis is a citation habit
    nobody told the judge about. A deliverable priced in people-visits has to say how many of those visits
    can find anything — see `ARTEFACT_FREE_RULE`.
    """

    def _side(frozen: dict[str, Any], path: str) -> dict[str, Any]:
        block = frozen["disagreement"]
        rows = block["rows"]
        by_rule: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_rule.setdefault(row["axe_rule"], []).append(row)
        return {
            "source": f"{path} §disagreement",
            "unit": block["unit"],
            "event": block["event"],
            "overall": block["overall"],
            "artefact_free_overall": _artefact_free(rows),
            "set_identity": _set_identity(rows),
            "per_class": [
                {
                    **{k: v for k, v in row.items() if k != "rows"},
                    "artefact_free_disagreements": _artefact_free(by_rule[row["axe_rule"]])[
                        "artefact_free_disagreements"
                    ],
                    "artefact_free_rate": _artefact_free(by_rule[row["axe_rule"]])["artefact_free_rate"],
                }
                for row in block["per_class"]
            ],
            "sc_axis_artefact": block["sc_axis_artefact"],
        }

    return {
        "unit": DISAGREEMENT_RATE_UNIT,
        "why_this_is_the_deliverable": (
            "It is the queue volume — how many people-visits the mechanism creates — and a rate alone "
            "hides the workload, so it never appears without its absolute count and the number of "
            "distinct cases it touches. Everything else either explains it or says whether following it "
            "pays."
        ),
        "artefact_free_rule": ARTEFACT_FREE_RULE,
        "never_averaged": (
            "⚠️ The two configurations count DIFFERENT EVENTS. Anchored: the judge graded the draft "
            "incorrect. Blind: the judge's own answer differs from the draft, decided in code. They may "
            "sit side by side and must never be averaged, differenced or presented as one series — the "
            "SC axis especially, where anchored grades a citation it was shown and blind compares a set "
            "it made."
        ),
        "anchored": _side(anchored_frozen, anchored_report_path().name),
        "blind": _side(blind_frozen, blind_report_path().name),
        "blind_direction": blind_frozen["disagreement"]["direction"],
        "blind_sc_axis_coupling": blind_frozen["disagreement"]["sc_axis_coupling"],
        "degenerate_endpoints": {
            "declared_in_advance": (
                "A very HIGH disagreement rate means the queue is not filtered and human cost returns to "
                "where it started; a very LOW one means almost nothing routes and the judge is "
                "effectively absent."
            ),
            "no_cutoff_is_pre_registered": (
                "These are health checks read in prose, not thresholds. Inventing a numeric cut-off "
                "without evidence is the mistake this milestone is trying not to make, so the rates are "
                "reported with their absolute counts and the reading is left to the written analysis."
            ),
            "anchored_rate": anchored_frozen["disagreement"]["overall"]["disagreement_rate"],
            "anchored_count": anchored_frozen["disagreement"]["overall"]["disagreements"],
            "blind_rate": blind_frozen["disagreement"]["overall"]["disagreement_rate"],
            "blind_count": blind_frozen["disagreement"]["overall"]["disagreements"],
            "findings": blind_frozen["disagreement"]["overall"]["findings"],
            "anchored_artefact_free_count": _artefact_free(anchored_frozen["disagreement"]["rows"])[
                "artefact_free_disagreements"
            ],
            "blind_artefact_free_count": _artefact_free(blind_frozen["disagreement"]["rows"])[
                "artefact_free_disagreements"
            ],
            "⚠️": (
                "BOTH FORMS OF EACH RATE SIT HERE ON PURPOSE. An endpoint read on the headline alone would "
                "be read on a figure part of which is a citation habit; one read on the artefact-free "
                "figure alone would understate the queue a person actually walks. Neither is the endpoint "
                "on its own."
            ),
        },
    }


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------


def _provenance(path: Path, record: dict[str, Any], *, fields: tuple[str, ...]) -> dict[str, Any]:
    known = {field: record[field] for field in fields if field in record}
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **known}


def build_record(
    *,
    replay_path: Path,
    anchored_path: Path,
    blind_path: Path,
    comparator_path: Path,
) -> dict[str, Any]:
    """Assemble both comparisons. Pure given the four files, so the whole shape is testable."""
    artifact = json.loads(replay_path.read_text())
    anchored_frozen = json.loads(anchored_path.read_text())
    blind_frozen = json.loads(blind_path.read_text())
    comparator = json.loads(comparator_path.read_text())

    anchored = anchored_releases(artifact, anchored_frozen)
    passes = blind_passes(artifact, blind_frozen)
    blind = releases(blind_asks(artifact), passes)

    test = paired_test(artifact, anchored, blind)
    null_wins = anchored_frozen["threshold"]["null_wins"]
    bar = threshold(test["per_case"]["discordant_pairs"], null_wins=null_wins)
    verdict = verdict_for(
        wins=test["per_case"]["blind_wins"],
        losses=test["per_case"]["anchored_wins"],
        required_wins=bar.required_wins,
    )
    guard = injected_versus_real(anchored_frozen)

    blind_scoring = score_blind(artifact, blind_asks(artifact), passes)

    return {
        "artifact": "both judge comparisons, computed off the frozen runs and kept apart",
        "version": 1,
        "model_calls_spent": 0,
        "created_at": artifact["created_at"],
        "read_in_this_order": (
            "COMPARISON 2 FIRST. It is the one that decides whether the signal is worth having, and it "
            "carries no p-value; Comparison 1 is a check on how the disagreement rate was arrived at. A "
            "report that opens on a significance verdict has buried its own result."
        ),
        "units": {
            "observation_unit": OBSERVATION_UNIT,
            "aggregation_order": AGGREGATION_ORDER,
            "disagreement_rate_unit": DISAGREEMENT_RATE_UNIT,
            "conformance_collapse_rule": COLLAPSE_RULE,
            "note": (
                "⚠️ TWO UNITS LIVE HERE. The tested comparison is per CASE (40); the disagreement rate is "
                "per FINDING (54), because it is a queue-volume number and disagreement is per finding by "
                "construction. Every figure names which one it is on, and a bare count is ambiguous even "
                "once its comparison is named."
            ),
        },
        "sources": {
            "frozen_drafts": _provenance(
                replay_path, artifact, fields=("run_ids", "config_id", "eval_set_id", "drafter_model", "created_at")
            ),
            "anchored_configuration": _provenance(
                anchored_path, anchored_frozen, fields=("judge_model", "judge_version", "created_at")
            ),
            "blind_configuration": _provenance(
                blind_path, blind_frozen, fields=("judge_model", "judge_version", "created_at")
            ),
            "drafter_comparator": _provenance(comparator_path, comparator, fields=("created_at",)),
            "read_only": (
                "Every source is read and replayed through its own harness, which refuses if the frozen "
                "rows are not those asks. Nothing here re-runs, re-judges or rewrites any of them."
            ),
        },
        "comparison_1_judge_vs_judge": {
            "asks": COMPARISON_1,
            "confusion": {
                "anchored": anchored_frozen["confusion"],
                "blind": blind_frozen["confusion"],
                "note": (
                    "The four routing cells at both units, per configuration. The two Group B rates that "
                    "are read TOGETHER ride on each block: the share of the flagged set that is genuinely "
                    "wrong (is a human visit worth making) and the share of all real errors that were "
                    "flagged (the signal's recall). Quoting the first without the second hides the uglier "
                    "number."
                ),
            },
            "sign_test": {
                **test,
                "alpha": ALPHA,
                "threshold": {
                    "required_wins": bar.required_wins,
                    "statistical_bar": bar.statistical_bar,
                    "floor_bar": bar.floor_bar,
                    "binding_bar": bar.binding_bar,
                    "null_wins": bar.null_wins,
                    "source": (
                        f"{anchored_report_path().name} §threshold — the floor bar was frozen from the "
                        "anchored configuration's own same-configuration pass-pairs before the blind "
                        "configuration ran, and is not re-derived here."
                    ),
                },
                "clears_the_bar": bar.clears(test["per_case"]["blind_wins"]),
            },
            "discordant_cases": paired_case_rows(artifact, anchored, blind),
            "aggregation_divergence": {
                "anchored": aggregation_divergence(flag_stream(artifact, anchored)),
                "blind": aggregation_divergence(flag_stream(artifact, blind)),
                "note": (
                    "What the flag-if-any case collapse hides, per configuration: the multi-finding cases "
                    "that are internally split, and the cases where flag-if-any lands on a different "
                    "answer from a within-case majority. Reported because a case-level figure that is "
                    "false one level below it is a mistake this project has already made once."
                ),
            },
            "injected_versus_real": guard,
            "verdict": verdict,
            "verdict_rule": (
                "Pre-committed before the run. Clears the bar → SUPPORTED. Directional but short of it → "
                "worked but uncertifiable. No directional movement → anchoring was not the dominant "
                "cause. A bar unattainable at this n → uncertifiable at that n, which is NOT a bar the "
                "evidence missed. Separately, injected detection rising while real detection does not → "
                "effective only on clean signal, and success may not be claimed."
            ),
            "success_may_not_be_claimed": guard["guard_against_the_historical_baseline"]["trips"],
        },
        "comparison_2_judge_vs_drafter": {
            "asks": COMPARISON_2,
            "group_a_disagreement": disagreement_side_by_side(anchored_frozen, blind_frozen),
            "group_a_drafter_judge_kappa": drafter_judge_kappa(artifact, passes),
            "group_b_rater_side_by_side": rater_side_by_side(artifact, passes, comparator),
            "blind_confusion_for_reference": {
                "per_case": scoring_block(blind_scoring.per_case),
                "per_finding": scoring_block(blind_scoring.per_finding),
                "note": (
                    "Re-derived here from the blind configuration's frozen answers rather than copied, so "
                    "the record's own arithmetic is checkable end to end. It is the ROUTING confusion and "
                    "belongs to Comparison 1; it sits here only because Comparison 2's reader needs the "
                    "same numbers in front of them."
                ),
            },
        },
    }


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_comparison.json"


def build_from_frozen() -> dict[str, Any]:
    """The record over the checked-in artifacts — the one form anything outside this module needs."""
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path

    return build_record(
        replay_path=run_path(CITATION_GROUNDING, 1),
        anchored_path=anchored_report_path(),
        blind_path=blind_report_path(),
        comparator_path=comparator_report_path(),
    )


def main() -> None:
    record = build_from_frozen()
    first = record["comparison_2_judge_vs_drafter"]
    overall = first["group_a_disagreement"]["blind"]["overall"]
    print(f"comparison stage — {record['model_calls_spent']} model calls")
    print("\nCOMPARISON 2 — the blind judge beside the drafter (read first)")
    print(
        f"  disagreement: {overall['disagreements']}/{overall['findings']} findings "
        f"({overall['disagreement_rate']}) over {overall['distinct_cases_touched']} cases — per finding"
    )
    kappa = first["group_a_drafter_judge_kappa"]
    print(f"  drafter-judge kappa: {kappa['kappa']} (descriptive only, per finding, raw four-value)")
    for row in first["group_b_rater_side_by_side"]["per_class"]:
        print(
            f"    {row['axe_rule']:<15} judge {row['judge_kappa']:+.4f} (n {row['judge_units']}) vs "
            f"drafter {row['drafter_kappa']:+.4f} (n {row['drafter_units']}) → {row['more_often_right']}"
        )

    second = record["comparison_1_judge_vs_judge"]
    test = second["sign_test"]
    print("\nCOMPARISON 1 — anchored vs blind (a check on how the above was arrived at)")
    print(
        f"  per case: {test['per_case']['blind_wins']} blind wins / {test['per_case']['anchored_wins']} "
        f"anchored wins over {test['per_case']['discordant_pairs']} discordant pairs, "
        f"p = {test['per_case']['one_sided_p']}"
    )
    print(
        f"  bar: required {test['threshold']['required_wins']} — {test['threshold']['binding_bar']}; "
        f"clears = {test['clears_the_bar']}"
    )
    print(f"  verdict: {second['verdict']}")

    path = report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
