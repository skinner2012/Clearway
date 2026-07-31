"""The blind judge measured for real: its routing decision, its disagreement rate, and its own floor.

The dry receipt beside `judge_blind` proved the *path* on stubbed answers. This one spends the calls.
It changes nothing about the loop — the asks, the code-side comparison, the two collapses and the
scorer are `judge_blind`'s, unchanged — and adds only what a live run needs and a stub cannot supply:
a ledger so a restart does not re-spend, usage captured below the judge, the run-to-run variance of a
fixed configuration, and the one contrast this milestone was built to make.

**⚠️ The contrast that exists here and nowhere earlier.** T3b measured the anchored configuration and
could not produce the anchored ↔ blind difference a paired comparison consumes: only one configuration
had judge output. What it reported instead was a confounded proxy — a run against earlier passes where
the prompt and the drafts moved together. Here both configurations have answered the **same drafts**
through the **same frozen finding side**, so the difference stream has one variable in it, and its
within-case correlation is the number the pinned unit's cost is a function of. **A materially negative
value means the case collapse is cancelling differences against each other and costing power rather
than buying honesty**, and the record says so in that case rather than burying it.

**⚠️ It reads the anchored side; it never re-runs it.** `judge_anchored_baseline.json` is the frozen
record of 441 paid calls. This module replays its rows through the anchored harness' own functions —
which refuse outright if the rows are not those asks — and writes nothing back to it.

**⚠️ Do not run the test suite while this is in flight.** Several test files call the real model; a
suite run during a live measurement shares cache slots with it and contaminates it. That has already
cost this project a re-run once.

**Two majorities, taken independently.** The routing decision is the majority of the derived
`conformance_correct` across passes. The judge's own four-valued verdict has its own majority, which
can fail to exist and is reported as undecided rather than resolved by pass order — see
`judge_blind.conformance_majorities`.

Invoke: `uv run --env-file .env python -m clearway.eval.judge_blind_baseline`

**To rebuild the frozen record after a change to how something is COMPUTED, add `--rederive`** — it
re-runs the whole builder over the answers already in the file and needs no key, no network and no
call. Every number in the record is a function of those answers; only when the *asks* move does a paid
re-run become the honest answer, and the ledger's digest check is what refuses to hide that.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clearway.eval.judge_anchored import require_odd_passes
from clearway.eval.judge_anchored_baseline import (
    NOT_A_MEASUREMENT_OF_THE_DRAFTER,
    case_act_wrong,
    finding_act_wrong,
    one_way_wins,
    scoring_block,
    spread,
)
from clearway.eval.judge_anchored_baseline import report_path as anchored_report_path
from clearway.eval.judge_blind import (
    CONFIGURATION,
    CONFIGURATION_MEANING,
    NO_MUTATIONS_HERE,
    BlindAsk,
    BlindOutcome,
    anchored_majority_releases,
    between_configuration_difference,
    blind_asks,
    disagreement_profile,
    distinct_ask_profile,
    paid_call_budget,
    run_pass,
    score_blind,
)
from clearway.eval.judge_finding_input import load_record, prepared_inputs
from clearway.eval.judge_finding_input import report_path as input_report_path
from clearway.eval.judge_observation_unit import (
    AGGREGATION_ORDER,
    OBSERVATION_UNIT,
    null_discordance,
    null_routing_sign_test,
    unanimity,
)
from clearway.eval.judge_transport import (
    PAID_CALLS,
    REPLAYED_CALLS,
    CallLedger,
    LedgerMismatch,
    RecordingJudgeClient,
    cost_block,
    ledger_block,
)
from clearway.judge import BlindAnswer, BlindJudge, citations_agree, conformance_agrees
from clearway.llm import LLMClient
from clearway.schemas.models import Conformance

# ⚠️ Stated in the record as well as here, because the reader who needs it is the one about to start a
# long run in another terminal.
NO_SUITE_WHILE_THIS_RUNS = (
    "⚠️ DO NOT RUN THE TEST SUITE WHILE THIS MEASUREMENT IS IN FLIGHT. Several test files call the "
    "real model, so a suite run during a live pass shares provider cache slots with the measurement "
    "and contaminates it — a cost this project has already paid once. Wait for the run to finish, or "
    "deselect the real-model tests."
)

# What a frozen record is allowed to move between two builds without that reading as an edit.
_VOLATILE_KEYS = ("created_at", "wall_clock_seconds", "reproducible_digest", "ledger")


def record_digest(record: dict[str, Any]) -> str:
    """sha256 over the record minus its own digest and the fields a re-run cannot reproduce.

    ⚠️ Everything scheduled to move sits OUTSIDE it — the clock, the elapsed time, and the ledger block,
    which describes the invocation that bought the answers rather than the one that last wrote the file.
    A digest that moved for a reason outside the record could not answer *did this record change?*
    """
    stable = {k: v for k, v in record.items() if k not in _VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------
# Answers as rows: what gets frozen, and what the record is re-derivable from
# ---------------------------------------------------------------------------------------------


def answer_rows(asks: Sequence[BlindAsk], outcomes: Sequence[BlindOutcome]) -> list[dict[str, Any]]:
    """One row per ask: which ask it was, **what the judge answered**, and what code concluded.

    The judge's own conformance and cited SC are the mandatory half — the direction of a disagreement
    cannot be recovered without them, and they exist nowhere else once the process ends. The two derived
    booleans ride along beside them even though they are recomputable, so a reader can see the
    comparison without running it; `outcomes_from_rows` re-derives them anyway and refuses a row where
    the stored pair and the recomputed pair disagree.

    The rationale rides along too. It is never compared and never scored, but it is the only qualitative
    trace that the model reasoned rather than stamped.
    """
    return [
        {
            "finding_id": ask.finding_id,
            "act_testcase_id": ask.act_testcase_id,
            "axe_rule": ask.axe_rule,
            "judge_conformance": outcome.answer.conformance.value,
            "judge_cited_sc_ids": list(outcome.answer.cited_sc_ids),
            "citation_correct": outcome.result.citation_correct,
            "conformance_correct": outcome.result.conformance_correct,
            "verdict": outcome.result.verdict.value,
            "rationale": outcome.answer.rationale,
        }
        for ask, outcome in zip(asks, outcomes, strict=True)
    ]


def outcomes_from_rows(
    asks: Sequence[BlindAsk], rows: Sequence[dict[str, Any]], *, judge_model: str, judge_version: str, run_id: str
) -> list[BlindOutcome]:
    """Frozen rows → the outcomes the scorer consumes, refused if they are not these asks.

    Two refusals, and both are the point. The rows must be *these* asks in *this* order, or a
    re-derivation would silently re-align itself to a different ask and reproduce the record while
    describing something else. And the stored booleans must equal the ones re-derived from the stored
    answer: they are the whole comparison, so a record whose conclusion no longer follows from its own
    evidence must not load at all.
    """
    from clearway.judge.judge import verdict_from
    from clearway.schemas.models import JudgeResult

    if len(rows) != len(asks):
        raise LedgerMismatch(f"{len(rows)} frozen answer rows against {len(asks)} asks — different runs")
    out: list[BlindOutcome] = []
    for ask, row in zip(asks, rows, strict=True):
        if row["finding_id"] != ask.finding_id:
            raise LedgerMismatch(
                f"frozen row {row['finding_id']} does not match ask {ask.finding_id} — the rows are not "
                "this configuration's asks"
            )
        answer = BlindAnswer(
            finding_id=ask.finding_id,
            conformance=Conformance(row["judge_conformance"]),
            cited_sc_ids=tuple(row["judge_cited_sc_ids"]),
            rationale=row["rationale"],
        )
        citation_correct = citations_agree(answer, ask.draft)
        conformance_correct = conformance_agrees(answer, ask.draft)
        if (citation_correct, conformance_correct) != (row["citation_correct"], row["conformance_correct"]):
            raise LedgerMismatch(
                f"row {ask.finding_id} stores ({row['citation_correct']}, {row['conformance_correct']}) "
                f"and its own answer re-derives ({citation_correct}, {conformance_correct}) — the "
                "record's conclusion no longer follows from its evidence"
            )
        out.append(
            BlindOutcome(
                answer=answer,
                result=JudgeResult(
                    finding_id=ask.finding_id,
                    run_id=run_id,
                    judge_model=judge_model,
                    judge_version=judge_version,
                    verdict=verdict_from(citation_correct, conformance_correct),
                    citation_correct=citation_correct,
                    conformance_correct=conformance_correct,
                    rationale=answer.rationale,
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# The noise floor
# ---------------------------------------------------------------------------------------------


def routing_flag_streams(
    artifact: dict[str, Any], asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]
) -> list[list[list[bool]]]:
    """`[pass][case][finding]` — did the judge raise its hand, per pass, in the artifact's case order.

    One pass at a time and no collapse yet: the floor is measured between passes, so the majority the
    routing decision is normally taken on would erase exactly the movement being counted.
    """
    streams: list[list[list[bool]]] = []
    for outcomes in passes:
        by_finding = {asks[i].finding_id: outcomes[i] for i in range(len(asks))}
        streams.append(
            [
                [not by_finding[d["finding_id"]].result.conformance_correct for d in case["drafts"]]
                for case in artifact["cases"]
            ]
        )
    return streams


def noise_floor_block(
    artifact: dict[str, Any], asks: Sequence[BlindAsk], passes: Sequence[Sequence[BlindOutcome]]
) -> dict[str, Any]:
    """What this configuration does to itself when nothing changes — read against T3b's floor.

    The same three things the anchored floor reports, through the same functions: the spread of each
    headline figure across the passes, the pass-to-pass movement of the routing decision at both units,
    and the largest one-way movement. **⚠️ Here it is a floor to READ the comparison against, not one to
    set a threshold from** — the threshold's floor bar was fixed at T3b from the anchored
    configuration's own pass-pairs, before this configuration ran, and it is not re-derived here.
    """
    per_pass = [score_blind(artifact, asks, [outcomes]) for outcomes in passes]
    flag_streams = routing_flag_streams(artifact, asks, passes)
    finding_streams = [[[flag] for case in stream for flag in case] for stream in flag_streams]

    case_rows = null_routing_sign_test(flag_streams, case_act_wrong(artifact))
    finding_rows = null_routing_sign_test(finding_streams, finding_act_wrong(artifact))
    return {
        "passes": len(passes),
        "per_pass": {
            "per_case": [scoring_block(s.per_case) for s in per_pass],
            "per_finding": [scoring_block(s.per_finding) for s in per_pass],
        },
        "spread": {
            unit: {
                metric: spread([float(block[metric]) for block in blocks])
                for metric in ("kappa", "miss_rate", "false_alarm_rate")
            }
            for unit, blocks in (
                ("per_case", [scoring_block(s.per_case) for s in per_pass]),
                ("per_finding", [scoring_block(s.per_finding) for s in per_pass]),
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
                "⚠️ This configuration's own jitter, reported so a difference between the two "
                "configurations can be read against it. It is NOT the threshold's floor bar: that was "
                "fixed at T3b from the anchored pass-pairs before this ran, and re-deriving it here "
                "would be choosing a bar after seeing a result. A kappa SD is not stability either — "
                "the discordant COUNT is what moves the routing decisions underneath it."
            ),
        },
    }


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------


def build_record(
    *,
    artifact: dict[str, Any],
    replay_path: Path,
    input_record: dict[str, Any],
    pass_rows: Sequence[Sequence[dict[str, Any]]],
    transport: Sequence[dict[str, Any]],
    judge_model: str,
    judge_version: str,
    anchored_frozen: dict[str, Any],
    created_at: str,
    wall_clock_seconds: float,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the record. **Pure given the frozen answer rows**, which is what makes it auditable.

    Nothing here calls a model, reads a clock or reaches the network: every computed field is a function
    of `pass_rows`, `transport` and the frozen artifacts, so the freeze test re-derives the whole record
    from the file's own rows rather than checking a digest against itself.
    """
    asks = blind_asks(artifact)
    prepared = prepared_inputs(input_record)
    passes = [
        outcomes_from_rows(
            asks, rows, judge_model=judge_model, judge_version=judge_version, run_id=f"blind-pass-{index + 1}"
        )
        for index, rows in enumerate(pass_rows)
    ]
    scoring = score_blind(artifact, asks, passes)
    anchored = anchored_majority_releases(artifact, anchored_frozen)

    record: dict[str, Any] = {
        "artifact": "the blind judge's own answers over the frozen drafts, and its own noise floor",
        "version": 1,
        "configuration": CONFIGURATION,
        "configuration_meaning": CONFIGURATION_MEANING,
        "created_at": created_at,
        "wall_clock_seconds": round(wall_clock_seconds, 1),
        "judge_model": judge_model,
        "judge_version": judge_version,
        "not_a_measurement_of_the_drafter": NOT_A_MEASUREMENT_OF_THE_DRAFTER,
        "no_suite_while_this_runs": NO_SUITE_WHILE_THIS_RUNS,
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
            "anchored_configuration": {
                "path": anchored_report_path().name,
                "judge_version": anchored_frozen["judge_version"],
                "read_only": (
                    "read and replayed through the anchored harness' own functions, which refuse if the "
                    "rows are not those asks. Nothing here re-runs, re-judges or rewrites it."
                ),
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
        "pre_run_budget": {
            **paid_call_budget(asks=len(asks), passes=len(passes)),
            "superseded_by": (
                "`cost.transport_calls`, which is the EXACT count this run put through the client seam, "
                "retries included. The floor and ceiling here are what was knowable before the run; the "
                "exact figure is what it did. The exact figure is itself a floor for the SPEND, because "
                "a retry made inside the provider client sits below this seam."
            ),
        },
        "aggregation_order": AGGREGATION_ORDER,
        "observation_unit": OBSERVATION_UNIT,
        "distinct_asks": distinct_ask_profile(asks, prepared),
        "confusion": {
            "per_case": scoring_block(scoring.per_case),
            "per_finding": scoring_block(scoring.per_finding),
        },
        "injected_versus_real": {
            "not_measured_here": NO_MUTATIONS_HERE,
            "injected_conformance_flip_n": scoring.per_case.confusion.injected_conformance_flip.n,
            "injected_sc_swap_n": scoring.per_case.confusion.injected_sc_swap.n,
        },
        "disagreement": disagreement_profile(artifact, asks, passes, prepared),
        "noise_floor": noise_floor_block(artifact, asks, passes),
        "between_configuration_difference": between_configuration_difference(artifact, asks, passes, anchored),
        "cost": cost_block(transport, asks_made=len(asks) * len(passes)),
        "ledger": ledger,
        "pass_results": [
            {"pass": index + 1, "run_id": f"blind-pass-{index + 1}", "results": list(rows)}
            for index, rows in enumerate(pass_rows)
        ],
        "transport": list(transport),
    }
    return {**record, "reproducible_digest": record_digest(record)}


def report_path() -> Path:
    """Where a REAL blind run is frozen.

    ⚠️ Nothing writes this file until the calls are spent. A stubbed record must never occupy it: the
    two are indistinguishable on shape, and only one of them is a measurement.
    """
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_blind_baseline.json"


def ledger_path() -> Path:
    """The append-only call ledger — transient working state, deliberately outside `reports/`."""
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR.parent / "judge_blind_baseline.partial.jsonl"


def live_run(
    passes: int = 3,
    *,
    client_factory: Callable[[], LLMClient] | None = None,
    ledger_file: Path | None = None,
) -> dict[str, Any]:
    """Run the blind configuration against a judge and freeze the record.

    `client_factory` and `ledger_file` exist so **this exact code path** can be exercised end to end
    with no cloud client and no real ledger. A runner proven only in its dry shape is a runner whose
    single-run assumptions — the ledger's ordering, the resume check, the usage capture, the record
    builder's inputs — were never tested; that failure mode has already cost this repo a re-run. The
    defaults are the paid ones, so a caller that passes nothing spends money.

    ⚠️ An EVEN pass count is refused at the door: the per-finding collapse is a strict majority.
    """
    import time

    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path
    from clearway.llm import CloudLLMClient, LocalLLMClient

    require_odd_passes(passes)
    factory: Callable[[], LLMClient] = client_factory or CloudLLMClient

    replay_path = run_path(CITATION_GROUNDING, 1)
    artifact = json.loads(replay_path.read_text())
    input_record = load_record()
    prepared = prepared_inputs(input_record)
    asks = blind_asks(artifact)
    anchored_frozen = json.loads(anchored_report_path().read_text())

    ledger = CallLedger.open(ledger_file or ledger_path())
    drafter_model = LocalLLMClient().model
    started = time.perf_counter()
    pass_rows: list[list[dict[str, Any]]] = []
    spent = replayed = 0
    judge_model = judge_version = ""
    for index in range(passes):
        client = RecordingJudgeClient(factory(), ledger, index + 1)
        judge = BlindJudge(client, drafter_model=drafter_model)
        judge_model, judge_version = client.model, judge.judge_version
        print(f"pass {index + 1}/{passes}: {len(asks)} asks", flush=True)
        outcomes = run_pass(judge, prepared, asks, run_id=f"blind-pass-{index + 1}")
        pass_rows.append(answer_rows(asks, outcomes))
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
        anchored_frozen=anchored_frozen,
        created_at=datetime.now(UTC).isoformat(),
        wall_clock_seconds=time.perf_counter() - started,
        ledger=ledger_block(path=ledger_file or ledger_path(), paid=spent, replayed=replayed),
    )


def rederive_frozen_record() -> dict[str, Any]:
    """Rebuild the frozen record from the answers already in it — no model, no network, no clock.

    Every derived field is a function of the judge's frozen answers, so a change to how something is
    *computed* must never be a reason to buy them again. Three facts are not derivable and are read back
    from the file rather than re-observed: when the calls were made, how long they took, and how many of
    them were paid for — re-observing them would date a re-computation as if it were the measurement.
    **⚠️ The last is read as two integers and its block reassembled**, never copied across.
    """
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path

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
        anchored_frozen=json.loads(anchored_report_path().read_text()),
        created_at=frozen["created_at"],
        wall_clock_seconds=frozen["wall_clock_seconds"],
        ledger=ledger_block(
            path=ledger_path(), paid=frozen["ledger"][PAID_CALLS], replayed=frozen["ledger"][REPLAYED_CALLS]
        ),
    )


def main() -> None:
    import sys

    rederive = "--rederive" in sys.argv[1:]
    if not rederive:
        print(NO_SUITE_WHILE_THIS_RUNS, flush=True)
    record = rederive_frozen_record() if rederive else live_run()
    if rederive:
        print("re-derived from the frozen answers — no call was made")
    print(f"\nblind baseline — {record['cost']['transport_calls']} transport calls (exact at the seam)")
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
    contrast = record["between_configuration_difference"]
    print(
        f"  anchored ↔ blind: {contrast['findings_whose_routing_decision_differs']} findings, "
        f"{contrast['cases_whose_collapsed_decision_differs']} cases, icc {contrast['icc']}"
    )
    print(f"  cost usd: {record['cost']['cost_usd']}")

    path = report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
