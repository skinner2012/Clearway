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

Grounding note: a retrieved `Citation` carries the criterion's **normative text**, so the candidate
block shows the model what each candidate actually requires instead of naming an id and leaving it
to supply the meaning from memory. The text is bounded here rather than at retrieval — see
`NORMATIVE_TEXT_CHARS`. A candidate with no text (an SC named but never retrieved) renders exactly
the id/url line it always rendered, so grounding appears only where there is grounding to show.

A picture, on the judgment path only
------------------------------------
`draft(finding, citations, image=…)` attaches one `ImagePart` to the model call. It exists because a
whole class of questions this drafter is asked is not answerable from the DOM: axe can say an image
*has* an accessible name, and whether that name describes the picture is a fact about pixels. The
referent blocks above carry the text such judgments need; this carries the one piece of referent
material that is not text.

Three properties, each load-bearing rather than tidy:

* **The prompt is untouched by it.** No sentence is added saying a picture is attached, so two
  requests can differ in pixels alone — the premise the image experiment's statistic is defined over,
  and the reason the model is never told to look. It also means the text-only classes are provably
  unaffected: a payload hash over a no-image call is unchanged by this whole channel
  (`eval/drafter_payload.py`).
* **The assembled path takes no picture, and says so loudly.** A confirmed violation's verdict and
  criteria come from axe's tags; the model writes one sentence against them. Handing that path an
  image is refused (`ImageOnAssembledPath`) rather than dropped — a dropped picture leaves a
  complete-looking row whose model was shown nothing, which is indistinguishable in an artifact from
  a model that looked and was unmoved. That distinction is the entire experiment.
* **What was sent is recorded.** `DraftResult.request` carries the request as a value — prompts,
  schema name, and the attached picture's digest — so a receipt records the sha256 of what actually
  went out instead of re-deriving what probably did.

Judging blind, and knowing it
-----------------------------
A whole class of question here is decided by pixels, and this drafter is routinely asked one of them
with no pixels attached. That is legitimate — production scans do not always capture — but answering
it *confidently and silently* is not, and it is the same family of failure as a confidence number
that does not move with correctness. Three pieces, each doing one job:

* **`visually_verified` is the system's own fact**, written by `_visually_verified` from what this
  module knows at the seam: a pixel-decided finding drafted with no picture carries `False`. It needs
  no model, it costs nothing, and it is what a row is marked with.
* **`visual_evidence` is the model's claim** about the evidence its judgment needed, and it is
  written only where the model was actually asked for it (`announce_image=True`). Two fields rather
  than one, because a single field would let the deterministic value stand in for the model's answer
  and any later measurement over it would be measuring this module rather than the drafter.
* **A row claiming `seen` against `visually_verified is False` fails**, and degrades through the
  existing validate-retry-then-fallback contract rather than through a second failure mode.

`announce_image` defaults **off**, and that is a control rather than caution: shipped on
unconditionally the announcement sentence moves every payload hash in
`benchmark/reports/drafter_payload_baseline.json` — the pre-wiring comparison those hashes exist for.
Two gates keep it still: the parameter (no existing caller changes at all) and the class gate (a
finding outside `PIXEL_DECIDED_RULES` is byte-identical even after the parameter flips). The
announced call also asks under its **own schema class**, because `LLMRequest` records
`schema.__name__` and not the schema's shape: widening `_LLMDraft` in place would change what the
model is asked to produce while moving neither `prompt_sha256` nor `payload_sha256`. That residual
gap — a field added in place is invisible to both hashes — is routed around here, not closed, and is
recorded in `CONTRACTS.md` §5.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clearway.llm import ImagePart, LLMClient, LLMRequest, LLMUsage
from clearway.oracle import tag_to_sc_ids
from clearway.schemas.models import AxeBucket, Citation, Conformance, DraftRow, Finding, VisualEvidence

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

# --------------------------------------------------------------------------------------
# The normative-text budget. Same house rule as the scanner's referent extractors: a named
# source, a pinned character budget, one deterministic truncation rule.
# --------------------------------------------------------------------------------------
#
# The candidate criteria's normative text is corpus prose, and prose is the input most likely to
# bloat a prompt. Measured over the 86 criteria of WCAG 2.2 as the corpus stores them, that text
# runs 41-1759 characters (median 253), so five unbounded candidates could add ~8,800 characters to
# a ~830-character prompt — a 10x input for a one-sentence answer, on a local model whose quality
# falls away as the prompt grows.
#
# 400 is ~1.6x the corpus median and leaves 54 of the 86 criteria whole. At the default k=5 it caps
# what grounding adds at 2,330 characters however retrieval lands — pinned by test, so the bound is
# checked rather than asserted here. **Truncation is prefix-only**, and
# that is the whole reason the cut is safe: WCAG states the requirement first and its exceptions,
# notes and enumerated cases after, so a prefix keeps the rule and drops the qualifications — a
# suffix cut would keep the footnotes and lose the rule. A truncated candidate says so in the
# prompt, with the budget named, so a bounded excerpt is never read as the whole criterion.
NORMATIVE_TEXT_CHARS = 400
_TRUNCATION_NOTE = f" (normative text truncated at {NORMATIVE_TEXT_CHARS} characters)"

# The classes whose judgment is decided by PIXELS — pinned here, beside the drafter that acts on it.
#
# Keyed by the RULE, where the scanner's `image_ref` is keyed by the NODE, and both are right. *"Did
# this node render a picture"* is a property of the node, which is why a reference rides on one; *"does
# this class's judgment need pixels"* is a property of the QUESTION, and a rule firing on the same node
# can ask a question no picture answers. It is never inferred from `image_ref`, which is `None` in
# exactly the case the marking exists for.
PIXEL_DECIDED_RULES = frozenset({"image-alt"})


class ImageOnAssembledPath(ValueError):
    """A picture was supplied for a finding that drafts on the assembled path.

    Refused rather than dropped. That path's verdict and criteria come from axe's own tags and the
    model writes one sentence against them, so there is nowhere for a picture to change an answer —
    but a silently discarded one produces a row that looks exactly like a row whose model looked at
    the pixels and was unmoved, and telling those two apart is the whole point of sending pixels.
    """


class DraftResult(NamedTuple):
    """A drafted row **plus** the usage of the LLM call that produced it, **plus** the request that
    was sent. The orchestrator seam (`do_draft`) returns this so `execute()` can fill the `Trace`
    quartet; `Drafter.draft()` stays a thin `.row`-only convenience for callers that don't care
    about telemetry.

    `request` is what went to the model, as a comparable value — the two prompts, the response
    schema's name and the attached picture's digest. It is here rather than re-derived by the caller
    because a receipt that reconstructs the request it *thinks* was sent cannot detect the one failure
    that matters: a picture that never left this module. `None` means no call was recorded, which only
    a hand-built `DraftResult` (a test stub, an orchestrator fake) produces.
    """

    row: DraftRow
    usage: LLMUsage
    request: LLMRequest | None = None


class _LLMDraft(BaseModel):
    """The semantic fields the LLM produces for a JUDGMENT finding — one axe could not decide.
    Code assembles the full `DraftRow` around it, so the model never touches identity (`finding_id`)
    or corpus-grounded citation metadata."""

    model_config = ConfigDict(extra="ignore")  # tolerate stray keys the model may add

    conformance: Conformance
    cited_sc_ids: list[str] = Field(default_factory=list)
    remediation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class _LLMDraftVisualEvidence(_LLMDraft):
    """`_LLMDraft` plus the one field the **announced** ask adds: what the model could see.

    A subclass rather than a widening of `_LLMDraft`, and the reason is a hash. `LLMRequest.of`
    records `schema.__name__` — the class name, not its shape — so adding this field to `_LLMDraft` in
    place would change what the model is asked to produce while moving neither `prompt_sha256` nor
    `payload_sha256`: the control built to catch a moved ask, blind to a moved answer. A distinct name
    moves the hash exactly when the ask moves, with no change to `LLMRequest`; the unannounced path
    keeps asking under `_LLMDraft`, so its existing hashes are not merely equal but produced by
    identical code; and a field the model was never asked for cannot be filled by accident, being
    absent from the shape it answers under.

    Required rather than defaulted: this class exists only where the prompt explains the field, so a
    response omitting it is off-schema and takes the same retry-then-degrade path as any other
    malformed draft. `None` on a persisted row therefore means *the model was not asked*, never *the
    model declined to answer*.
    """

    visual_evidence: VisualEvidence


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

    def draft(
        self,
        finding: Finding,
        citations: list[Citation],
        image: ImagePart | None = None,
        announce_image: bool = False,
    ) -> DraftRow:
        """Convenience for callers that only want the row (offline mechanics tests, the gated
        real-model tests). The durable orchestrator uses `draft_with_usage` to also thread usage
        into the `Trace`."""
        return self.draft_with_usage(finding, citations, image, announce_image).row

    def draft_with_usage(
        self,
        finding: Finding,
        citations: list[Citation],
        image: ImagePart | None = None,
        announce_image: bool = False,
    ) -> DraftResult:
        """Draft the row **and** return the usage of the LLM call that produced it. Usage is the
        successful call's; a fallback (model never parsed) carries empty usage — the tokens the
        failed attempts spent are not attributed to a row we're discarding.

        Dispatch is on what is already known: a confirmed violation with derivable criteria drafts
        remediation only; everything else takes the unchanged judgment path.

        `image` is optional and only the judgment path can carry it — see `ImageOnAssembledPath` for
        why the other path refuses rather than ignores one.

        `announce_image` tells the model whether a picture is attached and asks it to report what its
        judgment could see. **Default off** — see the module docstring for the two hashes that keeps
        still. It reaches the judgment path only: the assembled path takes no picture, re-judges
        nothing, and is left byte-identical rather than given a sentence about evidence it does not
        use. That is why the flag is not refused there — nothing is dropped by ignoring it, and the
        row says so, since `visual_evidence` stays `None` wherever no model wrote one.
        """
        sc_ids = confirmed_violation_sc_ids(finding)
        if sc_ids:
            if image is not None:
                raise ImageOnAssembledPath(
                    f"an image ({image.ref[:8]}…) was supplied for {finding.rule_id} finding {finding.id}, "
                    f"whose criteria are already derived from axe's tags ({', '.join(sc_ids)}) — that draft "
                    "asks the model for a remediation sentence only, so the picture would be dropped and the "
                    "row would be indistinguishable from one the model saw the picture for"
                )
            return self._draft_remediation(finding, citations, sc_ids)
        return self._draft_judgment(finding, citations, image, announce_image)

    def _draft_judgment(
        self,
        finding: Finding,
        citations: list[Citation],
        image: ImagePart | None = None,
        announce_image: bool = False,
    ) -> DraftResult:
        """The full judgment draft: the model decides conformance, citations and confidence — from the
        prompt, and from the picture where one is attached.

        The request is built once, before the retry loop, and returned on the result: every attempt
        sends the identical ask, so what is recorded is what was sent however many attempts it took,
        including the attempt sequence that ended in the fallback.

        A row that claims it saw a picture this module never sent is refused exactly like an
        off-schema one: retry, then degrade to the visible fallback. One failure mode, not two — a
        second one would need its own detector everywhere `is_fallback_draft` is already read.
        """
        announces = _announces_image(finding, announce_image)
        schema = _LLMDraftVisualEvidence if announces else _LLMDraft
        verified = _visually_verified(finding, image)
        system = _system_prompt(announce_image=announces)
        user = _user_prompt(finding, citations, announce_image=announce_image, image_attached=image is not None)
        request = LLMRequest.of(system, user, schema, image)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, schema, image)
            try:
                out = schema.model_validate_json(completion.content)
            except ValidationError:
                continue  # model drifted off-schema; try again, then fall back
            if _claims_evidence_it_was_never_sent(out, verified):
                continue  # a row claiming `seen` against the system's own record — same path
            return DraftResult(_assemble(finding, citations, out, verified), completion.usage, request)
        return DraftResult(_fallback(finding), LLMUsage(), request)

    def _draft_remediation(self, finding: Finding, citations: list[Citation], sc_ids: list[str]) -> DraftResult:
        """The confirmed-violation draft: code owns the verdict and the criteria; the model writes the
        fix against them. Same validate-retry-then-degrade contract as the judgment path, so a silent
        drafter failure stays detectable by `is_fallback_draft` on both.

        It takes no `image` parameter at all, which is the strongest form of "this path sends no
        picture": there is nothing here to forget to pass on, and the caller's mistake is caught one
        level up, where it can be named."""
        system = _remediation_system_prompt()
        user = _remediation_user_prompt(finding, sc_ids)
        request = LLMRequest.of(system, user, _LLMRemediation)
        for _ in range(self._retries + 1):
            completion = self._client.complete_json(system, user, _LLMRemediation)
            try:
                out = _LLMRemediation.model_validate_json(completion.content)
            except ValidationError:
                continue
            row = _assemble_confirmed_violation(finding, citations, sc_ids, out)
            return DraftResult(row, completion.usage, request)
        return DraftResult(_fallback(finding), LLMUsage(), request)


def _announces_image(finding: Finding, announce_image: bool) -> bool:
    """Both gates on the announcement, in one place so no site can apply only one of them.

    The **parameter** keeps every existing caller byte-identical; the **class gate** keeps a finding
    outside the pixel-decided classes byte-identical even after the parameter is flipped on. Each
    covers a hole the other leaves, and the answer decides all three halves of the ask at once — the
    system prompt, the user prompt's block, and the response schema — because `prompt_sha256` covers
    the schema's name as well as the two prompts.
    """
    return announce_image and finding.rule_id in PIXEL_DECIDED_RULES


def _visually_verified(finding: Finding, image: ImagePart | None) -> bool | None:
    """The system's own fact about one judgment, from what this module holds at the seam.

    Tri-state, and the `None` is the load-bearing value: a class no picture decides is not
    *unverified*, it is a class where the question does not arise, and spelling that `False` would
    mark every text finding in the product visually unverified. No model, no cost, no way for it to
    be wrong about the one thing it reports.
    """
    if finding.rule_id not in PIXEL_DECIDED_RULES:
        return None
    return image is not None


def _claims_evidence_it_was_never_sent(out: _LLMDraft, visually_verified: bool | None) -> bool:
    """A row claiming it saw a picture the system records not having sent — a hallucination catchable
    with no model and no judge, which is the whole reason the claim and the fact are two fields.

    Only `seen` contradicts: `absent` and `not_needed` are both answers a blind draft may correctly
    give, and `seen` against `None` is not a contradiction either — that judgment was never one
    pixels decide, so the model is reporting on evidence this module does not track.
    """
    return (
        isinstance(out, _LLMDraftVisualEvidence)
        and out.visual_evidence is VisualEvidence.SEEN
        and visually_verified is False
    )


def _system_prompt(announce_image: bool = False) -> str:
    """The judgment system prompt.

    The `cited_sc_ids` rule carries a **citation budget**: cite the single most applicable criterion.
    Without one, "only ids that genuinely apply" reads as permission to cite the whole candidate list,
    and a row that cites five criteria is not five times as grounded — it is one answer diluted, and
    it scores as one hit however loosely each id fits. The budget is stated with an explicit escape in
    both directions (a second id where the finding independently fails it; none where none applies),
    so it narrows the citation set without forcing a citation the model does not believe.

    `announce_image` adds the `visual_evidence` rule, and the default keeps this function returning
    the exact string it returned before the field existed. The rule states the question as *what this
    judgment needed*, never *what was attached*: the second is a fact the caller already holds, and a
    model told there is no picture would answer it correctly by repeating the sentence it was handed.

    **The example's value is `seen`, chosen against the measurement rather than for it.** Whether the
    drafter reports an absence is counted in `absent` rows, so an example showing `absent` would
    manufacture the very result; showing `seen` can only make that count harder to reach.
    """
    visual_evidence_rule = (
        "- visual_evidence: EXACTLY one of seen | absent | not_needed — about the evidence THIS "
        "judgment needed, not about what was attached: seen if you examined the picture and used it, "
        "absent if deciding this element required seeing the picture and none was available to you, "
        "not_needed if the element can be judged from the text alone\n"
        if announce_image
        else ""
    )
    visual_evidence_example = ',"visual_evidence":"seen"' if announce_image else ""
    return (
        "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
        "- cited_sc_ids: only WCAG SC ids from the provided candidates, and cite the SINGLE most "
        "applicable one — the criterion this finding most directly fails. Add a second only if the "
        "finding independently fails that one too; cite none if none of the candidates applies\n"
        "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
        "- remediation: one concrete sentence on how to fix it\n"
        f"{visual_evidence_rule}"
        'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
        f'"remediation":"Add a descriptive alt attribute.","confidence":0.9{visual_evidence_example}}}'
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


def _label_referent_block(finding: Finding) -> str:
    """The `label` referent block appended after the prompt body: the resolved accessible name and
    the nearest section heading, each as one short labelled line.

    `''` for any class other than `label`, or when no referent rode in on the finding — so the block
    is disjoint by class (the sibling injections append their own) and gated on presence: no
    referent, no change, which keeps every no-referent prompt byte-identical to the pre-injection one.

    `None` on a source means the source was absent (nothing to say, so no line); a source that WAS
    present but resolved to empty text is a `ReferentExcerpt` with `text == ""` and is rendered as
    empty quotes, because "no heading above the field" and "the heading is blank" are different facts.
    The heading carries its accessibility-tree flag verbatim, `unknown` where the check could not run.
    """
    if finding.rule_id != "label" or finding.referent is None:
        return ""
    ref = finding.referent
    lines: list[str] = []
    if ref.accessible_name is not None:
        lines.append(f'Resolved accessible name: "{ref.accessible_name.text}"')
    if ref.section_heading is not None:
        in_tree = ref.section_heading.in_accessibility_tree
        note = "unknown" if in_tree is None else ("yes" if in_tree else "no")
        lines.append(f'Nearest section heading: "{ref.section_heading.text}" (in accessibility tree: {note})')
    if not lines:
        return ""
    return "\n" + "\n".join(lines)


def _document_title_referent_block(finding: Finding) -> str:
    """The `document-title` referent block appended to the user prompt, or '' for any other class and
    for a finding that carries no referent.

    Two facts axe never puts in the prompt, on their own labelled lines: the **resolved <title>** the
    drafter is being asked to judge (for a `document-title` finding the target is `html`, so the
    element snippet is just `<html lang=…>` — the title itself is nowhere in the base prompt), and the
    **page-topic signal** it is compared against, tagged with the DOM tier that produced it
    (`ref.page_topic.source`) so a reader always knows whether the topic came from an `<h1>`, the main
    landmark, a meta description or the rendered body.

    The resolved title is load-bearing: a topic signal alone cannot decide whether a title describes
    its page, so an absent title (`document_title is None`) gates the whole block out — the topic is
    never injected without the title it is judged against. `text == ""` (a present-but-empty source)
    is a different fact from absent and is carried through verbatim rather than gated.
    """
    if finding.rule_id != "document-title" or finding.referent is None:
        return ""
    ref = finding.referent
    if ref.document_title is None:
        return ""
    lines = [f'Resolved page title: "{ref.document_title.text}"']
    if ref.page_topic is not None:
        topic = ref.page_topic
        lines.append(f'Page topic signal (source: {topic.source.value}): "{topic.text}"')
    return "\n" + "\n".join(lines)


def _link_name_referent_block(finding: Finding) -> str:
    """The `link-name` referent block: '' for any other class or when no usable referent is present.

    `link-name` is an INSUFFICIENCY class — every case already gets its own prompt, but none carries
    the deciding fact (what the link is *for*). This appends that fact where the scan captured it,
    matching the referent to the gap:

    * the resolved **accessible name**, where the name is computed elsewhere (an `aria-labelledby`
      link has no link text of its own), and
    * the bounded **surrounding context** with its ancestor depth, where the name is present but
      ambiguous ("EPUB" under a "Download Ulysses" cell).

    The extent is pinned by the scanner (`scanner/referent.py`): context climbs at most
    `CONTEXT_ANCESTOR_MAX_DEPTH = 3` ancestors and is bounded to `SURROUNDING_CONTEXT_CHARS = 500`;
    that bound is stated in the prompt so an injected window is never read as the whole neighbourhood.
    The block is honest that the link **destination** is outside the DOM and unavailable, so the model
    judges purpose from the referent rather than inventing a target URL.

    `None` (source absent) drops the line; a present-but-empty excerpt (`text == ""`) keeps its line,
    because "the surrounding text is blank" is a different fact from "there was none". If neither the
    accname nor the surrounding context is present, there is nothing this class can use — return ''.
    """
    if finding.rule_id != "link-name" or finding.referent is None:
        return ""
    ref = finding.referent
    lines: list[str] = []
    if ref.accessible_name is not None:
        lines.append(f'Resolved accessible name: "{ref.accessible_name.text}"')
    if ref.surrounding_context is not None:
        depth = ref.surrounding_context.ancestor_depth
        depth_label = depth if depth is not None else "unknown"
        lines.append(
            f"Surrounding context (ancestor depth {depth_label}, bounded to at most 3 ancestor levels "
            f'and 500 characters): "{ref.surrounding_context.text}"'
        )
    if not lines:
        return ""
    lines.insert(0, "Referent (captured deterministically at scan time, not by a model):")
    lines.append(
        "Link destination: not available — the surrounding context is a proxy for it, not the "
        "destination; judge the link's purpose from the accessible name and surrounding context only, "
        "and do not invent a target URL."
    )
    return "\n" + "\n".join(lines)


def _image_announcement_block(finding: Finding, announce_image: bool, image_attached: bool) -> str:
    """The one sentence that says whether a picture rode with this prompt — or `''`.

    Disjoint by class exactly like the three referent blocks above, and gated on the caller's request
    as well (`_announces_image` holds both gates). It states a fact and asks for nothing: the field's
    rules live in the system prompt, and an instruction to *look* here would make an announced call
    differ from an unannounced one in more than what it announces.

    It is rendered in **both** directions, because "no picture is attached" is the half that matters:
    the defect this closes is a model answering a question about pixels with no pixels and no sign
    that anything was missing. Saying so is what gives it somewhere to go.
    """
    if not _announces_image(finding, announce_image):
        return ""
    if image_attached:
        return "\nVisual evidence: a picture of this element, as the page rendered it, IS attached to this message."
    return "\nVisual evidence: NO picture of this element is attached to this message."


def _candidate_lines(citations: list[Citation]) -> str:
    """The candidate-criteria block: the id/url line each citation has always rendered, plus — where
    the corpus supplied one — the criterion's bounded normative text on an indented line beneath it.

    Gated on presence, exactly like the referent blocks: a citation carrying no text renders the one
    line and nothing else, so a bare `Citation(sc_id=…)` (an SC named but never retrieved) produces
    the pre-grounding block byte-for-byte. Truncation is prefix-only and announced — see
    `NORMATIVE_TEXT_CHARS` for the budget and why the cut runs that way.
    """
    lines: list[str] = []
    for citation in citations:
        lines.append(f"- {citation.sc_id} ({citation.url})")
        if citation.text:
            note = _TRUNCATION_NOTE if len(citation.text) > NORMATIVE_TEXT_CHARS else ""
            lines.append(f"  What it requires: {citation.text[:NORMATIVE_TEXT_CHARS]}{note}")
    return "\n".join(lines) or "- (none retrieved)"


def _user_prompt(
    finding: Finding,
    citations: list[Citation],
    announce_image: bool = False,
    image_attached: bool = False,
) -> str:
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
    candidates = _candidate_lines(citations)
    base = (
        f"Finding ({bucket}): axe rule '{finding.rule_id}' — {finding.help or '(no description)'}\n"
        f"Target element: {finding.target}\n"
        f"HTML: {finding.html or '(not captured)'}\n"
        f"Candidate WCAG success criteria you may cite:\n{candidates}\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )
    # Per-class referent injection: each block is disjoint by class and returns "" for every other
    # class (and for a finding that carries no referent), so `base` stays byte-identical wherever the
    # block does not apply — the property the control's byte-identity guard rests on. The appends
    # compose in class order and the run keeps clean per-class attribution. The image announcement is
    # the same idiom on the same terms, and is last because it is about the message rather than the
    # element: default off, disjoint by class, `''` everywhere it does not apply.
    return (
        base
        + _label_referent_block(finding)
        + _document_title_referent_block(finding)
        + _link_name_referent_block(finding)
        + _image_announcement_block(finding, announce_image, image_attached)
    )


def _resolve_citations(citations: list[Citation], sc_ids: list[str]) -> list[Citation]:
    """Resolve sc_ids against the retrieved set for corpus-grounded metadata, falling back to a bare
    `Citation` for any that was NOT retrieved. On the judgment path an unretrieved id is a citation
    the corpus never supported — exactly the hallucination the validator/oracle is built to catch, so
    we keep it, not drop it. On the assembled path it means retrieval missed an SC axe named; the
    criterion is still true of the finding, so it still ships, just without a url.

    The normative text is dropped on the way out. It is a drafting *input* — what the prompt shows the
    model — whereas a drafted row is a **reference**: id, title, level, url, the fields a report
    renders. Carrying the corpus prose through would copy the same paragraph into every row citing
    that criterion, inflating every persisted checkpoint, review record and frozen run artifact with
    text no consumer reads. Dropped here rather than never set, so the retriever's contract stays
    faithful and exactly one boundary makes the choice.
    """
    by_id = {c.sc_id: c for c in citations}
    return [(by_id.get(sc_id) or Citation(sc_id=sc_id)).model_copy(update={"text": ""}) for sc_id in sc_ids]


def _assemble(finding: Finding, citations: list[Citation], out: _LLMDraft, visually_verified: bool | None) -> DraftRow:
    """Build the full `DraftRow` for a judgment draft: identity + severity from code, the semantic
    verdict from the model, citations resolved from the retrieved set.

    The two evidence fields keep their two owners here. `visual_evidence` is copied off the response
    and is `None` wherever the model answered under the shape that does not carry it — no model wrote
    one, so the row holds none. `visually_verified` is passed in, because it is the caller's record of
    what was sent and not something re-derivable from an answer.
    """
    return DraftRow(
        finding_id=finding.id,
        conformance=out.conformance,
        citations=_resolve_citations(citations, out.cited_sc_ids),
        remediation=out.remediation,
        severity=finding.impact,
        confidence=out.confidence,
        visual_evidence=out.visual_evidence if isinstance(out, _LLMDraftVisualEvidence) else None,
        visually_verified=visually_verified,
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

    Both evidence fields stay empty for the same reason: nothing was judged here, so there is no
    judgment for either the model's claim or the system's fact to be about. It is also what keeps this
    row's signature fixed — one shape for every way a draft can fail, including a claim the system
    contradicted.
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
