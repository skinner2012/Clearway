# Clearway — CONTRACTS

- **Status:** Draft
- **Date:** 2026-07-05
- **Author:** FuYuan (Skinner) Cheng
- **Version:** 0.14

> **This file is the single source of truth for cross-module data shapes.** Any shape that crosses a module boundary is defined here and nowhere else — never redefined in `ARCHITECTURE.md`, in module code, or in an LLM prompt. `ARCHITECTURE.md §5` describes the `Oracle` seam's *role* and points back here for the definition. To add or change a shape: edit §3, then update the deferred list (§5) and the change log (§6) in the same change.

## Table of Contents

1. [Purpose & scope](#1-purpose--scope)
2. [Conventions](#2-conventions)
3. [Schemas (the contract)](#3-schemas-the-contract)
4. [Cross-module invariants](#4-cross-module-invariants)
5. [Deferred](#5-deferred)
6. [Change log](#6-change-log)

---

## 1. Purpose & scope

Every module under `clearway/` depends on these shapes; nothing else may be shared across module boundaries. Locking them first is what lets subagents work in parallel (one `git worktree` per module) without their interfaces drifting.

---

## 2. Conventions

- **Pydantic v2**, Python 3.13+.
- **IDs are opaque strings.** `Finding.id` is a deterministic content hash of `(source_url, rule_id, target)` so re-scans de-duplicate and every pipeline step is idempotent on it.
- **Timestamps are timezone-aware UTC** (`datetime`).
- **Ground truth is immutable:** `OracleVerdict` is frozen.
- **Strict by default:** contracts should set `extra="forbid"` to catch drift/typos at boundaries. The one intentional untyped passthrough is `ScanResult.raw` (the full axe payload).
- **Enum string values are the wire format** — stable; renaming a value is a breaking change and needs a version bump.
- **SC ids are canonical WCAG 2.2 dotted ids** (e.g. `"1.1.1"`), never prefixed forms like `wcag111`.
- **`impact` and `severity` are the same `Severity` enum.** Scanner/finding fields use axe-core's native term `impact`; drafted, validated, and oracle fields use `severity`. Same values — the name differs by origin.

---

## 3. Schemas (the contract)

Copy-pasteable as `clearway/schemas/models.py`.

```python
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
    VERIFIED = "verified"          # passed L0 and matched the oracle (L1)
    HALLUCINATED = "hallucinated"  # failed L0 (not a real SC) or contradicted the oracle
    UNVERIFIABLE = "unverifiable"  # valid SC (L0) but no oracle verdict to check against


class L1Status(str, Enum):
    """L1 citation-check outcome vs the oracle verdict (validator/, ARCHITECTURE 4.8)."""
    MATCH = "match"            # cited SC is in the oracle verdict's SCs
    MISMATCH = "mismatch"      # cited SC is contradicted by the oracle
    NO_ORACLE = "no_oracle"    # no oracle verdict to check against


class OracleRegime(str, Enum):
    """Which oracle regime produced a verdict / eval run (the transfer seam, §5)."""
    A_DIGITAL = "A-digital"    # Regime A: axe-core, near-free hard oracle
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
    PASSES = "passes"          # exists but quality unjudged — whitelisted judgment source, no oracle


class JudgeVerdict(str, Enum):
    """LLM-judge verdict on one drafted judgment item. `partial` = exactly one of
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
# Corpus / RAG grounding  (corpus/ -> retriever/)
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
        default=None, exclude=True, repr=False,
        description="dense vector; lives in pgvector, excluded from serialization",
    )


# ============================================================
# Retrieval output  (retriever/)
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
# Drafting output  (drafter/)
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
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="model's self-reported confidence. DECORATIVE — do NOT gate, route, or triage on it: "
        "measured to carry no usable signal (held-out over-confidence gap +0.329; values pinned ~0.85-1.0 "
        "regardless of correctness). Derive a real trust signal elsewhere — see docs/acceptance-analysis.md.",
    )


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
    config_id: str = Field(..., description="frozen routing-config id")
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
# Durable orchestration + HITL  (orchestrator/ — ARCHITECTURE §4.6)
# ============================================================

class PipelineStep(str, Enum):
    """The three per-finding steps the durable orchestrator checkpoints."""
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

class OnlineEvalMetrics(BaseModel):
    """Trust metrics for one eval run. The hallucination rate is stratified by whether an
    automated oracle could verify the citation: the verifiable subset (axe-detectable, ~0 by
    construction) vs the unverifiable share (judgment items with no oracle — the honest
    headline, and what the judge/gold exist to target). `expert_edit_distance` is the
    human-correction signal from the HITL gate. Judge-reliability (κ), judgment-item
    correctness, and confidence-calibration scalars are all Optional; the calibration curve
    itself is a typed list on `CalibrationReport`, never copied here."""
    model_config = ConfigDict(extra="forbid")

    citation_hallucination_rate: float = Field(..., ge=0.0, le=1.0, description="overall: hallucinations / all citations")
    findings_total: int = 0
    citations_total: int = 0
    hallucinations_total: int = 0

    # Stratification. Invariant: citations_verifiable_total + citations_unverifiable_total == citations_total.
    # UNVERIFIABLE is never a hallucination, so hallucinations_total is the numerator for BOTH rates below.
    citation_hallucination_rate_verifiable: float = Field(
        0.0, ge=0.0, le=1.0, description="hallucinations / oracle-verifiable citations (axe-detectable; ~0 by construction)"
    )
    unverifiable_share: float = Field(
        0.0, ge=0.0, le=1.0, description="unverifiable citations / all citations — the honest headline (no automated oracle)"
    )
    citations_verifiable_total: int = Field(0, description="citations with a definitive oracle verdict (VERIFIED | HALLUCINATED)")
    citations_unverifiable_total: int = Field(0, description="citations with no oracle verdict (UNVERIFIABLE)")

    # Human-correction signal from the HITL gate (needs a NeedsReview.edited_draft to exist).
    expert_edit_distance: float = Field(
        0.0, ge=0.0, description="mean human-edit distance over reviewed drafts this run (0 = no edits "
        "needed); unbounded above — a normalized [0,1] text ratio, type stays open for a future "
        "distance function"
    )

    # Judge reliability + judgment-item correctness + confidence calibration. All Optional
    # (a run without a judge carries none of these). SCALARS ONLY — the full calibration curve is a typed list on
    # CalibrationReport, never copied here. Store numerators + denominators, not just rates.
    judge_kappa: Optional[float] = Field(
        None, ge=-1.0, le=1.0, description="judge-vs-human Cohen's κ. Bounds [-1,1]: a negative κ (judge worse "
        "than chance) is the single most important red flag — do NOT copy ge=0.0 from the rate fields above",
    )
    judge_agreement_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="raw judge-vs-human agreement proportion")
    judge_gold_n: Optional[int] = Field(None, ge=0, description="gold findings the judge was calibrated on")
    judge_trusted: Optional[bool] = Field(None, description="did the judge clear the pre-committed κ bar")
    judgment_correctness_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="judge-scored correctness over judgment items — an ESTIMATE capped by κ, "
        "not promoted to verified (unverifiable_share stays as-is)",
    )
    judgment_items_total: Optional[int] = Field(None, ge=0, description="judgment items the judge scored — denominator")
    judgment_correct_total: Optional[int] = Field(None, ge=0, description="judgment items judged correct — numerator")
    expected_calibration_error: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="ECE — unsigned magnitude of confidence miscalibration"
    )
    overconfidence_gap: Optional[float] = Field(
        None, ge=-1.0, le=1.0, description="signed: mean confidence − mean correctness; positive = systematically over-confident"
    )


class OnlineEvalReport(BaseModel):
    """Output of eval/ for one run over a fixed eval set."""
    model_config = ConfigDict(extra="forbid")

    run_id: str
    config_id: str
    eval_set_id: str = Field(..., description="fixture-set id + version, for reproducibility")
    oracle_regime: OracleRegime = Field(..., description="which oracle regime this run used")
    oracle_version: str
    created_at: datetime
    metrics: OnlineEvalMetrics
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
    source: str = ""                     # "axe-core" | "expert-gold"
    confidence: float = 1.0              # 1.0 for hard oracle; <1.0 for expert gold
    raw: dict = Field(default_factory=dict)


@runtime_checkable
class Oracle(Protocol):
    """The single seam that makes Regime A <-> Regime B a swap, not a rewrite.
    eval/ and validator/ (L1) depend ONLY on this Protocol.

    Regime A: AxeCoreOracle   (near-free, hard ground truth from axe tags)
    Regime B: GoldLabelOracle (expert-provided, costly, sparse)
    """

    def verdict_for(self, finding: Finding) -> Optional[OracleVerdict]:
        """Ground truth for a finding, or None if this oracle can't judge it
        (-> falls through to LLM-judge / human review)."""
        ...

    @property
    def regime(self) -> OracleRegime: ...  # Regime A (digital) or B (physical)

    @property
    def version(self) -> str: ...        # pinned for reproducibility


# ============================================================
# Judge + calibration  (eval/ — LLM-judge for no-oracle judgment items)
# ============================================================

class GoldLabel(BaseModel):
    """Human-assigned ground truth for one judgment-item finding. The SINGLE gold shape:
    self-built digital gold now (labelled with WCAG knowledge, no external expert), and the
    same shape a future Regime B `GoldLabelOracle` reuses for expert physical gold — one gold
    contract, two labellers/regimes. Do NOT fork a second gold schema. `source` records which
    labeller regime produced the label — self-built WCAG gold or external W3C ACT expert gold."""
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    gold_success_criteria: list[str] = Field(
        default_factory=list, description="canonical WCAG 2.2 SC ids the labeller assigns as correct, e.g. ['1.1.1']"
    )
    gold_conformance: Conformance
    gold_severity: Optional[Severity] = None
    labeller: str = Field(..., description="who produced this label — judge-vs-human κ is really judge-vs-this-one-labeller")
    gold_version: str = Field(..., description="versioned gold-set id, for reproducibility")
    source: str = Field(
        "self", description='label provenance: "self" (WCAG-knowledge, no external expert) | "w3c-act" (W3C ACT '
        "expert gold). Optional-with-default so pre-existing gold (which carries neither new field) still loads "
        "under extra='forbid'",
    )
    act_testcase_id: Optional[str] = Field(
        None, description="the ACT case content-hash id (SHA-1 `testcaseId`) when source='w3c-act'; None for self gold"
    )
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
    judge_version: str = Field(..., description="pinned judge snapshot + temperature/prompt provenance, for reproducibility")
    verdict: JudgeVerdict = Field(..., description="correct | incorrect | partial (partial = one dimension right, the other wrong)")
    citation_correct: bool = Field(..., description="drafted SC(s) judged correct for the finding")
    conformance_correct: bool = Field(..., description="drafted conformance judged correct for the finding")
    rationale: str = Field(..., description="the judge's justification (rubric-based absolute scoring)")


class ConfidenceBin(BaseModel):
    """One bin of the confidence-vs-correctness calibration curve. `n` and `correct_n` are
    MANDATORY — a bin with n=1 otherwise makes the curve lie. This typed list (on
    `CalibrationReport`) is the curve's only home; it is never copied onto `OnlineEvalMetrics`."""
    model_config = ConfigDict(extra="forbid")

    lower: float = Field(..., ge=0.0, le=1.0, description="bin lower edge (drafter confidence)")
    upper: float = Field(..., ge=0.0, le=1.0, description="bin upper edge (drafter confidence)")
    n: int = Field(..., ge=0, description="drafts in this bin — mandatory")
    mean_confidence: float = Field(..., ge=0.0, le=1.0, description="mean self-reported confidence in the bin")
    correctness_rate: float = Field(
        ..., ge=0.0, le=1.0, description="fraction correct in the bin (oracle for verifiable items, trusted judge for judgment items)"
    )
    correct_n: int = Field(..., ge=0, description="correct count in the bin — mandatory")


class CalibrationReport(BaseModel):
    """Judge reliability (judge-vs-human κ against the gold set) + the confidence-vs-correctness
    curve. κ is judge-vs-ONE-labeller, not judge-vs-consensus — do not over-read it. A judge is
    only trusted to score models once κ clears a bar committed BEFORE the number is seen."""
    model_config = ConfigDict(extra="forbid")

    judge_kappa: float = Field(
        ..., ge=-1.0, le=1.0, description="Cohen's κ, judge vs human-derived verdicts. Bounds [-1,1]: a negative κ "
        "(judge worse than chance) is the key red flag and must NOT be clamped to 0",
    )
    judge_agreement: float = Field(..., ge=0.0, le=1.0, description="raw agreement proportion, reported alongside κ")
    n: int = Field(
        ..., ge=0, description="gold judgment-item findings compared (effective n is lower — same-fixture findings are correlated)"
    )
    kappa_threshold: float = Field(..., ge=-1.0, le=1.0, description="the trust bar, pre-committed before κ is seen")
    judge_trusted: bool = Field(..., description="κ >= threshold; only a trusted judge may score models on non-gold items")
    confidence_bins: list[ConfidenceBin] = Field(
        default_factory=list, description="the full calibration curve — a list, not a scalar; the curve's only home"
    )
    bias_notes: str = Field("", description="verbosity / self-preference observations (position bias N/A — absolute rubric scoring)")
    created_at: datetime


# ============================================================
# Acceptance benchmark output  (eval/ — held-out ACT-gold scorecard)
# ============================================================

class MetricCI(BaseModel):
    """A rate with its denominator and a confidence interval — the standard (value + n + CI)
    triple every headline benchmark number carries. The interval is the ASYMMETRIC Wilson score
    interval (never a symmetric ±), quoted as observed. `effective_n` records the clustering
    caveat: cases cluster in ~5 rules and the drafter shares one framing per rule, so within-rule
    outcomes correlate — the honest precision is `effective_n` (≈ #rules), not the raw `n`."""
    model_config = ConfigDict(extra="forbid")

    value: float = Field(..., ge=0.0, le=1.0, description="point estimate (a rate in [0,1])")
    n: int = Field(..., ge=0, description="denominator — the STRATUM size this rate runs on (e.g. 30 TN / 23 TP), not the pooled 53")
    ci_low: float = Field(..., ge=0.0, le=1.0, description="Wilson lower bound (asymmetric)")
    ci_high: float = Field(..., ge=0.0, le=1.0, description="Wilson upper bound (asymmetric)")
    effective_n: Optional[int] = Field(
        None, ge=0, description="clustering-adjusted n ≈ #rules; when set, the CI assumes an independence the data lacks — read this, not n"
    )
    ci_method: str = Field("wilson", description="interval method — Wilson by contract (asymmetric, tighter near 0/1 than a normal ±)")


class ExemptMetric(BaseModel):
    """A number the Scorecard explicitly EXEMPTS from the n+CI rule, and which MUST say why.
    Exactly two figures qualify: ECE (single-bin overconfidence at n ≤ 53 — the raw gap, no CI)
    and the judge's real-draft miss rate (too few naturally-wrong drafts; the injected-detection
    upper bound is the trustworthy figure instead)."""
    model_config = ConfigDict(extra="forbid")

    value: float = Field(..., ge=0.0, le=1.0, description="the reported magnitude (no interval)")
    n: int = Field(..., ge=0, description="the count behind it, reported even though no CI is claimed")
    exempt_reason: str = Field(..., description="why this figure carries no CI — mandatory, so the exemption is never silent")


class DrafterScore(BaseModel):
    """Subject #1: the drafter's `DraftRow` scored ENTIRELY by deterministic comparison against ACT
    gold — never via the judge. `false_positive_rate` (on the ACT-passed true negatives) is the
    headline: flagging clean content inverts the product's value. `recall` (on ACT-failed true
    positives) is the primary correctness axis. `sc_citation_match` is SECONDARY — the help text
    steers to SCs that disagree with ACT gold, so it reads low for framing not capability, and must
    NOT be 'fixed' by retuning the help text to the held-out set (contamination)."""
    model_config = ConfigDict(extra="forbid")

    recall: MetricCI = Field(..., description="conformance FLAGS vs ACT failed examples — does it find the problem")
    false_positive_rate: MetricCI = Field(..., description="conformance FLAGS vs ACT passed examples — does it cry wolf (the most important number)")
    sc_citation_match: MetricCI = Field(..., description="cited sc_id ∩ ACT gold_success_criteria, over correctly-flagged failed cases only — secondary")
    expected_calibration_error: ExemptMetric = Field(..., description="ECE — self-reported confidence vs ACT gold; exempt from CI (single-bin at this n)")
    overconfidence_gap: float = Field(..., ge=-1.0, le=1.0, description="signed: mean confidence − mean correctness; positive = over-confident")
    remediation_technique_match: Optional[MetricCI] = Field(None, description="fix aligns with the ACT canonical technique (G94/G95/F30…) — direction, a PROXY only")
    abstained_n: int = Field(0, ge=0, description="not_applicable drafts reported as a separate cell, never folded silently into 'clean'")


class JudgeConfusion(BaseModel):
    """Subject #2: the judge measured AGAINST ACT gold, not used as the ruler (M4's 'no oracle →
    use the judge' rule does not hold here — ACT supplies the oracle). The 2×2 confusion of judge
    verdict × ACT gold, with the two errors reported SEPARATELY and NEVER collapsed into one κ: a
    missed error (a wrong draft rubber-stamped 'verified') is dangerous; a false alarm is merely
    annoying. Detection on INJECTED bad drafts is an UPPER BOUND, split into two mutations each with
    its own n — a conformance flip (rationale regenerated) and an SC swap (citation-catching only)."""
    model_config = ConfigDict(extra="forbid")

    correct_release: int = Field(..., ge=0, description="judge pass · ACT correct — ✅ correct release")
    missed_error: int = Field(..., ge=0, description="judge pass · ACT wrong — ⚠️ the dangerous half")
    false_alarm: int = Field(..., ge=0, description="judge fail · ACT correct — ⚠️ merely annoying")
    correct_catch: int = Field(..., ge=0, description="judge fail · ACT wrong — ✅ correct catch")
    miss_rate: ExemptMetric = Field(..., description="missed_error / (missed_error + correct_catch) — EXEMPT: too few naturally-wrong drafts to CI")
    false_alarm_rate: MetricCI = Field(..., description="false_alarm / (false_alarm + correct_release) — the annoying half, with CI")
    kappa: float = Field(..., ge=-1.0, le=1.0, description="judge-vs-ACT-gold Cohen's κ — harder and more independent than M4's self-built-gold κ")
    injected_conformance_flip: MetricCI = Field(..., description="detection on conformance-flipped drafts (rationale regenerated) — an upper bound")
    injected_sc_swap: MetricCI = Field(..., description="detection on SC-swapped drafts — citation-catching only, secondary; an upper bound")
    rationale_coherence_note: str = Field("", description="how rationale coherence was preserved on the flip (LLM re-authorship is a bias to note)")


class NoiseFloor(BaseModel):
    """Variance over 3–5 repeat runs on the SAME acceptance set → the minimum detectable
    improvement: a change smaller than this may not be claimed as progress. Reports which source
    dominates — at temperature 0 on a local model the jitter may be near zero, leaving binomial
    sampling as the floor, not the model. The paired McNemar discordance (per stratum, TN→FP and
    TP→miss counted separately, never pooled) is the PRIMARY change signal; a change is real only if
    its discordance exceeds this same-config jitter floor, not zero."""
    model_config = ConfigDict(extra="forbid")

    runs: int = Field(..., ge=2, description="repeat runs the variance is computed over (3–5)")
    per_metric_sd: dict[str, float] = Field(..., description="standard deviation of each headline metric across the runs")
    min_detectable_improvement: float = Field(..., ge=0.0, description="smallest claimable improvement (pp) — the yardstick's smallest gradation")
    dominant_source: str = Field(..., description="'llm-jitter' | 'binomial-sampling' — which sets the floor, reported not assumed")
    paired_mdi_note: str = Field("", description="the per-stratum McNemar discordance floor for paired A/B comparison (separate from the CI)")


class TierBSmoke(BaseModel):
    """Tier B: ACT snippets embedded intact into realistic noisy pages, scored exactly like Tier A
    (deterministic vs ACT gold). At n = 2 this is ILLUSTRATIVE, not statistical — a smoke test that
    the pipeline survives real-page noise, NOT a measured rate (no CI attaches to two points). It
    does NOT enter the headline scorecard as a number. The report MUST state the embedding method
    used and its limits (methodology is preliminary)."""
    model_config = ConfigDict(extra="forbid")

    n: int = Field(2, ge=0, description="embedded instances — illustrative at this size, not a rate")
    instance_ids: list[str] = Field(default_factory=list, description="the acceptance-case ids embedded")
    clean_vs_noisy_note: str = Field("", description="the clean − noisy delta = the cost of real-world messiness, reported as illustration")
    method_and_limits: str = Field(..., description="the embedding / noise-construction method used and its limitations — mandatory")


class NotMeasuredItem(BaseModel):
    """One thing this benchmark explicitly does NOT measure — stated, not hidden (e.g.
    expert-minutes-per-finding, recall / missed findings, image alt-text quality, the judge's own
    ceiling)."""
    model_config = ConfigDict(extra="forbid")

    what: str = Field(..., description="the unmeasured thing")
    why: str = Field(..., description="why it is out of scope for this benchmark")


class OfflineEvalScorecard(BaseModel):
    """The metrics payload of a benchmark run: the drafter's ACT-gold score (subject #1), the
    judge's confusion against ACT gold (subject #2), the noise floor, the Tier B smoke test, and a
    structured not-measured list. Every rate carries n + a Wilson CI except the two figures
    `ExemptMetric` covers. `noise_floor` and `tier_b` are Optional — a single run has the drafter
    and judge scores, but the noise floor needs 3–5 repeats and Tier B is built separately."""
    model_config = ConfigDict(extra="forbid")

    drafter: DrafterScore
    judge: JudgeConfusion
    noise_floor: Optional[NoiseFloor] = Field(None, description="variance over repeat runs — absent on a single run, filled once repeats exist")
    tier_b: Optional[TierBSmoke] = Field(None, description="the realistic-page smoke test — illustrative, never part of the headline number")
    not_measured: list[NotMeasuredItem] = Field(default_factory=list, description="the explicit out-of-scope list — stated, not hidden")
    conformance_collapse_rule: str = Field(
        "FLAGS={does_not_support, partially_supports}; CLEAN={supports, not_applicable}",
        description="the four-value → binary collapse, stated so the scoring is auditable",
    )
    notes: str = Field("", description="methodology / sensitivity notes (e.g. partially_supports scored the other way; NA handling)")


class OfflineEvalReport(BaseModel):
    """The frozen, reproducible top-level benchmark artifact — the regression baseline for every
    later iteration. Freeze is by CONTENT HASH, not by a name: it pins the drafter / judge model
    DIGESTS (immutable hashes, not the mutable Ollama tags), the axe-core version, the corpus
    version, and the vendored ACT export hash. The nested `OfflineEvalScorecard` holds the numbers;
    this shell holds the provenance that makes them reproducible."""
    model_config = ConfigDict(extra="forbid")

    run_ids: list[str] = Field(..., description="run(s) this report aggregates — one for a single run, 3–5 for the frozen noise-floor artifact")
    config_id: str = Field(..., description="pinned pipeline config")
    eval_set_id: str = Field(..., description="the acceptance set id — DISTINCT from the dev fixtures, never overlapping")
    corpus_version: str = Field(..., description="RAG corpus version (lives on CorpusChunk, not OnlineEvalReport) — pinned")
    drafter_model: str = Field(..., description="drafter model tag, for readability")
    drafter_model_digest: str = Field(..., description="drafter model IMMUTABLE digest — the freeze key, not the mutable tag")
    judge_model: str = Field(..., description="judge model tag, for readability")
    judge_model_digest: str = Field(..., description="judge model IMMUTABLE digest — the freeze key")
    judge_version: str = Field(..., description="pinned judge snapshot + prompt / temperature provenance")
    axe_core_version: str = Field(..., description="pinned axe-core version — the coverage gate for every Finding")
    act_export_hash: str = Field(..., description="content hash of the vendored ACT export — the gold is pinned, never fetched live")
    created_at: datetime
    scorecard: OfflineEvalScorecard


class CaseVerdict(BaseModel):
    """One ACT case's paired verdict — the unit M7 pairs on. `drafter_flag` is FLAG (any finding on the
    case alarmed, flag-if-any) vs CLEAN; `gold_flag` is the ACT outcome (failed = FLAG). `conformances`
    are the case's underlying draft verdicts (empty = an honest miss: the case minted no finding).
    `axe_rule` is the fix-unit class (the two link rules share `link-name`)."""

    model_config = ConfigDict(extra="forbid")

    act_testcase_id: str = Field(..., description="the ACT case id — the stable key a future run pairs on")
    axe_rule: str = Field(..., description="the fix-unit class (axe rule); the two link rules pool as 'link-name'")
    drafter_flag: bool = Field(
        ..., description="True = the drafter FLAGGED the case (any finding alarmed), False = CLEAN"
    )
    gold_flag: bool = Field(..., description="True = ACT gold says the case FAILED, False = passed")
    conformances: list[Conformance] = Field(
        default_factory=list, description="the case's underlying draft conformances — empty for an honest miss"
    )


class VerdictVector(BaseModel):
    """The frozen per-case drafter verdict vector — M7's paired-comparison baseline. A κ scalar cannot be
    paired against, so without this vector M7's most sensitive test (case-by-case McNemar against a future
    run, keyed by `act_testcase_id`) does not exist. It carries the offline report's drafter-side
    provenance (model DIGEST, axe/corpus versions, ACT export hash) so the vector is reproducible, and the
    per-case rows keyed by `act_testcase_id` so a future run pairs without re-deriving alignment. Computed
    under one `partial_flags` reading."""

    model_config = ConfigDict(extra="forbid")

    partial_flags: bool = Field(..., description="the partially_supports reading drafter_flag was computed under")
    cases: list[CaseVerdict] = Field(
        ..., description="one row per ACT case (minting cases + honest misses), keyed by act_testcase_id"
    )
    run_ids: list[str] = Field(..., description="the run(s) this vector was frozen from")
    config_id: str = Field(..., description="pinned pipeline config")
    eval_set_id: str = Field(..., description="the acceptance set id")
    corpus_version: str = Field(..., description="RAG corpus version — pinned")
    drafter_model: str = Field(..., description="drafter model tag, for readability")
    drafter_model_digest: str = Field(..., description="drafter model IMMUTABLE digest — the freeze key")
    axe_core_version: str = Field(..., description="pinned axe-core version")
    act_export_hash: str = Field(..., description="content hash of the vendored ACT export — the gold is pinned")
    created_at: datetime = Field(
        ..., description="the source run's timestamp (read from the artifact, never generated)"
    )
    rationale: str = Field(..., description="why this artifact exists — a κ scalar cannot be paired against")
```

---

## 4. Cross-module invariants

Module ownership and pipeline order live in `ARCHITECTURE.md` §6; the shapes in §3 are the only things shared across those boundaries. The invariant the contract itself enforces:

The L1 check reads ground truth via the `Oracle` protocol, never by reaching into axe internals directly — that is what keeps Regime B (expert gold) a swap of the `Oracle` implementation with no change to `validator/` or `eval/`.

---

## 5. Deferred

Added when their milestone arrives, not before:

| Schema / concern | Note |
|---|---|
| `RoutingConfig` (frozen, versioned model/config artifact) | Lands when multi-model routing is built. |
| Full ACR/VPAT document assembly schema (beyond per-finding `DraftRow`) | Not yet needed. |
| L2 retrieval-faithfulness fields on `CitationCheck` | The judge produces `JudgeResult`, not L2 fields; per-citation faithfulness stays a distinct, deferred concern. |

---

## 6. Change log

> Historical record — entries describe what was true on their date and are not rewritten when milestones are renumbered.

| Date | Version | Change |
|---|---|---|
| 2026-07-23 | 0.18 | Added `VerdictVector` (the frozen per-case drafter verdict vector — M7's paired-comparison baseline, keyed by `act_testcase_id`) nesting `CaseVerdict` (per ACT case: drafter FLAG/CLEAN, gold FLAG/CLEAN, the underlying conformances, the axe_rule class). Carries the offline report's drafter-side provenance (config / eval-set / corpus versions, drafter model **digest**, axe-core version, ACT export hash, run ids, source timestamp) so the vector is reproducible. A κ scalar cannot be paired against, so this vector is what makes M7's most sensitive test exist. Additive — no existing shape changed; §5 unaffected. |
| 2026-07-23 | 0.17 | Vocabulary rename only — no field, bound, default, or wire change. The per-run eval types are now `OnlineEvalReport` (was `EvalReport`) and `OnlineEvalMetrics` (was `EvalMetrics`); the held-out acceptance types are `OfflineEvalReport` (was `BenchmarkReport`) nesting `OfflineEvalScorecard` (was `AcceptanceScorecard`). The `eval/` modules were renamed to match (`report`→`online`, `benchmark*`→`offline*`). JSON / DB payloads unchanged; §5 unaffected. |
| 2026-07-15 | 0.16 | Pre-release honesty pass: health-warned `DraftRow.confidence` — the description now states the field is **decorative** (do not gate/route/triage on it), citing the held-out over-confidence gap +0.329 and its pinned ~0.85–1.0 range. Description only, no shape change; §5 unaffected. Pairs with dropping the "confidence-scored" product claim from README/ARCHITECTURE. |
| 2026-07-14 | 0.15 | Quality-review whitelist grew from four rules to six: added `empty-heading` (SC 2.4.6 — a **new** existence-only judgment rule) and `document-title` (SC 2.4.2 — **reverses** the earlier deferral). Both were empirically confirmed against pinned axe 4.12.1 to PASS on present-but-non-descriptive content, so each mints an `AxeBucket.PASSES` judgment finding. The whitelist is global, so both mint new findings on every frozen fixture carrying a heading/title — versioned anchors moved, so the affected fixture sets were bumped (`quality-gold@1`→`@2`, scoped to its original three rules; the m0/m1 orchestrator counts updated). `button-name` and the alt/name variants stay deferred. No §3 schema change — this records a decision in code (`normalizer/quality_review.py`), not a shape. |
| 2026-07-14 | 0.14 | Acceptance-benchmark schemas (T0). Added `BenchmarkReport` (frozen, reproducible top-level artifact — pins config/corpus versions, drafter+judge model **digests**, axe-core version, and the vendored ACT export hash; freeze by content hash, not name) nesting `AcceptanceScorecard`, which composes `DrafterScore` (subject #1, scored vs ACT gold — FP rate on true negatives is the headline), `JudgeConfusion` (subject #2, 2×2 vs ACT gold with miss/false-alarm reported separately + injected-bad-draft detection), `NoiseFloor`, `TierBSmoke`, and `NotMeasuredItem`, plus the reusable `MetricCI` (value + n + asymmetric Wilson CI + clustering-aware `effective_n`) and `ExemptMetric` (the two figures that carry no CI, each with a mandatory reason). Extended `GoldLabel` with `source` (`"self"` \| `"w3c-act"`, default `"self"`) and `act_testcase_id` (Optional) — both Optional-with-default so the existing `calibration_set.json` gold still loads under `extra="forbid"`. Removed `BenchmarkReport` / `AcceptanceScorecard` from §5. Additive — existing shapes and reports unchanged. |
| 2026-07-14 | 0.13 | Editorial: removed milestone labels from all live content (docstrings, comments, §5). Milestones move; the schemas don't. §5 now carries a `Note` column instead of a `Milestone` column, and lists the benchmark's `BenchmarkReport` / `AcceptanceScorecard` as deferred. No §3 schema change. |
| 2026-07-05 | 0.1 | Initial M0-scoped contracts. |
| 2026-07-06 | 0.2 | Typed `l1_status` / `oracle_regime` / `Oracle.regime` as enums (`L1Status`, `OracleRegime`); marked `Trace.checks` the authoritative check record; noted `impact`/`severity` share the `Severity` enum. Wire values unchanged. |
| 2026-07-08 | 0.3 | M1 (T0): added `CorpusChunk` (corpus/ → retriever/) and stratified `EvalMetrics` fields (`citation_hallucination_rate_verifiable`, `unverifiable_share`, `citations_verifiable_total`, `citations_unverifiable_total`). `CorpusChunk.embedding` is optional and excluded from serialization (vector lives in pgvector). Additive — existing M0 shapes unchanged. |
| 2026-07-08 | 0.4 | M1 (T4): scanner captures axe's `incomplete` (needs-review) bucket distinctly. Factored `AxeViolation`'s fields into a shared `AxeRuleResult` base; added `AxeIncomplete` (same shape, not confirmed) and `ScanResult.incomplete: list[AxeIncomplete]`. `incomplete` is the source of eval's `unverifiable_share`. Additive — `AxeViolation` wire shape unchanged. |
| 2026-07-08 | 0.5 | M1 (T5): normalizer carries `incomplete` items through as `Finding`s. Added `AxeBucket` enum (provenance) and `Finding.source_bucket: AxeBucket` (default `VIOLATIONS`). The oracle allowlists `VIOLATIONS`, returning no verdict for any other bucket — incomplete-sourced findings become `UNVERIFIABLE`. `source_bucket` is not part of the finding id. Additive — existing findings default to `VIOLATIONS`, wire shape unchanged. |
| 2026-07-10 | 0.7 | M3 (T0): added `EvidenceQuery` (`rule_id: str = ""`, `description: str`) — the slim, reuse-shaped input the MCP retrieval tool accepts (any caller → retriever/). Deliberately not a `Finding`: omits the internal hashed `id` / `source_url` / `target`; a `Finding` maps to it losslessly for retrieval. `Citation` unchanged (its `title`/`level` fields get populated in T1). Additive — existing shapes unchanged. |
| 2026-07-10 | 0.8 | Swapped M4/M5 (§5 deferred): `JudgeResult` / `CalibrationReport` and `GoldLabel` move to **M4** (judge calibration now precedes routing; `GoldLabel` reworded to "judgment-item ground truth", same shape M6's `GoldLabelOracle` reuses); `RoutingConfig` moves to **M5**; L2 faithfulness follows the judge to **M4**. No §3 schema change — shapes still land at each milestone's own T0. |
| 2026-07-09 | 0.6 | M2 (T0): added durable-orchestration + HITL schemas — `RunState`, `StepState` (checkpoint/resume, keyed `(run_id, finding_id, step)` via the new `PipelineStep` enum) and `NeedsReview` (HITL approve/edit record, `ReviewReason` + `ReviewStatus` enums; written post-validation, carries the drafted `DraftRow`). Added `EvalMetrics.expert_edit_distance` (unbounded `float ≥ 0`, normalization left to T4). `NeedsReview` removed from §5 (no longer deferred). Additive — existing shapes unchanged. |
| 2026-07-12 | 0.9 | Editorial: retired the stale, M0-scoped "What M0 touches" section and the M0 pipeline sketch in §1 (retrieve/draft went real in M1; module data flow lives in `ARCHITECTURE.md` §6). Generalised §4 to the cross-module `Oracle` invariant and dropped the "(not in M0)" qualifier from §5's title. No §3 schema change. |
| 2026-07-12 | 0.12 | M4 (T1): scanner captures axe's `passes[]` bucket. Added `AxePass` (same `AxeRuleResult` shape, a PASS not a failure) and `ScanResult.passes: list[AxePass]` (faithful mirror of axe's passes). The normalizer surfaces a whitelist of *existence-only* rules from it as `AxeBucket.PASSES` judgment findings, reframing each finding's help to the quality-review task; the oracle is unchanged (allowlists `VIOLATIONS`) so they score `UNVERIFIABLE`. Additive — existing scans get an empty `passes`, wire shape unchanged. |
| 2026-07-12 | 0.11 | M4 (T1 scope): added `AxeBucket.PASSES` — provenance for judgment findings minted from axe's `passes[]` array for a whitelist of *existence-only* rules (`image-alt` & alt variants, `link-name`, `button-name`, `document-title`, `frame-title`, `label`), where axe confirms a name/attribute EXISTS but not that it is meaningful. Non-whitelisted passes are still not findings. The oracle is unchanged (allowlists only `VIOLATIONS`), so PASSES-sourced findings score `UNVERIFIABLE` — no verified-count inflation. **Rationale:** the pinned axe 4.12.1 `incomplete[]` bucket yields zero DOM-decidable judgment items (all 55 incomplete-capable rules are pixel/render/media/name-resolution bound), so `passes[]` is the only viable source for the judge gold set. This is a scoped forward-path change, recorded in `specs/M4-judge-calibration.md`. Additive — existing findings default to `VIOLATIONS`, wire shape unchanged. |
| 2026-07-12 | 0.10 | M4 (T0): added judge + calibration schemas — `GoldLabel` (the single gold shape, reused by M6's `GoldLabelOracle`), `JudgeResult` (+ `JudgeVerdict` enum), `ConfidenceBin`, and `CalibrationReport` (κ + the confidence-vs-correctness curve as a typed `ConfidenceBin` list). Extended `EvalMetrics` with judge/calibration **scalars only** (all Optional, default `None`): `judge_kappa` (bounds **[-1,1]** — a negative κ is signal, not an error to clamp), `judge_agreement_rate`, `judge_gold_n`, `judge_trusted`, `judgment_correctness_rate` + `judgment_items_total` + `judgment_correct_total`, `expected_calibration_error`, `overconfidence_gap`. Removed the three schemas from §5; softened the L2 row to "M4+ / when the judge exists". Judge-scored items are NOT promoted to verified — `unverifiable_share` unchanged. Additive — existing shapes unchanged. |
