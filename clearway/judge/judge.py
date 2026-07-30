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
fixed rubric is the honest best available. **⚠️ `judge_version` hashes the SYSTEM rubric only**, so an
edit to the finding-side template below moves the judge's input without moving the version string; the
tripwire for that template is a whole-prompt literal in the judge's tests.

The judge is for no-oracle judgment items only, and only once calibrated (κ); this module builds the
instrument — calibration lives elsewhere.

Two halves, and the seam between them is load-bearing
-----------------------------------------------------
The user prompt is `finding-side input` + `presentation of the draft`, assembled in that order and
never interleaved.

* **The finding side** is everything about the element being judged: the rule, the task, the target,
  the HTML, the **referent** captured at scan time, and the **retrieved candidate criteria**. The
  referent and the candidate block are rendered by the *drafter's own* builders
  (`drafter.llm.referent_blocks` / `candidate_lines`) rather than by copies of them — a second reader
  asked to answer the same question has to be given the same facts in the same sentences, and a copy
  would drift one edit later, at which point a difference between the two readers' answers could be a
  difference in wording. Reusing them costs a `judge → drafter` import, recorded in `ARCHITECTURE.md`
  §6.
* **The draft side** is the row being graded, and it is the *only* thing a configuration is allowed to
  vary. `FindingInput` exists so that half can be built once, frozen, and handed in — byte-identity
  across two configurations is then a property of one file rather than a claim about two code paths.

One wording difference from the drafter survives deliberately and is recorded here rather than in a
report: the drafter heads its candidates *"you may cite"*, an instruction to a rater that cites, while
this block heads them *"retrieved for this finding"*. The same block serves a configuration that
grades a citation and one that makes its own, so the heading has to be true of both.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from clearway.drafter.llm import candidate_lines, referent_blocks
from clearway.llm import LLMClient
from clearway.schemas.models import Citation, DraftRow, Finding, JudgeResult, JudgeVerdict


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


@dataclass(frozen=True)
class FindingInput:
    """The finding-side half of the judge's user prompt, as a value.

    It exists so that half can be **built once and read**, rather than rebuilt per configuration. The
    material it carries is not recoverable from a frozen drafter run — a draft record holds no
    `Finding`, so no `html`, no `help` and no `referent` — so rebuilding it needs a live scan and live
    retrieval, and two rebuilds are two claims. One frozen block is one fact.

    `finding_id` rides along because the assembled `JudgeResult` is keyed by it and a caller handing in
    a prepared block no longer passes the `Finding` the id would come from. It is code's, never the
    model's, exactly as it was before.
    """

    finding_id: str
    block: str


def finding_input(finding: Finding, citations: Sequence[Citation]) -> FindingInput:
    """Render the finding side of the prompt for one finding and the candidates retrieved for it."""
    return FindingInput(finding_id=finding.id, block=_finding_block(finding, citations))


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

    def judge(self, finding: Finding, draft: DraftRow, run_id: str, *, citations: Sequence[Citation]) -> JudgeResult:
        """Grade one draft, rendering the finding side from the finding and its retrieved candidates.

        `citations` is required and keyword-only rather than defaulted to none: an empty candidate list
        renders a different prompt ("(none retrieved)"), so a default would let a caller judge under a
        prompt it did not choose, and the drafter's own candidates are what the judge has to be shown to
        be answering the same question. A caller that genuinely retrieved nothing passes `[]` and says
        so at the call site.
        """
        return self.judge_prepared(finding_input(finding, citations), draft, run_id)

    def judge_prepared(self, prepared: FindingInput, draft: DraftRow, run_id: str) -> JudgeResult:
        """Grade one draft against a finding side that was rendered **elsewhere** — the frozen artifact.

        This is the entry point a comparison of two configurations uses. Nothing here re-renders the
        finding side, so the two configurations cannot drift apart in it: whatever bytes were frozen are
        the bytes sent.
        """
        system = _RUBRIC_SYSTEM
        user = _judge_user_prompt(prepared, draft)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, _JudgeVerdict)
            try:
                out = _JudgeVerdict.model_validate_json(completion.content)
            except ValidationError:
                continue  # model drifted off-schema; retry, then raise — never fabricate
            return JudgeResult(
                finding_id=prepared.finding_id,
                run_id=run_id,
                judge_model=self._client.model,
                judge_version=self._judge_version,
                verdict=verdict_from(out.citation_correct, out.conformance_correct),
                citation_correct=out.citation_correct,
                conformance_correct=out.conformance_correct,
                rationale=out.rationale,
            )
        raise JudgeError(
            f"judge {self._client.model!r} returned no parseable verdict for finding "
            f"{prepared.finding_id!r} after {self._retries + 1} attempts"
        )


# The heading the retrieved candidates are shown under. Role-neutral on purpose: the same block is
# read by a configuration that grades someone else's citation and by one that makes its own, so a
# heading phrased as an instruction to cite ("you may cite", the drafter's) would be false for one of
# them. Named here so the one surviving wording difference from the drafter is a constant, not a
# sentence buried in an f-string.
CANDIDATE_HEADING = "Candidate WCAG success criteria retrieved for this finding:"


def _finding_block(finding: Finding, citations: Sequence[Citation]) -> str:
    """The finding side of the prompt: the element, its referent, and the retrieved candidates.

    The referent and the candidate lines are the drafter's own renderings, so the two readers are shown
    the same facts in the same words — see the module docstring. A class with no referent injection
    contributes no line at all here, exactly as it contributes none to the drafter's prompt; the
    asymmetry between the classes is inherited rather than introduced.
    """
    return (
        "FINDING\n"
        f"- axe rule: {finding.rule_id}\n"
        f"- task: {finding.help or '(no description)'}\n"
        f"- target element: {finding.target}\n"
        f"- HTML: {finding.html or '(not captured)'}"
        f"{referent_blocks(finding)}\n"
        f"{CANDIDATE_HEADING}\n"
        f"{candidate_lines(list(citations))}"
    )


def _drafted_row_block(draft: DraftRow) -> str:
    """The presentation of the draft — the anchored configuration's whole addition to the prompt.

    Separated from the finding side so "only the presentation of the draft differs" is a property of
    the assembly rather than a claim about it: whatever this returns is appended after the frozen block
    and nothing here can reach back into it.
    """
    cited = ", ".join(c.sc_id for c in draft.citations) or "(none)"
    return (
        "\n\nDRAFTED ROW (grade this)\n"
        f"- conformance: {draft.conformance.value}\n"
        f"- cited WCAG SC(s): {cited}\n\n"
        "Grade citation_correct and conformance_correct for this finding."
    )


def _judge_user_prompt(prepared: FindingInput, draft: DraftRow) -> str:
    """The anchored configuration's user prompt: the frozen finding side, then the draft to grade."""
    return prepared.block + _drafted_row_block(draft)
