"""One blind judging pass over the frozen finding side — and the dry run that proves it for nothing.

The blind configuration shows the judge the finding side and nothing else, and asks it for its own
conformance verdict and its own criteria. **Agreement is then decided here, in code**: raw four-value
equality on `conformance`, exact set match on the cited ids. So a pass is one call per minted finding
and no mutations at all — a blind ask is byte-identical whether the draft was natural, SC-swapped or
conformance-flipped, so a mutation pass would spend money to re-derive arithmetic.

What is reused, and what could not be
-------------------------------------
The anchored path is the harness of record and most of it serves both configurations unchanged: the
frozen finding side and `Judge`-side plumbing, the pinned majority (`majority_stream`), the case
collapse and the scorer (`collapse_to_cases`, `score_judge`), the per-case and per-finding streams
(`judged_cases_from`, `judged_findings_from`) and the odd-pass guard. Three things could not be, and
each is a place where a runner written for one configuration would have failed silently on the second:

* **the asks.** `AnchoredAsk` carries a mutation and a draft to present; a blind ask carries a draft
  the model never sees, so a shared type would make "the draft was withheld" a convention rather than
  a fact.
* **the stub.** The anchored stub answers the anchored schema. Handed to this path it produces
  responses the blind schema rejects — which the judge turns into a raise, not a quiet zero, and there
  is a test that pins exactly that rather than assuming it.
* **the disagreement profile.** The anchored one keys off `mutation == natural` and off booleans the
  model emitted. Here the same JSON shape is assembled from booleans code derived, so the two
  artifacts can be read side by side, plus the one block only this configuration can produce — the
  DIRECTION of a conformance disagreement, which needs the judge's own verdict.

Why the dry run exists
----------------------
The live version of this path is paid, and every question about whether it *works* — do the asks
assemble from the frozen bytes, does the draft stay out of them, does every response parse, do the two
collapses land where they should, does the scorer record the unit its cells are on — is answerable
with no model at all. So it is answered first, against a deterministic stub, and the receipt is frozen.

**The stub is not a model and never pretends to be one.** Its answer is read off the sha256 of the ask,
so verdicts vary across findings and passes without any inference happening. Every number in the
receipt describes the HARNESS. None describes the judge, and the record says so in its own text.

Two collapses, in the pinned order
----------------------------------
Repeat passes collapse first, per finding, by strict majority; the case collapse is second,
flag-if-any. The order is taken from the pinned aggregation rather than re-decided here.

Invoke: `uv run python -m clearway.eval.judge_blind`
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from clearway.eval.judge_anchored import (
    anchored_asks,
    draft_row,
    judged_cases_from,
    judged_findings_from,
    require_odd_passes,
)
from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_finding_input import report_path as input_report_path
from clearway.eval.judge_observation_unit import (
    AGGREGATION_ORDER,
    DISAGREEMENT_RATE_UNIT,
    DegenerateClustering,
    majority_stream,
    within_cluster_agreement,
)
from clearway.eval.judge_score import (
    CONFUSION_UNIT_CASE,
    CONFUSION_UNIT_FINDING,
    JudgeScoring,
    collapse_to_cases,
    score_judge,
)
from clearway.judge import BlindAnswer, BlindJudge, FindingInput, blind_user_prompt
from clearway.llm import Completion, ImagePart, LLMUsage
from clearway.schemas.models import Conformance, DraftRow, JudgeResult

# The configuration this module runs. Named so an artifact says which side of the comparison it holds.
CONFIGURATION = "blind"

CONFIGURATION_MEANING = (
    "BLIND: the judge is shown the finding side ALONE and answers for itself — its own conformance "
    "verdict and its own cited criteria. It never sees the draft, so `citation_correct` and "
    "`conformance_correct` are NOT the judge's opinion of anything: they are computed in code, and "
    "they mean 'the judge named the same criteria' and 'the judge reached the same verdict'. The "
    "anchored configuration reuses both field names for a different question — there they are the "
    "model's own grade of the drafted answer — so neither artifact may be read without this marker."
)

# Why no mutation ever runs on this side. Recorded in the artifact rather than left to a reader.
NO_MUTATIONS_HERE = (
    "This configuration runs the natural draft only, and its two injected-detection rates are "
    "therefore empty (n = 0) rather than zero-valued. Both mutations edit the DRAFT, and a blind ask "
    "is byte-identical whatever the draft says, so 'caught' would reduce to arithmetic: an SC swap "
    "substitutes a criterion the judge did not name, so detection would be 1.000 by construction, and "
    "a conformance flip always changes the value, so detection would be a restatement of the natural "
    "agreement rate. Neither figure would contain one bit of judge behaviour, and reporting them "
    "would trip the injected-versus-real guard on pure algebra. The gap is measured on the anchored "
    "configuration only."
)

# The strictness order a DIRECTION of disagreement is read on. `not_applicable` is deliberately absent:
# it is a claim that the criterion does not apply, not a point on the supports → does_not_support line,
# so a pair involving it is counted as off-axis rather than silently ranked.
_STRICTNESS: dict[Conformance, int] = {
    Conformance.SUPPORTS: 0,
    Conformance.PARTIALLY_SUPPORTS: 1,
    Conformance.DOES_NOT_SUPPORT: 2,
}


@dataclass(frozen=True)
class BlindAsk:
    """One judge call a blind pass makes — and the frozen draft it will be compared against.

    ⚠️ `draft` is carried here for CODE's use after the answer comes back. It is never rendered into a
    prompt: `run_pass` hands `FindingInput` to `BlindJudge.answer`, whose signature has nowhere to put
    a draft. Keeping it on the ask is what lets the comparison be a pure function of the ask list and
    the responses, which is what makes a frozen run re-derivable without the drafter artifact being
    re-read row by row.
    """

    act_testcase_id: str
    rule_name: str
    axe_rule: str
    finding_id: str
    draft: DraftRow


@dataclass(frozen=True)
class BlindOutcome:
    """What one blind ask produced: the judge's own answer, and the comparison code made from it."""

    answer: BlindAnswer
    result: JudgeResult


def blind_asks(artifact: dict[str, Any]) -> list[BlindAsk]:
    """Every ask one blind pass makes over a frozen drafter run, in call order — one per minted finding.

    No mutations: see `NO_MUTATIONS_HERE`. The order is the artifact's own, so a blind pass and an
    anchored pass walk the same findings in the same sequence.
    """
    return [
        BlindAsk(
            act_testcase_id=case["act_testcase_id"],
            rule_name=case["rule_name"],
            axe_rule=case["axe_rule"],
            finding_id=record["finding_id"],
            draft=draft_row(record),
        )
        for case in artifact["cases"]
        for record in case["drafts"]
    ]


def run_pass(
    judge: BlindJudge, prepared: dict[str, FindingInput], asks: Sequence[BlindAsk], run_id: str
) -> list[BlindOutcome]:
    """Make every ask of one pass, in order, and compare each answer against its frozen draft.

    The model call and the comparison are two statements, and the draft appears only in the second.
    """
    missing = sorted({a.finding_id for a in asks} - set(prepared))
    if missing:
        raise KeyError(
            f"{len(missing)} finding(s) have no frozen finding-side block — the run artifact and the "
            f"frozen input describe different scans. First few: {missing[:3]}"
        )
    outcomes: list[BlindOutcome] = []
    for ask in asks:
        answer = judge.answer(prepared[ask.finding_id])
        outcomes.append(BlindOutcome(answer=answer, result=judge.compare(answer, ask.draft, run_id)))
    return outcomes


# ---------------------------------------------------------------------------------------------
# Collapsing the passes
# ---------------------------------------------------------------------------------------------


def axis_majorities(asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]) -> dict[str, dict[str, bool]]:
    """`finding_id → {axis: the majority of that DERIVED boolean across the passes}`.

    Each axis on its own, exactly as the anchored side does it and for the same reason: a strict
    majority over the PAIR can fail to exist, while each boolean axis always has one over an odd pass
    count. The routing decision was only ever the conformance axis.
    """
    keyed = [{o.result.finding_id: o.result for o in outcomes} for outcomes in passes]
    out: dict[str, dict[str, bool]] = {}
    for axis in ("citation_correct", "conformance_correct"):
        per_pass = [[[bool(getattr(k[a.finding_id], axis))] for a in asks] for k in keyed]
        for ask, row in zip(asks, majority_stream(per_pass), strict=True):
            out.setdefault(ask.finding_id, {})[axis] = bool(row[0])
    return out


def releases(asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]) -> dict[str, bool]:
    """`finding_id → the judge's routing decision`, majority across the configuration's passes.

    A blind judge raises its hand when its own answer differs from the draft, so the decision recorded
    here is the derived `conformance_correct` — an agreement, and therefore a release — and the routing
    flag is its negation. That is the same boolean the anchored side records, which is what makes the
    two configurations' routing decisions comparable at all; what differs is who computed it.
    """
    return {finding_id: axes["conformance_correct"] for finding_id, axes in axis_majorities(asks, passes).items()}


def conformance_majorities(
    asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]
) -> dict[str, Conformance | None]:
    """`finding_id → the judge's OWN verdict, majority across passes, or None where there is none.

    ⚠️ Deliberately NOT `majority_stream`, and the difference is not a loosening of the pin. That
    function refuses a tie because the quantity it collapses is the routing decision a paired test is
    scored on, where breaking a tie by pass order would put a coin flip inside the result. This
    quantity is descriptive — it answers *which rater was stricter* — and it is four-valued, so three
    passes returning three distinct verdicts is a real outcome that has to be reportable as undecided
    rather than fatal to the run. The routing decision above is unaffected: it is a boolean.
    """
    out: dict[str, Conformance | None] = {}
    for index, ask in enumerate(asks):
        votes = [outcomes[index].answer.conformance for outcomes in passes]
        winner, count = Counter(votes).most_common(1)[0]
        out[ask.finding_id] = winner if count * 2 > len(votes) else None
    return out


@dataclass(frozen=True)
class BlindScoring:
    """One blind configuration scored at both units."""

    per_case: JudgeScoring
    per_finding: JudgeScoring
    released: dict[str, bool]


def score_blind(
    artifact: dict[str, Any], asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]
) -> BlindScoring:
    """Frozen drafts + the configuration's passes → the confusion at the pinned unit and beside it.

    The two injected lists are empty on purpose (`NO_MUTATIONS_HERE`), which `score_judge` records as
    n = 0 — an absent measurement rather than a measured zero.
    """
    released = releases(asks, passes)
    return BlindScoring(
        per_case=score_judge(
            collapse_to_cases(judged_cases_from(artifact, released)),
            unit=CONFUSION_UNIT_CASE,
            conformance_flip=[],
            sc_swap=[],
        ),
        per_finding=score_judge(
            judged_findings_from(artifact, released),
            unit=CONFUSION_UNIT_FINDING,
            conformance_flip=[],
            sc_swap=[],
        ),
        released=released,
    )


# ---------------------------------------------------------------------------------------------
# The disagreement rate, its composition, and the direction only this configuration can report
# ---------------------------------------------------------------------------------------------


def _drafter_inconsistent_findings(artifact: dict[str, Any]) -> set[str]:
    """The clean drafts that cite anyway — the rows the drafter's own citation habit does not cover."""
    from clearway.eval.stats import is_flag

    return {
        d["finding_id"]
        for case in artifact["cases"]
        for d in case["drafts"]
        if not is_flag(Conformance(d["conformance"])) and d["cited_sc_ids"]
    }


def _findings_citing_nothing(artifact: dict[str, Any]) -> set[str]:
    """The drafts with an empty `cited_sc_ids` — the other side of the same unwritten convention."""
    return {d["finding_id"] for case in artifact["cases"] for d in case["drafts"] if not d["cited_sc_ids"]}


def sc_axis_coupling(artifact: dict[str, Any]) -> dict[str, Any]:
    """⚠️ How much of the SC axis is a RESTATEMENT of the conformance axis, counted by row.

    The rubric was frozen carrying the drafter's convention — *name the criterion you decided against,
    name nothing when you find no failure* — and that convention, set against the shape of the drafter's
    own rows, makes the two derived booleans non-independent on most of the set. Three groups, and only
    the third carries an SC judgment that is free of the verdict:

    * **a clean draft citing nothing.** A judge that follows the convention names nothing exactly when
      it agrees, so both axes agree together and disagree together. The SC comparison adds nothing the
      conformance comparison did not already say — except where the judge answers a verdict the
      convention does not clearly cover.
    * **a clean draft that cites anyway.** A judge that AGREES on the verdict is *guaranteed* to
      mismatch on SC, because agreeing means naming nothing and the draft named something. Perfectly
      anti-correlated, by construction rather than by opinion.
    * **a flagging draft.** Both readers are expected to name a criterion, so the sets can differ or
      coincide independently of the verdict.

    Recorded here rather than left to a reader because two consequences follow that a later stage
    cannot see from the counts alone. **The anchored configuration's SC count is not the same kind of
    quantity**: there the judge was GRADING a citation it was shown, which is a separate question from
    whether its own answer names the same ids, so the two counts may be reported side by side but never
    differenced. And **`verdict_from` inherits the coupling**: `partial` is manufactured on the second
    group and near-unreachable on the first, so the three-way verdict distribution differs between the
    configurations for reasons that are not judge behaviour.

    ⚠️ The convention is NOT repaired and the comparison rule is NOT loosened. Both were pre-registered
    before the frozen set was touched; the honest handling is to state the coupling and read the axis
    knowing it, which is what this block is for.
    """
    from clearway.eval.stats import is_flag

    rows = [d for case in artifact["cases"] for d in case["drafts"]]
    clean = [d for d in rows if not is_flag(Conformance(d["conformance"]))]
    return {
        "findings": len(rows),
        "clean_draft_citing_nothing": sum(1 for d in clean if not d["cited_sc_ids"]),
        "clean_draft_citing_anyway": sum(1 for d in clean if d["cited_sc_ids"]),
        "flagging_draft_carrying_an_sc_judgment_free_of_the_verdict": len(rows) - len(clean),
        "note": (
            "⚠️ THE TWO AXES ARE NOT INDEPENDENT ON THIS CONFIGURATION, and the coupling is a property "
            "of the frozen rubric meeting the drafter's row shape, not of the judge. On a clean draft "
            "citing nothing the SC axis moves WITH the conformance axis and adds no information beyond "
            "it; on a clean draft that cites anyway, agreement on the verdict FORCES an SC mismatch; "
            "only a flagging draft carries an SC judgment free of the verdict. So the three composition "
            "shares are not three independent channels, the SC count here and the anchored one answer "
            "DIFFERENT QUESTIONS (grading a shown citation against naming one's own) and must never be "
            "differenced, and the three-way `verdict` distribution differs between the configurations "
            "for a reason that is not judge behaviour."
        ),
    }


def _shares(subset: list[dict[str, Any]]) -> dict[str, Any]:
    disagreeing = [r for r in subset if r["conformance_disagreement"] or r["sc_disagreement"]]
    both = [r for r in disagreeing if r["conformance_disagreement"] and r["sc_disagreement"]]
    return {
        "findings": len(subset),
        "disagreements": len(disagreeing),
        "disagreement_rate": round(len(disagreeing) / len(subset), 4) if subset else 0.0,
        "distinct_cases_touched": len({r["act_testcase_id"] for r in disagreeing}),
        "conformance_axis_disagreements": sum(1 for r in subset if r["conformance_disagreement"]),
        "sc_axis_disagreements": sum(1 for r in subset if r["sc_disagreement"]),
        "composition": {
            "conformance_only": sum(
                1 for r in disagreeing if r["conformance_disagreement"] and not r["sc_disagreement"]
            ),
            "sc_only": sum(1 for r in disagreeing if r["sc_disagreement"] and not r["conformance_disagreement"]),
            "both": len(both),
        },
    }


def direction_block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Which rater is stricter where the two verdicts differ — **blind only**.

    An anchored judge emits a grade, not a verdict, so it has no answer to be stricter *with*. A
    one-sided skew here means the two are not peer raters, which is a useful thing to know and a
    different claim from either of them being right.
    """
    disputed = [r for r in rows if r["conformance_disagreement"]]
    ranked = [r for r in disputed if r["judge_strictness"] is not None and r["draft_strictness"] is not None]
    return {
        "conformance_disagreements": len(disputed),
        "judge_stricter": sum(1 for r in ranked if r["judge_strictness"] > r["draft_strictness"]),
        "drafter_stricter": sum(1 for r in ranked if r["judge_strictness"] < r["draft_strictness"]),
        "off_the_strictness_axis": sum(1 for r in disputed if r not in ranked),
        "undecided_judge_verdict": sum(1 for r in disputed if r["judge_conformance"] is None),
        "axis": "supports < partially_supports < does_not_support; not_applicable is off the axis",
        "note": (
            "⚠️ `off_the_strictness_axis` holds every disputed row where either verdict is "
            "not_applicable or the judge's own verdict has no strict majority across the passes — a "
            "four-valued field can return three distinct values over three passes. Those rows are a "
            "real disagreement and are counted in the rate; they simply have no direction, and folding "
            "them into either side would invent one."
        ),
    }


def disagreement_profile(
    artifact: dict[str, Any],
    asks: Sequence[BlindAsk],
    passes: Sequence[Sequence[BlindOutcome]],
    prepared: dict[str, FindingInput],
) -> dict[str, Any]:
    """The milestone's primary deliverable on this side: how often the two answers differ, and where.

    **Unit: the FINDING**, denominator the minted drafts, with the count of distinct cases the
    disagreements touch beside it — a rate alone hides the workload, and the queue is walked per
    finding whatever unit the paired test is scored on.

    ⚠️ The event is *the two answers differ on either axis*, which is NOT the routing predicate the
    confusion matrix scores: that one is the conformance axis alone. Both are reported, each named.

    ⚠️ `prepared` is required so **every per-class row carries its own ask duplication**. The classes
    are not equally independent — one of them is three observations of one question — and a caveat that
    lives only in the distinct-ask block is a caveat a reader of a per-class table never meets. Taken
    from `distinct_ask_profile`, so the two cannot disagree.
    """
    majorities = axis_majorities(asks, passes)
    verdicts = conformance_majorities(asks, passes)
    inconsistent = _drafter_inconsistent_findings(artifact)
    silent = _findings_citing_nothing(artifact)

    rows: list[dict[str, Any]] = []
    for ask in asks:
        axes = majorities[ask.finding_id]
        judge_verdict = verdicts[ask.finding_id]
        rows.append(
            {
                "finding_id": ask.finding_id,
                "act_testcase_id": ask.act_testcase_id,
                "axe_rule": ask.axe_rule,
                "conformance_disagreement": not axes["conformance_correct"],
                "sc_disagreement": not axes["citation_correct"],
                "judge_conformance": judge_verdict.value if judge_verdict is not None else None,
                "drafted_conformance": ask.draft.conformance.value,
                "judge_strictness": _STRICTNESS.get(judge_verdict) if judge_verdict is not None else None,
                "draft_strictness": _STRICTNESS.get(ask.draft.conformance),
                "drafter_cites_on_a_clean_row": ask.finding_id in inconsistent,
                "drafter_cites_nothing": ask.finding_id in silent,
            }
        )

    by_rule: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_rule.setdefault(row["axe_rule"], []).append(row)
    sc_rows = [r for r in rows if r["sc_disagreement"]]
    duplication = {row["axe_rule"]: row for row in distinct_ask_profile(asks, prepared)["per_class"]}

    return {
        "unit": DISAGREEMENT_RATE_UNIT,
        "event": (
            "the judge's own answer differs from the draft on EITHER axis — raw four-value conformance "
            "or the exact set of cited SC ids, each taken as its own majority across the passes"
        ),
        "not_the_routing_predicate": (
            "The confusion matrix's routing decision is the CONFORMANCE axis alone, so its flag count "
            "and this disagreement count are different quantities over the same findings and must not "
            "be substituted for one another. Both are reported; the conformance-axis subtotal here is "
            "the one that matches the routing decision."
        ),
        "overall": _shares(rows),
        "sc_axis_coupling": sc_axis_coupling(artifact),
        "per_class": [
            {
                "axe_rule": rule,
                **_shares(group),
                "drafter_cites_on_a_clean_row": sum(1 for r in group if r["drafter_cites_on_a_clean_row"]),
                "drafter_cites_nothing": sum(1 for r in group if r["drafter_cites_nothing"]),
                # ⚠️ Carried onto the row rather than left in the distinct-ask block: this class's
                # figures rest on this many genuinely different questions, and on the smallest class
                # that is materially fewer than its finding count.
                "distinct_asks": duplication[rule]["distinct_asks"],
                "findings_in_a_duplicate_group": duplication[rule]["findings_in_a_duplicate_group"],
            }
            for rule, group in sorted(by_rule.items())
        ],
        "direction": direction_block(rows),
        "sc_axis_artefact": {
            "drafter_rows_that_cite_while_clean": len(inconsistent),
            "drafter_rows_that_cite_nothing": len(silent),
            "sc_axis_disagreements": len(sc_rows),
            "sc_axis_disagreements_on_rows_that_cite_while_clean": sum(
                1 for r in sc_rows if r["drafter_cites_on_a_clean_row"]
            ),
            "sc_axis_disagreements_on_rows_that_cite_nothing": sum(1 for r in sc_rows if r["drafter_cites_nothing"]),
            "note": (
                "The drafter's clean rows usually cite nothing and sometimes cite anyway, and nobody "
                "told the judge which. ⚠️ BOTH halves are counted, because the axis can be a formatting "
                "habit in either direction — a judge that names a criterion where the drafter named "
                "none, and a judge that names none where the drafter did — and a count of only the "
                "first makes an axis dominated by the second look clean. Read either count against its "
                "own denominator above before reading any SC-axis figure, overall or per class. ⚠️ On "
                "THIS configuration the artefact reaches the axis through a SET COMPARISON code made, "
                "not through a graded row, and the rubric was frozen instructing the majority shape — "
                "name the criterion you decided against, name nothing when you find no failure — so "
                "the 7 rows the drafter is inconsistent on mismatch by construction wherever the judge "
                "followed it."
            ),
        },
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------------
# How many DISTINCT questions this configuration actually asks
# ---------------------------------------------------------------------------------------------


def distinct_ask_profile(asks: Sequence[BlindAsk], prepared: dict[str, FindingInput]) -> dict[str, Any]:
    """How many of the asks are the same question, per class — measured, never inherited.

    The anchored side found that the 54 findings render fewer distinct finding-side blocks than there
    are findings, in duplicate groups that cross case boundaries, so two clusters can be sent a
    byte-identical question. **The blind ask is the block ALONE**, so removing the draft presentation
    can only merge more asks together, never fewer — which makes the anchored figure an upper bound and
    not a value. It is therefore counted here, through `blind_user_prompt`, the function that renders
    what is sent: a count taken over the frozen rows instead would agree with reality only until that
    function stopped being the identity.

    The system rubric is constant across every ask, so it cannot distinguish two of them and is left
    out of the digest; what varies is the user prompt alone.
    """
    rendered = [(a, blind_user_prompt(prepared[a.finding_id])) for a in asks]
    groups: dict[str, list[BlindAsk]] = {}
    for ask, text in rendered:
        groups.setdefault(hashlib.sha256(text.encode()).hexdigest(), []).append(ask)
    duplicated = {digest: members for digest, members in groups.items() if len(members) > 1}

    def _class_rows() -> list[dict[str, Any]]:
        by_rule: dict[str, list[tuple[BlindAsk, str]]] = {}
        for ask, text in rendered:
            by_rule.setdefault(ask.axe_rule, []).append((ask, text))
        rows = []
        for rule, members in sorted(by_rule.items()):
            digests = [hashlib.sha256(text.encode()).hexdigest() for _, text in members]
            counts = Counter(digests)
            rows.append(
                {
                    "axe_rule": rule,
                    "findings": len(members),
                    "distinct_asks": len(counts),
                    "findings_in_a_duplicate_group": sum(n for n in counts.values() if n > 1),
                    "duplicate_groups": sum(1 for n in counts.values() if n > 1),
                }
            )
        return rows

    return {
        "asks": len(rendered),
        "distinct_asks": len(groups),
        "findings_in_a_duplicate_group": sum(len(m) for m in duplicated.values()),
        "duplicate_groups": len(duplicated),
        "duplicate_groups_spanning_more_than_one_case": sum(
            1 for members in duplicated.values() if len({m.act_testcase_id for m in members}) > 1
        ),
        "distinct_frozen_blocks": len({hashlib.sha256(p.block.encode()).hexdigest() for p in prepared.values()}),
        "per_class": _class_rows(),
        "note": (
            "⚠️ Two clusters can be sent a byte-identical question, so the observations are less "
            "independent than the cluster count suggests, and the effect is not spread evenly across "
            "the classes — every per-class figure is read beside this row's own class. "
            "`distinct_frozen_blocks` is the same count taken over the frozen finding side rather than "
            "over the rendered asks: the two coincide exactly while the blind prompt appends nothing "
            "to the block, and they are reported together so that identity is a measurement rather "
            "than an assumption."
        ),
    }


# ---------------------------------------------------------------------------------------------
# The contrast that did not exist until this configuration ran
# ---------------------------------------------------------------------------------------------


def anchored_majority_releases(artifact: dict[str, Any], frozen: dict[str, Any]) -> dict[str, bool]:
    """The anchored configuration's per-finding routing decision, read off its frozen record.

    Rebuilt through the anchored harness' own functions rather than lifted from a field: the frozen
    rows are replayed into `JudgeResult`s against freshly-built anchored asks, which refuses outright
    if the rows are not those asks, and then collapsed by the same majority the anchored run used.
    """
    from clearway.eval.judge_anchored import natural_majority
    from clearway.eval.judge_anchored_baseline import results_from_rows

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


def between_configuration_difference(
    artifact: dict[str, Any],
    asks: Sequence[BlindAsk],
    passes: Sequence[Sequence[BlindOutcome]],
    anchored: dict[str, bool],
) -> dict[str, Any]:
    """The within-case correlation of the REAL anchored ↔ blind difference — the contrast a paired
    test consumes, which no earlier stage could measure.

    Earlier stages measured the correlation of each configuration's routing *levels*, and the *null*
    difference between two passes of one configuration. Neither is this: one variable moves here — the
    judge's prompt — over the same drafts and the same frozen finding side.

    A positive within-case correlation means discordant findings arrive together on the same page,
    which is what the case collapse is paid to absorb. **A materially negative one would mean the
    collapse cancels differences against each other and costs power rather than buying honesty**, and
    it is reported as such rather than smoothed over.
    """
    blind = releases(asks, passes)
    missing = sorted(set(blind) - set(anchored))
    if missing:
        raise DegenerateClustering(
            f"{len(missing)} finding(s) have a blind decision and no anchored one — the two "
            f"configurations did not run over the same findings. First few: {missing[:3]}"
        )
    clusters = [[d["finding_id"] for d in case["drafts"]] for case in artifact["cases"]]
    difference = [[blind[fid] != anchored[fid] for fid in cluster] for cluster in clusters]
    block: dict[str, Any] = {
        "left": "the anchored configuration's majority routing decision over these drafts",
        "right": "the blind configuration's majority routing decision over the same drafts",
        "one_variable": (
            "the judge's prompt, and nothing else: the same frozen drafts, the same frozen finding "
            "side, the same model and the same reasoning effort"
        ),
        "findings_whose_routing_decision_differs": sum(1 for cluster in difference for v in cluster if v),
        "findings": sum(len(cluster) for cluster in difference),
        "cases_whose_collapsed_decision_differs": sum(
            1
            for cluster in clusters
            if any(not blind[fid] for fid in cluster) != any(not anchored[fid] for fid in cluster)
        ),
        "cases": len(clusters),
    }
    try:
        agreement = within_cluster_agreement(difference)
    except DegenerateClustering as exc:
        block["icc"] = None
        block["icc_undefined_because"] = str(exc)
        return block
    block["icc"] = round(agreement.icc, 4)
    block["icc_detail"] = agreement.to_dict()
    # The sign is emitted rather than a verdict against some cutoff: "materially negative" has no
    # pre-registered threshold, and inventing one after seeing the number is the move this project
    # does not permit itself. What the record owes a reader is that a negative value is the bad case
    # and that it is THIS case, in the file, without anyone having to know the sign convention.
    block["sign"] = "negative" if agreement.icc < 0 else ("positive" if agreement.icc > 0 else "zero")
    block["reading"] = (
        "A POSITIVE within-case correlation of the DIFFERENCE means discordant findings arrive together "
        "on the same page, which is what the case collapse is paid to absorb. A NEGATIVE one means the "
        "collapse is cancelling differences against each other, so the pinned unit is COSTING POWER "
        "rather than buying honesty — and this run's value is "
        f"{block['sign']}. Unlike every earlier estimate in this milestone, nothing here is confounded: "
        "the two sides differ in the judge's prompt alone, over the same drafts and the same frozen "
        "finding side. ⚠️ It does not license re-cutting the unit — the unit was pinned before any run "
        "and the threshold's floor bar before this configuration existed — it says what the pinned unit "
        "cost, which is a finding to record rather than a knob to turn."
    )
    return block


# ---------------------------------------------------------------------------------------------
# The stub, and the dry receipt
# ---------------------------------------------------------------------------------------------

STUB_DISCLAIMER = (
    "Every judge answer in this record came from a DETERMINISTIC STUB, not from a model: the verdict "
    "and the citation are read off the sha256 of the ask. Zero model calls were made and zero tokens "
    "were spent. So every rate, cell, direction and kappa below describes the HARNESS — that the asks "
    "assemble from the frozen finding side and carry no draft, that each answer parses, that agreement "
    "is computed in code, that the two collapses apply in their pinned order, and that the scorer "
    "records the unit its cells are on. None of them describes the judge, and none may be quoted as a "
    "baseline, a floor, a disagreement rate or a result."
)

_STUB_SC_POOL: tuple[tuple[str, ...], ...] = ((), ("1.1.1",), ("2.4.4",), ("3.3.2", "2.4.6"))


class StubBlindJudgeClient:
    """A deterministic non-model client answering the BLIND schema. Not a model, and never pretends to be.

    `salt` makes one pass differ from the next, which is what gives the majority-across-passes collapse
    something to decide — and, because the verdict here is four-valued rather than boolean, what makes
    the undecided-direction path reachable at all.

    It records every user prompt it was handed, for the same reason the anchored stub does: what a
    caller actually sent is otherwise unobservable, and "the draft leaked into the ask" is exactly the
    failure this configuration exists to rule out.
    """

    reasoning_effort = "stub"

    def __init__(self, model: str = "stub-judge", salt: str = "") -> None:
        self._model = model
        self._salt = salt
        self.calls = 0
        self.requests: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        self.calls += 1
        self.requests.append(user)
        digest = hashlib.sha256(f"{self._salt}\x00{system}\x00{user}".encode()).digest()
        conformance = list(Conformance)[digest[0] % len(Conformance)]
        payload = {
            "conformance": conformance.value,
            "cited_sc_ids": list(_STUB_SC_POOL[digest[1] % len(_STUB_SC_POOL)]),
            "rationale": "stubbed answer — no inference happened",
        }
        return Completion(json.dumps(payload), LLMUsage())


def blind_attempts_per_call() -> int:
    """How many times ONE blind ask may reach the model, read from `BlindJudge`'s declared default.

    Derived rather than restated, and derived from **`BlindJudge`** rather than from the pre-flight's
    `judge_attempts_per_call`, which inspects the anchored `Judge`: the two happen to share a default
    today, and a number copied from the other configuration would stay right only until one of them
    changed. No harness passes `retries`, so the constructor default IS the effective value.
    """
    import inspect

    return int(inspect.signature(BlindJudge.__init__).parameters["retries"].default) + 1


def paid_call_budget(*, asks: int, passes: int) -> dict[str, Any]:
    """⚠️ What a LIVE run of this configuration would cost — as a FLOOR and a ceiling, never a value.

    A judge call retries on an unparseable response and **a retry leaves nothing on disk**: the run
    artifact holds one row whether the verdict came back first try or second. So the ask count is what
    the configuration costs if no response is ever off-schema, and the ceiling is that times the
    attempts one call is allowed. The true figure sits between them and is only recoverable by counting
    at the client seam — which is what a recording client below the judge is for, and this
    configuration does not have one yet.

    ⚠️ **The dry run's own count is exact, and that is a different fact.** The stub cannot fail, so it
    served exactly one response per ask; nothing about that bounds what a real model will cost.
    """
    attempts = blind_attempts_per_call()
    floor = asks * passes
    return {
        "asks": floor,
        "floor": floor,
        "max_attempts_per_call": attempts,
        "ceiling": floor * attempts,
        "arithmetic": f"{asks} asks × {passes} passes = {floor} floor; × {attempts} attempts = {floor * attempts}",
        "note": (
            "⚠️ NEVER quote the floor as the spend. A retried call leaves no trace in a run artifact — "
            "one row is written whether the answer parsed on the first attempt or a later one — so the "
            "amount between floor and ceiling cannot be recovered afterwards and has to be counted at "
            "the client seam or read off the provider. The stubbed count in this receipt is exact "
            "instead, and only because a stub cannot return an unparseable answer."
        ),
    }


def _confusion_block(scoring: JudgeScoring) -> dict[str, Any]:
    c = scoring.confusion
    return {
        "unit": scoring.unit,
        "observations": scoring.n,
        "correct_release": c.correct_release,
        "missed_error": c.missed_error,
        "false_alarm": c.false_alarm,
        "correct_catch": c.correct_catch,
        "kappa": round(c.kappa, 4),
        "miss_rate": round(c.miss_rate.value, 4),
        "miss_rate_n": c.miss_rate.n,
        "false_alarm_rate": round(c.false_alarm_rate.value, 4),
        "false_alarm_rate_n": c.false_alarm_rate.n,
    }


def build_receipt(
    *,
    artifact: dict[str, Any],
    replay_path: Path,
    input_record: dict[str, Any],
    input_path: Path,
    asks: Sequence[BlindAsk],
    prepared: dict[str, FindingInput],
    passes: Sequence[Sequence[BlindOutcome]],
    scoring: BlindScoring,
    judge_version: str,
    stub_calls: int,
    anchored: dict[str, bool] | None,
) -> dict[str, Any]:
    """The dry receipt: what the path did, what it cost, and what none of it means."""
    ask_digest = hashlib.sha256("\x00".join(f"{a.finding_id}|{a.act_testcase_id}" for a in asks).encode()).hexdigest()
    receipt: dict[str, Any] = {
        "artifact": "a dry run of the blind judging path over stubbed responses",
        "version": 1,
        "configuration": CONFIGURATION,
        "configuration_meaning": CONFIGURATION_MEANING,
        "model_calls_spent": 0,
        "stubbed": True,
        "stub_disclaimer": STUB_DISCLAIMER,
        "stub_responses_served": stub_calls,
        "created_at": artifact["created_at"],
        "judge_version": judge_version,
        "sources": {
            "frozen_drafts": {
                "path": replay_path.name,
                "config_id": artifact["config_id"],
                "eval_set_id": artifact["eval_set_id"],
                "cases": len(artifact["cases"]),
                "honest_misses": len(artifact["honest_misses"]),
            },
            "frozen_finding_side": {
                "path": input_path.name,
                "rows": len(input_record["rows"]),
                "reproducible_digest": input_record["reproducible_digest"],
            },
        },
        "asks_per_pass": {
            "natural": len(asks),
            "total": len(asks),
            "arithmetic": f"{len(asks)} natural + 0 mutated = {len(asks)}",
            "no_mutations_here": NO_MUTATIONS_HERE,
        },
        "passes": len(passes),
        "asks_over_the_whole_configuration": len(asks) * len(passes),
        "stubbed_calls_are_exact": (
            "`stub_responses_served` is the exact number of responses served, because a stub cannot "
            "return an unparseable answer and therefore never triggers a retry. That is a property of "
            "the stub and says nothing about a paid run — see `paid_call_budget_if_run_live`."
        ),
        "paid_call_budget_if_run_live": paid_call_budget(asks=len(asks), passes=len(passes)),
        "ask_digest": ask_digest,
        "distinct_asks": distinct_ask_profile(asks, prepared),
        "collapse": {
            "order": AGGREGATION_ORDER,
            "findings": scoring.per_finding.n,
            "cases": scoring.per_case.n,
            "findings_the_majority_decided": len(scoring.released),
        },
        "confusion": {
            "per_case": _confusion_block(scoring.per_case),
            "per_finding": _confusion_block(scoring.per_finding),
        },
        "injected": {
            "conformance_flip_n": scoring.per_case.confusion.injected_conformance_flip.n,
            "sc_swap_n": scoring.per_case.confusion.injected_sc_swap.n,
            "denominator": NO_MUTATIONS_HERE,
        },
        "disagreement": disagreement_profile(artifact, asks, passes, prepared),
    }
    if anchored is not None:
        receipt["between_configuration_difference"] = between_configuration_difference(artifact, asks, passes, anchored)
    return receipt


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_blind_dry_receipt.json"


def dry_run(passes: int = 3) -> dict[str, Any]:
    """Exercise the whole blind path on stubbed responses and freeze the receipt. Zero model calls.

    The anchored configuration's frozen record is read if it is on disk, so the between-configuration
    contrast is exercised too — against real anchored decisions and stubbed blind ones, which makes the
    resulting correlation a statement about the harness and nothing else. Its absence is not fatal: the
    rest of the path does not depend on it.
    """
    from clearway.eval.judge_anchored_baseline import report_path as anchored_report_path
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path
    from clearway.llm import LocalLLMClient

    require_odd_passes(passes)

    replay_path = run_path(CITATION_GROUNDING, 1)
    artifact = json.loads(replay_path.read_text())
    input_record = load_record()
    prepared = prepared_inputs(input_record)
    asks = blind_asks(artifact)

    served = 0
    results: list[list[BlindOutcome]] = []
    judge_version = ""
    for index in range(passes):
        client = StubBlindJudgeClient(salt=f"pass-{index + 1}")
        judge = BlindJudge(client, drafter_model=LocalLLMClient().model)
        judge_version = judge.judge_version
        results.append(run_pass(judge, prepared, asks, run_id=f"dry-pass-{index + 1}"))
        served += client.calls

    anchored_path = anchored_report_path()
    anchored = (
        anchored_majority_releases(artifact, json.loads(anchored_path.read_text())) if anchored_path.exists() else None
    )
    return build_receipt(
        artifact=artifact,
        replay_path=replay_path,
        input_record=input_record,
        input_path=input_report_path(),
        asks=asks,
        prepared=prepared,
        passes=results,
        scoring=score_blind(artifact, asks, results),
        judge_version=judge_version,
        stub_calls=served,
        anchored=anchored,
    )


def main() -> None:
    receipt = dry_run()
    print(f"blind dry run — {receipt['model_calls_spent']} model calls, {receipt['stub_responses_served']} stubbed")
    print(f"  asks per pass: {receipt['asks_per_pass']['arithmetic']}")
    print(f"  over {receipt['passes']} passes: {receipt['asks_over_the_whole_configuration']}")
    distinct = receipt["distinct_asks"]
    print(f"  distinct asks: {distinct['distinct_asks']} of {distinct['asks']}")
    for row in distinct["per_class"]:
        print(f"    {row['axe_rule']:<15} {row['distinct_asks']} distinct of {row['findings']}")
    for unit, block in receipt["confusion"].items():
        print(
            f"  {unit}: {block['observations']} obs, cells "
            f"{block['correct_release']}/{block['missed_error']}/{block['false_alarm']}/{block['correct_catch']}"
        )
    path = report_path()
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(Path.cwd())}")
    print("  ⚠ every number above describes the harness, never the judge")


if __name__ == "__main__":
    main()
