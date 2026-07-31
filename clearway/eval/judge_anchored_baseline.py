"""The anchored judge measured for real: the baseline it sets, and the noise floor beneath it.

The dry receipt beside this module proved the *path* on stubbed responses. This one spends the calls.
It changes nothing about the loop — the asks, the two collapses and the scorer are
`judge_anchored`'s, unchanged — and adds only the three things a live run needs and a stub cannot
supply:

1. **A ledger, so a restart does not re-spend.** Every transport call is appended to a JSONL file the
   moment it returns. A re-run replays the recorded responses in order, verifying each against the
   digest of the prompt it is about to answer, and calls the model only for the asks the ledger has
   not reached. Hundreds of paid calls take a long time, a long measurement is indistinguishable from
   a hang, and the cost of guessing wrong is the whole run again.
2. **Usage captured where it survives.** `Judge.judge_prepared` returns a `JudgeResult`, which carries
   no tokens, no cost and no latency — the `Completion.usage` the client produced is dropped at that
   seam. Rather than widen a production shape for an eval-only need, the usage is recorded one layer
   below the judge, by a client wrapper. **⚠️ The consequence is that usage is per TRANSPORT CALL and
   cannot be attributed to a particular ask**: a retry is a second call on the same prompt, and the
   judge does not report which of its attempts succeeded. What that buys instead is better than a
   join — the recorded call count is the count of asks *plus* every retry, so the retry budget is
   visible in the aggregate rather than being the invisible gap between a floor and a ceiling.
3. **The run-to-run variance of a fixed configuration**, which is the whole reason a single pass is not
   a baseline. Each pass is scored on its own, the spread across passes is reported, and the
   pass-to-pass movement of the routing decision at the pinned unit is what fixes the floor bar the
   paired comparison's threshold rule consumes.

**⚠️ The recorded call count is still a floor, one layer tighter than the artifact's.** It counts
every call this process made through the client seam, retries included. What it cannot see is a
retry made *below* the seam, inside the provider client itself. Read the spend off the provider.

**Two majorities, taken independently, and that is a decision rather than an oversight.** The routing
decision is the majority of `conformance_correct` across the configuration's passes, exactly as the
pinned aggregation says. The *disagreement* event needs both of the judge's booleans, and a strict
majority over the PAIR can fail to exist — three passes can return three distinct pairs — so each
axis's majority is taken on its own boolean, where three passes always have one. The routing decision
is unaffected: it was only ever the conformance axis.

Invoke: `uv run --env-file .env python -m clearway.eval.judge_anchored_baseline`

**To rebuild the frozen record after a change to how something is COMPUTED, add `--rederive`** — it
re-runs the whole builder over the responses already in the file and needs no key, no network and no
call. Every number in the record is a function of those responses; only when the *asks* move does a
paid re-run become the honest answer, and that is what the ledger's digest check refuses to hide.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from clearway.eval.judge_anchored import (
    CONFORMANCE_FLIP,
    MUTATIONS,
    NATURAL,
    SC_SWAP,
    AnchoredAsk,
    anchored_asks,
    run_pass,
    score_anchored,
)
from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_finding_input import report_path as input_report_path
from clearway.eval.judge_observation_unit import (
    AGGREGATION_ORDER,
    DISAGREEMENT_RATE_UNIT,
    OBSERVATION_UNIT,
    DegenerateClustering,
    judge_routing_streams,
    majority_stream,
    null_discordance,
    null_routing_sign_test,
    unanimity,
    within_cluster_agreement,
)
from clearway.eval.judge_score import JudgeScoring
from clearway.eval.judge_threshold import THRESHOLD_RULE, smallest_attainable_n, threshold
from clearway.eval.stats import is_flag
from clearway.judge import Judge, verdict_from
from clearway.llm import Completion, ImagePart, LLMClient, LLMRequest, LLMUsage
from clearway.schemas.models import Conformance, JudgeResult

# The configuration this module runs. Named so the artifact says which of the comparison's two sides
# it holds: `citation_correct` and `conformance_correct` mean "the drafted answer is right" here and
# would mean "the judge named the same answer" under a blinded configuration, and two artifacts with
# the same field names and different questions are indistinguishable on disk without this.
CONFIGURATION = "anchored"

CONFIGURATION_MEANING = (
    "ANCHORED: the judge is shown the finding side AND the draft written for it, and grades that "
    "draft. So `conformance_correct` is the judge's opinion of the DRAFTER's verdict, not a verdict "
    "of its own, and the judge raises its hand exactly when that opinion is negative. A blinded "
    "configuration reuses both field names for a different question — its booleans are computed in "
    "code from the judge's own answer — so neither artifact may be read without this marker."
)

# The ceiling every gold-scored figure here is bounded by, and it is not the judge's to move.
NOT_A_MEASUREMENT_OF_THE_DRAFTER = (
    "Every cell below scores the JUDGE's routing decision against ACT gold. The drafts are frozen and "
    "are never re-drafted, so the count of act-wrong units is a property of the drafter and fixes the "
    "ceiling on `correct_catch`; a judge that raised its hand on everything would still be bounded by "
    "it. Nothing here is a measurement of the drafter. ⚠️ THE TWO WRONG-COUNTS ARE DIFFERENT SETS AND "
    "CAN COME OUT NUMERICALLY EQUAL. The act-wrong units are `missed_error` + `correct_catch`; the "
    "units the judge routes wrongly are `missed_error` + `false_alarm`. Only `missed_error` is in both, "
    "and every `false_alarm` is a unit whose draft was RIGHT — so the judge's own error count set beside "
    "the ceiling is two overlapping sets, never one, and their union is larger than either."
)


class LedgerMismatch(RuntimeError):
    """A recorded response offered for a prompt it was not the answer to.

    Raised rather than ignored: a ledger is only a saving if replaying it is indistinguishable from
    having made the call. A row whose prompt digest does not match the ask about to be sent means the
    asks moved under the ledger — a re-scan, an edited frozen block, a changed rubric — and replaying
    it would silently fabricate a measurement out of answers to different questions.
    """


# ---------------------------------------------------------------------------------------------
# The ledger and the recording client
# ---------------------------------------------------------------------------------------------


@dataclass
class CallLedger:
    """Every transport call the measurement has made, appended the moment each one returns.

    Deliberately append-only JSONL rather than a rewritten JSON document: the file has to survive the
    process being killed between two paid calls, and a partial line is recoverable while a truncated
    re-serialization of the whole record is not.
    """

    path: Path
    rows: list[dict[str, Any]]

    @classmethod
    def open(cls, path: Path) -> CallLedger:
        rows: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return cls(path=path, rows=rows)

    def recorded(self, pass_index: int) -> list[dict[str, Any]]:
        """This pass's calls, in the order they were made."""
        return [row for row in self.rows if row["pass"] == pass_index]

    def append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows.append(row)


class RecordingJudgeClient:
    """An `LLMClient` that wraps another one, records what each call cost, and replays a ledger.

    It sits below the judge rather than inside it because the alternative is widening `JudgeResult`,
    a production shape under the contracts, with three fields only a measurement wants. The price of
    that choice is stated in the module docstring and in the artifact: usage is per transport call,
    so it cannot be attributed to a particular ask.
    """

    def __init__(self, inner: LLMClient, ledger: CallLedger, pass_index: int) -> None:
        self._inner = inner
        self._ledger = ledger
        self._pass = pass_index
        self._replay = ledger.recorded(pass_index)
        self._ordinal = 0
        self.spent = 0
        self.replayed = 0

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def reasoning_effort(self) -> str:
        effort = getattr(self._inner, "reasoning_effort", "")
        return str(effort)

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        digest = LLMRequest.of(system, user, schema, image).prompt_sha256
        ordinal, self._ordinal = self._ordinal, self._ordinal + 1
        if ordinal < len(self._replay):
            row = self._replay[ordinal]
            if row["prompt_sha256"] != digest:
                raise LedgerMismatch(
                    f"ledger row {ordinal} of pass {self._pass} answers prompt {row['prompt_sha256'][:12]}… "
                    f"and the ask about to be sent is {digest[:12]}…. The asks have moved under the "
                    "ledger, so replaying it would answer a question that was never put. Delete the "
                    "ledger and re-run, or find what moved the prompt."
                )
            self.replayed += 1
            return Completion(row["content"], _usage_of(row))
        completion = self._inner.complete_json(system, user, schema, image)
        self.spent += 1
        self._ledger.append(
            {
                "pass": self._pass,
                "ordinal": ordinal,
                "prompt_sha256": digest,
                "content": completion.content,
                **_usage_row(completion.usage),
            }
        )
        return completion


def _usage_row(usage: LLMUsage) -> dict[str, Any]:
    return {
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
        "cost_usd": usage.cost_usd,
        "latency_ms": usage.latency_ms,
    }


def _usage_of(row: dict[str, Any]) -> LLMUsage:
    return LLMUsage(
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        cost_usd=row["cost_usd"],
        latency_ms=row["latency_ms"],
    )


# ---------------------------------------------------------------------------------------------
# Results as rows: what gets frozen, and what the record is re-derivable from
# ---------------------------------------------------------------------------------------------


def result_rows(asks: Sequence[AnchoredAsk], results: Sequence[JudgeResult]) -> list[dict[str, Any]]:
    """One row per ask: which ask it was, and what the judge answered.

    The rationale rides along. It is never compared and never scored — prose is not a compared field —
    but it is the only qualitative trace a reader has that the model reasoned rather than stamped, and
    a run whose text nobody can read is a number that has to be taken on trust.
    """
    return [
        {
            "finding_id": ask.finding_id,
            "act_testcase_id": ask.act_testcase_id,
            "axe_rule": ask.axe_rule,
            "mutation": ask.mutation,
            "citation_correct": result.citation_correct,
            "conformance_correct": result.conformance_correct,
            "verdict": result.verdict.value,
            "rationale": result.rationale,
        }
        for ask, result in zip(asks, results, strict=True)
    ]


def results_from_rows(
    asks: Sequence[AnchoredAsk], rows: Sequence[dict[str, Any]], *, judge_model: str, judge_version: str, run_id: str
) -> list[JudgeResult]:
    """Frozen rows → the `JudgeResult` list the scorer consumes, refused if they are not these asks.

    The refusal is the point: every computed field in the record is re-derived from these rows by the
    freeze test, and a re-derivation that silently re-aligned itself to a different ask order would
    reproduce the record while describing something else.
    """
    if len(rows) != len(asks):
        raise LedgerMismatch(f"{len(rows)} frozen result rows against {len(asks)} asks — different runs")
    out: list[JudgeResult] = []
    for ask, row in zip(asks, rows, strict=True):
        if (row["finding_id"], row["mutation"]) != (ask.finding_id, ask.mutation):
            raise LedgerMismatch(
                f"frozen row {row['finding_id']}/{row['mutation']} does not match ask "
                f"{ask.finding_id}/{ask.mutation} — the rows are not this configuration's asks"
            )
        out.append(
            JudgeResult(
                finding_id=ask.finding_id,
                run_id=run_id,
                judge_model=judge_model,
                judge_version=judge_version,
                verdict=verdict_from(row["citation_correct"], row["conformance_correct"]),
                citation_correct=row["citation_correct"],
                conformance_correct=row["conformance_correct"],
                rationale=row["rationale"],
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# The judge's two axes, collapsed across passes
# ---------------------------------------------------------------------------------------------


def _keyed(asks: Sequence[AnchoredAsk], results: Sequence[JudgeResult]) -> dict[tuple[str, str], JudgeResult]:
    return {(a.finding_id, a.mutation): r for a, r in zip(asks, results, strict=True)}


def axis_majorities(asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]) -> dict[str, dict[str, bool]]:
    """`finding_id → {axis: the majority of that axis across the passes}` on the natural drafts.

    **Each axis on its own, and the reason is that a joint majority can fail to exist.** Three passes
    can return three distinct (citation, conformance) pairs, at which point the pinned majority refuses
    — correctly, since resolving it would break a tie by pass order. Each boolean axis always has a
    strict majority over an odd pass count, and the routing decision was only ever the conformance one,
    so nothing about the paired comparison changes; what this makes possible is the composition of the
    disagreement, which needs both.
    """
    naturals = [a for a in asks if a.mutation == NATURAL]
    keyed = [_keyed(asks, results) for results in passes]
    out: dict[str, dict[str, bool]] = {}
    for axis in ("citation_correct", "conformance_correct"):
        per_pass = [[[bool(getattr(k[(a.finding_id, NATURAL)], axis))] for a in naturals] for k in keyed]
        for ask, row in zip(naturals, majority_stream(per_pass), strict=True):
            out.setdefault(ask.finding_id, {})[axis] = bool(row[0])
    return out


def _drafter_inconsistent_findings(artifact: dict[str, Any]) -> set[str]:
    """The clean drafts that cite anyway — the rows the drafter's own citation habit does not cover.

    Recorded because the SC axis has to be read knowing how much of it is a formatting habit rather
    than a difference of opinion. A `supports` draft usually cites nothing; these are the ones that do.
    """
    return {
        d["finding_id"]
        for case in artifact["cases"]
        for d in case["drafts"]
        if not is_flag(Conformance(d["conformance"])) and d["cited_sc_ids"]
    }


def _findings_citing_nothing(artifact: dict[str, Any]) -> set[str]:
    """The drafts with an empty `cited_sc_ids` — the other side of the same unwritten convention.

    Both halves are counted because a rubric can only be wrong one way at a time: told to stay silent
    when clean it mismatches the rows that cite anyway, told to always cite it mismatches these. Which
    half the SC-axis disagreements land on is what says whether that axis carries opinion or format.
    """
    return {d["finding_id"] for case in artifact["cases"] for d in case["drafts"] if not d["cited_sc_ids"]}


def disagreement_profile(
    artifact: dict[str, Any], asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]
) -> dict[str, Any]:
    """The milestone's primary deliverable on this side: how often the judge raised its hand, and where.

    **Unit: the FINDING**, denominator the natural drafts, with the count of distinct cases the
    disagreements touch beside it — a rate alone hides the workload, and the queue is walked per
    finding whatever unit the paired test is scored on.

    ⚠️ The event here is *the judge graded the draft incorrect on either axis*, which is NOT the same
    predicate as the routing decision the confusion matrix scores: that one is the conformance axis
    alone. Two predicates, both reported, each named where it appears.
    """
    naturals = [a for a in asks if a.mutation == NATURAL]
    majorities = axis_majorities(asks, passes)
    inconsistent = _drafter_inconsistent_findings(artifact)
    silent = _findings_citing_nothing(artifact)

    rows: list[dict[str, Any]] = []
    for ask in naturals:
        axes = majorities[ask.finding_id]
        rows.append(
            {
                "finding_id": ask.finding_id,
                "act_testcase_id": ask.act_testcase_id,
                "axe_rule": ask.axe_rule,
                "conformance_disagreement": not axes["conformance_correct"],
                "sc_disagreement": not axes["citation_correct"],
                "drafter_cites_on_a_clean_row": ask.finding_id in inconsistent,
                "drafter_cites_nothing": ask.finding_id in silent,
            }
        )

    def _shares(subset: list[dict[str, Any]]) -> dict[str, Any]:
        disagreeing = [r for r in subset if r["conformance_disagreement"] or r["sc_disagreement"]]
        both = [r for r in disagreeing if r["conformance_disagreement"] and r["sc_disagreement"]]
        conformance_only = [r for r in disagreeing if r["conformance_disagreement"] and not r["sc_disagreement"]]
        sc_only = [r for r in disagreeing if r["sc_disagreement"] and not r["conformance_disagreement"]]
        return {
            "findings": len(subset),
            "disagreements": len(disagreeing),
            "disagreement_rate": round(len(disagreeing) / len(subset), 4) if subset else 0.0,
            "distinct_cases_touched": len({r["act_testcase_id"] for r in disagreeing}),
            "conformance_axis_disagreements": sum(1 for r in subset if r["conformance_disagreement"]),
            "sc_axis_disagreements": sum(1 for r in subset if r["sc_disagreement"]),
            "composition": {
                "conformance_only": len(conformance_only),
                "sc_only": len(sc_only),
                "both": len(both),
            },
        }

    by_rule: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_rule.setdefault(row["axe_rule"], []).append(row)

    sc_rows = [r for r in rows if r["sc_disagreement"]]
    return {
        "unit": DISAGREEMENT_RATE_UNIT,
        "event": (
            "the judge graded the draft incorrect on EITHER axis — citation_correct or "
            "conformance_correct false, taken as each axis's own majority across the passes"
        ),
        "not_the_routing_predicate": (
            "The confusion matrix's routing decision is the CONFORMANCE axis alone, so its flag count "
            "and this disagreement count are different quantities over the same 54 findings and must "
            "not be substituted for one another. Both are reported; the conformance-axis subtotal here "
            "is the one that matches the routing decision."
        ),
        "overall": _shares(rows),
        "per_class": [
            {
                "axe_rule": rule,
                **_shares(group),
                "drafter_cites_on_a_clean_row": sum(1 for r in group if r["drafter_cites_on_a_clean_row"]),
                "drafter_cites_nothing": sum(1 for r in group if r["drafter_cites_nothing"]),
            }
            for rule, group in sorted(by_rule.items())
        ],
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
                "habit in either direction — a judge that disputes a citation it was shown, and a judge "
                "that disputes the ABSENCE of one — and a count of only the first makes an axis "
                "dominated by the second look clean. Read either count against its own denominator "
                "above before reading any SC-axis figure, overall or per class; a figure quoted on its "
                "own is not interpretable. ⚠️ On THIS configuration the judge is grading a citation "
                "rather than making one, so the artefact reaches it through the graded row's `(none)` "
                "and not through a set comparison; the counts are reported at the same denominator so "
                "the two configurations' SC axes can be read side by side."
            ),
        },
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------------
# The noise floor
# ---------------------------------------------------------------------------------------------


def routing_flag_streams(
    artifact: dict[str, Any], asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]
) -> list[list[list[bool]]]:
    """`[pass][case][finding]` — did the judge raise its hand, per pass, in the artifact's case order.

    One pass at a time and no collapse yet: the floor is measured between passes, so the majority the
    routing decision is normally taken on would erase exactly the movement being counted.
    """
    streams: list[list[list[bool]]] = []
    for results in passes:
        keyed = _keyed(asks, results)
        streams.append(
            [
                [not keyed[(d["finding_id"], NATURAL)].conformance_correct for d in case["drafts"]]
                for case in artifact["cases"]
            ]
        )
    return streams


def case_act_wrong(artifact: dict[str, Any]) -> list[bool]:
    """Per case, in artifact order: is the case's drafted answer wrong against ACT gold?

    Flag-if-any over the case's own drafts against the gold outcome — the case-level predicate, never
    a roll-up of the per-finding ones.
    """
    return [
        any(is_flag(Conformance(d["conformance"])) for d in case["drafts"]) != (case["expected"] == "failed")
        for case in artifact["cases"]
    ]


def finding_act_wrong(artifact: dict[str, Any]) -> list[bool]:
    """Per finding, in artifact order: is this draft's verdict wrong against ACT gold?"""
    return [
        is_flag(Conformance(d["conformance"])) != (case["expected"] == "failed")
        for case in artifact["cases"]
        for d in case["drafts"]
    ]


def one_way_wins(rows: Sequence[dict[str, Any]]) -> int:
    """The largest ONE-WAY movement any same-configuration pass-pair produced.

    ⚠️ `max(improved, regressed)` per pair, then `max` across pairs — not the larger `improved` column.
    Under the null neither pass of a pair precedes the other, so a pair recorded 3 improvements against
    6 regressions is the same event as 6 against 3 with the labels swapped, and a floor taken off the
    `improved` column alone would be one relabelling short of the movement the judge actually produces.
    """
    return max((max(row["improved"], row["regressed"]) for row in rows), default=0)


def _spread(values: list[float]) -> dict[str, Any]:
    return {
        "values": [round(v, 4) for v in values],
        "mean": round(statistics.fmean(values), 4),
        "sd": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _scoring_block(scoring: JudgeScoring) -> dict[str, Any]:
    c = scoring.confusion
    catches = c.correct_catch
    flagged = c.correct_catch + c.false_alarm
    wrong = c.correct_catch + c.missed_error
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
        "share_of_the_flagged_set_that_is_genuinely_wrong": round(catches / flagged, 4) if flagged else 0.0,
        "flagged_set_size": flagged,
        "share_of_all_real_errors_that_were_flagged": round(catches / wrong, 4) if wrong else 0.0,
        "real_errors": wrong,
    }


def noise_floor_block(
    artifact: dict[str, Any], asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]
) -> dict[str, Any]:
    """What a fixed configuration does to itself when nothing changes — and the bar that follows.

    Three things, and only the last one leaves this module: the spread of each headline figure across
    the passes, the pass-to-pass movement of the routing decision at both units, and the largest
    one-way movement, which is the floor bar the pre-registered threshold rule consumes.
    """
    per_pass = [score_anchored(artifact, asks, [results]) for results in passes]
    flag_streams = routing_flag_streams(artifact, asks, passes)
    finding_streams = [[[flag] for case in stream for flag in case] for stream in flag_streams]

    case_rows = null_routing_sign_test(flag_streams, case_act_wrong(artifact))
    finding_rows = null_routing_sign_test(finding_streams, finding_act_wrong(artifact))
    return {
        "passes": len(passes),
        "per_pass": {
            "per_case": [_scoring_block(s.per_case) for s in per_pass],
            "per_finding": [_scoring_block(s.per_finding) for s in per_pass],
        },
        "spread": {
            unit: {
                metric: _spread([float(block[metric]) for block in blocks])
                for metric in ("kappa", "miss_rate", "false_alarm_rate")
            }
            for unit, blocks in (
                ("per_case", [_scoring_block(s.per_case) for s in per_pass]),
                ("per_finding", [_scoring_block(s.per_finding) for s in per_pass]),
            )
        },
        "pass_to_pass_disagreement": unanimity(
            [[[not flag for flag in case] for case in stream] for stream in flag_streams]
        ),
        "movement_per_pass_pair": {
            "per_case": case_rows,
            "per_finding": finding_rows,
            "erasure": null_discordance(flag_streams),
        },
        "one_way_wins": {
            "per_case": one_way_wins(case_rows),
            "per_finding": one_way_wins(finding_rows),
            "note": (
                "The per-case figure is the floor bar's input, because a threshold counted per finding "
                "cannot govern a test scored per case. The per-finding figure is reported beside it so "
                "the cost of the flag-if-any collapse stays visible."
            ),
        },
    }


def threshold_block(null_wins: int, *, up_to: int = 14) -> dict[str, Any]:
    """The pre-registered rule with this run's floor plugged in, tabulated over the counts it could meet.

    Nothing is chosen here. The rule was fixed before the floor existed; this supplies the one number
    it was waiting for and reads out what that number implies at each discordant count a later paired
    comparison might realize.
    """
    rows = []
    for n in range(up_to + 1):
        bar = threshold(n, null_wins=null_wins)
        rows.append(
            {
                "discordant_pairs": n,
                "statistical_bar": bar.statistical_bar,
                "floor_bar": bar.floor_bar,
                "required_wins": bar.required_wins,
                "binding_bar": bar.binding_bar,
            }
        )
    return {
        "rule": THRESHOLD_RULE,
        "null_wins": null_wins,
        "floor_bar": null_wins + 1,
        "smallest_attainable_n": smallest_attainable_n(null_wins=null_wins),
        "required_wins_by_discordant_count": rows,
        "source_of_null_wins": (
            "the largest ONE-WAY movement any same-configuration pass-pair produced at the pinned "
            "unit, taken after the case collapse — max(improved, regressed) per pair, then max across "
            "pairs, because the pass ordering inside a same-configuration pair is arbitrary"
        ),
    }


# ---------------------------------------------------------------------------------------------
# The correlation of a difference that is not null
# ---------------------------------------------------------------------------------------------


def between_configuration_difference(
    artifact: dict[str, Any],
    asks: Sequence[AnchoredAsk],
    passes: Sequence[Sequence[JudgeResult]],
    judged_paths: Sequence[Path],
) -> dict[str, Any]:
    """The within-case correlation of a REAL difference between two judged configurations.

    ⚠️ **The contrast a paired comparison of the two prompt configurations consumes does not exist
    yet**, and cannot: only one configuration has ever produced judge output on this input, and the
    other is a later stage's to run. What is available is the nearest real (non-null) contrast on the
    same clusters — this run against the earlier judged passes, which graded the same 40 cases and the
    same finding ids under a finding side carrying no referent and no candidate list, on an earlier
    draft set. **Prompt and drafts moved together**, so the correlation below describes a real
    difference and attributes it to nothing.

    Reported because the pinned unit's cost is a function of how a difference clusters, not of how a
    level does, and because a materially negative figure would mean the case collapse costs power
    rather than buying honesty. Refused rather than defaulted when the difference stream is constant.
    """
    from clearway.eval.judge_observation_unit import _scoped_finding_map

    order = [[d["finding_id"] for d in case["drafts"]] for case in artifact["cases"]]
    # ⚠️ Asserted rather than assumed. The earlier passes' streams are ordered by the scoped finding
    # map and this run's by the artifact's own case list; the two coincide today because every scoped
    # case mints, and a silent divergence would zip one configuration's answers against another's
    # findings and report the misalignment as a difference of opinion.
    scoped = [list(fids) for fids in _scoped_finding_map(artifact).values()]
    if scoped != order:
        raise DegenerateClustering(
            "the scoped finding order and the artifact's case order differ, so the two configurations' "
            "streams cannot be paired position by position"
        )
    earlier = [json.loads(path.read_text()) for path in judged_paths]
    earlier_streams = judge_routing_streams(earlier, artifact)
    earlier_majority = majority_stream(earlier_streams)

    keyed = [_keyed(asks, results) for results in passes]
    here_per_pass = [
        [[bool(k[(fid, NATURAL)].conformance_correct) for fid in cluster] for cluster in order] for k in keyed
    ]
    here_majority = majority_stream(here_per_pass)

    difference = [
        [bool(a) != bool(b) for a, b in zip(left, right, strict=True)]
        for left, right in zip(earlier_majority, here_majority, strict=True)
    ]
    differing = sum(1 for cluster in difference for value in cluster if value)
    block: dict[str, Any] = {
        "left": "the earlier judged passes' majority routing decision — anchored, referent-free input, "
        "an earlier draft set",
        "right": "this run's majority routing decision — anchored, referent-carrying input, the frozen replay drafts",
        "findings_whose_routing_decision_differs": differing,
        "findings": sum(len(cluster) for cluster in difference),
        "cases_whose_collapsed_decision_differs": sum(
            1
            for left, right in zip(earlier_majority, here_majority, strict=True)
            if any(not bool(v) for v in left) != any(not bool(v) for v in right)
        ),
        "cases": len(difference),
        "confounded": (
            "The two sides differ in the judge's prompt AND in the drafts being graded, so this "
            "quantity is a real between-configuration difference and NOT the contrast a paired "
            "comparison of the two prompt configurations would consume. That contrast needs a second "
            "configuration's judge output over these same drafts, which no artifact carries."
        ),
    }
    try:
        agreement = within_cluster_agreement(difference)
    except DegenerateClustering as exc:
        block["icc"] = None
        block["icc_undefined_because"] = str(exc)
        return block
    block["icc"] = round(agreement.icc, 4)
    block["icc_detail"] = agreement.to_dict()
    block["reading"] = (
        "A positive within-case correlation of the DIFFERENCE means discordant findings arrive "
        "together on the same page, which is what the case collapse is paid to absorb. A materially "
        "negative one would mean the collapse cancels differences against each other and costs power "
        "rather than buying honesty. ⚠️ THIS FIGURE DISCHARGES NEITHER READING. It is measured on the "
        "confounded contrast described above — a different prompt over different drafts — so a "
        "positive value here is not evidence that the contrast a paired comparison consumes is also "
        "positive, and the negative case is NOT ruled out but simply NOT YET MEASURED. Only two "
        "configurations' judge output over these same drafts can settle it."
    )
    return block


# ---------------------------------------------------------------------------------------------
# Cost and latency
# ---------------------------------------------------------------------------------------------


def cost_block(transport: Sequence[dict[str, Any]], *, asks_made: int) -> dict[str, Any]:
    """What the calls cost and how long they took — per TRANSPORT CALL, which is not per ask.

    ⚠️ The count here is a floor for the whole spend, one layer tighter than the run artifact's: it
    counts every call this process put through the client seam, retries included, and cannot see a
    retry made inside the provider client below it. The provider's own usage page is the only place
    the true total lives.
    """
    latencies = [float(row["latency_ms"]) for row in transport if row["latency_ms"] is not None]
    costs = [float(row["cost_usd"]) for row in transport if row["cost_usd"] is not None]
    tokens_in = [int(row["tokens_in"]) for row in transport if row["tokens_in"] is not None]
    tokens_out = [int(row["tokens_out"]) for row in transport if row["tokens_out"] is not None]

    def _stat(values: list[float], name: str) -> dict[str, Any]:
        if not values:
            return {"n": 0, "note": f"no {name} was reported on any call"}
        return {
            "n": len(values),
            "total": round(sum(values), 6),
            "mean": round(statistics.fmean(values), 6),
            "median": round(statistics.median(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }

    return {
        "transport_calls": len(transport),
        "asks": asks_made,
        "calls_beyond_one_per_ask": len(transport) - asks_made,
        "calls_are_a_floor": (
            "Counted at the client seam, so every retry the judge made is included — which is one "
            "layer tighter than a count taken off the artifact, where a retried ask writes one row "
            "either way. It is still a floor: a retry inside the provider client is invisible here, "
            "and the real spend is read off the provider."
        ),
        "latency_ms": _stat(latencies, "latency"),
        "cost_usd": _stat(costs, "cost"),
        "cost_priced_on": f"{len(costs)} of {len(transport)} calls",
        "tokens_in": _stat([float(v) for v in tokens_in], "input token count"),
        "tokens_out": _stat([float(v) for v in tokens_out], "output token count"),
        "unit": (
            "per transport call, never per ask: usage is captured below the judge, and the judge does "
            "not report which of its attempts produced the verdict it returned"
        ),
        "pricing_source": (
            "⚠️ `cost_usd` is a LOCAL PRICE TABLE applied to the provider's reported token counts, not "
            "an amount anyone was billed: the client asks LiteLLM to price each response, and a table "
            "that is stale for a snapshot prices it wrongly while one that has never heard of it "
            "prices it not at all — which is what `cost_priced_on` counts. The token counts themselves "
            "are the provider's own, and the output count includes whatever reasoning tokens the "
            "effort setting bought. Latency is measured locally around the call, so it carries this "
            "machine's network path as well as the model's. Read the billed total off the provider."
        ),
    }


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------

_VOLATILE_KEYS = ("created_at", "wall_clock_seconds", "reproducible_digest", "ledger")


def record_digest(record: dict[str, Any]) -> str:
    """sha256 over the record minus its own digest and the fields a re-run cannot reproduce."""
    stable = {k: v for k, v in record.items() if k not in _VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_record(
    *,
    artifact: dict[str, Any],
    replay_path: Path,
    input_record: dict[str, Any],
    pass_rows: Sequence[Sequence[dict[str, Any]]],
    transport: Sequence[dict[str, Any]],
    judge_model: str,
    judge_version: str,
    judged_paths: Sequence[Path],
    created_at: str,
    wall_clock_seconds: float,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the record. **Pure given the frozen response rows**, which is what makes it auditable.

    Nothing here calls a model, reads a clock or reaches the network: every computed field is a
    function of `pass_rows`, `transport` and the frozen artifacts, so the freeze test re-derives the
    whole record from the file's own rows rather than checking a digest against itself.
    """
    asks = anchored_asks(artifact)
    passes = [
        results_from_rows(
            asks, rows, judge_model=judge_model, judge_version=judge_version, run_id=f"anchored-pass-{index + 1}"
        )
        for index, rows in enumerate(pass_rows)
    ]
    scoring = score_anchored(artifact, asks, passes)
    per_mutation = {m: sum(1 for a in asks if a.mutation == m) for m in MUTATIONS}
    floor = noise_floor_block(artifact, asks, passes)

    record: dict[str, Any] = {
        "artifact": "the anchored judge's baseline on referent-carrying input, and its own noise floor",
        "version": 1,
        "configuration": CONFIGURATION,
        "configuration_meaning": CONFIGURATION_MEANING,
        "created_at": created_at,
        "wall_clock_seconds": round(wall_clock_seconds, 1),
        "judge_model": judge_model,
        "judge_version": judge_version,
        "not_a_measurement_of_the_drafter": NOT_A_MEASUREMENT_OF_THE_DRAFTER,
        "sources": {
            "frozen_drafts": {
                "path": replay_path.name,
                "sha256": hashlib.sha256(replay_path.read_bytes()).hexdigest(),
                "config_id": artifact["config_id"],
                "eval_set_id": artifact["eval_set_id"],
                "drafter_model": artifact["drafter_model"],
                "cases": len(artifact["cases"]),
                "honest_misses": len(artifact["honest_misses"]),
            },
            "frozen_finding_side": {
                "path": input_report_path().name,
                "rows": len(input_record["rows"]),
                "reproducible_digest": input_record["reproducible_digest"],
            },
            "earlier_judged_passes": [p.name for p in judged_paths],
        },
        "asks_per_pass": {
            **per_mutation,
            "total": len(asks),
            "arithmetic": (
                f"{per_mutation[NATURAL]} natural + {per_mutation[SC_SWAP]} SC-swap + "
                f"{per_mutation[CONFORMANCE_FLIP]} conformance-flip = {len(asks)}"
            ),
        },
        "passes": len(passes),
        "asks_over_the_whole_configuration": len(asks) * len(passes),
        "aggregation_order": AGGREGATION_ORDER,
        "observation_unit": OBSERVATION_UNIT,
        "confusion": {
            "per_case": _scoring_block(scoring.per_case),
            "per_finding": _scoring_block(scoring.per_finding),
        },
        "injected_versus_real": {
            "injected_conformance_flip_detection": round(scoring.per_case.confusion.injected_conformance_flip.value, 4),
            "injected_conformance_flip_n": scoring.per_case.confusion.injected_conformance_flip.n,
            "injected_sc_swap_detection": round(scoring.per_case.confusion.injected_sc_swap.value, 4),
            "injected_sc_swap_n": scoring.per_case.confusion.injected_sc_swap.n,
            "real_detection_per_case": _scoring_block(scoring.per_case)["share_of_all_real_errors_that_were_flagged"],
            "real_detection_per_finding": _scoring_block(scoring.per_finding)[
                "share_of_all_real_errors_that_were_flagged"
            ],
            "denominators": (
                "both injected rates are per mutated DRAFT and are never re-based by the confusion's "
                "unit; the two real-detection figures are the flagged share of the act-wrong units at "
                "the unit each is named for"
            ),
            "read_the_swap_knowing_this": (
                "The SC swap substitutes a decoy criterion, and no decoy appears in any class's "
                "retrieved candidate list — which this configuration now shows the judge. So 'is this "
                "citation wrong' is answerable by list membership, with no WCAG judgment involved, and "
                "a high swap-detection figure here carries LESS judge behaviour than the same figure "
                "did before the candidate list was shared. The conformance flip is unaffected: it "
                "changes a verdict, and no candidate list speaks to a verdict."
            ),
        },
        "disagreement": disagreement_profile(artifact, asks, passes),
        "noise_floor": floor,
        "threshold": threshold_block(int(floor["one_way_wins"]["per_case"])),
        "between_configuration_difference": between_configuration_difference(artifact, asks, passes, judged_paths),
        "cost": cost_block(transport, asks_made=len(asks) * len(passes)),
        "ledger": ledger,
        "pass_results": [
            {"pass": index + 1, "run_id": f"anchored-pass-{index + 1}", "results": list(rows)}
            for index, rows in enumerate(pass_rows)
        ],
        "transport": list(transport),
    }
    return {**record, "reproducible_digest": record_digest(record)}


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_anchored_baseline.json"


PAID_CALLS = "calls_that_bought_these_responses"
REPLAYED_CALLS = "calls_replayed_from_an_earlier_attempt"


def ledger_block(*, paid: int, replayed: int) -> dict[str, Any]:
    """How the responses in this record were obtained — assembled here, never carried through verbatim.

    ⚠️ **Both counts describe the invocation that BOUGHT the responses, not the process that last wrote
    the file.** A re-derivation recomputes every field from those same responses and makes no call, so a
    block copied across unchanged would eventually describe a run nobody made. It is rebuilt from the
    two integers instead, which is also what keeps this note true when the note itself is edited.
    """
    return {
        "path": ledger_path().name,
        PAID_CALLS: paid,
        REPLAYED_CALLS: replayed,
        "note": (
            "⚠️ Both counts describe the invocation that BOUGHT the responses in this record, and "
            "neither ever describes the process that last wrote the file: a re-derivation "
            "(`--rederive`) recomputes every field from those same responses, makes no call at all, "
            "and reproduces these two unchanged. A run resumed from the ledger spends only what the "
            "ledger had not reached, so the two split the measurement between paid and replayed and "
            "their sum is `cost.transport_calls` — itself a floor."
        ),
    }


def ledger_path() -> Path:
    """The append-only call ledger — transient working state, deliberately outside `reports/`.

    Gitignored for the same reason the per-case checkpoint is: it is resume state, not a measurement,
    and every response in it is copied into the frozen record when the run completes.
    """
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR.parent / "judge_anchored_baseline.partial.jsonl"


def live_run(passes: int = 3) -> dict[str, Any]:
    """Run the anchored configuration against the real judge and freeze the record.

    ⚠️ An EVEN pass count is refused for the reason the dry run refuses one: the per-finding collapse
    is a strict majority, and an even count can tie.
    """
    import time

    from clearway.eval.run_artifacts import CITATION_GROUNDING, acceptance_pass_paths, run_path
    from clearway.llm import CloudLLMClient, LocalLLMClient

    if passes < 1 or passes % 2 == 0:
        raise ValueError(
            f"a configuration runs an ODD number of passes, not {passes}: the per-finding collapse is a "
            "strict majority across passes, and an even count can tie."
        )

    replay_path = run_path(CITATION_GROUNDING, 1)
    artifact = json.loads(replay_path.read_text())
    input_record = load_record()
    prepared = prepared_inputs(input_record)
    asks = anchored_asks(artifact)

    ledger = CallLedger.open(ledger_path())
    drafter_model = LocalLLMClient().model
    started = time.perf_counter()
    pass_rows: list[list[dict[str, Any]]] = []
    spent = replayed = 0
    judge_model = judge_version = ""
    for index in range(passes):
        client = RecordingJudgeClient(CloudLLMClient(), ledger, index + 1)
        judge = Judge(client, drafter_model=drafter_model)
        judge_model, judge_version = client.model, judge.judge_version
        print(f"pass {index + 1}/{passes}: {len(asks)} asks", flush=True)
        results = run_pass(judge, prepared, asks, run_id=f"anchored-pass-{index + 1}")
        pass_rows.append(result_rows(asks, results))
        spent += client.spent
        replayed += client.replayed
        print(f"  pass {index + 1} done — {client.spent} calls made, {client.replayed} replayed", flush=True)

    return build_record(
        artifact=artifact,
        replay_path=replay_path,
        input_record=input_record,
        pass_rows=pass_rows,
        transport=[row for row in ledger.rows if row["pass"] <= passes],
        judge_model=judge_model,
        judge_version=judge_version,
        judged_paths=acceptance_pass_paths(),
        created_at=datetime.now(UTC).isoformat(),
        wall_clock_seconds=time.perf_counter() - started,
        ledger=ledger_block(paid=spent, replayed=replayed),
    )


def rederive_frozen_record() -> dict[str, Any]:
    """Rebuild the frozen record from the answers already in it — no model, no network, no clock.

    Every derived field in the record is a function of the judge's frozen responses, so a change to
    how something is *computed* must never be a reason to buy the responses again. Three facts are not
    derivable and are read back from the file rather than re-observed: when the calls were made, how
    long they took, and how many of them were paid for — re-observing them would date a re-computation
    as if it were the measurement. **⚠️ The last of those is read as two integers and its block is
    reassembled**, never copied across: a block carried through verbatim keeps whatever it said about
    the process that produced it, and after a re-derivation that is no longer this one.

    It is also what the freeze rests on: the same function the test re-derives the file with, so a
    record edited by hand and a record rebuilt by its own builder are distinguishable.
    """
    from clearway.eval.run_artifacts import CITATION_GROUNDING, acceptance_pass_paths, run_path

    frozen = json.loads(report_path().read_text())
    replay_path = run_path(CITATION_GROUNDING, 1)
    return build_record(
        artifact=json.loads(replay_path.read_text()),
        replay_path=replay_path,
        input_record=load_record(),
        pass_rows=[block["results"] for block in frozen["pass_results"]],
        transport=frozen["transport"],
        judge_model=frozen["judge_model"],
        judge_version=frozen["judge_version"],
        judged_paths=acceptance_pass_paths(),
        created_at=frozen["created_at"],
        wall_clock_seconds=frozen["wall_clock_seconds"],
        ledger=ledger_block(paid=frozen["ledger"][PAID_CALLS], replayed=frozen["ledger"][REPLAYED_CALLS]),
    )


def main() -> None:
    import sys

    rederive = "--rederive" in sys.argv[1:]
    record = rederive_frozen_record() if rederive else live_run()
    if rederive:
        print("re-derived from the frozen responses — no call was made")
    print(f"\nanchored baseline — {record['cost']['transport_calls']} transport calls (a floor)")
    for unit in ("per_case", "per_finding"):
        block = record["confusion"][unit]
        print(
            f"  {unit}: {block['observations']} obs, cells {block['correct_release']}/"
            f"{block['missed_error']}/{block['false_alarm']}/{block['correct_catch']}, "
            f"kappa {block['kappa']}, miss {block['miss_rate']}"
        )
    overall = record["disagreement"]["overall"]
    print(
        f"  disagreement: {overall['disagreements']}/{overall['findings']} findings "
        f"({overall['disagreement_rate']}) over {overall['distinct_cases_touched']} cases"
    )
    print(
        f"  floor bar input: {record['noise_floor']['one_way_wins']['per_case']} one-way case wins "
        f"under the null; smallest attainable n = {record['threshold']['smallest_attainable_n']}"
    )
    cost = record["cost"]
    print(f"  latency ms: {cost['latency_ms']}")
    print(f"  cost usd: {cost['cost_usd']}")

    path = report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
