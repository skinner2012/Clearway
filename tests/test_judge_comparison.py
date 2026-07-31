"""The two comparisons, checked by re-deriving them rather than by re-running the builder.

A test that calls the module's own functions and compares the answers to the module's own record proves
determinism, which is a different claim from the numbers being right. So the load-bearing properties
here are re-derived from the frozen JSON by hand: the paired counts are rebuilt from the raw
`conformance_correct` booleans in both configurations' rows, the sign-test tail is re-derived by
enumerating coin flips, and every kappa is re-derived from its own 2x2 by the textbook formula.
"""

from __future__ import annotations

import json
from collections import Counter
from itertools import product
from pathlib import Path

import pytest

from clearway.eval.judge_comparison import (
    HISTORICAL_CONFORMANCE_FLIP_DETECTION,
    HISTORICAL_REAL_DETECTION,
    VERDICT_DIRECTIONAL,
    VERDICT_NO_MOVEMENT,
    VERDICT_SUPPORTED,
    VERDICT_UNCERTIFIABLE_AT_N,
    blind_passes,
    build_from_frozen,
    build_record,
    drafter_judge_kappa,
    judge_rater_flags,
    report_path,
    verdict_for,
)

_REPO = Path(__file__).resolve().parent.parent
_REPLAY = _REPO / "benchmark" / "runs" / "citation_grounding_run_1.json"
_ANCHORED = _REPO / "benchmark" / "reports" / "judge_anchored_baseline.json"
_BLIND = _REPO / "benchmark" / "reports" / "judge_blind_baseline.json"
_COMPARATOR = _REPO / "benchmark" / "reports" / "judge_drafter_comparator.json"
_PRE_REFERENT = _REPO / "benchmark" / "reports" / "drafter_kappa_baseline.json"

# The four-value verdicts that raise an alarm, restated here rather than imported: a test that borrows
# the collapse it is checking cannot notice the collapse changing underneath a frozen number.
_FLAGS = {"does_not_support", "partially_supports"}


def _artifact() -> dict:
    return json.loads(_REPLAY.read_text())


def _record() -> dict:
    return build_record(replay_path=_REPLAY, anchored_path=_ANCHORED, blind_path=_BLIND, comparator_path=_COMPARATOR)


def _majority_release(frozen: dict, *, natural_only: bool) -> dict[str, bool]:
    """`finding_id → released`, taken by hand off the frozen rows — the module's harness not involved."""
    votes: dict[str, list[bool]] = {}
    for block in frozen["pass_results"]:
        for row in block["results"]:
            if natural_only and row.get("mutation") != "natural":
                continue
            votes.setdefault(row["finding_id"], []).append(bool(row["conformance_correct"]))
    released = {}
    for finding_id, cast in votes.items():
        winner, count = Counter(cast).most_common(1)[0]
        assert count * 2 > len(cast), f"{finding_id} has no strict majority"
        released[finding_id] = winner
    return released


def _case_decisions(artifact: dict, released: dict[str, bool]) -> list[tuple[str, bool, bool]]:
    """Per case: its id, whether the configuration raised its hand, and whether the draft is act-wrong."""
    rows = []
    for case in artifact["cases"]:
        flagged = any(d["conformance"] in _FLAGS for d in case["drafts"])
        act_wrong = flagged != (case["expected"] == "failed")
        raised = any(not released[d["finding_id"]] for d in case["drafts"])
        rows.append((case["act_testcase_id"], raised, act_wrong))
    return rows


def _one_sided_tail(b: int, c: int) -> float:
    """P(X >= b) under Bin(b + c, 1/2), by enumerating every coin-flip sequence.

    Written out rather than imported so the record's p is checked against the definition of the test and
    not against the closed form that produced it.
    """
    n = b + c
    if n == 0:
        return 1.0
    outcomes = list(product((0, 1), repeat=n))
    return sum(1 for row in outcomes if sum(row) >= b) / len(outcomes)


def _kappa_from_pairs(left: list[str], right: list[str]) -> float:
    """Cohen's kappa over two aligned categorical streams, stated independently of the repo's helper."""
    n = len(left)
    observed = sum(1 for a, b in zip(left, right, strict=True) if a == b) / n
    categories = set(left) | set(right)
    chance = sum((left.count(k) / n) * (right.count(k) / n) for k in categories)
    return (observed - chance) / (1 - chance)


# ---------------------------------------------------------------------------------------------
# Comparison 1 — the paired routing test
# ---------------------------------------------------------------------------------------------


def test_the_paired_counts_re_derive_from_both_configurations_raw_rows() -> None:
    """The whole of Comparison 1 rebuilt by hand from the two frozen files, gold read off the artifact."""
    artifact = _artifact()
    anchored = _case_decisions(artifact, _majority_release(json.loads(_ANCHORED.read_text()), natural_only=True))
    blind = _case_decisions(artifact, _majority_release(json.loads(_BLIND.read_text()), natural_only=False))

    wins = losses = 0
    for (left_id, left_raised, wrong), (right_id, right_raised, right_wrong) in zip(anchored, blind, strict=True):
        assert (left_id, wrong) == (right_id, right_wrong), "the two configurations must walk the same cases"
        anchored_right = left_raised == wrong
        blind_right = right_raised == wrong
        wins += blind_right and not anchored_right
        losses += anchored_right and not blind_right

    block = _record()["comparison_1_judge_vs_judge"]["sign_test"]["per_case"]
    assert block["observations"] == len(anchored) == 40
    assert (block["blind_wins"], block["anchored_wins"]) == (wins, losses)
    assert block["discordant_pairs"] == wins + losses
    assert block["one_sided_p"] == pytest.approx(_one_sided_tail(wins, losses), abs=5e-5)


def test_the_bar_is_the_one_frozen_before_this_stage_ran_and_names_which_half_bound() -> None:
    """The floor bar is read out of the anchored record, never re-derived after seeing a result."""
    frozen = json.loads(_ANCHORED.read_text())["threshold"]
    test = _record()["comparison_1_judge_vs_judge"]["sign_test"]
    bar, n = test["threshold"], test["per_case"]["discordant_pairs"]

    assert bar["null_wins"] == frozen["null_wins"]
    assert bar["floor_bar"] == frozen["floor_bar"] == frozen["null_wins"] + 1
    row = next(r for r in frozen["required_wins_by_discordant_count"] if r["discordant_pairs"] == n)
    assert (bar["required_wins"], bar["statistical_bar"], bar["binding_bar"]) == (
        row["required_wins"],
        row["statistical_bar"],
        row["binding_bar"],
    )
    assert bar["binding_bar"], "a report must be able to say whether jitter, alpha or the count bound it"
    assert test["clears_the_bar"] is (
        bar["required_wins"] is not None and test["per_case"]["blind_wins"] >= bar["required_wins"]
    )


def test_the_verdict_follows_the_pre_committed_rule_in_its_fixed_order() -> None:
    """Unattainability is read first: a bar no win count could have met is not an effect that failed."""
    assert verdict_for(wins=5, losses=0, required_wins=5) == VERDICT_SUPPORTED
    assert verdict_for(wins=4, losses=1, required_wins=5) == VERDICT_DIRECTIONAL
    assert verdict_for(wins=3, losses=3, required_wins=6) == VERDICT_NO_MOVEMENT
    assert verdict_for(wins=2, losses=4, required_wins=6) == VERDICT_NO_MOVEMENT
    assert verdict_for(wins=4, losses=0, required_wins=None) == VERDICT_UNCERTIFIABLE_AT_N


def test_the_discordant_cases_are_named_and_reconcile_to_the_counts() -> None:
    """A pair of integers is taken on trust; the case ids are what makes the result auditable."""
    record = _record()
    rows = record["comparison_1_judge_vs_judge"]["discordant_cases"]
    block = record["comparison_1_judge_vs_judge"]["sign_test"]["per_case"]
    assert len(rows) == block["discordant_pairs"]
    assert sum(1 for r in rows if r["winner"] == "blind") == block["blind_wins"]
    assert sum(1 for r in rows if r["winner"] == "anchored") == block["anchored_wins"]

    known = {c["act_testcase_id"]: c for c in _artifact()["cases"]}
    for row in rows:
        case = known[row["act_testcase_id"]]
        assert row["axe_rule"] == case["axe_rule"]
        assert row["findings_on_the_case"] == len(case["drafts"])
        # A discordant pair is exactly a case the two configurations decide differently, and because gold
        # is fixed per case a flip of the decision is always a flip of correctness.
        assert row["anchored_raised_its_hand"] != row["blind_raised_its_hand"]


def test_the_per_finding_row_rides_along_and_says_it_does_not_govern() -> None:
    record = _record()["comparison_1_judge_vs_judge"]["sign_test"]
    beside = record["per_finding_does_not_govern"]
    assert beside["unit"] == "finding" and beside["observations"] == 54
    assert record["per_case"]["unit"] == "case" and record["per_case"]["observations"] == 40
    assert "cannot govern" in beside["note"]


def test_the_injected_guard_is_read_on_the_anchored_configuration_only() -> None:
    """Blind's mutations are inert, so its detection rates are algebra and are not eligible to trip it."""
    gap = _record()["comparison_1_judge_vs_judge"]["injected_versus_real"]
    assert gap["configuration"] == "anchored"

    blind = json.loads(_BLIND.read_text())["injected_versus_real"]
    assert blind["injected_conformance_flip_n"] == 0 and blind["injected_sc_swap_n"] == 0

    measured = gap["measured"]
    guard = gap["guard_against_the_historical_baseline"]
    assert guard["injected_detection_rose"] is (
        measured["injected_conformance_flip_detection"] > HISTORICAL_CONFORMANCE_FLIP_DETECTION
        or measured["injected_sc_swap_detection"] > 1.0
    )
    assert guard["real_detection_rose"] is (measured["real_detection_per_finding"] > HISTORICAL_REAL_DETECTION)
    assert guard["trips"] is (guard["injected_detection_rose"] and not guard["real_detection_rose"])
    # The gap that needs no cross-set comparison at all, re-derived from the two measured rates.
    within = gap["within_run_gap"]
    assert within["injected_over_real_per_finding_conformance_flip"] == pytest.approx(
        round(measured["injected_conformance_flip_detection"] / measured["real_detection_per_finding"], 2)
    )


# ---------------------------------------------------------------------------------------------
# Comparison 2 — the blind judge beside the drafter
# ---------------------------------------------------------------------------------------------


def test_every_raters_per_class_kappa_re_derives_from_its_own_two_by_two() -> None:
    """Both sides, from the cells the record prints, by the textbook formula rather than the repo's."""
    for row in _record()["comparison_2_judge_vs_drafter"]["group_b_rater_side_by_side"]["per_class"]:
        for side, units in (("judge", "judge_units"), ("drafter", "drafter_units")):
            cells = row[f"{side}_cells"]
            n = sum(cells.values())
            assert n == row[units], f"{row['axe_rule']}: the {side}'s 2x2 must exhaust its own denominator"
            observed = (cells["tp"] + cells["tn"]) / n
            chance = (
                (cells["tp"] + cells["fp"]) * (cells["tp"] + cells["fn"])
                + (cells["fn"] + cells["tn"]) * (cells["fp"] + cells["tn"])
            ) / n**2
            assert row[f"{side}_kappa"] == pytest.approx((observed - chance) / (1 - chance), abs=5e-5)
            assert row[f"{side}_raw_agreement"] == pytest.approx(observed, abs=5e-5)


def test_the_declared_denominator_puts_both_n_on_every_row_and_subtracts_neither() -> None:
    """The declaration this stage owes: the judge on its 40, the drafter on its 44, the gap named."""
    block = _record()["comparison_2_judge_vs_drafter"]["group_b_rater_side_by_side"]
    comparator = json.loads(_COMPARATOR.read_text())
    by_class = {row["axe_rule"]: row for row in comparator["per_class"]}

    assert "40" in block["denominator_declaration"] and "44" in block["denominator_declaration"]
    assert sum(r["judge_units"] for r in block["per_class"]) == comparator["totals"]["judge_visible_units"] == 40
    assert sum(r["drafter_units"] for r in block["per_class"]) == comparator["totals"]["drafter_units"] == 44
    for row in block["per_class"]:
        assert (
            row["judge_units"] + row["unit_gap"] == row["drafter_units"] == by_class[row["axe_rule"]]["drafter_units"]
        )
        assert row["judge_units"] == by_class[row["axe_rule"]]["judge_visible_units"]


def test_the_drafter_side_is_the_recomputed_comparator_and_not_the_pre_referent_baseline() -> None:
    """Reading the frozen baseline instead would get *which of them is right* wrong on two classes."""
    rows = _record()["comparison_2_judge_vs_drafter"]["group_b_rater_side_by_side"]["per_class"]
    comparator = {r["axe_rule"]: r["kappa"] for r in json.loads(_COMPARATOR.read_text())["per_class"]}
    stale = {c["axe_rule"]: round(c["kappa"], 4) for c in json.loads(_PRE_REFERENT.read_text())["classes"]}

    for row in rows:
        assert row["drafter_kappa"] == comparator[row["axe_rule"]]
    moved = [r["axe_rule"] for r in rows if r["drafter_kappa"] != stale[r["axe_rule"]]]
    assert moved, "if nothing moved, the pre-referent baseline would be a harmless substitution — it is not"
    # And the substitution would flip the verdict this table exists to give, not merely shift a decimal.
    flipped = [
        r["axe_rule"]
        for r in rows
        if (r["judge_kappa"] > r["drafter_kappa"]) != (r["judge_kappa"] > stale[r["axe_rule"]])
    ]
    assert flipped, "the stale baseline must change *which rater is more often right* somewhere"


def test_the_judges_rater_stream_is_not_its_routing_stream() -> None:
    """Two quantities out of one configuration: *the content fails* against *the draft is right*.

    They are not the same collapse — the routing decision is raw four-value equality and the rater stream
    runs through FLAG/CLEAN — so a `partially_supports` draft can agree on one axis and differ on the
    other. Asserted on the frozen answers rather than assumed, because conflating the two would score the
    judge against gold on a stream that is really a measure of the drafter.
    """
    from clearway.eval.judge_blind import blind_asks, releases

    artifact = _artifact()
    passes = blind_passes(artifact, json.loads(_BLIND.read_text()))
    asks = blind_asks(artifact)
    rater = judge_rater_flags(artifact, passes)
    routing = releases(asks, passes)
    drafted = {d["finding_id"]: d["conformance"] for case in artifact["cases"] for d in case["drafts"]}

    divergent = [
        ask.finding_id
        for ask in asks
        if (rater[ask.finding_id] == (drafted[ask.finding_id] in _FLAGS)) != routing[ask.finding_id]
    ]
    assert divergent, "the two streams must be demonstrably different quantities on this data"


def test_the_drafter_judge_kappa_is_on_the_four_value_scale_and_re_derives() -> None:
    """Descriptive, per finding, and on the scale code compares the two answers on."""
    artifact = _artifact()
    passes = blind_passes(artifact, json.loads(_BLIND.read_text()))
    block = drafter_judge_kappa(artifact, passes)

    judge = [v for value, count in block["judge_verdict_counts"].items() for v in [value] * count]
    draft = [v for value, count in block["drafted_verdict_counts"].items() for v in [value] * count]
    assert len(judge) == len(draft) == block["observations"] == 54
    assert block["unit"] == "finding"
    # Raw four-value, not the FLAG/CLEAN collapse: the drafter's `partially_supports` rows survive as
    # their own category, which is what makes this the chance-corrected form of the compared rule.
    assert "partially_supports" in block["drafted_verdict_counts"]
    assert block["drafted_verdict_counts"]["partially_supports"] > 0

    # κ re-derived from the paired stream itself rather than from the marginals above.
    from clearway.eval.judge_blind import blind_asks, conformance_majorities

    asks = blind_asks(artifact)
    verdicts = conformance_majorities(asks, passes)
    drafted = {d["finding_id"]: d["conformance"] for case in artifact["cases"] for d in case["drafts"]}
    left = [v.value for a in asks if (v := verdicts[a.finding_id]) is not None]
    right = [drafted[a.finding_id] for a in asks]
    assert block["kappa"] == pytest.approx(_kappa_from_pairs(left, right), abs=5e-5)
    assert block["raw_agreement"] == pytest.approx(
        sum(1 for a, b in zip(left, right, strict=True) if a == b) / len(left), abs=5e-5
    )
    assert "NEVER A TARGET" in block["descriptive_only"]


def test_the_disagreement_rate_is_lifted_from_both_records_and_never_averaged() -> None:
    """The primary deliverable, both configurations, each naming the event it counts."""
    block = _record()["comparison_2_judge_vs_drafter"]["group_a_disagreement"]
    assert block["unit"] == "finding"
    for side, path in (("anchored", _ANCHORED), ("blind", _BLIND)):
        frozen = json.loads(path.read_text())["disagreement"]
        assert block[side]["overall"] == frozen["overall"]
        assert block[side]["event"] == frozen["event"]
        assert block[side]["overall"]["distinct_cases_touched"] > 0, "a rate alone hides the workload"
    assert block["anchored"]["event"] != block["blind"]["event"], "the two count different events"
    assert "never be averaged" in block["never_averaged"]
    endpoints = block["degenerate_endpoints"]
    assert endpoints["blind_count"] / endpoints["findings"] == pytest.approx(endpoints["blind_rate"], abs=5e-5)
    assert endpoints["anchored_count"] / endpoints["findings"] == pytest.approx(endpoints["anchored_rate"], abs=5e-5)


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------


def test_the_record_carries_no_clock_and_rebuilds_byte_identical() -> None:
    first, second = _record(), _record()
    assert first == second
    assert first["created_at"] == _artifact()["created_at"]
    assert first["model_calls_spent"] == 0


def test_rows_that_are_not_these_asks_are_refused_rather_than_re_aligned(tmp_path: Path) -> None:
    """A record that no longer describes these drafts must fail to load, not compare something else."""
    from clearway.eval.judge_transport import LedgerMismatch

    frozen = json.loads(_BLIND.read_text())
    frozen["pass_results"][0]["results"] = frozen["pass_results"][0]["results"][:-1]
    path = tmp_path / "blind.json"
    path.write_text(json.dumps(frozen))
    with pytest.raises(LedgerMismatch):
        build_record(replay_path=_REPLAY, anchored_path=_ANCHORED, blind_path=path, comparator_path=_COMPARATOR)


def test_the_two_comparisons_are_named_and_kept_apart() -> None:
    record = build_from_frozen()
    assert set(record) >= {"comparison_1_judge_vs_judge", "comparison_2_judge_vs_drafter"}
    assert "COMPARISON 1" in record["comparison_1_judge_vs_judge"]["asks"]
    assert "COMPARISON 2" in record["comparison_2_judge_vs_drafter"]["asks"]
    # Every source is read-only: the four files this record is built from are untouched by building it.
    before = {p: p.read_bytes() for p in (_REPLAY, _ANCHORED, _BLIND, _COMPARATOR)}
    build_from_frozen()
    assert {p: p.read_bytes() for p in before} == before


def test_the_committed_record_is_the_one_a_rebuild_produces() -> None:
    """Deterministic given its four sources, so the freeze is pinned by comparison rather than by a
    digest computed from the file's own bytes — which any edit that recomputes it would pass."""
    assert json.loads(report_path().read_text()) == build_from_frozen()
