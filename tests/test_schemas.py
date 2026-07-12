"""T0 acceptance tests: models import, JSON-schema smoke, extra=forbid, frozen OracleVerdict."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import BaseModel, ValidationError

from clearway import schemas
from clearway.schemas import models
from clearway.schemas.models import (
    AxeBucket,
    CalibrationReport,
    ConfidenceBin,
    Conformance,
    CorpusChunk,
    DraftRow,
    EvalMetrics,
    EvidenceQuery,
    Finding,
    GoldLabel,
    JudgeResult,
    JudgeVerdict,
    L1Status,
    NeedsReview,
    Oracle,
    OracleRegime,
    OracleVerdict,
    PipelineStep,
    ReviewReason,
    ReviewStatus,
    RunState,
    RunStatus,
    Severity,
    StepState,
    StepStatus,
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
    m0_style = EvalMetrics(
        citation_hallucination_rate=2 / 3, findings_total=3, citations_total=3, hallucinations_total=2
    )
    assert m0_style.citation_hallucination_rate_verifiable == 0.0
    assert m0_style.unverifiable_share == 0.0
    assert m0_style.citations_verifiable_total == 0
    assert m0_style.citations_unverifiable_total == 0

    stratified = EvalMetrics(
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
    m1_style = EvalMetrics(
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
            reason=ReviewReason.LOW_CONFIDENCE,
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
    m3_style = EvalMetrics(
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


@pytest.mark.parametrize("kappa", [-1.0, -0.42, 0.0, 0.6, 1.0])
def test_kappa_bounds_admit_negative_values(kappa: float) -> None:
    """The κ landmine: judge_kappa spans [-1, 1], NOT [0, 1]. A negative κ (judge worse than
    chance) is the single most important red flag and must validate — not crash the run —
    on both the report and the flat EvalMetrics scalar."""
    report = CalibrationReport(
        judge_kappa=kappa, judge_agreement=0.5, n=25, kappa_threshold=0.6, judge_trusted=False, created_at=_AT
    )
    assert report.judge_kappa == kappa
    assert EvalMetrics(citation_hallucination_rate=0.0, judge_kappa=kappa).judge_kappa == kappa


@pytest.mark.parametrize("kappa", [-1.0001, 1.5, 2.0])
def test_kappa_out_of_range_is_rejected(kappa: float) -> None:
    """κ is still bounded — outside [-1, 1] is invalid on both carriers."""
    with pytest.raises(ValidationError):
        CalibrationReport(
            judge_kappa=kappa, judge_agreement=0.5, n=1, kappa_threshold=0.6, judge_trusted=False, created_at=_AT
        )
    with pytest.raises(ValidationError):
        EvalMetrics(citation_hallucination_rate=0.0, judge_kappa=kappa)


def test_overconfidence_gap_is_signed_ece_is_unsigned() -> None:
    """overconfidence_gap is signed (positive = over-confident), bounded [-1, 1]; ECE is an
    unsigned magnitude, so a negative ECE is invalid."""
    m = EvalMetrics(citation_hallucination_rate=0.0, overconfidence_gap=-0.3, expected_calibration_error=0.3)
    assert m.overconfidence_gap == -0.3
    with pytest.raises(ValidationError):
        EvalMetrics(citation_hallucination_rate=0.0, expected_calibration_error=-0.1)


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
