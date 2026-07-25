"""Fix-direction: does a drafted remediation point at the WCAG technique ACT says fixes the case?

The product's actual promise is the remediation sentence — "here is how to fix it" — and until now no
instrument in this repo scored it at all. This module scores its DIRECTION by reverse-inference: take the
drafted remediation text, infer the WCAG technique the proposed fix would apply, then check that inferred
technique against ACT's canonical technique gold (the `wcag-technique:` namespace already carried by the
vendored export).

**Direction is not usefulness, and this is a FLOOR.** A pass says only that the fix points at the right
technique. Whether the fix is actually useful to an implementer still needs a human accessibility
specialist and remains unmeasured — nothing here licenses "remediation is validated". Read it as a
regression guard on a floor, never as evidence that fixes are good.

**Coverage is 2 of the 4 scored classes, and that is stated everywhere this number travels.** In the
vendored export only `label` (G131) and `document-title` (G88 / H25) carry technique requirements;
`link-name` and `empty-heading` carry none, so they are unscoreable here — not passing, not failing,
absent. The covered/uncovered split is DERIVED from the export at read time (`technique_gold_by_class`),
never restated, so a re-vendoring moves it automatically.

**Three model roles exist in this codebase and must never be conflated.** The DRAFTER is the local model
that writes the remediation. The JUDGE is the cloud model that grades no-oracle judgment items — it takes
no part in any number here. The TECHNIQUE CLASSIFIER is a third, separate cloud model whose only job is
the reverse-inference above.

**The classifier is NOT an LLM-as-judge.** Its output is a *classification*, and that classification is
then scored deterministically against ACT gold — checked, never trusted. Gold, not the classifier, is the
oracle, so the classifier inherits none of the Goodhart problem that made this project drop its cloud
judge as a trust instrument: if the classifier is bad, κ falls, and the number stays honest. That is also
why a cloud model is acceptable here at all. Its input is the remediation sentence ALONE — never the
element, the rule or the class — so it cannot read the answer off the case it is scoring.

**Scored chance-corrected (κ), never as a raw match rate.** Technique gold is RULE-LEVEL: every `label`
case shares gold G131. So a constant classifier that always answers "G131" scores ~0.69 raw match on this
set while having learned nothing — the exact failure κ was built to catch, and one this project has
already been burned by once. The κ streams are therefore the gold technique key per case against the
key the inferred technique lands in, so the question κ asks is discriminative: can the chain tell a
label fix from a title fix? A constant answer scores κ 0.0 at high raw agreement. Raw agreement rides
along as context (it is the constant-classifier tell), never as the metric — and it carries information
κ does not: a chain that answers a consistent but WRONG id for one class has still separated the classes,
so κ credits it while raw agreement shows that not one case in that class was actually right. Both
numbers are needed to read the result, and neither is sufficient alone.

**It measures the drafter→classifier CHAIN, not the drafter alone.** A low κ may be a vague remediation
or a classifier that cannot place a code; the metric does not separate them. And it is STRICT: a real,
sensible technique that is simply not the one ACT lists counts as a disagreement.

The scoring half is pure — the κ, its seeded bootstrap interval and the coverage split replay from a set
of classifications with no model and no network. Only `classify` touches a model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clearway.eval.act_gold import _EXPORT, RULE_TO_AXE
from clearway.eval.drafter_kappa import _BOOTSTRAP_SEED, _RESAMPLES, _bootstrap_ci
from clearway.eval.kappa import cohen_kappa, raw_agreement
from clearway.llm.client import LLMClient
from clearway.schemas.models import TechniqueMatch

_TECHNIQUE_PREFIX = "wcag-technique:"

# The classifier's escape hatch: the remediation implies no technique in the vocabulary. Lower-case so it
# can never collide with a technique id (which are upper-case: G131, H25, F30…).
NO_TECHNIQUE = "none"


def technique_vocabulary() -> tuple[str, ...]:
    """Every distinct WCAG technique id in the vendored ACT export, sorted — the classifier's whole
    answer space.

    Deliberately the FULL namespace, not the handful the scored classes need: narrowing the choice to the
    covered classes' codes would hand the classifier the answer and turn the measurement into a coin flip
    it cannot lose. Derived from the export so a re-vendoring updates it without a code change.
    """
    export = json.loads(_EXPORT.read_text())
    codes = {
        key.removeprefix(_TECHNIQUE_PREFIX)
        for case in export["testcases"]
        for key in (case.get("ruleAccessibilityRequirements") or {})
        if key.startswith(_TECHNIQUE_PREFIX)
    }
    return tuple(sorted(codes))


def technique_gold_by_class() -> dict[str, tuple[str, ...]]:
    """Fix-unit class (`axe_rule`) → the technique ids ACT requires for it, for the SCOPED classes only.

    A class whose ACT rule declares no technique requirement is absent from the map entirely — that is
    the coverage limit, read off the gold rather than asserted. Every entry's technique set is the
    rule-level gold shared by all of that class's cases, which is precisely why the score is
    chance-corrected.
    """
    export = json.loads(_EXPORT.read_text())
    by_class: dict[str, set[str]] = {}
    for case in export["testcases"]:
        axe_rule = RULE_TO_AXE.get(case["ruleName"])
        if axe_rule is None:
            continue
        codes = {
            key.removeprefix(_TECHNIQUE_PREFIX)
            for key in (case.get("ruleAccessibilityRequirements") or {})
            if key.startswith(_TECHNIQUE_PREFIX)
        }
        if codes:
            by_class.setdefault(axe_rule, set()).update(codes)
    return {axe_rule: tuple(sorted(codes)) for axe_rule, codes in sorted(by_class.items())}


def covered_classes() -> tuple[str, ...]:
    """The scored classes that carry technique gold — the ones this metric can speak about."""
    return tuple(technique_gold_by_class())


def uncovered_classes() -> tuple[str, ...]:
    """The scored classes that carry NO technique gold, named rather than silently missing: their
    remediation direction is not measured by anything, here or elsewhere."""
    return tuple(sorted(set(RULE_TO_AXE.values()) - set(technique_gold_by_class())))


def gold_key(techniques: tuple[str, ...]) -> str:
    """A class's technique gold as one categorical label for the κ stream (`("G88","H25")` → `G88+H25`).
    Set-valued gold is one category, not two: ACT lists alternative techniques for the same fix, so any
    member is the same answer."""
    return "+".join(sorted(techniques))


@dataclass(frozen=True)
class RemediationDraft:
    """One drafted remediation sentence to classify, tied to the ACT case and fix-unit class it was
    written for. `remediation` is the ONLY field the classifier ever sees."""

    act_testcase_id: str
    axe_rule: str
    remediation: str


@dataclass(frozen=True)
class TechniqueClassification:
    """One classified remediation: the draft plus the technique the classifier inferred from it
    (`NO_TECHNIQUE` when it declined). Scoring is a pure function of a list of these, so a frozen set of
    classifications replays to the same κ forever."""

    act_testcase_id: str
    axe_rule: str
    remediation: str
    inferred_technique: str


class _TechniqueAnswer(BaseModel):
    """The classifier's structured output — one technique id, or `none`."""

    model_config = ConfigDict(extra="forbid")

    technique: str = Field(..., description="one WCAG technique id from the allowed list, or 'none'")


def classification_schema(vocabulary: tuple[str, ...]) -> type[BaseModel]:
    """`_TechniqueAnswer` with the allowed answers pinned into its JSON schema as an enum, so the
    provider's structured-output mode constrains the answer instead of the parser having to reject it."""

    class TechniqueAnswer(_TechniqueAnswer):
        technique: str = Field(
            ...,
            description="one WCAG technique id from the allowed list, or 'none'",
            json_schema_extra={"enum": [*vocabulary, NO_TECHNIQUE]},
        )

    return TechniqueAnswer


def classifier_system_prompt(vocabulary: tuple[str, ...]) -> str:
    """The classifier's fixed instruction. The allowed ids live here (fixed across every call, so they
    cache) and the remediation sentence alone travels in the user turn. It is told nothing about the
    element, the rule, the class or the expected outcome — everything that would leak the answer."""
    return (
        "You classify accessibility REMEDIATION text by the W3C WCAG technique it implies.\n"
        "You are given one sentence proposing how to fix an accessibility problem on a web page. Decide "
        "which single WCAG technique the proposed fix would apply, and answer with that technique's id.\n"
        "Rules:\n"
        "- Answer with exactly one id from the allowed list below, or 'none' if the sentence implies no "
        "technique in the list.\n"
        "- Judge only the change the sentence actually proposes. Do not guess what problem a page usually "
        "has, and do not answer from the wording of the sentence alone if it proposes a different change.\n"
        "- Output only the JSON object.\n"
        f"Allowed ids: {', '.join(vocabulary)}, {NO_TECHNIQUE}"
    )


def classifier_user_prompt(remediation: str) -> str:
    return f"Remediation: {remediation.strip()}"


def prompt_sha256(vocabulary: tuple[str, ...]) -> str:
    """Content hash of the fixed classifier instruction — the reproducibility pin recorded beside the
    model id and reasoning effort, since a cloud snapshot is not bit-reproducible on its own."""
    return hashlib.sha256(classifier_system_prompt(vocabulary).encode()).hexdigest()


def _normalize(answer: str, vocabulary: tuple[str, ...]) -> str:
    """Answer → a vocabulary member or `NO_TECHNIQUE`. An id outside the vocabulary is RAISED on, never
    quietly folded into 'none': the structured-output enum already forbids it, so seeing one means the
    constraint is not holding and the run must stop rather than record a silently degraded stream."""
    candidate = answer.strip()
    if candidate.lower() == NO_TECHNIQUE:
        return NO_TECHNIQUE
    candidate = candidate.upper()
    if candidate not in vocabulary:
        raise ValueError(f"classifier answered {answer!r}, which is not a WCAG technique id in the ACT export")
    return candidate


def classify(client: LLMClient, draft: RemediationDraft, *, vocabulary: tuple[str, ...]) -> TechniqueClassification:
    """Classify ONE remediation sentence — the only function here that touches a model.

    The classifier sees the sentence and nothing else. Its answer is not believed: it is a stream that
    `score_technique_match` then compares against ACT gold.
    """
    completion = client.complete_json(
        classifier_system_prompt(vocabulary),
        classifier_user_prompt(draft.remediation),
        classification_schema(vocabulary),
    )
    answer = _TechniqueAnswer.model_validate_json(completion.content)
    return TechniqueClassification(
        act_testcase_id=draft.act_testcase_id,
        axe_rule=draft.axe_rule,
        remediation=draft.remediation,
        inferred_technique=_normalize(answer.technique, vocabulary),
    )


def classify_all(
    client: LLMClient, drafts: list[RemediationDraft], *, vocabulary: tuple[str, ...] | None = None
) -> list[TechniqueClassification]:
    """Classify a list of drafts in order — one call each, one-shot, at scoring time only."""
    vocab = vocabulary if vocabulary is not None else technique_vocabulary()
    return [classify(client, draft, vocabulary=vocab) for draft in drafts]


def scoreable(drafts: list[RemediationDraft]) -> list[RemediationDraft]:
    """The drafts this metric can speak about: those in a class carrying technique gold. Dropping the
    rest is the COVERAGE limit, not a filter on quality — an uncovered class has no gold to disagree
    with, so including it would score noise."""
    covered = technique_gold_by_class()
    return [d for d in drafts if d.axe_rule in covered]


def _streams(classifications: list[TechniqueClassification]) -> tuple[list[str], list[str]]:
    """The paired (gold, inferred) categorical streams.

    Gold is the case's class-level technique key. The inferred label is the key of whichever covered
    class the inferred technique belongs to — so "did the fix point at THIS class's technique" — and any
    other answer forms its own category, which is a disagreement with every gold key. The covered classes'
    technique sets are disjoint (asserted), so the mapping is unambiguous.
    """
    gold_by_class = technique_gold_by_class()
    keys = {gold_key(codes): set(codes) for codes in gold_by_class.values()}
    if sum(len(codes) for codes in keys.values()) != len(set().union(*keys.values())):
        raise ValueError(f"covered classes share a technique id — the gold keys are not disjoint: {keys}")
    gold: list[str] = []
    inferred: list[str] = []
    for c in classifications:
        if c.axe_rule not in gold_by_class:
            raise ValueError(f"case {c.act_testcase_id} is in class {c.axe_rule!r}, which carries no technique gold")
        gold.append(gold_key(gold_by_class[c.axe_rule]))
        inferred.append(
            next((k for k, codes in sorted(keys.items()) if c.inferred_technique in codes), c.inferred_technique)
        )
    return gold, inferred


@dataclass(frozen=True)
class TechniqueMatchScoring:
    """The `TechniqueMatch` schema payload plus the method prose that travels with it wherever the
    number is reported — coverage, the floor caveat, and why no raw match rate is quoted as the metric."""

    metric: TechniqueMatch
    notes: str


def coverage_note() -> str:
    """The coverage sentence, derived from the gold so it cannot drift from what is actually scored."""
    covered = covered_classes()
    uncovered = uncovered_classes()
    gold = technique_gold_by_class()
    detail = "; ".join(f"{axe_rule} ({'/'.join(gold[axe_rule])})" for axe_rule in covered)
    return (
        f"Coverage is {len(covered)} of {len(covered) + len(uncovered)} scored classes: {detail}. "
        f"{', '.join(uncovered)} carry no technique requirement in the ACT export and are NOT scored here "
        "— absent, not passing."
    )


def _notes(metric: TechniqueMatch) -> str:
    return (
        f"remediation_technique_match is CHANCE-CORRECTED (Cohen's κ {metric.kappa:+.3f}, n={metric.n}, "
        f"bootstrap CI [{metric.ci_low:+.3f}, {metric.ci_high:+.3f}], seed={metric.seed}). No raw match rate "
        f"is reported as the metric: the technique gold is rule-level, so a constant classifier answering one "
        f"id for everything scores high on raw match while carrying no signal — raw agreement "
        f"{metric.raw_agreement:.3f} is context and the constant-classifier tell, never the number. "
        f"{coverage_note()} It scores DIRECTION — that a drafted fix points at the right technique — as a "
        "floor and a regression guard; whether a fix is USEFUL still needs a human specialist and remains "
        "unmeasured. Strict: a sensible technique ACT does not list counts as a disagreement. It measures "
        f"the drafter-plus-classifier chain, not the drafter alone (classifier: {metric.classifier_model}, "
        "a different model from both the drafter and the judge; its output is checked against ACT gold, "
        "never trusted)."
    )


def score_technique_match(
    classifications: list[TechniqueClassification],
    *,
    classifier_model: str,
    seed: int = _BOOTSTRAP_SEED,
    resamples: int = _RESAMPLES,
) -> TechniqueMatchScoring:
    """Classifications → the chance-corrected fix-direction metric. Pure: no model, no network, no clock.

    κ between the gold technique key and the key the inferred technique lands in, with the same seeded
    case-level percentile bootstrap the per-class drafter κ uses (κ is not a proportion, so it never
    travels through a Wilson interval).

    `constant_classifier` is set from the STREAM — one and the same answer on every case — not from a
    zero-width interval, because on this metric the two are not the same fact: perfect agreement also
    collapses the interval to a point, and calling that "no signal" would be exactly backwards.
    """
    if not classifications:
        raise ValueError("no classified remediations to score — nothing to compare against technique gold")
    gold, inferred = _streams(classifications)
    ci_low, ci_high, degenerate = _bootstrap_ci(inferred, gold, seed=seed, resamples=resamples)
    metric = TechniqueMatch(
        kappa=cohen_kappa(inferred, gold),
        n=len(classifications),
        ci_low=ci_low,
        ci_high=ci_high,
        degenerate_share=degenerate,
        resamples=resamples,
        seed=seed,
        constant_classifier=len(set(inferred)) < 2,
        raw_agreement=raw_agreement(inferred, gold),
        covered_classes=list(covered_classes()),
        uncovered_classes=list(uncovered_classes()),
        classifier_model=classifier_model,
    )
    return TechniqueMatchScoring(metric=metric, notes=_notes(metric))


def classification_rows(classifications: list[TechniqueClassification]) -> list[dict[str, Any]]:
    """The per-case audit trail an artifact carries beside the metric: the exact sentence classified, the
    inferred technique and the gold it was scored against, so the κ can be recomputed from the artifact
    without re-calling the classifier."""
    gold_by_class = technique_gold_by_class()
    gold, inferred = _streams(classifications)
    return [
        {
            "act_testcase_id": c.act_testcase_id,
            "axe_rule": c.axe_rule,
            "remediation": c.remediation,
            "inferred_technique": c.inferred_technique,
            "gold_techniques": list(gold_by_class[c.axe_rule]),
            "gold_key": g,
            "inferred_key": i,
            "agrees": g == i,
        }
        for c, g, i in zip(classifications, gold, inferred)
    ]
