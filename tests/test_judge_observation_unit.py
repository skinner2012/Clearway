"""The judge's observation structure and the unit its paired comparison is pinned to.

Three properties carry the weight. First, a case that mints nothing is a manifest ROW and not a
cluster, so the structure is refused rather than flattened when a zero is handed in. Second, the
judge-side correlation is only usable as a prior if it was measured over the same clusters the pin
governs, so the cluster identity is asserted against the replay pass rather than assumed. Third, the
decision itself is arithmetic — a per-finding unit is worth its dependence only where its effective n
exceeds the cluster count — so the effective-n comparison is pinned as a number, and an edit that
flips it fails here instead of quietly changing what the test is scored on.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from clearway.eval.judge_observation_unit import (
    AGGREGATION_ORDER,
    DISAGREEMENT_RATE_UNIT,
    OBSERVATION_UNIT,
    WITHIN_CASE_AGGREGATION,
    Clustering,
    DegenerateClustering,
    aggregation_divergence,
    anova_icc,
    assert_distinct_case_bytes,
    assert_same_clusters,
    build_record,
    drafter_streams,
    judge_routing_streams,
    majority_stream,
    manifest_rows,
    minting_cases,
    unanimity,
    within_cluster_agreement,
)

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"
_REPLAY = _RUNS / "citation_grounding_run_1.json"
_JUDGED = [_RUNS / f"run_{n}.json" for n in (1, 2, 3)]


def _load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text()))


# --- the pin ------------------------------------------------------------------------------------


def test_the_pinned_unit_is_the_case_and_the_rate_unit_is_not() -> None:
    """A deliberate tripwire. Two units live in this comparison and they answer different questions;
    a later stage that moved either silently would produce a figure nobody can interpret."""
    assert OBSERVATION_UNIT == "case"
    assert WITHIN_CASE_AGGREGATION == "flag-if-any"
    assert DISAGREEMENT_RATE_UNIT == "finding"
    assert AGGREGATION_ORDER.index("majority") < AGGREGATION_ORDER.index("flag-if-any"), (
        "the repeat-pass collapse runs first, per finding; reversing the order answers a different "
        "question and can land on a different case decision"
    )


# --- cluster structure --------------------------------------------------------------------------


def test_a_case_that_mints_nothing_is_refused_as_a_cluster() -> None:
    """The observations are the minted findings. Admitting a non-minting row divides by a bigger
    denominator and reports the structure as flatter than it is."""
    with pytest.raises(DegenerateClustering, match="manifest ROW"):
        Clustering((1, 0, 2))


def test_a_clustering_over_nothing_is_refused() -> None:
    with pytest.raises(DegenerateClustering, match="not a structure"):
        Clustering(())


def test_kish_mean_size_weights_the_larger_clusters() -> None:
    """`Σm²/Σm`, not the plain mean — which is why the design effect is driven by the big clusters."""
    clustering = Clustering((1, 1, 4))
    assert clustering.observations == 6
    assert clustering.clusters == 3
    assert clustering.mean_size == 2.0
    assert clustering.kish_mean_size == pytest.approx(18 / 6)


def test_design_effect_is_one_at_independence_and_the_kish_mean_at_total_agreement() -> None:
    clustering = Clustering((1, 1, 4))
    assert clustering.design_effect(0.0) == 1.0
    assert clustering.effective_n(0.0) == 6
    assert clustering.design_effect(1.0) == pytest.approx(clustering.kish_mean_size)
    assert clustering.effective_n(1.0) == pytest.approx(2.0)


def test_singleton_and_multi_counts_split_the_observations() -> None:
    clustering = Clustering((1, 1, 1, 2, 3))
    assert (clustering.singletons, clustering.multi_clusters) == (3, 2)
    assert clustering.observations_in_multi_clusters == 5
    assert clustering.histogram == {1: 3, 2: 1, 3: 1}


# --- within-cluster agreement -------------------------------------------------------------------


def test_within_cluster_agreement_reads_a_hand_countable_stream() -> None:
    """Four clusters of two, balanced 4 True / 4 False: chance agreement is 0.5, and two of the four
    within-cluster pairs agree — so an observed 0.5 corrects to an ICC of exactly zero."""
    agreement = within_cluster_agreement([[True, True], [False, False], [True, False], [False, True]])
    assert (agreement.pairs, agreement.agreeing) == (4, 2)
    assert agreement.chance == pytest.approx(0.5)
    assert agreement.observed == pytest.approx(0.5)
    assert agreement.icc == pytest.approx(0.0)
    assert (agreement.multi_clusters, agreement.homogeneous_clusters) == (4, 2)


def test_the_chance_term_follows_the_marginals_not_the_cluster_count() -> None:
    """Three True to one False over four observations gives chance (3² + 1²)/4² = 0.625, so the same
    one-of-two agreeing pairs now reads as anti-clustering rather than as independence."""
    agreement = within_cluster_agreement([[True, True], [False, True]])
    assert (agreement.pairs, agreement.agreeing) == (2, 1)
    assert agreement.chance == pytest.approx(0.625)
    assert agreement.icc == pytest.approx(-1 / 3)


def test_perfect_within_cluster_agreement_is_an_icc_of_one() -> None:
    agreement = within_cluster_agreement([[True, True], [False, False]])
    assert agreement.icc == pytest.approx(1.0)
    assert agreement.homogeneous_clusters == 2


def test_disagreeing_more_than_chance_is_a_negative_icc() -> None:
    agreement = within_cluster_agreement([[True, False], [True, False]])
    assert agreement.icc < 0.0


def test_singletons_alone_have_no_correlation_to_report() -> None:
    with pytest.raises(DegenerateClustering, match="not zero"):
        within_cluster_agreement([[True], [False], [True]])


def test_a_constant_stream_is_refused_rather_than_reported_as_independent() -> None:
    with pytest.raises(DegenerateClustering, match="undefined"):
        within_cluster_agreement([[True, True], [True, True]])


def test_no_observations_at_all_is_refused() -> None:
    with pytest.raises(DegenerateClustering, match="no observations"):
        within_cluster_agreement([])


# --- the replay pass's real structure -----------------------------------------------------------


def test_the_replay_pass_carries_more_manifest_rows_than_clusters() -> None:
    """The ticket's counting trap, as a number: dividing by manifest rows understates the mean
    cluster size, so the two denominators are both recorded and the gap is strictly positive."""
    artifact = _load(_REPLAY)
    cases = minting_cases(artifact)
    rows = manifest_rows(artifact)
    observations = sum(len(c.drafts) for c in cases)
    assert (observations, len(cases), rows) == (54, 40, 44)
    assert observations / rows < observations / len(cases)
    assert all(c.drafts for c in cases), "a non-minting case must never reach the clustering"


def test_the_clustering_lives_in_two_of_the_four_classes() -> None:
    """`document-title` and `empty-heading` are all singletons, so the unit cannot move a number on
    them — which is what keeps a per-class table from reading as a uniform tax."""
    record = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    by_rule = {row["axe_rule"]: row for row in record["structure"]["per_class"]}
    assert by_rule["document-title"]["unit_choice_changes_this_class"] is False
    assert by_rule["empty-heading"]["unit_choice_changes_this_class"] is False
    assert by_rule["label"]["multi_observation_clusters"] == 2
    assert by_rule["link-name"]["multi_observation_clusters"] == 5


def test_every_cluster_is_a_distinct_page() -> None:
    """The premise the unit rests on, checked over the cases' own bytes. It must not be inferred from
    `contradictory_gold_twins()`, which only surfaces byte-identical groups whose gold DIFFERS — so a
    same-gold twin is invisible there and its emptiness proves nothing about this."""
    cases = minting_cases(_load(_REPLAY))
    checked = assert_distinct_case_bytes(cases)
    assert checked["cases_hashed"] == checked["distinct_fixture_digests"] == len(cases) == 40


def test_two_clusters_over_one_page_are_refused() -> None:
    cases = minting_cases(_load(_REPLAY))
    with pytest.raises(DegenerateClustering, match="not distinct pages"):
        assert_distinct_case_bytes([cases[0], cases[0]])


def test_a_case_outside_the_manifest_is_refused_rather_than_skipped() -> None:
    case = replace(minting_cases(_load(_REPLAY))[0], act_testcase_id="0" * 40)
    with pytest.raises(DegenerateClustering, match="not in the gold manifest"):
        assert_distinct_case_bytes([case])


def test_the_hazard_the_twin_helper_cannot_see_is_live_in_this_tree() -> None:
    """An in-scope minting case IS byte-identical to a fixture the scoping dropped, and
    `contradictory_gold_twins()` reports nothing — because the pair's gold outcomes are what it filters
    on and the dropped side is no longer in the manifest at all. So the distinctness of the 40 clusters
    has to be hashed, and a scope change that re-admitted that rule would put two clusters on one page."""
    import hashlib

    from clearway.eval.act_gold import _ACT_GOLD, contradictory_gold_twins

    in_scope = "6566c139dc811b5a566a8e58c85d1f7f3c550d04"
    dropped = "48cbc84f4c020393cfb56fd53337827278b2d528"
    digests = {
        hashlib.sha256((_ACT_GOLD / "html" / f"{tid}.html").read_bytes()).hexdigest() for tid in (in_scope, dropped)
    }
    assert len(digests) == 1, "the pair is no longer byte-identical — re-read the hazard before trusting this"
    assert contradictory_gold_twins() == {}, "the helper is empty, which is exactly why it cannot carry the claim"
    assert in_scope in {c.act_testcase_id for c in minting_cases(_load(_REPLAY))}


def test_the_drafters_own_verdicts_disagree_within_a_case_more_than_chance() -> None:
    """The measured fact that keeps the per-case unit from resting on 'the elements are homogeneous':
    on the replay pass the drafter's four-value verdicts inside a case agree LESS than random draws."""
    agreement = within_cluster_agreement(drafter_streams(_load(_REPLAY))["conformance_four_value"])
    assert agreement.icc < 0.0
    assert agreement.homogeneous_clusters == 1
    assert agreement.multi_clusters == 7


# --- the judged passes, and the clusters they must share ----------------------------------------


@pytest.mark.parametrize("path", _JUDGED)
def test_each_judged_pass_shares_the_replay_passs_clusters(path: Path) -> None:
    """Same cases, same per-case finding ids — the join that makes the judge-side correlation a prior
    on the pinned unit rather than a number about another structure."""
    assert_same_clusters(_load(path), _load(_REPLAY)) is None


def test_a_judged_pass_with_a_resized_case_is_refused() -> None:
    judged = _load(_JUDGED[0])
    for case in judged["cases"]:
        if len(case["drafts"]) > 1:
            case["drafts"] = case["drafts"][:1]
            break
    with pytest.raises(DegenerateClustering, match="different structure"):
        assert_same_clusters(judged, _load(_REPLAY))


def test_the_judge_routing_streams_follow_the_replay_passs_cluster_order() -> None:
    replay = _load(_REPLAY)
    streams = judge_routing_streams([_load(p) for p in _JUDGED], replay)
    expected = [len(c.drafts) for c in minting_cases(replay)]
    assert len(streams) == 3
    for stream in streams:
        assert [len(cluster) for cluster in stream] == expected


def test_an_even_split_across_passes_has_no_majority() -> None:
    with pytest.raises(DegenerateClustering, match="no strict majority"):
        majority_stream([[[True]], [[False]]])


def test_a_three_way_split_is_refused_rather_than_broken_by_vote_order() -> None:
    """An odd pass count is not sufficient. Three passes answering three different values have no
    majority, and resolving it would let whichever pass was read first decide the observation — the
    exact coin flip the even-count refusal was written to prevent."""
    with pytest.raises(DegenerateClustering, match="no strict majority"):
        majority_stream([[["supports"]], [["partially_supports"]], [["does_not_support"]]])


def test_an_even_pass_count_with_a_strict_majority_is_allowed() -> None:
    """The guard is about the majority, not about parity: four passes at 3–1 have a real winner."""
    assert majority_stream([[["a"]], [["a"]], [["a"]], [["b"]]]) == [["a"]]


def test_the_majority_verdict_is_taken_per_observation() -> None:
    assert majority_stream([[[True, False]], [[True, True]], [[False, False]]]) == [[True, False]]


def test_a_four_valued_majority_resolves_when_one_value_leads_outright() -> None:
    votes = [[["supports"]], [["supports"]], [["does_not_support"]]]
    assert majority_stream(votes) == [["supports"]]


def test_passes_that_disagree_about_the_cluster_shape_are_refused() -> None:
    with pytest.raises(DegenerateClustering, match="cluster shape"):
        majority_stream([[[True]], [[True], [False]], [[True]]])


def test_unanimity_counts_the_observations_the_passes_disagreed_on() -> None:
    assert unanimity([[[True, True]], [[True, False]], [[True, True]]]) == {
        "passes": 3,
        "observations": 2,
        "non_unanimous": 1,
        "rate": 0.5,
    }


# --- what the case collapse hides ---------------------------------------------------------------


def test_flag_if_any_and_a_within_case_majority_part_company_on_a_minority_flag() -> None:
    cost = aggregation_divergence([[True, False, False], [False, False], [True]])
    assert cost["multi_observation_clusters"] == 2
    assert cost["heterogeneous_clusters"] == 1
    assert cost["observations_inside_heterogeneous_clusters"] == 3
    assert cost["clusters_where_flag_if_any_differs_from_within_case_majority"] == 1


# --- the decision, pinned as arithmetic ---------------------------------------------------------


def test_the_judges_measured_correlation_leaves_per_finding_no_better_than_per_case() -> None:
    """The ground the unit rests on. At the judge's majority-verdict correlation the per-finding
    effective n sits within one observation of the cluster count — and two of the three individual
    passes land below it. If this ever moves materially, the pin has to be re-argued rather than
    inherited."""
    record = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    effective = record["effective_n"]
    rows = {row["icc_source"]: row for row in effective["per_finding_at"]}
    majority = rows["judge routing, majority across passes"]
    assert majority["icc"] > 0.0
    assert majority["beats_per_case"] is False
    assert abs(majority["effective_n"] - effective["per_case_units"]) < 1.0
    below = [r for r in rows.values() if r["icc_source"].startswith("judge routing, pass") and not r["beats_per_case"]]
    assert len(below) == 2


def test_the_two_estimators_straddle_the_cluster_count() -> None:
    """Both are reported because the decision sits at the boundary: the pairwise form puts the
    per-finding effective n just under 40 and the ANOVA form just over it. Claiming a strict inequality
    from either alone would be a result that flips with the estimator, so the record carries both."""
    record = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    rows = {row["icc_source"]: row for row in record["effective_n"]["per_finding_at"]}
    pairwise = rows["judge routing, majority across passes"]
    anova = rows["judge routing, majority across passes — ANOVA estimator"]
    clusters = record["effective_n"]["per_case_units"]
    assert pairwise["effective_n"] < clusters < anova["effective_n"]
    assert anova["effective_n"] - pairwise["effective_n"] < 2.0
    majority = record["homogeneity"]["judge_routing_majority_across_passes"]
    assert majority["icc_anova"] == anova["icc"]


def test_the_anova_estimator_refuses_a_stream_it_cannot_code() -> None:
    with pytest.raises(DegenerateClustering, match="binary"):
        anova_icc([["supports", "does_not_support"], ["partially_supports", "supports"]])


def test_the_anova_estimator_agrees_with_the_pairwise_one_at_total_agreement() -> None:
    """Both estimators return 1.0 when every cluster is internally uniform and the clusters differ."""
    streams = [[True, True], [False, False], [True, True], [False, False]]
    assert anova_icc(streams) == pytest.approx(1.0)
    assert within_cluster_agreement(streams).icc == pytest.approx(1.0)


def test_the_bound_at_total_agreement_falls_below_the_cluster_count() -> None:
    """Unequal cluster sizes: the size-weighted mean exceeds one, so a per-finding analysis at perfect
    within-case agreement has FEWER effective observations than there are clusters."""
    record = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    rows = {row["icc_source"]: row for row in record["effective_n"]["per_finding_at"]}
    bound = rows["total within-case agreement, the bound"]
    assert bound["effective_n"] < record["effective_n"]["per_case_units"]


def test_the_coarser_rule_layer_carries_no_routing_correlation() -> None:
    """Recorded so the rule-level clustering caveat is not carried into a paired contrast by habit:
    the judge's routing correlation sits at the case, and at the rule it is absent."""
    record = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    assert record["homogeneity"]["judge_routing_within_rule"]["icc"] <= 0.0


# --- the frozen record --------------------------------------------------------------------------


def test_the_record_is_a_deterministic_function_of_its_sources() -> None:
    """No clock: `created_at` is read off the replay pass, so a rebuild is byte-identical and a
    genuine edit is the only thing that can move the file."""
    first = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    second = build_record(replay_path=_REPLAY, judged_paths=_JUDGED)
    assert first == second
    assert first["sources"]["replay_pass"]["created_at"] == _load(_REPLAY)["created_at"]


def test_the_record_on_disk_is_the_one_these_numbers_were_measured_from() -> None:
    from clearway.eval.judge_observation_unit import _report_path

    fresh = json.dumps(build_record(replay_path=_REPLAY, judged_paths=_JUDGED), indent=2, ensure_ascii=False) + "\n"
    assert _report_path().read_text() == fresh, (
        "the frozen observation-unit record no longer matches a rebuild — the unit was pinned from the "
        "numbers in that file, so rebuild it deliberately rather than editing it in place"
    )


def test_the_frozen_record_states_the_structure_the_unit_was_pinned_from() -> None:
    from clearway.eval.judge_observation_unit import _report_path

    on_disk = json.loads(_report_path().read_text())
    structure = on_disk["structure"]
    assert (structure["observations"], structure["clusters"], structure["manifest_rows"]) == (54, 40, 44)
    assert structure["non_minting_rows"] == 4
    assert structure["cluster_size_histogram"] == {"1": 33, "2": 2, "3": 3, "4": 2}
    assert structure["observations_in_multi_observation_clusters"] == 21
    assert on_disk["unit"]["observation_unit"] == OBSERVATION_UNIT
    assert on_disk["unit"]["unit_key"] == "act_testcase_id"
