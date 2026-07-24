"""The real LLM drafter — answers per-finding: build a prompt from the finding + its retrieved
citations → ask the model for a small *semantic* shape → **assemble the full `DraftRow` in code** (we
own `finding_id` + `severity`, and resolve cited ids against the retrieved citations so the citation
metadata is corpus-grounded, never model-invented).

The model call goes through the shared `LLMClient` gateway (`clearway.llm`); this module owns only
the drafting. Two things it gets right: it assembles identity/citations in code rather than trusting
the model, and it is defensive — LLM output is not guaranteed, so it validates, retries once, then
degrades to a low-confidence fallback `DraftRow` rather than crashing.

Two prompts, chosen by what is already known
--------------------------------------------
A finding reaches this module in one of two epistemic states, and asking the same question of both
wastes tokens on the first and invites a guess where an answer already exists.

- **A confirmed axe violation whose tags decode to WCAG success criteria.** axe has *established*
  the failure, and the criteria it fails are mechanically derivable from its own tags — the exact
  derivation `AxeCoreOracle` grades citations against (`tag_to_sc_ids`, reused here rather than
  reimplemented, so the two can never drift apart). Nothing is left to judge, so conformance and
  citations are assembled in code and the model is asked for `remediation` alone
  (`_LLMRemediation`). The fix is then written *against the criteria axe named*, instead of against
  whichever criterion the model guessed. Note what the reuse costs: this branch is bound to the
  axe-tag regime, so a future gold-label oracle would need its own derivation here rather than
  inheriting one through the `Oracle` protocol.
- **Everything else** — quality-review `passes` items, needs-review `incomplete` items, and
  confirmed violations whose tags carry no success criterion at all (axe's `best-practice` rules) —
  is a genuine judgment call, and keeps the full `_LLMDraft` shape unchanged.

⚠️ **What this change does and does not claim.** There is no violations-bucket gold set, so this
**ships unmeasured**. Its benefit is *mechanical* — a decision the model should never have been
making is removed, and the remediation is now written against the correct criterion — **not
demonstrated**. Nothing here has been shown to improve any number, and "narrows hallucination
surface" must not be read as a measured result. The one measurable side effect is a *loss*: because
the drafter and the oracle now read the same tags through the same function, an assembled violation
citation is VERIFIED by construction, so `citation_hallucination_rate` no longer measures anything
on this bucket — and neither does the oracle-scored half of the confidence curve
(`eval/confidence_build.py`), whose points come from exactly these findings. Both measured a guess
that no longer happens; a re-freeze of those artifacts will be degenerate, by design and not by
accident.

Grounding note: the retrieved `Citation`s carry sc_id + url but not the SC's normative text, so the
prompt names the *relevant SC ids* and the model supplies their meaning from its own knowledge.
Passing the SC text into the prompt for stronger grounding is a fast-follow.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clearway.llm import LLMClient, LLMUsage
from clearway.oracle import tag_to_sc_ids
from clearway.schemas.models import AxeBucket, Citation, Conformance, DraftRow, Finding

_FALLBACK_CONFIDENCE = 0.0  # a draft we could not parse is worth nothing — say so, don't crash
FALLBACK_REMEDIATION = "(draft unavailable — the model did not return a usable response)"

# A confirmed violation does not "partially support" the criterion it was confirmed to fail. The unit
# of a `DraftRow` is ONE finding — one element, one confirmed failure — so `does_not_support` is the
# verdict at this granularity; rolling many rows up to a page-level `partially_supports` is a report
# decision made over rows, never a property of one. It is also the only choice that is stable under
# the documented `partial_flags` sensitivity variant (`eval/stats.is_flag`): assembling
# `partially_supports` would make a code-assembled fact change meaning depending on how a downstream
# reader scores it, which is not something an assembled fact may do.
_CONFIRMED_VIOLATION_CONFORMANCE = Conformance.DOES_NOT_SUPPORT

# Confidence on an assembled violation row is code's, not a model self-report. It is scored — wherever
# it is scored at all — against whether the CONFORMANCE was right (`eval/drafter_score`,
# `eval/confidence_build`), never against the quality of the remediation sentence. That conformance is
# axe's confirmed finding, so 1.0 is the calibrated value rather than a boast: any lower number would
# be miscalibrated by construction. It says nothing about the remediation, which stays unmeasured.
_ORACLE_GROUNDED_CONFIDENCE = 1.0


class DraftResult(NamedTuple):
    """A drafted row **plus** the usage of the LLM call that produced it. The orchestrator seam
    (`do_draft`) returns this so `execute()` can fill the `Trace` quartet; `Drafter.draft()` stays
    a thin `.row`-only convenience for callers that don't care about telemetry."""

    row: DraftRow
    usage: LLMUsage


class _LLMDraft(BaseModel):
    """The semantic fields the LLM produces for a JUDGMENT finding — one axe could not decide.
    Code assembles the full `DraftRow` around it, so the model never touches identity (`finding_id`)
    or corpus-grounded citation metadata."""

    model_config = ConfigDict(extra="ignore")  # tolerate stray keys the model may add

    conformance: Conformance
    cited_sc_ids: list[str] = Field(default_factory=list)
    remediation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class _LLMRemediation(BaseModel):
    """The single field the LLM still writes for a CONFIRMED violation: how to fix it.

    Required and non-empty, unlike `_LLMDraft.remediation`. It is the whole of the model's
    contribution now, so a blank one is not a thin draft but no draft at all — it must fail
    validation and degrade to the visible fallback rather than ship a complete-looking empty row.

    `extra="ignore"` means a model still emitting the old four-field shape cannot smuggle a verdict
    or a citation back in: the stray keys are dropped, not honoured.
    """

    model_config = ConfigDict(extra="ignore")

    remediation: str = Field(min_length=1)


def confirmed_violation_sc_ids(finding: Finding) -> list[str]:
    """The WCAG success criteria a finding is ALREADY known to fail — non-empty exactly when
    conformance and citations can be assembled instead of asked for.

    Same allowlist and same derivation as `AxeCoreOracle.verdict_for`, and deliberately the same
    function: only the confirmed `violations` bucket carries hard ground truth (`passes` and
    `incomplete` carry WCAG tags too, but axe decided nothing about them), and a violation whose tags
    decode to no criterion — axe's `best-practice` rules — yields an empty list, which routes it back
    to the judgment path where the oracle also declines to rule.
    """
    if finding.source_bucket is not AxeBucket.VIOLATIONS:
        return []
    return tag_to_sc_ids(finding.axe_tags)


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
        failed attempts spent are not attributed to a row we're discarding.

        Dispatch is on what is already known: a confirmed violation with derivable criteria drafts
        remediation only; everything else takes the unchanged judgment path.
        """
        sc_ids = confirmed_violation_sc_ids(finding)
        if sc_ids:
            return self._draft_remediation(finding, citations, sc_ids)
        return self._draft_judgment(finding, citations)

    def _draft_judgment(self, finding: Finding, citations: list[Citation]) -> DraftResult:
        """The full judgment draft: the model decides conformance, citations and confidence."""
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

    def _draft_remediation(self, finding: Finding, citations: list[Citation], sc_ids: list[str]) -> DraftResult:
        """The confirmed-violation draft: code owns the verdict and the criteria; the model writes the
        fix against them. Same validate-retry-then-degrade contract as the judgment path, so a silent
        drafter failure stays detectable by `is_fallback_draft` on both."""
        system = _remediation_system_prompt()
        user = _remediation_user_prompt(finding, sc_ids)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, _LLMRemediation)
            try:
                out = _LLMRemediation.model_validate_json(completion.content)
            except ValidationError:
                continue
            return DraftResult(_assemble_confirmed_violation(finding, citations, sc_ids, out), completion.usage)
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


def _remediation_system_prompt() -> str:
    """The confirmed-violation system prompt. It states that the verdict and the criteria are settled
    so the model spends no reasoning re-deriving them, and its schema offers nowhere to put one."""
    return (
        "You are an accessibility specialist writing the REMEDIATION for ONE confirmed WCAG failure. "
        "The failure and the success criteria it breaks are already established by an automated "
        "scanner — do NOT re-judge them, and do NOT cite different criteria. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- remediation: one concrete sentence naming the change to make to THIS element so it meets "
        "the stated criteria; never empty\n"
        'Example: {"remediation":"Add an alt attribute describing what the image shows."}'
    )


def _remediation_user_prompt(finding: Finding, sc_ids: list[str]) -> str:
    """Naming the confirmed criteria is the point of this branch: the fix is written against the SC
    axe actually derived, not against whichever one the model would have picked."""
    return (
        f"Confirmed accessibility failure: axe rule '{finding.rule_id}' — {finding.help or '(no description)'}\n"
        f"Target element: {finding.target}\n"
        f"HTML: {finding.html or '(not captured)'}\n"
        f"WCAG success criteria it fails: {', '.join(sc_ids)}\n"
        "Write the one-sentence remediation."
    )


def _user_prompt(finding: Finding, citations: list[Citation]) -> str:
    # Three-way framing by provenance. PASSES is the subtle one: axe *passed* the mechanical
    # check (a name/attribute/title EXISTS) but never judged its quality — so without this branch
    # the model reads "has alt text" as conformant and drafts `supports`, defeating the whole
    # quality-review gold set. The finding's help is already reframed to the specific task
    # (normalizer/quality_review.py); this states the general stance.
    # A VIOLATIONS finding only reaches this prompt when its tags decode to no success criterion
    # (axe's `best-practice` rules) — there is nothing to assemble, so it is a judgment call again.
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


def _resolve_citations(citations: list[Citation], sc_ids: list[str]) -> list[Citation]:
    """Resolve sc_ids against the retrieved set for corpus-grounded metadata, falling back to a bare
    `Citation` for any that was NOT retrieved. On the judgment path an unretrieved id is a citation
    the corpus never supported — exactly the hallucination the validator/oracle is built to catch, so
    we keep it, not drop it. On the assembled path it means retrieval missed an SC axe named; the
    criterion is still true of the finding, so it still ships, just without a url."""
    by_id = {c.sc_id: c for c in citations}
    return [(by_id.get(sc_id) or Citation(sc_id=sc_id)).model_copy() for sc_id in sc_ids]


def _assemble(finding: Finding, citations: list[Citation], out: _LLMDraft) -> DraftRow:
    """Build the full `DraftRow` for a judgment draft: identity + severity from code, the semantic
    verdict from the model, citations resolved from the retrieved set."""
    return DraftRow(
        finding_id=finding.id,
        conformance=out.conformance,
        citations=_resolve_citations(citations, out.cited_sc_ids),
        remediation=out.remediation,
        severity=finding.impact,
        confidence=out.confidence,
    )


def _assemble_confirmed_violation(
    finding: Finding, citations: list[Citation], sc_ids: list[str], out: _LLMRemediation
) -> DraftRow:
    """Build the `DraftRow` for a confirmed violation: everything except the remediation sentence is
    code's, derived from axe's own tags rather than asked of the model."""
    return DraftRow(
        finding_id=finding.id,
        conformance=_CONFIRMED_VIOLATION_CONFORMANCE,
        citations=_resolve_citations(citations, sc_ids),
        remediation=out.remediation,
        severity=finding.impact,
        confidence=_ORACLE_GROUNDED_CONFIDENCE,
    )


def _fallback(finding: Finding) -> DraftRow:
    """A draft we could not parse after retries: conservative verdict, zero confidence, no
    citations — surfaces as low-trust rather than crashing the run (graceful degradation).

    Deliberately bucket-independent, including for a confirmed violation whose criteria code already
    knows. A fallback is the statement "no usable row was produced", and `is_fallback_draft` reads it
    off exactly this signature; dressing it with the assembled citations would give a remediation-less
    row a confident-looking citation set and blunt the one signal that says do not trust it.
    """
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=[],
        remediation=FALLBACK_REMEDIATION,
        severity=finding.impact,
        confidence=_FALLBACK_CONFIDENCE,
    )


def is_fallback_draft(row: DraftRow) -> bool:
    """True iff `row` is the graceful-degradation fallback (`_fallback`): the model never returned
    parseable JSON. Detected by its exact signature — zero confidence *and* the fixed fallback
    remediation — so a genuine low-confidence draft is never mistaken for one. The acceptance
    benchmark aborts rather than freeze a fallback: a `does_not_support`@0.0 row would score as a
    phantom flag and silently skew FP/recall."""
    return row.confidence == _FALLBACK_CONFIDENCE and row.remediation == FALLBACK_REMEDIATION
