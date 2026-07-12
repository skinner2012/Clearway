from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# Enums (wire-stable string values)
# ============================================================


class ConformanceLevel(str, Enum):
    """WCAG level at which a success criterion sits."""

    A = "A"
    AA = "AA"
    AAA = "AAA"


class Conformance(str, Enum):
    """VPAT/ACR conformance verdict for a finding (the specialist's terms)."""

    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    DOES_NOT_SUPPORT = "does_not_support"
    NOT_APPLICABLE = "not_applicable"


class Severity(str, Enum):
    """axe-core impact levels."""

    MINOR = "minor"
    MODERATE = "moderate"
    SERIOUS = "serious"
    CRITICAL = "critical"


class CitationVerdict(str, Enum):
    """Result of validating one cited SC against the trust layers (ARCHITECTURE 4.8)."""

    VERIFIED = "verified"  # passed L0 and matched the oracle (L1)
    HALLUCINATED = "hallucinated"  # failed L0 (not a real SC) or contradicted the oracle
    UNVERIFIABLE = "unverifiable"  # valid SC (L0) but no oracle verdict to check against


class L1Status(str, Enum):
    """L1 citation-check outcome vs the oracle verdict (validator/, ARCHITECTURE 4.8)."""

    MATCH = "match"  # cited SC is in the oracle verdict's SCs
    MISMATCH = "mismatch"  # cited SC is contradicted by the oracle
    NO_ORACLE = "no_oracle"  # no oracle verdict to check against


class OracleRegime(str, Enum):
    """Which oracle regime produced a verdict / eval run (the transfer seam, §5)."""

    A_DIGITAL = "A-digital"  # Regime A: axe-core, near-free hard oracle
    B_PHYSICAL = "B-physical"  # Regime B: expert gold — costly, sparse


class AxeBucket(str, Enum):
    """Which axe result array a Finding came from — its provenance, and why it does (or
    doesn't) carry an oracle verdict:
    - VIOLATIONS — axe decided the element fails: hard ground truth, oracle-backed.
    - INCOMPLETE — axe ran the rule but could NOT decide (needs pixels / render / media
      it can't see): no oracle verdict, feeds `unverifiable_share`.
    - PASSES — axe confirmed something EXISTS (an alt, an accessible name, a title) but
      does not judge its QUALITY. A whitelist of existence-only rules is surfaced from
      here as judgment findings ("exists, quality unjudged"); non-whitelisted passes are
      not findings. This is the LLM-judge's real domain — quality IS decidable from the
      DOM the drafter sees (unlike INCOMPLETE, which usually isn't).
    The oracle allowlists VIOLATIONS only: INCOMPLETE and PASSES have no oracle verdict
    and score UNVERIFIABLE (never folded into the verified count). Values match axe's
    payload keys."""

    VIOLATIONS = "violations"  # confirmed failure — oracle-backed
    INCOMPLETE = "incomplete"  # axe couldn't decide — no oracle verdict
    PASSES = "passes"  # exists but quality unjudged — whitelisted judgment source, no oracle


class JudgeVerdict(str, Enum):
    """LLM-judge verdict on one drafted judgment item (M4). `partial` = exactly one of
    citation / conformance is correct; severity is not part of the verdict."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"


# ============================================================
# Scanner output  (scanner/ -> normalizer/)
# ============================================================


class AxeNode(BaseModel):
    """One offending DOM node inside an axe violation."""

    model_config = ConfigDict(extra="forbid")

    target: list[str] = Field(..., description="CSS selector path(s) to the node")
    html: str = Field("", description="outer HTML snippet of the node")


class AxeRuleResult(BaseModel):
    """One axe rule result over a page (may span multiple nodes). Base for the buckets
    we consume — `violations` (confirmed), `incomplete` (needs review), and whitelisted
    `passes` (existence-only → quality-review) — which are structurally identical in the
    axe payload."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., description="axe rule id, e.g. 'image-alt'")
    tags: list[str] = Field(
        default_factory=list,
        description="axe tags, e.g. ['wcag2a', 'wcag111'] — the L1 ground-truth carrier",
    )
    impact: Optional[Severity] = None
    help: str = ""
    help_url: str = ""
    nodes: list[AxeNode] = Field(default_factory=list)


class AxeViolation(AxeRuleResult):
    """A confirmed axe-core violation (axe's `violations` bucket)."""


class AxeIncomplete(AxeRuleResult):
    """An axe needs-review result (axe's `incomplete` bucket): the rule ran but axe could
    not decide, so ground truth is unknown. These are the oracle-poor / judgment items —
    the source of eval's `unverifiable_share`. Same shape as a violation, but NOT confirmed."""


class AxePass(AxeRuleResult):
    """An axe PASS result (axe's `passes` bucket): the rule's mechanical check succeeded — a
    name / attribute / title EXISTS. For a whitelist of existence-only rules, passing means only
    "present", never "meaningful", so the normalizer surfaces those as quality-review judgment
    findings (`AxeBucket.PASSES`). Same shape as a violation, but a PASS, not a failure."""


class ScanResult(BaseModel):
    """Output of scanner/ for one page scan. Consumed by normalizer/."""

    model_config = ConfigDict(extra="forbid")

    url: str
    scanned_at: datetime
    tool: str = "axe-core"
    tool_version: str = Field(..., description="pinned axe-core version, for reproducibility")
    violations: list[AxeViolation] = Field(default_factory=list)
    incomplete: list[AxeIncomplete] = Field(
        default_factory=list, description="axe needs-review items, kept distinct from violations"
    )
    passes: list[AxePass] = Field(
        default_factory=list,
        description="axe's passes[] bucket (faithful mirror); the normalizer surfaces a whitelisted "
        "existence-only subset as quality-review judgment findings",
    )
    raw: dict = Field(default_factory=dict, description="full axe payload passthrough (untyped)")


# ============================================================
# Canonical finding  (normalizer/ -> everything downstream)
# ============================================================


class Finding(BaseModel):
    """A normalized, de-duplicated single issue."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="deterministic hash of (source_url, rule_id, target) — dedup + idempotency key")
    source_url: str
    rule_id: str
    axe_tags: list[str] = Field(
        default_factory=list,
        description="carried from the scan; AxeCoreOracle derives SC ids from these",
    )
    target: str = Field(..., description="primary CSS selector")
    html: str = Field("", description="offending element snippet")
    impact: Optional[Severity] = None
    help: str = ""
    help_url: str = ""
    source_bucket: AxeBucket = Field(
        AxeBucket.VIOLATIONS,
        description="axe provenance; the oracle only grounds VIOLATIONS. Not part of the id "
        "(a place is never in two buckets at once).",
    )


# ============================================================
# Reuse-shaped retrieval input  (any caller -> retriever/ over MCP)
# ============================================================


class EvidenceQuery(BaseModel):
    """A described accessibility problem — the slim, reuse-shaped input the MCP retrieval
    tool accepts. Deliberately NOT a `Finding`: it omits the internal hashed `id`,
    `source_url`, and CSS `target` an external caller does not possess. A `Finding` maps to
    an `EvidenceQuery` losslessly for retrieval (rule_id -> rule_id, help -> description),
    since the retriever's query text stays `f"{rule_id} {description}".strip()`."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field("", description="optional axe rule id, if the caller has one")
    description: str = Field(..., description="the human-readable problem")


# ============================================================
# Corpus / RAG grounding  (corpus/ -> retriever/, M1)
# ============================================================


class CorpusChunk(BaseModel):
    """One embedded WCAG/ARIA corpus chunk: corpus/ produces these, retriever/ queries them.
    `embedding` lives in pgvector, not in the transported contract — it is optional and
    excluded from serialization; the field exists only so ingestion can carry it in-process."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="stable id for this chunk within a corpus_version")
    sc_ids: list[str] = Field(
        default_factory=list, description="canonical WCAG 2.2 SC ids this chunk grounds, e.g. ['1.1.1']"
    )
    text: str = Field(..., description="the chunk's retrievable text")
    source: str = Field("", description="corpus origin: 'WCAG-SC' | 'Understanding' | 'Technique' | 'ARIA-APG'")
    url: str = ""
    corpus_version: str = Field(..., description="frozen corpus build id; encodes the embedding model + dimension")
    embedding: Optional[list[float]] = Field(
        default=None,
        exclude=True,
        repr=False,
        description="dense vector; lives in pgvector, excluded from serialization",
    )


# ============================================================
# Retrieval output  (retriever/ — STUB in M0, real in M1)
# ============================================================


class Citation(BaseModel):
    """A reference to a WCAG success criterion (+ optional fix technique)."""

    model_config = ConfigDict(extra="forbid")

    sc_id: str = Field(..., description="canonical WCAG 2.2 SC id, e.g. '1.1.1'")
    title: str = ""
    level: Optional[ConformanceLevel] = None
    source: str = Field("", description="corpus origin: 'WCAG-SC' | 'Understanding' | 'Technique' | 'ARIA-APG'")
    url: str = ""
    technique_id: Optional[str] = None


# ============================================================
# Drafting output  (drafter/ — STUB in M0)
# ============================================================


class DraftRow(BaseModel):
    """A drafted ACR/VPAT row for one finding.
    What validator/ checks and what a human later approves/edits."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    conformance: Conformance
    citations: list[Citation] = Field(default_factory=list)
    remediation: str = ""
    severity: Optional[Severity] = None
    confidence: float = Field(..., ge=0.0, le=1.0, description="model's self-reported confidence")


# ============================================================
# Validation output  (validator/ — trust layering 4.8)
# ============================================================


class CitationCheck(BaseModel):
    """Result of validating one cited SC."""

    model_config = ConfigDict(extra="forbid")

    sc_id: str
    l0_valid: bool = Field(..., description="L0: sc_id is a real WCAG 2.2 SC")
    l1_status: L1Status = Field(..., description="L1 result vs the oracle verdict")
    verdict: CitationVerdict


# ============================================================
# Observability record  (orchestrator/ + observability/ -> eval/)
# ============================================================


class Trace(BaseModel):
    """Per-finding provenance + operational record. Also emitted as OTel span
    attributes; eval/ aggregates these. `checks` is the authoritative per-finding
    CitationCheck record — eval/ reads them from the traces, not a separate list."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    finding_id: str
    config_id: str = Field(..., description="frozen routing-config id (single model in M0)")
    model: str = Field(..., description="model that produced the draft")
    retrieved_sc_ids: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    cost_usd: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[float] = None
    checks: list[CitationCheck] = Field(default_factory=list)
    created_at: datetime


# ============================================================
# Durable orchestration + HITL  (orchestrator/, M2 — ARCHITECTURE §4.6)
# ============================================================


class PipelineStep(str, Enum):
    """The three per-finding steps the durable orchestrator checkpoints (M1's real modules)."""

    RETRIEVE = "retrieve"
    DRAFT = "draft"
    VALIDATE = "validate"


class RunStatus(str, Enum):
    """Lifecycle of one orchestrator run — the `RunState` checkpoint."""

    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Lifecycle of one finding's one step — the `StepState` checkpoint / resume unit."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class RunState(BaseModel):
    """Durable run-level checkpoint: persisted so a killed run can be found and resumed."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    config_id: str
    status: RunStatus = RunStatus.RUNNING
    created_at: datetime


class StepState(BaseModel):
    """Durable per-(finding, step) checkpoint — the resume unit. Idempotency key is
    `(run_id, finding_id, step)`: a completed step re-runs as a no-op on resume. Distinct
    from `Finding.id`'s cross-run content-hash dedup — a fresh run of the same page still
    re-processes every step."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    finding_id: str
    step: PipelineStep
    status: StepStatus = StepStatus.PENDING
    attempts: int = Field(0, description="retry attempts made on this step so far")
    updated_at: datetime = Field(..., description="last transition time — the checkpoint clock")


class ReviewReason(str, Enum):
    """Why a finding was flagged for human review. When more than one applies, precedence is
    LOW_CONFIDENCE > AXE_INCOMPLETE > UNVERIFIABLE_JUDGMENT (orchestrator/, T3) — a single
    reason is stored, not a set."""

    LOW_CONFIDENCE = "low_confidence"
    AXE_INCOMPLETE = "axe_incomplete"
    UNVERIFIABLE_JUDGMENT = "unverifiable_judgment"


class ReviewStatus(str, Enum):
    """Lifecycle of one `NeedsReview` record, driven by the human reviewer."""

    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class NeedsReview(BaseModel):
    """A finding flagged for human review — the HITL durable-interrupt record (ARCHITECTURE
    §4.6). Written post-validation (it carries the drafted+checked `DraftRow`), so a human can
    approve, edit, or reject it from a separate entrypoint (`clearway review`); an edit's
    `edited_draft` is what T4's `expert_edit_distance` measures against `draft`."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    run_id: str
    draft: DraftRow
    reason: ReviewReason
    status: ReviewStatus = ReviewStatus.PENDING
    edited_draft: Optional[DraftRow] = None
    created_at: datetime
    updated_at: datetime


# ============================================================
# Eval output  (eval/)
# ============================================================


class EvalMetrics(BaseModel):
    """Trust metrics for one eval run. M1 stratifies the hallucination rate by whether an
    automated oracle could verify the citation: the verifiable subset (axe-detectable, ~0 by
    construction) vs the unverifiable share (judgment items with no oracle — the honest
    headline, and exactly what M4's judge/gold must target). M2 adds `expert_edit_distance`,
    the human-correction signal from the HITL gate. M4 adds judge-reliability (κ),
    judgment-item correctness, and confidence-calibration scalars — all Optional; the
    calibration curve itself is a typed list on `CalibrationReport`, never copied here."""

    model_config = ConfigDict(extra="forbid")

    citation_hallucination_rate: float = Field(
        ..., ge=0.0, le=1.0, description="overall: hallucinations / all citations"
    )
    findings_total: int = 0
    citations_total: int = 0
    hallucinations_total: int = 0

    # M1 stratification. Invariant: citations_verifiable_total + citations_unverifiable_total == citations_total.
    # UNVERIFIABLE is never a hallucination, so hallucinations_total is the numerator for BOTH rates.
    citation_hallucination_rate_verifiable: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="hallucinations / oracle-verifiable citations (axe-detectable; ~0 by construction)",
    )
    unverifiable_share: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="unverifiable citations / all citations — the honest headline (no automated oracle)",
    )
    citations_verifiable_total: int = Field(
        0, description="citations with a definitive oracle verdict (VERIFIED | HALLUCINATED)"
    )
    citations_unverifiable_total: int = Field(0, description="citations with no oracle verdict (UNVERIFIABLE)")

    # M2: human-correction signal from the HITL gate (needs a NeedsReview.edited_draft to exist).
    expert_edit_distance: float = Field(
        0.0,
        ge=0.0,
        description="mean human-edit distance over reviewed drafts this run (0 = no edits needed); "
        "unbounded above — M2 uses a normalized [0,1] text ratio, type stays open for a future distance function",
    )

    # M4: judge reliability + judgment-item correctness + confidence calibration. All Optional
    # (M0–M3 runs carry no judge). SCALARS ONLY — the full calibration curve is a typed list on
    # CalibrationReport, never copied here. Store numerators + denominators, not just rates.
    judge_kappa: Optional[float] = Field(
        None,
        ge=-1.0,
        le=1.0,
        description="judge-vs-human Cohen's κ. Bounds [-1,1]: a negative κ (judge worse than chance) is the single "
        "most important red flag — do NOT copy ge=0.0 from the rate fields above",
    )
    judge_agreement_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="raw judge-vs-human agreement proportion"
    )
    judge_gold_n: Optional[int] = Field(None, ge=0, description="gold findings the judge was calibrated on")
    judge_trusted: Optional[bool] = Field(None, description="did the judge clear the pre-committed κ bar")
    judgment_correctness_rate: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="judge-scored correctness over judgment items — an ESTIMATE capped by κ, not promoted to "
        "verified (unverifiable_share stays as-is)",
    )
    judgment_items_total: Optional[int] = Field(None, ge=0, description="judgment items the judge scored — denominator")
    judgment_correct_total: Optional[int] = Field(None, ge=0, description="judgment items judged correct — numerator")
    expected_calibration_error: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="ECE — unsigned magnitude of confidence miscalibration"
    )
    overconfidence_gap: Optional[float] = Field(
        None,
        ge=-1.0,
        le=1.0,
        description="signed: mean confidence − mean correctness; positive = systematically over-confident",
    )


class EvalReport(BaseModel):
    """Output of eval/ for one run over a fixed eval set."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    config_id: str
    eval_set_id: str = Field(..., description="fixture-set id + version, for reproducibility")
    oracle_regime: OracleRegime = Field(..., description="which oracle regime this run used")
    oracle_version: str
    created_at: datetime
    metrics: EvalMetrics
    trace_ids: list[str] = Field(default_factory=list, description="per-finding traces this report aggregates")


# ============================================================
# Oracle — the transfer seam  (oracle/; consumed by validator/ L1 + eval/)
# ============================================================


class OracleVerdict(BaseModel):
    """Ground-truth answer for a single finding, from whatever oracle is in play."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    success_criteria: list[str] = Field(default_factory=list, description="canonical WCAG SC ids, e.g. ['1.1.1']")
    conformance: Optional[Conformance] = None
    severity: Optional[Severity] = None
    source: str = ""  # "axe-core" | "expert-gold"
    confidence: float = 1.0  # 1.0 for hard oracle; <1.0 for expert gold
    raw: dict = Field(default_factory=dict)


@runtime_checkable
class Oracle(Protocol):
    """The single seam that makes Regime A <-> Regime B a swap, not a rewrite.
    eval/ and validator/ (L1) depend ONLY on this Protocol.

    Regime A: AxeCoreOracle   (near-free, hard ground truth from axe tags)
    Regime B: GoldLabelOracle (expert-provided, costly, sparse)  [M6]
    """

    def verdict_for(self, finding: Finding) -> Optional[OracleVerdict]:
        """Ground truth for a finding, or None if this oracle can't judge it
        (-> falls through to LLM-judge / human review)."""
        ...

    @property
    def regime(self) -> OracleRegime: ...  # Regime A (digital) or B (physical)

    @property
    def version(self) -> str: ...  # pinned for reproducibility


# ============================================================
# Judge + calibration  (eval/ — LLM-judge for no-oracle judgment items, M4)
# ============================================================


class GoldLabel(BaseModel):
    """Human-assigned ground truth for one judgment-item finding. The SINGLE gold shape:
    self-built digital gold now (labelled with WCAG knowledge, no external expert), and the
    same shape a future Regime B `GoldLabelOracle` reuses for expert physical gold — one gold
    contract, two labellers/regimes. Do NOT fork a second gold schema."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    gold_success_criteria: list[str] = Field(
        default_factory=list, description="canonical WCAG 2.2 SC ids the labeller assigns as correct, e.g. ['1.1.1']"
    )
    gold_conformance: Conformance
    gold_severity: Optional[Severity] = None
    labeller: str = Field(
        ..., description="who produced this label — judge-vs-human κ is really judge-vs-this-one-labeller"
    )
    gold_version: str = Field(..., description="versioned gold-set id, for reproducibility")
    notes: str = Field("", description="labelling basis / WCAG spot-check disagreements")


class JudgeResult(BaseModel):
    """One LLM-judge verdict on one drafted judgment-item finding. Kept SEPARATE from
    `CitationCheck`: a per-draft correctness verdict is a different granularity than the
    per-citation validator layer — which is why L2-faithfulness fields on `CitationCheck` stay
    deferred. The judge scores citation + conformance only (severity is out of the verdict:
    noisier, lower-stakes). Used ONLY for no-oracle judgment items, never the axe-verifiable
    subset, and only after the judge is calibrated (κ)."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    run_id: str
    judge_model: str = Field(..., description="judge model id — MUST differ from the drafter model (self-preference)")
    judge_version: str = Field(
        ..., description="pinned judge snapshot + temperature/prompt provenance, for reproducibility"
    )
    verdict: JudgeVerdict = Field(
        ..., description="correct | incorrect | partial (partial = one dimension right, the other wrong)"
    )
    citation_correct: bool = Field(..., description="drafted SC(s) judged correct for the finding")
    conformance_correct: bool = Field(..., description="drafted conformance judged correct for the finding")
    rationale: str = Field(..., description="the judge's justification (rubric-based absolute scoring)")


class ConfidenceBin(BaseModel):
    """One bin of the confidence-vs-correctness calibration curve. `n` and `correct_n` are
    MANDATORY — a bin with n=1 otherwise makes the curve lie. This typed list (on
    `CalibrationReport`) is the curve's only home; it is never copied onto `EvalMetrics`."""

    model_config = ConfigDict(extra="forbid")

    lower: float = Field(..., ge=0.0, le=1.0, description="bin lower edge (drafter confidence)")
    upper: float = Field(..., ge=0.0, le=1.0, description="bin upper edge (drafter confidence)")
    n: int = Field(..., ge=0, description="drafts in this bin — mandatory")
    mean_confidence: float = Field(..., ge=0.0, le=1.0, description="mean self-reported confidence in the bin")
    correctness_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="fraction correct in the bin (oracle for verifiable items, trusted judge for judgment items)",
    )
    correct_n: int = Field(..., ge=0, description="correct count in the bin — mandatory")


class CalibrationReport(BaseModel):
    """Judge reliability (judge-vs-human κ against the gold set) + the confidence-vs-correctness
    curve. κ is judge-vs-ONE-labeller, not judge-vs-consensus — do not over-read it. A judge is
    only trusted to score models once κ clears a bar committed BEFORE the number is seen."""

    model_config = ConfigDict(extra="forbid")

    judge_kappa: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Cohen's κ, judge vs human-derived verdicts. Bounds [-1,1]: a negative κ (judge worse than "
        "chance) is the key red flag and must NOT be clamped to 0",
    )
    judge_agreement: float = Field(..., ge=0.0, le=1.0, description="raw agreement proportion, reported alongside κ")
    n: int = Field(
        ...,
        ge=0,
        description="gold findings compared (effective n is lower — same-fixture findings are correlated)",
    )
    kappa_threshold: float = Field(..., ge=-1.0, le=1.0, description="the trust bar, pre-committed before κ is seen")
    judge_trusted: bool = Field(
        ..., description="κ >= threshold; only a trusted judge may score models on non-gold items"
    )
    confidence_bins: list[ConfidenceBin] = Field(
        default_factory=list, description="the full calibration curve — a list, not a scalar; the curve's only home"
    )
    bias_notes: str = Field(
        "", description="verbosity / self-preference observations (position bias N/A — absolute rubric scoring)"
    )
    created_at: datetime
