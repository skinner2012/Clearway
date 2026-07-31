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

Reproducibility: `judge_model` + `judge_version` (whole-prompt hash + reasoning effort) are recorded on
every result. Cloud models are not bit-reproducible even so — a pinned snapshot + fixed effort + a fixed
prompt is the honest best available.

**`judge_version` hashes the WHOLE prompt**, not the system rubric alone: the system text plus the user
prompt rendered over fixed sentinels (`_version_sentinels`), so a reworded finding-side line, a moved
field, a changed candidate heading or an edited draft presentation all move the string. It hashed the
rubric alone until the finding side grew a referent and a candidate list, at which point the unhashed
half stopped being four field labels and started carrying the material a measurement rests on — a
version string that cannot date the input it was taken under is not provenance.

⚠️ Two consequences of that reach, both intended. The sentinels render through the **drafter's** own
`referent_blocks` / `candidate_lines`, so a drafter-side reword moves the judge's version string — which
is true, because it moves the judge's prompt. And the string moved once when the hash was widened, so a
`JudgeResult` carrying the older `rubric=…` form was taken under a prompt this module can no longer
produce; the older form is historical and is never re-derivable from here.

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

Two configurations, and only the second half of the prompt tells them apart
---------------------------------------------------------------------------
`Judge` is the **anchored** configuration: it is shown the draft and grades it. `BlindJudge` is the
**blind** one: it is shown the finding side alone, answers for itself, and never learns that a draft
exists. Agreement is then decided by CODE — raw four-value equality on `conformance`, exact set match
on the cited criteria — which is what makes the judge an independent rater and κ mean what κ claims to
measure. Neither model call can leak the other configuration's material, because the blind entry point
takes no draft at all: the withholding is a property of the signature rather than a promise in prose.

**Each configuration carries its OWN `judge_version`, and that is deliberate.** The string is a hash
over the prompt a result was taken under, so two configurations that send different prompts must not
report one string — a run frozen under either has to be datable to the prompt it actually saw. The
converse matters just as much: adding the blind rubric leaves the anchored prompt byte-identical, so
the anchored string does **not** move, and a measurement already frozen under it stays current rather
than being falsely re-dated by an edit that could not have reached it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from clearway.drafter.llm import candidate_lines, referent_blocks
from clearway.llm import LLMClient
from clearway.schemas.models import (
    Citation,
    Conformance,
    ConformanceLevel,
    DraftRow,
    Finding,
    JudgeResult,
    JudgeVerdict,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
)


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


def require_distinct_models(client: LLMClient, drafter_model: str) -> None:
    """Refuse a judge that is the drafter. Shared by both configurations, because the discipline is
    the judge's rather than any one configuration's — a blind second reader drawn from the drafter's
    own family is not a second reader at all."""
    if client.model == drafter_model:
        raise ValueError(
            f"judge model {client.model!r} must differ from the drafter model — a model grading "
            "its own output self-preferences"
        )


def version_string(client: LLMClient, prompt_digest: str) -> str:
    """`prompt=<digest>; effort=<effort>` — the provenance a result carries, assembled in one place.

    The digest is the CONFIGURATION's own, never a shared one: see the module docstring. The effort is
    read off the client because it is not a constant (it resolves from the environment first), and a
    client that reports none contributes no term rather than an empty one.
    """
    effort = getattr(client, "reasoning_effort", None)
    parts = [f"prompt={prompt_digest}"]
    if effort:
        parts.append(f"effort={effort}")
    return "; ".join(parts)


class Judge:
    """Grades drafted judgment items with a cloud reference model on a fixed rubric.

    `retries` is the number of *extra* attempts on an unparseable response before raising.
    """

    def __init__(self, client: LLMClient, drafter_model: str, retries: int = 1) -> None:
        require_distinct_models(client, drafter_model)
        self._client = client
        self._retries = retries
        self._judge_version = version_string(client, prompt_hash())

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


_BLIND_SYSTEM = (
    "You are a WCAG 2.2 accessibility expert drafting ONE conformance row for a VPAT/ACR. You are "
    "given ONE accessibility finding and the WCAG success criteria retrieved for it, and you decide "
    "the verdict yourself. No other rater's answer is shown to you: there is nothing here to agree "
    "with, to grade, or to defer to.\n"
    "For a QUALITY-REVIEW finding (axe confirmed a name/attribute is PRESENT but did not judge its "
    "quality), a present-but-inadequate value is does_not_support or partially_supports, never "
    "supports.\n"
    "Rules:\n"
    "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
    "- cited_sc_ids: name the criterion you decided against — only WCAG SC ids from the candidates "
    "shown, the SINGLE most applicable one, adding a second only if the finding independently fails "
    "that one too. Name NOTHING when you find no failure.\n"
    "Do NOT judge severity and do NOT write remediation. Output ONLY the JSON object with "
    "conformance, cited_sc_ids, and a one-sentence rationale."
)


class _BlindAnswer(BaseModel):
    """The judge's OWN answer — the drafter's two semantic fields, asked of a second reader.

    Deliberately the same shape the drafter answers under (`drafter.llm._LLMDraft`'s `conformance` and
    `cited_sc_ids`), because two readers can only be compared field-for-field if they were asked for
    the same fields. `remediation` and `confidence` are not asked for: prose is never compared and the
    schema already declares confidence decorative, so asking would spend tokens on fields no
    comparison may read. `extra="forbid"` → `additionalProperties:false`, the cloud Responses API's
    strict json-schema mode.
    """

    model_config = ConfigDict(extra="forbid")

    conformance: Conformance
    cited_sc_ids: list[str]
    rationale: str


@dataclass(frozen=True)
class BlindAnswer:
    """One blind judge's own answer to one finding, before any comparison has happened.

    It is kept as its own value rather than folded straight into a `JudgeResult` because the two are
    different facts: this is what the judge said, and a `JudgeResult` is what code concluded by
    setting that beside a draft. Only the first survives a configuration change; only the second fits
    the production shape. The run artifact carries both, and `Direction of disagreement` can be
    answered from this one alone.
    """

    finding_id: str
    conformance: Conformance
    cited_sc_ids: tuple[str, ...]
    rationale: str


def conformance_agrees(answer: BlindAnswer, draft: DraftRow) -> bool:
    """RAW four-value equality — `partially_supports` and `does_not_support` are a disagreement.

    The FLAG/CLEAN collapse exists because ACT gold is binary and four drafted verdicts have to reach
    it; that constraint governs scoring against gold, not the comparison of two raters' answers. Both
    readers emit the same four-value enum, so they are compared directly, and a difference of degree is
    a real difference of opinion worth a human's attention.
    """
    return answer.conformance is draft.conformance


def citations_agree(answer: BlindAnswer, draft: DraftRow) -> bool:
    """EXACT set match on the cited ids, with no normalisation of any kind.

    Nothing is stripped, case-folded or canonicalised on the way in: every looser rule is a tunable,
    and a tunable settled after seeing results is the failure this comparison exists to avoid. The
    drafter's ids are already canonical dotted form, and a judge that answers in some other form is
    disagreeing about what it was asked for, which the artifact shows as prose beside the count.
    """
    return set(answer.cited_sc_ids) == {c.sc_id for c in draft.citations}


class BlindJudge:
    """Answers for itself, and never learns that a draft exists.

    The blinding is structural: `answer` takes a finding side and nothing else, so there is no draft
    in scope at the point the model is called. `compare` is pure — it makes no call — and turns an
    answer plus the frozen draft into the same `JudgeResult` the anchored configuration produces, with
    both booleans derived here rather than emitted by the model.

    ⚠️ `citation_correct` and `conformance_correct` therefore mean something different on this
    configuration: *the judge named the same criteria* and *the judge reached the same verdict*, not
    *the drafted answer is right*. The field names are the anchored ones because the production shape
    is fixed, so any artifact holding these results states its configuration beside them.
    """

    def __init__(self, client: LLMClient, drafter_model: str, retries: int = 1) -> None:
        require_distinct_models(client, drafter_model)
        self._client = client
        self._retries = retries
        self._judge_version = version_string(client, blind_prompt_hash())

    @property
    def judge_version(self) -> str:
        return self._judge_version

    @property
    def judge_model(self) -> str:
        return self._client.model

    def answer(self, prepared: FindingInput) -> BlindAnswer:
        """Ask the judge for its own verdict on one finding. **No draft is in scope here.**

        Raises rather than fabricating, exactly as the anchored path does: an instrument that invents
        an answer when the model drifts off-schema corrupts every number computed from it.
        """
        user = blind_user_prompt(prepared)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(_BLIND_SYSTEM, user, _BlindAnswer)
            try:
                out = _BlindAnswer.model_validate_json(completion.content)
            except ValidationError:
                continue  # model drifted off-schema; retry, then raise — never fabricate
            return BlindAnswer(
                finding_id=prepared.finding_id,
                conformance=out.conformance,
                cited_sc_ids=tuple(out.cited_sc_ids),
                rationale=out.rationale,
            )
        raise JudgeError(
            f"blind judge {self._client.model!r} returned no parseable answer for finding "
            f"{prepared.finding_id!r} after {self._retries + 1} attempts"
        )

    def compare(self, answer: BlindAnswer, draft: DraftRow, run_id: str) -> JudgeResult:
        """The judge's answer beside the frozen draft — **pure, and it makes no call.**

        This is the whole of "agreement is decided by code": two comparisons, both spelled out above,
        and a `verdict` derived by the same rule the anchored configuration derives it under.
        """
        citation_correct = citations_agree(answer, draft)
        conformance_correct = conformance_agrees(answer, draft)
        return JudgeResult(
            finding_id=answer.finding_id,
            run_id=run_id,
            judge_model=self._client.model,
            judge_version=self._judge_version,
            verdict=verdict_from(citation_correct, conformance_correct),
            citation_correct=citation_correct,
            conformance_correct=conformance_correct,
            rationale=answer.rationale,
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


def blind_user_prompt(prepared: FindingInput) -> str:
    """The blind configuration's user prompt: **the frozen finding side, alone.**

    It appends nothing — not even an instruction line — so the bytes sent are exactly the bytes
    frozen, and "the two configurations were asked the same question" is a property of one file rather
    than a claim about two code paths. Everything the blind configuration adds lives in its system
    rubric, where a draft cannot reach it.

    Public because a measurement of how many DISTINCT asks the configuration makes has to render them
    through the path that sends them; a count taken over the frozen rows instead would go on agreeing
    with reality only until this function stopped being the identity.
    """
    return prepared.block


# ---------------------------------------------------------------------------------------------
# What `judge_version` hashes: the system rubric plus the user prompt over fixed sentinels.
# ---------------------------------------------------------------------------------------------
#
# One sentinel cannot reach the whole template. The referent block is gated by CLASS — `label`,
# `document-title` and `link-name` each have their own builder and a finding carries one rule id — so a
# single sentinel would leave two of the three builders outside the hash, and a reword there would move
# the judge's prompt invisibly again. The set below covers every branch a judged finding can take:
# the three referent classes, a class with no referent block at all, a candidate carrying normative text
# and one carrying none, an empty candidate list, and a draft presentation with and without citations.
#
# The values are arbitrary; only their STABILITY matters. Changing one re-dates every measurement taken
# under the old string, which is why they are frozen here rather than derived from the corpus.

_LONG_NORMATIVE_TEXT = "The purpose of each link can be determined from the link text alone. " * 8


def _sentinel_referent() -> NodeReferent:
    """A referent populated on every source, so no per-class builder's branch escapes the hash."""
    return NodeReferent(
        accessible_name=ReferentExcerpt(text="sentinel name", source=ReferentSource.ACCESSIBLE_NAME),
        document_title=ReferentExcerpt(text="sentinel title", source=ReferentSource.DOCUMENT_TITLE),
        page_topic=ReferentExcerpt(text="sentinel topic", source=ReferentSource.H1),
        section_heading=ReferentExcerpt(
            text="sentinel heading", source=ReferentSource.NEAREST_SECTION_HEADING, in_accessibility_tree=True
        ),
        surrounding_context=ReferentExcerpt(
            text="sentinel context", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
        ),
    )


def _sentinel_finding(rule_id: str, *, referent: NodeReferent | None) -> Finding:
    return Finding(
        id=f"version-sentinel:{rule_id}",
        source_url="file://version-sentinel.html",
        rule_id=rule_id,
        target="#sentinel",
        html="<span>sentinel</span>",
        help="sentinel task",
        referent=referent,
    )


def _sentinel_citation(sc_id: str, text: str) -> Citation:
    return Citation(
        sc_id=sc_id,
        title="Sentinel Criterion",
        level=ConformanceLevel.A,
        source="WCAG-SC",
        url=f"https://www.w3.org/TR/WCAG22/#sentinel-{sc_id}",
        text=text,
    )


def _sentinel_draft(finding: Finding, conformance: Conformance, *sc_ids: str) -> DraftRow:
    return DraftRow(
        finding_id=finding.id,
        conformance=conformance,
        citations=[Citation(sc_id=s) for s in sc_ids],
        remediation="sentinel remediation",
        confidence=0.5,
    )


def _version_sentinels() -> tuple[tuple[Finding, list[Citation], DraftRow], ...]:
    referent = _sentinel_referent()
    label = _sentinel_finding("label", referent=referent)
    title = _sentinel_finding("document-title", referent=referent)
    link = _sentinel_finding("link-name", referent=referent)
    bare = _sentinel_finding("empty-heading", referent=None)
    with_text = _sentinel_citation("3.3.2", "Labels or instructions are provided.")
    over_budget = _sentinel_citation("2.4.4", _LONG_NORMATIVE_TEXT)
    text_less = _sentinel_citation("2.4.2", "")
    return (
        (label, [with_text], _sentinel_draft(label, Conformance.DOES_NOT_SUPPORT, "3.3.2")),
        (title, [text_less], _sentinel_draft(title, Conformance.PARTIALLY_SUPPORTS, "2.4.2", "1.3.1")),
        (link, [over_budget], _sentinel_draft(link, Conformance.NOT_APPLICABLE)),
        (bare, [], _sentinel_draft(bare, Conformance.SUPPORTS)),
    )


def version_prompts() -> tuple[str, ...]:
    """Every prompt the version hash is taken over — the system text, then one user prompt per sentinel.

    Public so a test can assert what the hash reaches rather than restate the hash: a pin on the digest
    alone would pass a sentinel that silently stopped rendering a block.
    """
    asks = [_judge_user_prompt(finding_input(f, c), d) for f, c, d in _version_sentinels()]
    return (_RUBRIC_SYSTEM, *asks)


def blind_version_prompts() -> tuple[str, ...]:
    """Every prompt surface the BLIND configuration can produce — its rubric, then one ask per sentinel.

    The same sentinels, because the finding side is the same file and its per-class builders are the
    same builders; what differs is that a blind ask ends where the finding side ends. The sentinels'
    drafts are unused here, and deliberately not removed from the set: they exist to cover the
    ANCHORED half, and one shared sentinel set is what keeps a reworded referent line moving both
    configurations' strings.
    """
    asks = [blind_user_prompt(finding_input(f, c)) for f, c, _ in _version_sentinels()]
    return (_BLIND_SYSTEM, *asks)


def _digest_of(prompts: tuple[str, ...]) -> str:
    return hashlib.sha256("\x00".join(prompts).encode()).hexdigest()[:8]


def prompt_hash() -> str:
    """The first 8 hex of the sha256 over every prompt surface a judged finding can produce."""
    return _digest_of(version_prompts())


def blind_prompt_hash() -> str:
    """The same, for the blind configuration — **a separate digest, on purpose.**

    Two configurations send two different prompts, so one string could not date either. Computing them
    apart also means adding this configuration did not move the anchored one: an anchored measurement
    frozen before the blind rubric existed was taken under a prompt this module still produces
    byte-for-byte, and re-dating it would be a false positive in the one field that exists to say when
    a prompt moved.
    """
    return _digest_of(blind_version_prompts())
