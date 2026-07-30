"""One anchored judging pass over the frozen finding side — and the dry run that proves it for nothing.

The anchored configuration shows the judge a finding and the draft written for it, and asks it to grade
that draft. It costs three calls on most findings, not one: the injected-versus-real diagnostic mutates
the *draft*, and every mutation is its own call. So a pass is

    one natural draft per finding
  + one SC-swapped draft per finding
  + one conformance-flipped draft per **conformance-correct** finding

and the flip is gated because flipping an already-wrong verdict can land on the right one, at which
point the mutation is no longer known-wrong.

Why the dry run exists
----------------------
The live version of this path is the expensive stage of the comparison, and every question about
whether it *works* — do the asks assemble from the frozen bytes, does every response parse, does the
majority-then-flag-if-any collapse land where it should, does the scorer record the unit its cells are
on — is answerable with no model at all. So it is answered first, against a deterministic stub, and the
receipt is frozen. The same discipline as the drafter's offline gate: a run started with a defect in the
harness is a wasted run, and here the waste is measured in cloud calls.

**The stub is not a model and never pretends to be one.** It returns a schema-valid verdict derived from
the sha256 of the ask, so the two booleans vary across findings and across passes without any inference
happening — which is what makes the receipt reproducible and what makes it worthless as a measurement.
Every number in the receipt describes the HARNESS. None of them describes the judge, and the record says
so in its own text rather than relying on a reader to remember.

Two collapses, in the pinned order
----------------------------------
Repeat passes collapse first, per finding, by strict majority — a single pass of a judge that is not
bit-reproducible is one draw. The case collapse is second, flag-if-any. Reversing them answers a
different question and can land on a different case decision, so the order is taken from the pinned
aggregation rather than re-decided here, and the majority itself is the pinned implementation.

Pure given a judge and the frozen files: no scan, no retrieval, no clock in the record.

Invoke: `uv run python -m clearway.eval.judge_anchored`
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_finding_input import report_path as input_report_path
from clearway.eval.judge_observation_unit import AGGREGATION_ORDER, majority_stream
from clearway.eval.judge_score import (
    CONFUSION_UNIT_CASE,
    CONFUSION_UNIT_FINDING,
    InjectedResult,
    JudgedCase,
    JudgedDraft,
    JudgeScoring,
    collapse_to_cases,
    score_judge,
)
from clearway.eval.offline_inject import RATIONALE_NOTE, conformance_flip, sc_swap
from clearway.eval.stats import is_flag
from clearway.judge import FindingInput, Judge
from clearway.llm import Completion, ImagePart, LLMUsage
from clearway.schemas.models import Citation, Conformance, DraftRow, JudgeResult

NATURAL = "natural"
SC_SWAP = "sc_swap"
CONFORMANCE_FLIP = "conformance_flip"

# Every ask a pass makes, in the order it makes them. Named so the receipt's counts are keyed to a
# declared vocabulary rather than to strings spelled at three call sites.
MUTATIONS: tuple[str, ...] = (NATURAL, SC_SWAP, CONFORMANCE_FLIP)

# Which of the judge's two booleans can detect each mutation — **the mutation is only visible on the
# axis it moved.** An SC swap edits the CITATION and leaves the verdict exactly as drafted, so
# `conformance_correct` says nothing whatever about it: reading that axis would report how often the
# judge disputed an untouched verdict and publish the answer as citation-catching. A conformance flip
# is the mirror image. Keyed here rather than spelled at the call site, and taken from the acceptance
# builder's own rule (`offline_build`: `not swapped.citation_correct`, `not flipped.conformance_correct`)
# so the two paths cannot answer the same question differently.
DETECTION_AXIS: dict[str, str] = {SC_SWAP: "citation_correct", CONFORMANCE_FLIP: "conformance_correct"}

# ACT's gold outcome for a case that genuinely fails its rule.
_GOLD_FAILED = "failed"

STUB_DISCLAIMER = (
    "Every judge response in this record came from a DETERMINISTIC STUB, not from a model: the two "
    "booleans are read off the sha256 of the ask. Zero model calls were made and zero tokens were "
    "spent. So every rate, cell and kappa below describes the HARNESS — that the asks assemble from "
    "the frozen finding side, that each one parses, that the two collapses apply in their pinned "
    "order, and that the scorer records the unit its cells are on. None of them describes the judge, "
    "and none may be quoted as a baseline, a floor or a result."
)


@dataclass(frozen=True)
class AnchoredAsk:
    """One judge call a pass makes: which finding, which presentation of its draft."""

    act_testcase_id: str
    rule_name: str
    axe_rule: str
    finding_id: str
    mutation: str
    draft: DraftRow


def draft_row(record: dict[str, Any]) -> DraftRow:
    """One frozen draft record → the `DraftRow` the anchored prompt presents.

    The frozen record carries the drafted fields by name rather than a serialized `DraftRow`, so the row
    is rebuilt here. Only the two fields the judge is shown — the verdict and the cited criteria — carry
    into the prompt; `remediation` and `confidence` ride along because the mutations copy a whole row and
    because a row missing them would not be the row that was drafted.
    """
    return DraftRow(
        finding_id=record["finding_id"],
        conformance=Conformance(record["conformance"]),
        citations=[Citation(sc_id=sc) for sc in record["cited_sc_ids"]],
        remediation=record.get("remediation", ""),
        confidence=record["confidence"],
    )


def anchored_asks(artifact: dict[str, Any]) -> list[AnchoredAsk]:
    """Every ask one anchored pass makes over a frozen drafter run, in call order.

    The conformance flip is applied only where the natural verdict is already correct against ACT gold —
    the same gate the call budget was counted under. The SC swap applies everywhere, because swapping a
    citation for a decoy the finding's gold does not contain is wrong whatever the verdict was.
    """
    asks: list[AnchoredAsk] = []
    for case in artifact["cases"]:
        should_flag = case["expected"] == _GOLD_FAILED
        gold = tuple(case["gold_success_criteria"])
        for record in case["drafts"]:
            natural = draft_row(record)
            common = {
                "act_testcase_id": case["act_testcase_id"],
                "rule_name": case["rule_name"],
                "axe_rule": case["axe_rule"],
                "finding_id": record["finding_id"],
            }
            asks.append(AnchoredAsk(**common, mutation=NATURAL, draft=natural))
            asks.append(AnchoredAsk(**common, mutation=SC_SWAP, draft=sc_swap(natural, gold)))
            if is_flag(natural.conformance) == should_flag:
                asks.append(AnchoredAsk(**common, mutation=CONFORMANCE_FLIP, draft=conformance_flip(natural)))
    return asks


def run_pass(
    judge: Judge, prepared: dict[str, FindingInput], asks: Sequence[AnchoredAsk], run_id: str
) -> list[JudgeResult]:
    """Make every ask of one pass, in order, through the prepared finding side.

    `judge_prepared` re-renders nothing: the bytes frozen for the finding side are the bytes sent, and
    the only thing this loop varies is the presentation of the draft appended after them.
    """
    missing = sorted({a.finding_id for a in asks} - set(prepared))
    if missing:
        raise KeyError(
            f"{len(missing)} finding(s) have no frozen finding-side block — the run artifact and the "
            f"frozen input describe different scans. First few: {missing[:3]}"
        )
    return [judge.judge_prepared(prepared[a.finding_id], a.draft, run_id) for a in asks]


def _by_key(asks: Sequence[AnchoredAsk], results: Sequence[JudgeResult]) -> dict[tuple[str, str], JudgeResult]:
    return {(a.finding_id, a.mutation): r for a, r in zip(asks, results, strict=True)}


def natural_majority(asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]) -> dict[str, bool]:
    """`finding_id → the judge's routing decision`, majority across the configuration's passes.

    The anchored judge raises its hand when it grades the draft incorrect, so the decision recorded here
    is `conformance_correct` — a release — and the routing flag is its negation. A strict majority is
    required; the pinned implementation refuses a tie rather than letting pass order decide it.
    """
    naturals = [a for a in asks if a.mutation == NATURAL]
    per_pass = [
        [[_by_key(asks, results)[(a.finding_id, NATURAL)].conformance_correct] for a in naturals] for results in passes
    ]
    winners = majority_stream(per_pass)
    return {a.finding_id: bool(row[0]) for a, row in zip(naturals, winners, strict=True)}


def injected_results(
    asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]], mutation: str
) -> list[InjectedResult]:
    """The known-wrong drafts of one mutation and whether the judge caught each, majority across passes.

    ⚠️ Per mutated DRAFT, and it stays there whatever unit the confusion is on: a mutation is applied to
    a draft, not to a case, so collapsing these would need an aggregation rule for a quantity that is not
    a routing decision.

    ⚠️ Read on the mutation's OWN axis — see `DETECTION_AXIS`. The two mutations move different fields,
    and a detection rate taken off the other field is a well-formed number describing nothing.
    """
    if mutation not in DETECTION_AXIS:
        raise ValueError(f"{mutation!r} has no detection axis — only a mutated draft can be caught or missed")
    axis = DETECTION_AXIS[mutation]
    mutated = [a for a in asks if a.mutation == mutation]
    if not mutated:
        return []
    per_pass = [
        [[getattr(_by_key(asks, results)[(a.finding_id, mutation)], axis)] for a in mutated] for results in passes
    ]
    winners = majority_stream(per_pass)
    return [
        InjectedResult(rule_name=a.rule_name, caught=not bool(row[0])) for a, row in zip(mutated, winners, strict=True)
    ]


def judged_cases_from(artifact: dict[str, Any], releases: dict[str, bool]) -> list[JudgedCase]:
    """The judge's per-case stream: its per-finding decisions grouped onto the cases they were minted on.

    `act_correct` is the case-level predicate — flag-if-any over the case's own drafts against the gold
    outcome — taken from the artifact rather than from anything the judge said.
    """
    cases: list[JudgedCase] = []
    for case in artifact["cases"]:
        should_flag = case["expected"] == _GOLD_FAILED
        flagged = any(is_flag(Conformance(d["conformance"])) for d in case["drafts"])
        cases.append(
            JudgedCase(
                act_testcase_id=case["act_testcase_id"],
                rule_name=case["rule_name"],
                act_correct=flagged == should_flag,
                judge_passes=tuple(releases[d["finding_id"]] for d in case["drafts"]),
            )
        )
    return cases


def judged_findings_from(artifact: dict[str, Any], releases: dict[str, bool]) -> list[JudgedDraft]:
    """The per-finding stream, reported beside the test and never instead of it."""
    drafts: list[JudgedDraft] = []
    for case in artifact["cases"]:
        should_flag = case["expected"] == _GOLD_FAILED
        for d in case["drafts"]:
            drafts.append(
                JudgedDraft(
                    rule_name=case["rule_name"],
                    act_correct=is_flag(Conformance(d["conformance"])) == should_flag,
                    judge_pass=releases[d["finding_id"]],
                )
            )
    return drafts


@dataclass(frozen=True)
class AnchoredScoring:
    """One anchored configuration scored at both units, with the injected rates beside them."""

    per_case: JudgeScoring
    per_finding: JudgeScoring
    releases: dict[str, bool]


def score_anchored(
    artifact: dict[str, Any], asks: Sequence[AnchoredAsk], passes: Sequence[Sequence[JudgeResult]]
) -> AnchoredScoring:
    """Frozen drafts + the configuration's passes → the confusion at the pinned unit and beside it.

    The injected rates ride on the per-case scoring only to avoid computing them twice; they are per
    mutated draft in both, and `score_judge` never re-bases them.
    """
    releases = natural_majority(asks, passes)
    flips = injected_results(asks, passes, CONFORMANCE_FLIP)
    swaps = injected_results(asks, passes, SC_SWAP)
    return AnchoredScoring(
        per_case=score_judge(
            collapse_to_cases(judged_cases_from(artifact, releases)),
            unit=CONFUSION_UNIT_CASE,
            conformance_flip=flips,
            sc_swap=swaps,
            rationale_note=RATIONALE_NOTE,
        ),
        per_finding=score_judge(
            judged_findings_from(artifact, releases),
            unit=CONFUSION_UNIT_FINDING,
            conformance_flip=flips,
            sc_swap=swaps,
            rationale_note=RATIONALE_NOTE,
        ),
        releases=releases,
    )


class StubJudgeClient:
    """A deterministic non-model client: the verdict is read off the sha256 of the ask.

    It exists so the anchored path can be exercised end to end for nothing. `salt` makes one pass differ
    from the next, which is what gives the majority-across-passes collapse something to decide; without
    it three passes would be identical and the collapse would be exercised without ever being tested.

    It records every user prompt it was handed, for the same reason the offline fake does: what a caller
    actually sent is otherwise unobservable, and "the frozen finding side never left the file" is exactly
    the failure a dry run exists to rule out.
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
        citation_correct = bool(digest[0] & 1)
        conformance_correct = bool(digest[1] & 1)
        payload = {
            "citation_correct": citation_correct,
            "conformance_correct": conformance_correct,
            "rationale": "stubbed verdict — no inference happened",
        }
        return Completion(json.dumps(payload), LLMUsage())


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
    asks: Sequence[AnchoredAsk],
    passes: Sequence[Sequence[JudgeResult]],
    scoring: AnchoredScoring,
    judge_version: str,
    stub_calls: int,
) -> dict[str, Any]:
    """The dry receipt: what the path did, what it cost, and what none of it means."""
    per_mutation = {m: sum(1 for a in asks if a.mutation == m) for m in MUTATIONS}
    ask_digest = hashlib.sha256(
        "\x00".join(
            f"{a.finding_id}|{a.mutation}|{a.draft.conformance.value}|{','.join(c.sc_id for c in a.draft.citations)}"
            for a in asks
        ).encode()
    ).hexdigest()
    return {
        "artifact": "a dry run of the anchored judging path over stubbed responses",
        "version": 1,
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
            **per_mutation,
            "total": len(asks),
            "arithmetic": (
                f"{per_mutation[NATURAL]} natural + {per_mutation[SC_SWAP]} SC-swap + "
                f"{per_mutation[CONFORMANCE_FLIP]} conformance-flip = {len(asks)}"
            ),
        },
        "passes": len(passes),
        "asks_over_the_whole_configuration": len(asks) * len(passes),
        "ask_digest": ask_digest,
        "collapse": {
            "order": AGGREGATION_ORDER,
            "findings": scoring.per_finding.n,
            "cases": scoring.per_case.n,
            "findings_the_majority_decided": len(scoring.releases),
        },
        "confusion": {
            "per_case": _confusion_block(scoring.per_case),
            "per_finding": _confusion_block(scoring.per_finding),
        },
        "injected": {
            "conformance_flip_n": scoring.per_case.confusion.injected_conformance_flip.n,
            "sc_swap_n": scoring.per_case.confusion.injected_sc_swap.n,
            "denominator": "per mutated DRAFT at both units — a mutation is applied to a draft, never to a case",
        },
    }


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_anchored_dry_receipt.json"


def dry_run(passes: int = 3) -> dict[str, Any]:
    """Exercise the whole anchored path on stubbed responses and freeze the receipt. Zero model calls.

    ⚠️ An EVEN pass count is refused. The per-finding collapse is a strict majority, which an even number
    of passes cannot always produce; the pinned implementation raises on the tie rather than letting pass
    order settle it, so a two-pass configuration fails deep inside the collapse instead of at the door.
    Caught here because the dry run is where a harness defect is supposed to surface.
    """
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path
    from clearway.llm import LocalLLMClient

    if passes < 1 or passes % 2 == 0:
        raise ValueError(
            f"a configuration runs an ODD number of passes, not {passes}: the per-finding collapse is a "
            "strict majority across passes, and an even count can tie. A tie has no majority to take, "
            "and resolving it by pass order would put a coin flip inside the decision the paired test "
            "is scored on."
        )

    replay_path = run_path(CITATION_GROUNDING, 1)
    artifact = json.loads(replay_path.read_text())
    input_record = load_record()
    prepared = prepared_inputs(input_record)
    asks = anchored_asks(artifact)

    served = 0
    results: list[list[JudgeResult]] = []
    judge_version = ""
    for index in range(passes):
        client = StubJudgeClient(salt=f"pass-{index + 1}")
        judge = Judge(client, drafter_model=LocalLLMClient().model)
        judge_version = judge.judge_version
        results.append(run_pass(judge, prepared, asks, run_id=f"dry-pass-{index + 1}"))
        served += client.calls

    scoring = score_anchored(artifact, asks, results)
    return build_receipt(
        artifact=artifact,
        replay_path=replay_path,
        input_record=input_record,
        input_path=input_report_path(),
        asks=asks,
        passes=results,
        scoring=scoring,
        judge_version=judge_version,
        stub_calls=served,
    )


def main() -> None:
    receipt = dry_run()
    asks = receipt["asks_per_pass"]
    print(f"anchored dry run — {receipt['model_calls_spent']} model calls, {receipt['stub_responses_served']} stubbed")
    print(f"  asks per pass: {asks['arithmetic']}")
    print(f"  over {receipt['passes']} passes: {receipt['asks_over_the_whole_configuration']}")
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
