"""The judge's observation structure, and the unit its paired comparison is scored on.

A replay produces one **observation** per minted finding — the natural judgment of that finding — but
the findings are not scattered independently. They arrive in **ACT cases**: one fixture page, one
gold outcome, one rule, and between one and four elements the rule mints a finding on. A paired test
that treats those as independent units pseudo-replicates, and the fix is not free either: collapsing
to the case needs an aggregation rule, and an aggregation rule hides whatever it aggregates over.

**⚠️ An observation is not a call.** A configuration that also judges mutated drafts spends two or
three calls on one finding, and those extra calls feed a separate diagnostic rather than the routing
comparison. Counting calls here would inflate the structure by a factor that has nothing to do with
clustering, so every count below is a natural judgment.

So the unit is measured before it is pinned, and this module is that measurement. Pure — no model, no
network, no clock. Every number replays from frozen artifacts, and `created_at` is READ off the
replay pass rather than generated, so the record is a deterministic function of its sources and a
rebuild is byte-identical.

**Two things are counted, and they are not the same number.** The *observations* are the minted
findings; the *manifest rows* include the cases that minted nothing. A case that mints no finding is
never judged, so it contributes no observation and is not a cluster at all — dividing findings by
manifest rows makes the structure look flatter than it is, and both figures are recorded here so the
gap is visible rather than implied.

**The correlation is estimated pairwise, on the routing axis a test would consume.** Within-cluster
pair agreement against the marginal chance rate gives the intracluster correlation in the
kappa-shaped form `(observed − chance) / (1 − chance)`; the Kish mean cluster size
`Σm² / Σm` turns that into a design effect, and the design effect into an effective n a per-finding
analysis would really have. Comparing that against the plain cluster count is the whole decision: a
per-finding unit is worth its dependence only if it buys observations after the inflation is paid.

**Two raters are measured, because they cluster differently and only one of them is the subject.**
The drafter's per-finding verdicts exist on the replay pass itself. The judge's do not — that pass is
drafter-only — so its side is read from the earlier judged passes, restricted to the rules the gold
still scores, where the case set and the per-case finding ids are **identical** to the replay pass
(asserted, not assumed). That makes the judge-side estimate a measurement over the same clusters the
pin governs, from input the judge no longer receives — a prior worth stating and not the thing
itself, which is why the noise-floor stage re-measures it on live output.

Invoke: `uv run python -m clearway.eval.judge_observation_unit`
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import RULE_TO_AXE
from clearway.eval.drafter_kappa import _grouped
from clearway.eval.drafter_score import DraftedCase
from clearway.eval.stats import COLLAPSE_RULE, is_flag

# ---------------------------------------------------------------------------------------------
# The pin. Imported by the stages downstream rather than restated by each of them: a unit spelled
# in two places can be corrected in one of them and stay wrong in the other, with nothing to show
# for it but a p-value.
# ---------------------------------------------------------------------------------------------

# The unit the paired routing test is scored on — one ACT case, keyed by `act_testcase_id`.
OBSERVATION_UNIT = "case"

# How a case's findings become one routing decision. Flag-if-any, matching the drafter scorer's own
# `_flagged` and the product reading: a specialist experiences one raised hand on a page as "go look".
WITHIN_CASE_AGGREGATION = "flag-if-any"

# The order the two aggregations apply in, and they are not interchangeable. Repeat passes collapse
# FIRST, per finding, because a single pass of a non-reproducible judge is one draw; the case
# collapse comes second. Flagging-if-any per pass and then taking a majority over cases answers a
# different question and can land on a different decision.
AGGREGATION_ORDER = (
    "majority verdict across the configuration's passes, per finding; then flag-if-any across the "
    "findings within the case"
)

# The disagreement rate keeps the FINDING as its denominator, and that is deliberate rather than an
# oversight of the pin above. Disagreement is defined per finding by construction — code compares the
# judge's answer against THAT finding's draft — and the rate is a queue-volume figure, so collapsing
# it would report fewer people-visits than the queue holds. Two units, two questions, both named
# wherever either is quoted.
DISAGREEMENT_RATE_UNIT = "finding"

UNIT_PREREGISTRATION = (
    "Pinned before any judge call is spent, from the clustering measured over the frozen replay pass "
    "and the earlier judged passes on the same case set. The paired routing test is scored PER CASE, "
    "keyed by act_testcase_id, on discordant pairs — the same unit every other paired test in this "
    "repo is already pre-registered on. Three grounds, and the first is arithmetic rather than "
    "preference: (1) at the measured within-case correlation of the judge's own majority routing "
    "decision the per-finding effective n lands within ONE observation of the cluster count — below it "
    "under the pairwise estimator and above it under the ANOVA one — so a per-finding unit buys nothing "
    "measurable while costing an independence assumption the data does not support; (2) the "
    "repo's frozen per-class drafter kappa is a per-case number keyed by act_testcase_id, so the "
    "side-by-side comparison against it is only like-for-like at the case; (3) the gold label is a "
    "property of the case, so every finding inside one is scored against the same answer key. What "
    "would have decided the other way: a within-case correlation at or below zero — the drafter's "
    "own verdicts measure there — which would have left the per-finding effective n near the raw "
    "finding count and made the extra observations real. Declared costs: the case collapse needs "
    "flag-if-any, which hides within-case disagreement, so the per-finding table is reported beside "
    "the test rather than replaced by it; and the disagreement rate stays per-finding because it "
    "counts people-visits, so every reported figure names its unit."
)


class DegenerateClustering(ValueError):
    """A clustering question asked of a stream that cannot answer it.

    Raised rather than defaulted, for the reason every refusal in this tree is raised: an undefined
    correlation returned as `0.0` is indistinguishable from a measured independence, and only one of
    those is a finding.
    """


# ---------------------------------------------------------------------------------------------
# Cluster structure
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Clustering:
    """The observation structure of one grouped stream: how many observations sit in each cluster.

    `sizes` holds one entry per cluster that carries at least one observation. A zero is refused
    rather than stored: a case that mints no finding is never judged, so it is a manifest row and not
    a cluster, and admitting it here is exactly what makes the structure read flatter than it is.
    """

    sizes: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.sizes:
            raise DegenerateClustering("a clustering over zero clusters is not a structure — check the source pass")
        if any(size <= 0 for size in self.sizes):
            raise DegenerateClustering(
                "a cluster of size 0 was passed in. A case that mints no finding contributes no judge "
                "observation, so it is a manifest ROW, not a cluster; counting it here divides the "
                "observations by a larger denominator and reports the structure as flatter than it is."
            )

    @property
    def observations(self) -> int:
        return sum(self.sizes)

    @property
    def clusters(self) -> int:
        return len(self.sizes)

    @property
    def singletons(self) -> int:
        return sum(1 for size in self.sizes if size == 1)

    @property
    def multi_clusters(self) -> int:
        return sum(1 for size in self.sizes if size > 1)

    @property
    def observations_in_multi_clusters(self) -> int:
        """How much of the data sits where the unit choice can matter at all."""
        return sum(size for size in self.sizes if size > 1)

    @property
    def mean_size(self) -> float:
        return self.observations / self.clusters

    @property
    def kish_mean_size(self) -> float:
        """`Σm² / Σm` — the size-weighted mean cluster size that drives the design effect.

        Not the plain mean: an unweighted average over all observations gives the larger clusters
        more weight, so the variance inflation follows this figure. It is why a per-finding effective
        n at perfect within-case agreement lands BELOW the cluster count rather than on it.
        """
        return sum(size * size for size in self.sizes) / self.observations

    @property
    def histogram(self) -> dict[int, int]:
        return dict(sorted(Counter(self.sizes).items()))

    def design_effect(self, icc: float) -> float:
        """`1 + (kish_mean_size − 1) · icc` — the variance inflation a per-observation analysis pays."""
        return 1.0 + (self.kish_mean_size - 1.0) * icc

    def effective_n(self, icc: float) -> float:
        """The observations a per-observation analysis really has, once the inflation is paid."""
        return self.observations / self.design_effect(icc)


# ---------------------------------------------------------------------------------------------
# Within-cluster homogeneity
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WithinClusterAgreement:
    """Pairwise within-cluster agreement against the marginal chance rate → the intracluster correlation.

    The estimator is the kappa-shaped one for clustered categorical data: take every pair of
    observations inside a cluster, ask how often the pair agrees, and correct that against the
    agreement two draws from the marginal distribution would produce. `homogeneous_clusters` rides
    beside it because a rate over 23 pairs from 7 clusters is imprecise, and the count of clusters
    that answered one value throughout is the same fact in a form that cannot be over-read.
    """

    observations: int
    pairs: int
    agreeing: int
    chance: float
    multi_clusters: int
    homogeneous_clusters: int
    distinct_values: int

    @property
    def observed(self) -> float:
        return self.agreeing / self.pairs

    @property
    def icc(self) -> float:
        return (self.observed - self.chance) / (1.0 - self.chance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "within_cluster_pairs": self.pairs,
            "agreeing_pairs": self.agreeing,
            "observed_agreement": round(self.observed, 4),
            "chance_agreement": round(self.chance, 4),
            "icc": round(self.icc, 4),
            "multi_observation_clusters": self.multi_clusters,
            "homogeneous_clusters": self.homogeneous_clusters,
            "distinct_values": self.distinct_values,
        }


def within_cluster_agreement(streams: Sequence[Sequence[Hashable]]) -> WithinClusterAgreement:
    """The within-cluster correlation of one grouped value stream.

    Refuses two degenerate shapes instead of reporting a number for them: a stream with no
    within-cluster pair at all (every cluster a singleton — nothing to correlate), and a constant
    stream (chance agreement 1.0, so the correction is 0/0). Both would otherwise return a
    plausible-looking `0.0` and be read as measured independence.
    """
    values = [value for stream in streams for value in stream]
    if not values:
        raise DegenerateClustering("no observations to correlate")
    marginal = Counter(values)
    chance = sum(count * count for count in marginal.values()) / (len(values) ** 2)
    if chance >= 1.0:
        raise DegenerateClustering(
            f"the stream answered {next(iter(marginal))!r} on all {len(values)} observations, so chance "
            "agreement is 1.0 and the intracluster correlation is undefined (0/0). A constant stream "
            "carries no variance to correlate; reporting 0.0 would read as measured independence."
        )
    pairs = agreeing = homogeneous = multi = 0
    for stream in streams:
        if len(stream) < 2:
            continue
        multi += 1
        homogeneous += len(set(stream)) == 1
        for left, right in itertools.combinations(stream, 2):
            pairs += 1
            agreeing += left == right
    if not pairs:
        raise DegenerateClustering(
            "every cluster holds a single observation, so there is no within-cluster pair and the "
            "intracluster correlation is undefined — not zero. A structure this flat needs no unit "
            "decision at all; say so rather than reporting an ICC of 0.0."
        )
    return WithinClusterAgreement(
        observations=len(values),
        pairs=pairs,
        agreeing=agreeing,
        chance=chance,
        multi_clusters=multi,
        homogeneous_clusters=homogeneous,
        distinct_values=len(marginal),
    )


def anova_icc(streams: Sequence[Sequence[Hashable]]) -> float:
    """The one-way random-effects intracluster correlation of a BINARY stream — a second estimator.

    Reported beside the pairwise one on purpose. The two are not identical at these cluster sizes and
    the decision they inform sits right at the boundary, so a reader who recomputes with the textbook
    ANOVA form must find that figure in the record rather than a different answer to the same question.
    `(MSB − MSW) / (MSB + (m₀ − 1)·MSW)` with the usual unequal-size correction
    `m₀ = (n − Σm²/n) / (k − 1)`.

    Binary only, and refused otherwise: the pairwise estimator handles a categorical stream (any two
    observations either match or do not), while this one needs a numeric coding, and silently coding a
    four-value verdict onto 0/1 would answer a question nobody asked.
    """
    values = [value for stream in streams for value in stream]
    levels = sorted({str(value) for value in values})
    if len(levels) != 2:
        raise DegenerateClustering(
            f"the ANOVA estimator needs a binary stream and this one carries {len(levels)} distinct "
            "values; coding a categorical verdict onto 0/1 to make it fit would change the question"
        )
    if len(streams) < 2:
        raise DegenerateClustering("the ANOVA estimator needs at least two clusters")
    coded = [[float(str(value) == levels[1]) for value in stream] for stream in streams]
    n, clusters = len(values), len(coded)
    grand = sum(v for stream in coded for v in stream) / n
    means = [sum(stream) / len(stream) for stream in coded]
    between = sum(len(stream) * (mean - grand) ** 2 for stream, mean in zip(coded, means, strict=True)) / (clusters - 1)
    within_ss = sum((v - mean) ** 2 for stream, mean in zip(coded, means, strict=True) for v in stream)
    if n == clusters:
        raise DegenerateClustering("every cluster holds one observation — there is no within-cluster variance")
    within = within_ss / (n - clusters)
    size_correction = (n - sum(len(stream) ** 2 for stream in coded) / n) / (clusters - 1)
    denominator = between + (size_correction - 1.0) * within
    if denominator == 0.0:
        raise DegenerateClustering("no variance to partition — the ANOVA estimator is undefined here")
    return (between - within) / denominator


# ---------------------------------------------------------------------------------------------
# The streams: what each rater answered, grouped by case
# ---------------------------------------------------------------------------------------------


def minting_cases(artifact: dict[str, Any]) -> list[DraftedCase]:
    """The replay pass's cases that carry at least one observation, in artifact order.

    Built from the scorer's own scoped case stream, so the class definition is the gold's and the
    honest-misses arrive as drafts-less cases — and are then dropped HERE, deliberately and in one
    place, because they are the manifest rows the observation count must not be divided by.
    """
    return [case for group in _grouped(artifact).values() for case in group if case.drafts]


def manifest_rows(artifact: dict[str, Any]) -> int:
    """Every scoped row of the gold the pass covers, minting or not — the wrong denominator, recorded
    so the right one can be read against it."""
    return sum(len(group) for group in _grouped(artifact).values())


def drafter_streams(artifact: dict[str, Any]) -> dict[str, list[list[Hashable]]]:
    """The drafter's per-case value streams, one entry per axis a comparison would run on.

    Four axes rather than one, because they answer differently: the raw four-value conformance is
    what the routing comparison compares, the collapsed flag is what gold scoring uses, the cited-SC
    set is the second compared field, and the joint pair is the disagreement event itself.
    """
    cases = minting_cases(artifact)
    return {
        "conformance_four_value": [[d.conformance.value for d in c.drafts] for c in cases],
        "conformance_flag_collapse": [[is_flag(d.conformance) for d in c.drafts] for c in cases],
        "cited_sc_set": [[tuple(sorted(d.cited_sc_ids)) for d in c.drafts] for c in cases],
        "conformance_and_sc": [[(d.conformance.value, tuple(sorted(d.cited_sc_ids))) for d in c.drafts] for c in cases],
    }


def _scoped_finding_map(artifact: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """`act_testcase_id → the finding ids it minted`, over the rules the gold still scores."""
    return {
        case["act_testcase_id"]: tuple(d["finding_id"] for d in case["drafts"])
        for case in artifact["cases"]
        if case["rule_name"] in RULE_TO_AXE and case["drafts"]
    }


def assert_same_clusters(judged: dict[str, Any], replay: dict[str, Any]) -> None:
    """Refuse a judged pass whose scoped clusters are not the replay pass's, case for case and
    finding for finding.

    The judge-side correlation is only usable as a prior on the pinned unit if it was measured over
    the SAME structure. A pass carrying a different case set, or the same cases with a different
    number of elements minted on them, would produce a perfectly well-formed correlation describing
    a clustering the pin does not govern.
    """
    theirs, ours = _scoped_finding_map(judged), _scoped_finding_map(replay)
    if theirs != ours:
        missing = sorted(set(ours) - set(theirs))
        extra = sorted(set(theirs) - set(ours))
        resized = sorted(k for k in set(ours) & set(theirs) if ours[k] != theirs[k])
        raise DegenerateClustering(
            "the judged pass does not share the replay pass's clustering, so its within-case "
            f"correlation describes a different structure: {len(missing)} case(s) absent, "
            f"{len(extra)} extra, {len(resized)} minting a different finding set "
            f"(absent={missing[:3]}, extra={extra[:3]}, resized={resized[:3]})"
        )


def judge_routing_streams(passes: Sequence[dict[str, Any]], replay: dict[str, Any]) -> tuple[list[list[Hashable]], ...]:
    """One per-case stream of the judge's routing decision per pass, over the replay pass's clusters.

    The decision is `judge_conformance_correct`: the anchored judge raises its hand exactly when it
    grades the draft incorrect, so the flag is that boolean negated — and negating a boolean stream
    changes neither its within-cluster agreement nor its marginal chance term, which is why the
    correlation is read off the field as recorded.
    """
    if not passes:
        raise DegenerateClustering("no judged pass to read a routing decision from")
    order = _scoped_finding_map(replay)
    streams: list[list[list[Hashable]]] = []
    for judged in passes:
        assert_same_clusters(judged, replay)
        verdicts = {
            d["finding_id"]: d["judge_conformance_correct"]
            for case in judged["cases"]
            if case["rule_name"] in RULE_TO_AXE
            for d in case["drafts"]
        }
        streams.append([[verdicts[fid] for fid in fids] for fids in order.values()])
    return tuple(streams)


def majority_stream(per_pass: Sequence[Sequence[Sequence[Hashable]]]) -> list[list[Hashable]]:
    """The per-finding majority verdict across passes — the quantity the paired test consumes.

    **A STRICT majority is required at every observation, and anything less is refused.** An odd pass
    count is not enough on its own: three passes returning three different values have no majority
    either, and `Counter.most_common` would resolve that by insertion order — a coin flip inside the
    decision the whole comparison is scored on, decided by which pass happened to be read first. The
    routing stream is boolean and cannot split three ways, but the judge's own conformance is
    four-valued and *Direction of disagreement* needs a majority over exactly that, so the guard is
    written for the general case rather than for the caller that exists today.
    """
    if not per_pass:
        raise DegenerateClustering("no passes to take a majority over")
    shapes = {tuple(len(stream) for stream in streams) for streams in per_pass}
    if len(shapes) != 1:
        raise DegenerateClustering(f"the passes disagree about the cluster shape: {sorted(shapes)}")
    majority: list[list[Hashable]] = []
    for cluster_index, first in enumerate(per_pass[0]):
        row: list[Hashable] = []
        for position in range(len(first)):
            votes = [streams[cluster_index][position] for streams in per_pass]
            winner, count = Counter(votes).most_common(1)[0]
            if count * 2 <= len(votes):
                raise DegenerateClustering(
                    f"no strict majority over {len(votes)} passes at cluster {cluster_index}, position "
                    f"{position}: the votes were {votes!r}, and the leading value {winner!r} carries only "
                    f"{count} of them. Resolving that would break the tie by vote order — a coin flip "
                    "inside the decision the paired test is scored on. Add passes or report the "
                    "observation as undecided; do not let insertion order decide it."
                )
            row.append(winner)
        majority.append(row)
    return majority


def aggregation_divergence(flag_streams: Sequence[Sequence[bool]]) -> dict[str, Any]:
    """What the case collapse hides, counted rather than conceded.

    Flag-if-any is the pinned rule, and its cost is that a case with one raised hand and three lowered
    ones reads exactly like a case with four raised. So the alternative collapse — a within-case
    majority — is computed beside it and the cases where the two land differently are counted. Unlike
    the correlation above, this one is direction-sensitive: it runs on the RAISED-HAND stream, not on
    the recorded correctness boolean.
    """
    heterogeneous = [stream for stream in flag_streams if len(stream) > 1 and len(set(stream)) > 1]
    divergent = [stream for stream in flag_streams if any(stream) != (sum(1 for f in stream if f) * 2 > len(stream))]
    return {
        "clusters": len(flag_streams),
        "multi_observation_clusters": sum(1 for stream in flag_streams if len(stream) > 1),
        "heterogeneous_clusters": len(heterogeneous),
        "observations_inside_heterogeneous_clusters": sum(len(stream) for stream in heterogeneous),
        "clusters_where_flag_if_any_differs_from_within_case_majority": len(divergent),
        "note": (
            "The count of divergent clusters is what flag-if-any decides differently from a within-case "
            "majority, and the heterogeneous count is the within-case disagreement the collapse makes "
            "invisible. Flag-if-any is kept because it is the product reading — one raised hand on a page "
            "sends the specialist — and because it matches the drafter scorer's own collapse; the cost is "
            "recorded here so the per-finding table is read beside the test rather than instead of it."
        ),
    }


def unanimity(per_pass: Sequence[Sequence[Sequence[Hashable]]]) -> dict[str, Any]:
    """How often the passes of ONE configuration disagreed with themselves, per observation.

    Context for the pin rather than part of it: it says the repeat-pass collapse is doing real work,
    and it is a prior on the noise floor the next stage measures properly.
    """
    total = non_unanimous = 0
    for cluster_index, first in enumerate(per_pass[0]):
        for position in range(len(first)):
            total += 1
            non_unanimous += len({streams[cluster_index][position] for streams in per_pass}) > 1
    return {
        "passes": len(per_pass),
        "observations": total,
        "non_unanimous": non_unanimous,
        "rate": round(non_unanimous / total, 4) if total else 0.0,
    }


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------


def _per_class(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Where the clustering actually lives. Two of the four classes are all singletons, so the unit
    choice cannot move a number on them at all — worth recording, because a per-class table read
    without it invites the idea that the unit is a uniform tax."""
    rows: list[dict[str, Any]] = []
    for axe_rule, group in sorted(_grouped(artifact).items()):
        clustering = Clustering(tuple(len(c.drafts) for c in group if c.drafts))
        rows.append(
            {
                "axe_rule": axe_rule,
                "clusters": clustering.clusters,
                "observations": clustering.observations,
                "multi_observation_clusters": clustering.multi_clusters,
                "cluster_size_histogram": {str(k): v for k, v in clustering.histogram.items()},
                "unit_choice_changes_this_class": clustering.multi_clusters > 0,
            }
        )
    return rows


def _structure(artifact: dict[str, Any]) -> dict[str, Any]:
    clustering = Clustering(tuple(len(c.drafts) for c in minting_cases(artifact)))
    rows = manifest_rows(artifact)
    return {
        "observations": clustering.observations,
        "clusters": clustering.clusters,
        "manifest_rows": rows,
        "non_minting_rows": rows - clustering.clusters,
        "observations_per_cluster": round(clustering.mean_size, 4),
        "observations_per_manifest_row": round(clustering.observations / rows, 4),
        "manifest_row_divisor_understates_cluster_size_by": round(
            clustering.mean_size - clustering.observations / rows, 4
        ),
        "kish_mean_cluster_size": round(clustering.kish_mean_size, 4),
        "singleton_clusters": clustering.singletons,
        "multi_observation_clusters": clustering.multi_clusters,
        "observations_in_multi_observation_clusters": clustering.observations_in_multi_clusters,
        "share_in_multi_observation_clusters": round(
            clustering.observations_in_multi_clusters / clustering.observations, 4
        ),
        "largest_cluster": max(clustering.sizes),
        "cluster_size_histogram": {str(k): v for k, v in clustering.histogram.items()},
        "per_class": _per_class(artifact),
    }


def _effective_n(clustering: Clustering, icc_sources: list[tuple[str, float]]) -> dict[str, Any]:
    """The per-finding effective n at each measured correlation, beside the plain cluster count.

    This table IS the decision. A per-finding unit is worth its dependence only where its effective
    n exceeds the cluster count a per-case unit gives for free.
    """
    return {
        "formula": "design_effect = 1 + (kish_mean_cluster_size - 1) * icc; effective_n = observations / design_effect",
        "reading": (
            "The rows to decide on are the judge's, because the judge is the rater the test scores — and "
            "its two estimators STRADDLE the cluster count, so the finer unit's advantage is under one "
            "observation either way and `beats_per_case` must not be read as a strict result. A row with a "
            "NEGATIVE icc returns an effective n above the observation count: that is the correct "
            "arithmetic for anti-clustering — a cluster whose members disagree more than random draws — "
            "and it is not extra data, so it is never read as a power gain. The icc = 1 row is the bound, "
            "and it lands BELOW the cluster count because unequal cluster sizes weight the larger clusters "
            "more heavily than a per-cluster analysis would."
        ),
        "kish_mean_cluster_size": round(clustering.kish_mean_size, 4),
        "per_case_units": clustering.clusters,
        "per_finding_at": [
            {
                "icc_source": source,
                "icc": round(icc, 4),
                "design_effect": round(clustering.design_effect(icc), 4),
                "effective_n": round(clustering.effective_n(icc), 2),
                "beats_per_case": clustering.effective_n(icc) > clustering.clusters,
            }
            for source, icc in icc_sources
        ],
    }


def _provenance(path: Path, artifact: dict[str, Any], *, fields: Sequence[str]) -> dict[str, Any]:
    record: dict[str, Any] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    record.update({f: artifact[f] for f in fields})
    return record


def build_record(*, replay_path: Path, judged_paths: Sequence[Path]) -> dict[str, Any]:
    """Assemble the observation-unit record from a frozen replay pass and the earlier judged passes.

    Deterministic: no clock, no network, no model. `created_at` is the replay pass's own, so a
    rebuild reproduces the file byte for byte and a genuine edit is the only thing that can move it.
    """
    replay = json.loads(replay_path.read_text())
    judged = [json.loads(p.read_text()) for p in judged_paths]
    clustering = Clustering(tuple(len(c.drafts) for c in minting_cases(replay)))

    drafter = {axis: within_cluster_agreement(streams).to_dict() for axis, streams in drafter_streams(replay).items()}
    per_pass = judge_routing_streams(judged, replay)
    majority = majority_stream(per_pass)
    pass_rows = [within_cluster_agreement(streams) for streams in per_pass]
    majority_row = within_cluster_agreement(majority)

    by_rule: dict[str, list[Hashable]] = {}
    for case, stream in zip(minting_cases(replay), majority, strict=True):
        by_rule.setdefault(RULE_TO_AXE[case.rule_name], []).extend(stream)
    rule_row = within_cluster_agreement(list(by_rule.values()))

    majority_anova = anova_icc(majority)
    icc_sources = [(f"judge routing, pass {i}", row.icc) for i, row in enumerate(pass_rows, start=1)]
    icc_sources.append(("judge routing, majority across passes", majority_row.icc))
    icc_sources.append(("judge routing, majority across passes — ANOVA estimator", majority_anova))
    icc_sources.append(("drafter four-value conformance on the replay pass", drafter["conformance_four_value"]["icc"]))
    icc_sources.extend([("independence, for reference", 0.0), ("total within-case agreement, the bound", 1.0)])

    return {
        "unit": {
            "observation_unit": OBSERVATION_UNIT,
            "unit_key": "act_testcase_id",
            "within_case_aggregation": WITHIN_CASE_AGGREGATION,
            "aggregation_order": AGGREGATION_ORDER,
            "disagreement_rate_unit": DISAGREEMENT_RATE_UNIT,
            "preregistration": UNIT_PREREGISTRATION,
        },
        "sources": {
            "replay_pass": _provenance(
                replay_path, replay, fields=("config_id", "eval_set_id", "drafter_model", "created_at")
            ),
            "judged_passes": [
                _provenance(p, a, fields=("judge_model", "judge_version", "created_at"))
                for p, a in zip(judged_paths, judged, strict=True)
            ],
            "judged_pass_caveat": (
                "The judged passes carry the same 40 clusters and the same per-case finding ids as the "
                "replay pass (asserted, not assumed), but they graded a DIFFERENT draft set under "
                "referent-free input. Their correlation is a prior on the pinned unit, measured over the "
                "right structure by the wrong instrument; the noise-floor stage re-measures it live."
            ),
        },
        "structure": _structure(replay),
        "homogeneity": {
            "conformance_collapse_rule": COLLAPSE_RULE,
            "drafter_on_the_replay_pass": drafter,
            "judge_routing_per_pass": [row.to_dict() for row in pass_rows],
            "judge_routing_majority_across_passes": {
                **majority_row.to_dict(),
                "icc_anova": round(majority_anova, 4),
                "note": (
                    "Two estimators for one quantity, and they are reported together because the decision "
                    "sits at the boundary: the pairwise form and the one-way random-effects (ANOVA) form "
                    "straddle the cluster count, so the per-finding effective n lands just below it under "
                    "one and just above it under the other. The honest reading is that the two units "
                    "differ by less than a single observation, which is what 'the finer unit buys nothing' "
                    "means here — not a strict inequality that would flip with the estimator."
                ),
            },
            "judge_routing_within_rule": {
                **rule_row.to_dict(),
                "note": (
                    "The coarser layer, over the four scored rules. Reported as context and NOT as a "
                    "candidate unit: a paired contrast gives both configurations the same rule framing, "
                    "so a shared per-rule effect cancels rather than inflating the test. Measured here it "
                    "is absent anyway — the routing correlation lives at the case, not at the rule."
                ),
            },
            "judge_pass_to_pass": unanimity(per_pass),
            "case_collapse_cost": aggregation_divergence([[not v for v in stream] for stream in majority]),
        },
        "effective_n": _effective_n(clustering, icc_sources),
    }


def _report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_observation_unit.json"


def main() -> None:
    """Freeze the observation-unit record from the checked-in passes. Pure and offline — zero model calls."""
    from clearway.eval.run_artifacts import CITATION_GROUNDING, acceptance_pass_paths, run_path

    record = build_record(replay_path=run_path(CITATION_GROUNDING, 1), judged_paths=acceptance_pass_paths())
    structure = record["structure"]
    print(
        f"{structure['observations']} observations in {structure['clusters']} clusters "
        f"({structure['manifest_rows']} manifest rows — {structure['non_minting_rows']} mint nothing)"
    )
    print(
        f"  sizes {structure['cluster_size_histogram']}; Kish mean {structure['kish_mean_cluster_size']}; "
        f"{structure['share_in_multi_observation_clusters']:.3f} of observations in a multi-finding case"
    )
    majority = record["homogeneity"]["judge_routing_majority_across_passes"]
    print(f"  judge routing ICC (majority across passes) {majority['icc']:+.4f}")
    for row in record["effective_n"]["per_finding_at"]:
        verdict = "beats per-case" if row["beats_per_case"] else "does not beat per-case"
        print(f"    n_eff {row['effective_n']:>6} at ICC {row['icc']:+.4f} — {verdict} ({row['icc_source']})")
    print(f"  unit pinned: per {record['unit']['observation_unit']}, {record['unit']['within_case_aggregation']}")

    path = _report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {path.relative_to(Path.cwd())} — 0 model calls")


if __name__ == "__main__":
    main()
