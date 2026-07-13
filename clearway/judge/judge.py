"""The LLM-as-judge: grade one drafted judgment-item row against WCAG on a fixed rubric.

Consumes a judgment-item `Finding` + its `DraftRow`; produces a `JudgeResult`. The judge scores two
INDEPENDENT dimensions — is the cited SC correct, and is the conformance verdict correct — and the
3-way `verdict` (correct / partial / incorrect) is DERIVED IN CODE from those two booleans, never
emitted by the model (the model supplies only the semantic booleans + a rationale, exactly as the
drafter supplies only its semantic shape).

Two disciplines this encodes:
- **Judge ≠ drafter.** Construction raises if the judge model equals the drafter model — a model
  grading its own family self-preferences, which is the whole reason the judge is a separate cloud
  reference model.
- **Raise, don't fabricate.** A measurement instrument must not invent data: if the model never
  returns a parseable verdict, the judge raises rather than degrading to a made-up one (unlike the
  drafter, whose low-confidence fallback is a safe production behaviour, not a measurement).

Reproducibility: `judge_model` + `judge_version` (rubric-prompt hash + reasoning effort) are recorded
on every result. Cloud models are not bit-reproducible even so — a pinned snapshot + fixed effort +
fixed rubric is the honest best available.

The judge is for no-oracle judgment items only, and only once calibrated (κ); this module builds the
instrument — calibration lives elsewhere.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, ValidationError

from clearway.llm import LLMClient
from clearway.schemas.models import DraftRow, Finding, JudgeResult, JudgeVerdict


class JudgeError(RuntimeError):
    """The judge could not produce a parseable verdict after retries. Raised rather than fabricating
    a verdict — a made-up grade would silently corrupt κ and every downstream trust number."""


_RUBRIC_SYSTEM = (
    "You are a WCAG 2.2 accessibility expert acting as an impartial JUDGE. You are given ONE "
    "accessibility finding and ONE drafted conformance row produced by another model. Grade the "
    "draft on two INDEPENDENT dimensions using rubric-based absolute scoring — judge the draft "
    "against WCAG on its own merits, never by comparison to another draft.\n"
    "1. citation_correct: TRUE only if the drafted WCAG success-criterion id(s) are the correct "
    "SC(s) a WCAG expert would cite for this finding; FALSE if any cited SC is wrong or irrelevant, "
    "or a clearly-required SC is missing.\n"
    "2. conformance_correct: TRUE only if the drafted conformance verdict "
    "(supports | partially_supports | does_not_support | not_applicable) is correct for this "
    "finding.\n"
    "For a QUALITY-REVIEW finding (axe confirmed a name/attribute is PRESENT but did not judge its "
    "quality), a present-but-inadequate value is does_not_support or partially_supports, never "
    "supports.\n"
    "Do NOT judge severity or remediation wording. Output ONLY the JSON object with "
    "citation_correct, conformance_correct, and a one-sentence rationale."
)

# Hash the rubric text so `judge_version` tracks any prompt edit automatically — a stale hand-bumped
# version string would let a changed rubric masquerade as the calibrated one.
_RUBRIC_HASH = hashlib.sha256(_RUBRIC_SYSTEM.encode()).hexdigest()[:8]


class _JudgeVerdict(BaseModel):
    """The semantic booleans the judge model produces; code derives the `JudgeVerdict` and assembles
    the full `JudgeResult`. `extra="forbid"` → additionalProperties:false, required for the cloud
    Responses API's strict json-schema mode."""

    model_config = ConfigDict(extra="forbid")

    citation_correct: bool
    conformance_correct: bool
    rationale: str


def verdict_from(citation_correct: bool, conformance_correct: bool) -> JudgeVerdict:
    """correct = both right; incorrect = both wrong; partial = exactly one right.

    Public because calibration derives the *human* verdict with this exact rule so the two rater
    streams κ compares are on one scale (spec: map to the verdict "by the same rule the judge uses").
    """
    if citation_correct and conformance_correct:
        return JudgeVerdict.CORRECT
    if not citation_correct and not conformance_correct:
        return JudgeVerdict.INCORRECT
    return JudgeVerdict.PARTIAL


class Judge:
    """Grades drafted judgment items with a cloud reference model on a fixed rubric.

    `retries` is the number of *extra* attempts on an unparseable response before raising.
    """

    def __init__(self, client: LLMClient, drafter_model: str, retries: int = 1) -> None:
        if client.model == drafter_model:
            raise ValueError(
                f"judge model {client.model!r} must differ from the drafter model — a model grading "
                "its own output self-preferences"
            )
        self._client = client
        self._retries = retries
        effort = getattr(client, "reasoning_effort", None)
        parts = [f"rubric={_RUBRIC_HASH}"]
        if effort:
            parts.append(f"effort={effort}")
        self._judge_version = "; ".join(parts)

    @property
    def judge_version(self) -> str:
        return self._judge_version

    def judge(self, finding: Finding, draft: DraftRow, run_id: str) -> JudgeResult:
        system = _RUBRIC_SYSTEM
        user = _judge_user_prompt(finding, draft)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, _JudgeVerdict)
            try:
                out = _JudgeVerdict.model_validate_json(completion.content)
            except ValidationError:
                continue  # model drifted off-schema; retry, then raise — never fabricate
            return JudgeResult(
                finding_id=finding.id,
                run_id=run_id,
                judge_model=self._client.model,
                judge_version=self._judge_version,
                verdict=verdict_from(out.citation_correct, out.conformance_correct),
                citation_correct=out.citation_correct,
                conformance_correct=out.conformance_correct,
                rationale=out.rationale,
            )
        raise JudgeError(
            f"judge {self._client.model!r} returned no parseable verdict for finding {finding.id!r} "
            f"after {self._retries + 1} attempts"
        )


def _judge_user_prompt(finding: Finding, draft: DraftRow) -> str:
    cited = ", ".join(c.sc_id for c in draft.citations) or "(none)"
    return (
        "FINDING\n"
        f"- axe rule: {finding.rule_id}\n"
        f"- task: {finding.help or '(no description)'}\n"
        f"- target element: {finding.target}\n"
        f"- HTML: {finding.html or '(not captured)'}\n\n"
        "DRAFTED ROW (grade this)\n"
        f"- conformance: {draft.conformance.value}\n"
        f"- cited WCAG SC(s): {cited}\n\n"
        "Grade citation_correct and conformance_correct for this finding."
    )
