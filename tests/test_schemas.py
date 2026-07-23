"""T0 acceptance tests: models import, JSON-schema smoke, extra=forbid, frozen OracleVerdict."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from clearway import schemas
from clearway.schemas import models
from clearway.schemas.models import (
    AxeBucket,
    AxeNode,
    AxePass,
    CalibrationReport,
    ConfidenceBin,
    Conformance,
    CorpusChunk,
    DrafterScore,
    DraftRow,
    EvidenceQuery,
    ExemptMetric,
    Finding,
    GoldLabel,
    JudgeConfusion,
    JudgeResult,
    JudgeVerdict,
    L1Status,
    MetricCI,
    NeedsReview,
    NoiseFloor,
    NotMeasuredItem,
    OfflineEvalReport,
    OfflineEvalScorecard,
    OnlineEvalMetrics,
    Oracle,
    OracleRegime,
    OracleVerdict,
    PipelineStep,
    ReviewReason,
    ReviewStatus,
    RunState,
    RunStatus,
    ScanResult,
    Severity,
    StepState,
    StepStatus,
    TierBSmoke,
)

# Every concrete BaseModel defined in the contract (Oracle is a Protocol, excluded).
MODEL_CLASSES = [
    obj
    for obj in vars(models).values()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
]


def test_public_names_are_importable() -> None:
    """Every name promised by clearway.schemas.__all__ resolves."""
    for name in schemas.__all__:
        assert hasattr(schemas, name), f"clearway.schemas is missing {name!r}"


@pytest.mark.parametrize("model", MODEL_CLASSES, ids=lambda m: m.__name__)
def test_json_schema_generates(model: type[BaseModel]) -> None:
    """Each model produces a valid JSON schema titled after the class."""
    js = model.model_json_schema()
    assert isinstance(js, dict)
    assert js["title"] == model.__name__


def test_extra_forbid_rejects_unknown_field() -> None:
    """Contracts are strict: an unexpected field is a validation error."""
    with pytest.raises(ValidationError):
        Finding(id="x", source_url="u", rule_id="image-alt", target="img", bogus=1)


def test_oracle_verdict_is_frozen() -> None:
    """Ground truth is immutable — assignment after construction must fail."""
    verdict = OracleVerdict(success_criteria=["1.1.1"])
    with pytest.raises(ValidationError):
        verdict.source = "axe-core"


def test_enum_wire_values_are_stable() -> None:
    """Wire strings are the contract; renaming a value is a breaking change."""
    assert Conformance.DOES_NOT_SUPPORT.value == "does_not_support"
    assert L1Status.NO_ORACLE.value == "no_oracle"
    assert OracleRegime.A_DIGITAL.value == "A-digital"
    # AxeBucket values must match axe's payload keys — the scanner reads results by these names.
    assert AxeBucket.VIOLATIONS.value == "violations"
    assert AxeBucket.INCOMPLETE.value == "incomplete"
    assert AxeBucket.PASSES.value == "passes"
    # M2: durable orchestration + HITL wire values.
    assert PipelineStep.RETRIEVE.value == "retrieve"
    assert RunStatus.PAUSED.value == "paused"
    assert StepStatus.NEEDS_REVIEW.value == "needs_review"
    assert ReviewReason.UNVERIFIABLE_JUDGMENT.value == "unverifiable_judgment"
    assert ReviewStatus.EDITED.value == "edited"


def test_finding_defaults_to_the_violations_bucket() -> None:
    """Provenance is additive: an M0-style finding (no source_bucket) is a confirmed violation."""
    finding = Finding(id="x", source_url="u", rule_id="image-alt", target="img")
    assert finding.source_bucket is AxeBucket.VIOLATIONS


def test_scan_result_passes_bucket_is_additive() -> None:
    """The `passes` bucket is additive: an M0-style scan (no passes) round-trips with an empty
    list, and an `AxePass` carries the same `AxeRuleResult` shape as a violation."""
    empty = ScanResult(url="u", scanned_at=datetime(2026, 7, 12), tool_version="4.12.1")
    assert empty.passes == []

    scan = ScanResult(
        url="u",
        scanned_at=datetime(2026, 7, 12),
        tool_version="4.12.1",
        passes=[AxePass(rule_id="image-alt", tags=["wcag111"], nodes=[AxeNode(target=["img"], html="<img>")])],
    )
    assert scan.passes[0].rule_id == "image-alt"
    assert ScanResult.model_validate_json(scan.model_dump_json()).passes[0].rule_id == "image-alt"


def test_corpus_chunk_embedding_is_optional_and_excluded_from_serialization() -> None:
    """The vector lives in pgvector, not the transported contract: it defaults to None and
    is dropped from model_dump()/model_dump_json() even when set."""
    chunk = CorpusChunk(chunk_id="c1", text="images need a text alternative", corpus_version="wcag22-nomic768@1")
    assert chunk.embedding is None  # optional

    with_vec = chunk.model_copy(update={"embedding": [0.1, 0.2, 0.3]})
    assert with_vec.embedding == [0.1, 0.2, 0.3]  # carried in-process
    dumped = with_vec.model_dump()
    assert "embedding" not in dumped  # excluded from serialization
    assert "embedding" not in with_vec.model_dump_json()
    assert dumped["chunk_id"] == "c1" and dumped["corpus_version"] == "wcag22-nomic768@1"


def test_corpus_chunk_is_strict() -> None:
    """Contracts are strict: an unexpected field is a validation error."""
    with pytest.raises(ValidationError):
        CorpusChunk(chunk_id="c1", text="t", corpus_version="v1", bogus=1)


def test_evidence_query_round_trips_and_defaults_rule_id() -> None:
    """Reuse input: `description` is required, `rule_id` defaults empty, and the model
    survives a JSON round-trip unchanged."""
    q = EvidenceQuery(description="images need a text alternative")
    assert q.rule_id == ""

    full = EvidenceQuery(rule_id="image-alt", description="images need a text alternative")
    assert EvidenceQuery.model_validate_json(full.model_dump_json()) == full
    # The retriever's query text is lossless in form: f"{rule_id} {description}".strip().
    assert f"{full.rule_id} {full.description}".strip() == "image-alt images need a text alternative"


def test_evidence_query_requires_description() -> None:
    """`description` is the one mandatory field — a caller must describe the problem."""
    with pytest.raises(ValidationError):
        EvidenceQuery(rule_id="image-alt")


def test_evidence_query_is_strict() -> None:
    """Contracts are strict: an unexpected field is a validation error. In particular a
    caller must not smuggle internal `Finding` fields (id / source_url / target) through."""
    with pytest.raises(ValidationError):
        EvidenceQuery(description="x", target="img")


def test_eval_metrics_has_stratified_fields_defaulting_safely() -> None:
    """M1 stratification is additive: an M0-style construction still validates, the new
    fields default, and the verifiable/unverifiable counts partition citations_total."""
    m0_style = OnlineEvalMetrics(
        citation_hallucination_rate=2 / 3, findings_total=3, citations_total=3, hallucinations_total=2
    )
    assert m0_style.citation_hallucination_rate_verifiable == 0.0
    assert m0_style.unverifiable_share == 0.0
    assert m0_style.citations_verifiable_total == 0
    assert m0_style.citations_unverifiable_total == 0

    stratified = OnlineEvalMetrics(
        citation_hallucination_rate=0.0,
        citations_total=5,
        hallucinations_total=0,
        citation_hallucination_rate_verifiable=0.0,
        unverifiable_share=0.4,
        citations_verifiable_total=3,
        citations_unverifiable_total=2,
    )
    assert stratified.citations_verifiable_total + stratified.citations_unverifiable_total == stratified.citations_total


def test_eval_metrics_expert_edit_distance_defaults_to_zero() -> None:
    """M2 addition is additive: an M1-style construction still validates and the new field defaults."""
    m1_style = OnlineEvalMetrics(
        citation_hallucination_rate=0.2,
        citations_total=5,
        hallucinations_total=1,
        citation_hallucination_rate_verifiable=0.2,
        citations_verifiable_total=5,
    )
    assert m1_style.expert_edit_distance == 0.0


_AT = datetime(2026, 7, 9, 12, 0, 0)


def test_needs_review_defaults_to_pending_with_no_edit() -> None:
    """A freshly flagged finding is pending review with no edit yet."""
    draft = DraftRow(finding_id="f1", conformance=Conformance.DOES_NOT_SUPPORT, confidence=0.5)
    review = NeedsReview(
        finding_id="f1", run_id="r1", draft=draft, reason=ReviewReason.AXE_INCOMPLETE, created_at=_AT, updated_at=_AT
    )
    assert review.status is ReviewStatus.PENDING
    assert review.edited_draft is None


def test_needs_review_is_strict() -> None:
    """Contracts are strict: an unexpected field is a validation error."""
    draft = DraftRow(finding_id="f1", conformance=Conformance.DOES_NOT_SUPPORT, confidence=0.5)
    with pytest.raises(ValidationError):
        NeedsReview(
            finding_id="f1",
            run_id="r1",
            draft=draft,
            reason=ReviewReason.AXE_INCOMPLETE,
            created_at=_AT,
            updated_at=_AT,
            bogus=1,
        )


def test_run_state_defaults_to_running() -> None:
    """A freshly created run starts in the running state."""
    state = RunState(run_id="r1", config_id="m2-single@1", created_at=_AT)
    assert state.status is RunStatus.RUNNING


def test_step_state_defaults_to_pending_with_zero_attempts() -> None:
    """A freshly created step checkpoint has made no attempts yet."""
    step = StepState(run_id="r1", finding_id="f1", step=PipelineStep.RETRIEVE, updated_at=_AT)
    assert step.status is StepStatus.PENDING
    assert step.attempts == 0


def test_oracle_protocol_is_runtime_checkable() -> None:
    """A structural implementation satisfies isinstance(..., Oracle)."""

    class DummyOracle:
        def verdict_for(self, finding):  # noqa: ANN001, ANN201
            return None

        @property
        def regime(self):  # noqa: ANN201
            return OracleRegime.A_DIGITAL

        @property
        def version(self):  # noqa: ANN201
            return "test-1"

    assert isinstance(DummyOracle(), Oracle)


# ---------------------------------------------------------------------------
# M4: judge + calibration
# ---------------------------------------------------------------------------


def test_judge_verdict_wire_values_are_stable() -> None:
    """Wire strings are the contract; renaming a value is a breaking change."""
    assert JudgeVerdict.CORRECT.value == "correct"
    assert JudgeVerdict.INCORRECT.value == "incorrect"
    assert JudgeVerdict.PARTIAL.value == "partial"


def test_eval_metrics_judge_scalars_default_to_none() -> None:
    """M4 additions are additive: an M3-style construction still validates and every judge/
    calibration scalar defaults to None (M0–M3 runs carry no judge)."""
    m3_style = OnlineEvalMetrics(
        citation_hallucination_rate=0.0,
        citations_total=5,
        hallucinations_total=0,
        unverifiable_share=0.4,
        citations_verifiable_total=3,
        citations_unverifiable_total=2,
    )
    assert m3_style.judge_kappa is None
    assert m3_style.judge_agreement_rate is None
    assert m3_style.judge_gold_n is None
    assert m3_style.judge_trusted is None
    assert m3_style.judgment_correctness_rate is None
    assert m3_style.judgment_items_total is None
    assert m3_style.judgment_correct_total is None
    assert m3_style.expected_calibration_error is None
    assert m3_style.overconfidence_gap is None


def test_eval_metrics_composite_and_reflection_scaffold_default_to_none() -> None:
    """The composite (report ⊕ queue) hallucination fields and the reflection counters are
    inert scaffold: a construction that omits them still validates and every one defaults to
    None — 'not yet produced', never a measured zero. Nothing routes findings to the review
    queue and no reflection loop runs, so None is the only honest reading."""
    current_style = OnlineEvalMetrics(
        citation_hallucination_rate=0.0,
        citations_total=5,
        hallucinations_total=0,
        unverifiable_share=0.4,
        citations_verifiable_total=3,
        citations_unverifiable_total=2,
    )
    assert current_style.citation_hallucination_rate_composite is None
    assert current_style.hallucinations_queued_total is None
    assert current_style.citations_queued_total is None
    assert current_style.reflection_iterations_total is None
    assert current_style.reflection_caught_repaired_total is None


def test_eval_metrics_loads_persisted_payload_without_scaffold_fields() -> None:
    """A report persisted before the scaffold existed carries none of the new keys; under
    extra='forbid' it must still deserialise, with the scaffold fields defaulting to None."""
    persisted = json.dumps(
        {
            "citation_hallucination_rate": 0.2,
            "findings_total": 3,
            "citations_total": 5,
            "hallucinations_total": 1,
        }
    )
    m = OnlineEvalMetrics.model_validate_json(persisted)
    assert m.citation_hallucination_rate == 0.2
    assert m.citation_hallucination_rate_composite is None
    assert m.reflection_iterations_total is None


@pytest.mark.parametrize(
    "field",
    [
        "hallucinations_queued_total",
        "citations_queued_total",
        "reflection_iterations_total",
        "reflection_caught_repaired_total",
    ],
)
def test_eval_metrics_scaffold_counters_are_non_negative(field: str) -> None:
    """The queue and reflection counters are counts: a negative value is a validation error."""
    with pytest.raises(ValidationError):
        OnlineEvalMetrics(citation_hallucination_rate=0.0, **{field: -1})


@pytest.mark.parametrize("kappa", [-1.0, -0.42, 0.0, 0.6, 1.0])
def test_kappa_bounds_admit_negative_values(kappa: float) -> None:
    """The κ landmine: judge_kappa spans [-1, 1], NOT [0, 1]. A negative κ (judge worse than
    chance) is the single most important red flag and must validate — not crash the run —
    on both the report and the flat OnlineEvalMetrics scalar."""
    report = CalibrationReport(
        judge_kappa=kappa, judge_agreement=0.5, n=25, kappa_threshold=0.6, judge_trusted=False, created_at=_AT
    )
    assert report.judge_kappa == kappa
    assert OnlineEvalMetrics(citation_hallucination_rate=0.0, judge_kappa=kappa).judge_kappa == kappa


@pytest.mark.parametrize("kappa", [-1.0001, 1.5, 2.0])
def test_kappa_out_of_range_is_rejected(kappa: float) -> None:
    """κ is still bounded — outside [-1, 1] is invalid on both carriers."""
    with pytest.raises(ValidationError):
        CalibrationReport(
            judge_kappa=kappa, judge_agreement=0.5, n=1, kappa_threshold=0.6, judge_trusted=False, created_at=_AT
        )
    with pytest.raises(ValidationError):
        OnlineEvalMetrics(citation_hallucination_rate=0.0, judge_kappa=kappa)


def test_overconfidence_gap_is_signed_ece_is_unsigned() -> None:
    """overconfidence_gap is signed (positive = over-confident), bounded [-1, 1]; ECE is an
    unsigned magnitude, so a negative ECE is invalid."""
    m = OnlineEvalMetrics(citation_hallucination_rate=0.0, overconfidence_gap=-0.3, expected_calibration_error=0.3)
    assert m.overconfidence_gap == -0.3
    with pytest.raises(ValidationError):
        OnlineEvalMetrics(citation_hallucination_rate=0.0, expected_calibration_error=-0.1)


def test_gold_label_is_the_single_gold_shape() -> None:
    """GoldLabel carries a labeller + version and defaults optional severity/SCs/notes — the
    one gold shape reused across regimes (digital self-built now, expert physical later)."""
    label = GoldLabel(
        finding_id="f1",
        gold_success_criteria=["1.1.1"],
        gold_conformance=Conformance.DOES_NOT_SUPPORT,
        labeller="skinner",
        gold_version="digital-gold@1",
    )
    assert label.gold_severity is None
    assert label.notes == ""

    minimal = GoldLabel(
        finding_id="f2",
        gold_conformance=Conformance.SUPPORTS,
        gold_severity=Severity.SERIOUS,
        labeller="skinner",
        gold_version="digital-gold@1",
    )
    assert minimal.gold_success_criteria == []


def test_judge_result_decomposes_the_verdict() -> None:
    """A verdict decomposes into citation_correct + conformance_correct, and the judge model/
    version are recorded for reproducibility."""
    jr = JudgeResult(
        finding_id="f1",
        run_id="r1",
        judge_model="gpt-5.6-luna",
        judge_version="2026-01-01",
        verdict=JudgeVerdict.PARTIAL,
        citation_correct=True,
        conformance_correct=False,
        rationale="right SC, wrong conformance",
    )
    assert (jr.citation_correct, jr.conformance_correct) == (True, False)
    assert jr.judge_model == "gpt-5.6-luna"


def test_confidence_bin_requires_counts() -> None:
    """`n` and `correct_n` are mandatory — a bin without them would let the curve lie."""
    with pytest.raises(ValidationError):
        ConfidenceBin(lower=0.8, upper=1.0, mean_confidence=0.9, correctness_rate=0.5)


def test_calibration_report_holds_the_curve_and_is_strict() -> None:
    """The calibration curve lives on CalibrationReport as a typed ConfidenceBin list, and the
    model is strict like every contract."""
    report = CalibrationReport(
        judge_kappa=0.7,
        judge_agreement=0.85,
        n=28,
        kappa_threshold=0.6,
        judge_trusted=True,
        confidence_bins=[
            ConfidenceBin(lower=0.9, upper=1.0, n=20, mean_confidence=0.95, correctness_rate=0.6, correct_n=12)
        ],
        created_at=_AT,
    )
    assert report.judge_trusted is True
    assert report.confidence_bins[0].correct_n == 12
    with pytest.raises(ValidationError):
        CalibrationReport(
            judge_kappa=0.7,
            judge_agreement=0.85,
            n=1,
            kappa_threshold=0.6,
            judge_trusted=True,
            created_at=_AT,
            bogus=1,
        )


# ---------------------------------------------------------------------------
# GoldLabel gains an ACT-gold provenance (must stay backward-compatible)
# ---------------------------------------------------------------------------


def test_gold_label_new_provenance_fields_default_for_pre_existing_gold() -> None:
    """The two new fields are Optional-with-default: gold written before they existed (no
    `source`, no `act_testcase_id`) must still validate under extra='forbid', defaulting to
    self-built provenance. This is what keeps the M4 calibration gold loading."""
    pre_existing = GoldLabel(
        finding_id="f1",
        gold_success_criteria=["1.1.1"],
        gold_conformance=Conformance.DOES_NOT_SUPPORT,
        labeller="skinner",
        gold_version="quality-gold@1",
    )
    assert pre_existing.source == "self"
    assert pre_existing.act_testcase_id is None


def test_gold_label_carries_w3c_act_provenance() -> None:
    """W3C ACT gold records its external labeller + the case's content-hash id."""
    act = GoldLabel(
        finding_id="f1",
        gold_success_criteria=["2.4.6"],
        gold_conformance=Conformance.SUPPORTS,
        labeller="ACT Rules Community Group",
        gold_version="act-export@<sha>",
        source="w3c-act",
        act_testcase_id="0a1b2c3d",
    )
    assert (act.source, act.act_testcase_id) == ("w3c-act", "0a1b2c3d")


_CALIBRATION_SET = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "calibration_set.json"


@pytest.mark.skipif(not _CALIBRATION_SET.exists(), reason="calibration_set.json not built yet")
def test_existing_calibration_gold_still_loads_unchanged() -> None:
    """T0 acceptance: the existing M4 gold must load unchanged. Reconstruct a GoldLabel from each
    calibration_set.json row exactly as the replay path does (without the new fields) and confirm
    it validates, defaulting to self-built provenance."""
    rows = json.loads(_CALIBRATION_SET.read_text())["drafts"]
    assert rows, "calibration_set.json has no drafts to check"
    for row in rows:
        gold = GoldLabel(
            finding_id=row["finding_id"],
            gold_success_criteria=row["gold"]["gold_success_criteria"],
            gold_conformance=Conformance(row["gold"]["gold_conformance"]),
            labeller="(replay)",
            gold_version="(replay)",
        )
        assert gold.source == "self"
        assert gold.act_testcase_id is None


# ---------------------------------------------------------------------------
# Acceptance benchmark: OfflineEvalReport / OfflineEvalScorecard
# ---------------------------------------------------------------------------


def _ci(value: float, n: int) -> MetricCI:
    return MetricCI(value=value, n=n, ci_low=max(0.0, value - 0.1), ci_high=min(1.0, value + 0.1))


def _drafter_score() -> DrafterScore:
    return DrafterScore(
        recall=_ci(0.7, 23),
        false_positive_rate=_ci(0.2, 30),
        sc_citation_match=_ci(0.4, 16),
        expected_calibration_error=ExemptMetric(
            value=0.39, n=53, exempt_reason="single-bin overconfidence; nothing to bin"
        ),
        overconfidence_gap=0.39,
    )


def _judge_confusion() -> JudgeConfusion:
    return JudgeConfusion(
        correct_release=20,
        missed_error=2,
        false_alarm=3,
        correct_catch=5,
        miss_rate=ExemptMetric(
            value=2 / 7, n=7, exempt_reason="too few naturally-wrong drafts; see injected detection"
        ),
        false_alarm_rate=_ci(3 / 23, 23),
        kappa=0.6,
        injected_conformance_flip=_ci(0.8, 20),
        injected_sc_swap=_ci(0.9, 20),
    )


def _benchmark_report(scorecard: OfflineEvalScorecard) -> OfflineEvalReport:
    return OfflineEvalReport(
        run_ids=["r1"],
        config_id="bench-single@1",
        eval_set_id="act-acceptance@1",
        corpus_version="wcag22-nomic-embed-text-768@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="sha256:aaaa",
        judge_model="gpt-5.6-luna",
        judge_model_digest="sha256:bbbb",
        judge_version="rubric=e396f37f; effort=medium",
        axe_core_version="4.12.1",
        act_export_hash="sha1:cccc",
        created_at=_AT,
        scorecard=scorecard,
    )


def test_single_run_scorecard_is_complete_without_noise_floor_or_tier_b() -> None:
    """A single run has the drafter + judge scores; the noise floor (needs 3–5 repeats) and Tier B
    (built separately) are Optional and absent, while not_measured and the collapse rule default."""
    card = OfflineEvalScorecard(drafter=_drafter_score(), judge=_judge_confusion())
    assert card.noise_floor is None
    assert card.tier_b is None
    assert card.not_measured == []
    assert card.conformance_collapse_rule.startswith("FLAGS=")


def test_benchmark_report_nests_the_scorecard_and_round_trips() -> None:
    """The frozen artifact nests the scorecard and survives a JSON round-trip unchanged, carrying
    the model digests + ACT export hash that make it reproducible by content, not name."""
    card = OfflineEvalScorecard(
        drafter=_drafter_score(),
        judge=_judge_confusion(),
        noise_floor=NoiseFloor(
            runs=5,
            per_metric_sd={"false_positive_rate": 0.03, "recall": 0.04},
            min_detectable_improvement=0.04,
            dominant_source="binomial-sampling",
        ),
        tier_b=TierBSmoke(
            instance_ids=["b1", "b2"], method_and_limits="ACT snippet embedded intact; n=2, illustrative"
        ),
        not_measured=[NotMeasuredItem(what="expert-minutes-per-finding", why="needs a real specialist + stopwatch")],
    )
    report = _benchmark_report(card)
    assert report.scorecard.drafter.false_positive_rate.n == 30
    assert report.drafter_model_digest == "sha256:aaaa"
    assert OfflineEvalReport.model_validate_json(report.model_dump_json()) == report


def test_benchmark_report_is_strict() -> None:
    """Every contract is strict: an unexpected field on the frozen artifact is a validation error."""
    with pytest.raises(ValidationError):
        OfflineEvalReport(
            run_ids=["r1"],
            config_id="bench-single@1",
            eval_set_id="act-acceptance@1",
            corpus_version="v1",
            drafter_model="gemma4:31b",
            drafter_model_digest="sha256:aaaa",
            judge_model="gpt-5.6-luna",
            judge_model_digest="sha256:bbbb",
            judge_version="v1",
            axe_core_version="4.12.1",
            act_export_hash="sha1:cccc",
            created_at=_AT,
            scorecard=OfflineEvalScorecard(drafter=_drafter_score(), judge=_judge_confusion()),
            bogus=1,
        )


def test_metric_ci_and_exempt_metric_bounds() -> None:
    """MetricCI is a rate (bounds [0,1]); ExemptMetric must carry its mandatory reason and a rate
    out of range is rejected on both."""
    ci = MetricCI(value=0.2, n=30, ci_low=0.1, ci_high=0.35, effective_n=5)
    assert ci.ci_method == "wilson" and ci.effective_n == 5
    with pytest.raises(ValidationError):
        MetricCI(value=1.5, n=30, ci_low=0.1, ci_high=0.35)
    with pytest.raises(ValidationError):
        ExemptMetric(value=0.3, n=10)  # missing the mandatory exempt_reason
