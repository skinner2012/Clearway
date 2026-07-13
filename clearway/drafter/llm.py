"""The real LLM drafter — answers per-finding: build a prompt from the finding + its retrieved
citations → ask the model for a small *semantic* shape (`_LLMDraft`: conformance, which SC ids it
cites, remediation, confidence) → **assemble the full `DraftRow` in code** (we own `finding_id` +
`severity`, and resolve cited ids against the retrieved citations so the citation metadata is
corpus-grounded, never model-invented).

The model call goes through the shared `LLMClient` gateway (`clearway.llm`); this module owns only
the drafting. Two things it gets right: it assembles identity/citations in code rather than trusting
the model, and it is defensive — LLM output is not guaranteed, so it validates, retries once, then
degrades to a low-confidence fallback `DraftRow` rather than crashing.

Grounding note: the retrieved `Citation`s carry sc_id + url but not the SC's normative text, so the
prompt names the *relevant SC ids* and the model supplies their meaning from its own knowledge.
Passing the SC text into the prompt for stronger grounding is a fast-follow.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clearway.llm import LLMClient, LLMUsage
from clearway.schemas.models import AxeBucket, Citation, Conformance, DraftRow, Finding

_FALLBACK_CONFIDENCE = 0.0  # a draft we could not parse is worth nothing — say so, don't crash


class DraftResult(NamedTuple):
    """A drafted row **plus** the usage of the LLM call that produced it. The orchestrator seam
    (`do_draft`) returns this so `execute()` can fill the `Trace` quartet; `Drafter.draft()` stays
    a thin `.row`-only convenience for callers that don't care about telemetry."""

    row: DraftRow
    usage: LLMUsage


class _LLMDraft(BaseModel):
    """The semantic fields the LLM produces. Code assembles the full `DraftRow` around it, so the
    model never touches identity (`finding_id`) or corpus-grounded citation metadata."""

    model_config = ConfigDict(extra="ignore")  # tolerate stray keys the model may add

    conformance: Conformance
    cited_sc_ids: list[str] = Field(default_factory=list)
    remediation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class Drafter:
    """Real LLM drafting: `Finding` + retrieved `Citation[]` → `DraftRow`.

    `retries` is the number of *extra* attempts on an unparseable response before falling back.
    """

    def __init__(self, client: LLMClient, retries: int = 1) -> None:
        self._client = client
        self._retries = retries

    def draft(self, finding: Finding, citations: list[Citation]) -> DraftRow:
        """Convenience for callers that only want the row (offline mechanics tests, the gated
        real-model tests). The durable orchestrator uses `draft_with_usage` to also thread usage
        into the `Trace`."""
        return self.draft_with_usage(finding, citations).row

    def draft_with_usage(self, finding: Finding, citations: list[Citation]) -> DraftResult:
        """Draft the row **and** return the usage of the LLM call that produced it. Usage is the
        successful call's; a fallback (model never parsed) carries empty usage — the tokens the
        failed attempts spent are not attributed to a row we're discarding."""
        system = _system_prompt()
        user = _user_prompt(finding, citations)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, _LLMDraft)
            try:
                out = _LLMDraft.model_validate_json(completion.content)
            except ValidationError:
                continue  # model drifted off-schema; try again, then fall back
            return DraftResult(_assemble(finding, citations, out), completion.usage)
        return DraftResult(_fallback(finding), LLMUsage())


def _system_prompt() -> str:
    return (
        "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
        "- cited_sc_ids: only WCAG SC ids from the provided candidates that genuinely apply (may be empty)\n"
        "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
        "- remediation: one concrete sentence on how to fix it\n"
        'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
        '"remediation":"Add a descriptive alt attribute.","confidence":0.9}'
    )


def _user_prompt(finding: Finding, citations: list[Citation]) -> str:
    # Three-way framing by provenance. PASSES is the subtle one: axe *passed* the mechanical
    # check (a name/attribute/title EXISTS) but never judged its quality — so without this branch
    # the model reads "has alt text" as conformant and drafts `supports`, defeating the whole
    # quality-review gold set. The finding's help is already reframed to the specific task
    # (normalizer/quality_review.py); this states the general stance.
    if finding.source_bucket is AxeBucket.VIOLATIONS:
        bucket = "a CONFIRMED failure"
    elif finding.source_bucket is AxeBucket.PASSES:
        bucket = (
            "a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
            "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
            "does_not_support or partially_supports, never supports"
        )
    else:
        bucket = "a NEEDS-REVIEW item the scanner could not decide"
    candidates = "\n".join(f"- {c.sc_id} ({c.url})" for c in citations) or "- (none retrieved)"
    return (
        f"Finding ({bucket}): axe rule '{finding.rule_id}' — {finding.help or '(no description)'}\n"
        f"Target element: {finding.target}\n"
        f"HTML: {finding.html or '(not captured)'}\n"
        f"Candidate WCAG success criteria you may cite:\n{candidates}\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )


def _assemble(finding: Finding, citations: list[Citation], out: _LLMDraft) -> DraftRow:
    """Build the full `DraftRow`: identity + severity from code; citations resolved from the
    retrieved set by sc_id (corpus-grounded metadata), falling back to a bare `Citation` for any
    sc_id the model cites that was NOT retrieved — a citation the corpus never supported is exactly
    the hallucination the validator/oracle is built to catch, so we keep it, not drop it."""
    by_id = {c.sc_id: c for c in citations}
    cited = [by_id.get(sc_id) or Citation(sc_id=sc_id) for sc_id in out.cited_sc_ids]
    return DraftRow(
        finding_id=finding.id,
        conformance=out.conformance,
        citations=[c.model_copy() for c in cited],
        remediation=out.remediation,
        severity=finding.impact,
        confidence=out.confidence,
    )


def _fallback(finding: Finding) -> DraftRow:
    """A draft we could not parse after retries: conservative verdict, zero confidence, no
    citations — surfaces as low-trust rather than crashing the run (graceful degradation)."""
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=[],
        remediation="(draft unavailable — the model did not return a usable response)",
        severity=finding.impact,
        confidence=_FALLBACK_CONFIDENCE,
    )
