"""The quality-review rule set (`QUALITY_REVIEW_RULES`): which axe `passes[]` rules the normalizer
surfaces as judgment findings, and the task-honest help each one carries. The set is GLOBAL — a rule
listed here mints findings on EVERY page, so adding one is never a local change (see the cost note).

Why this module exists — the empirical finding behind the judgment gold set
--------------------------------------------------------------------------
The oracle only grounds axe `violations`. The obvious place to look for oracle-poor
*judgment* items is axe's `incomplete[]` bucket — but that bucket is the wrong source, and
we verified why against the pinned axe-core 4.12.1: of the 55 rules that can go `incomplete`,
every one hesitates because it needs pixels / render / media / cross-frame resolution
(`color-contrast` on a gradient, `video-caption`, `frame-tested`, …) — exactly the inputs the
LLM judge and the drafter also lack, since they see only HTML. Calibrating a judge on items it
is structurally unable to decide yields a κ that is noise at best; a meaningless κ is worse
than none.

The DOM-decidable judgment items live in axe's `passes[]` bucket instead. A family of
*existence-only* rules passes the moment a name / attribute / title is merely PRESENT and
never checks whether it is MEANINGFUL — `image-alt` passes `alt="DSC_0042.jpg"`, `link-name`
passes "click here", `label` passes a placeholder-only input. Those are precisely the
"axe confirms it exists; an expert judges whether it's any good" calls that make up the
oracle-poor share of a real audit — and they are decidable from the DOM, so the judge can make
them too. The normalizer therefore mints a judgment `Finding` (`AxeBucket.PASSES`) for each pass of
a rule in this set.

Why these six rules — and why one is still deliberately deferred
----------------------------------------------------------------
Each rule below was **empirically confirmed** (against pinned axe 4.12.1) to PASS on a
present-but-poor value, so it yields a real judgment finding. `empty-heading` and `document-title`
were confirmed against the vendored ACT test cases: `empty-heading` PASSES on a present-but-
non-descriptive heading (only `aria-hidden` headings fall out of the accessibility tree and mint
nothing — an honest miss), and `document-title` PASSES on every page with a `<title>`. Both are
existence-only in the same sense as the others: axe confirms the heading/title EXISTS but never
whether it is meaningful.

One further existence-only rule, `button-name`, is still **deferred**: a button with any text
usually reads as adequate, so a clean "present-but-inadequate" case is hard to plant, and it was
not confirmed to pass on poor content. The alt/name variants (`svg-img-alt`, `object-alt`,
`role-img-alt`, `input-image-alt`, `select-name`) remain deferred on the same empirical bar.

Note the cost paid for `empty-heading` / `document-title`: the set is GLOBAL, so both mint new
judgment findings on every frozen fixture that has a heading/title (all of them). That moved
versioned anchors and required a fixture version bump — the mechanism this module already
prescribes for any change to the set.

The reframe (the VALUES)
------------------------
The KEYS are the rule set. The VALUES REPLACE axe's rule-level help — which for a pass reads
misleadingly, e.g. "Images must have alternate text" — with the actual quality-review task, so
the finding is self-describing to the drafter and the judge. Without this, a passes-sourced
finding reads as already-conformant and the drafter would draft "supports", producing a gold
set of non-issues.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import NamedTuple

QUALITY_REVIEW_RULES: dict[str, str] = {
    "image-alt": (
        "An alt attribute is PRESENT — judge whether it MEANINGFULLY describes the image for "
        "WCAG 1.1.1; a filename or generic word ('image', 'photo', 'logo') does NOT."
    ),
    "link-name": (
        "The link has an accessible name — judge whether it describes the link's PURPOSE in "
        "context for WCAG 2.4.4; 'click here', 'read more', or a bare URL does NOT."
    ),
    "label": (
        "The form field has a programmatic label — judge whether it clearly identifies the "
        "field's PURPOSE for WCAG 1.3.1 / 3.3.2; a placeholder-as-label or a vague label does NOT."
    ),
    "frame-title": (
        "The frame has a title — judge whether it DESCRIBES the frame's content for "
        "WCAG 4.1.2 / 2.4.1; a generic 'frame' / 'iframe' does NOT."
    ),
    "empty-heading": (
        "The heading has non-empty text — judge whether it DESCRIBES the section's topic for "
        "WCAG 2.4.6; a generic or off-topic heading (e.g. 'Weather' over opening hours) does NOT."
    ),
    "document-title": (
        "The page has a non-empty <title> — judge whether it DESCRIBES the page's topic or purpose "
        "for WCAG 2.4.2; a generic 'Untitled' / 'Home' / boilerplate title does NOT."
    ),
}


class FindingClassTrust(str, Enum):
    """How far a finding class's judgment is trusted — DERIVED from that class's Cohen's κ against
    W3C ACT expert gold on the latest frozen scored run, never hand-assigned. A specialist can then
    tell a measured-reliable class from a measured-weak or a never-measured one instead of receiving
    them as indistinguishable peers.

    ⚠️ A tier is not a certification, and the tiers are not equally well established. `document-title`
    reaches RELIABLE on κ = 1.00 over **n = 5** cases — a sample too small to certify anything: its
    structural ceiling is p = 0.125, so it cannot reach statistical significance at that n however
    good the drafter is. Read it as "no measured errors on five cases", NOT as standing on the same
    evidence as `empty-heading` (κ 0.675 over n = 13). `docs/finding-class-trust.md` carries the
    caveat in full, per class, with n."""

    RELIABLE = "reliable"  # measured vs ACT gold at or above the threshold below
    WEAK = "weak"  # measured vs ACT gold, below the threshold — expect false alarms
    UNMEASURED = "unmeasured"  # never scored against gold — no trust signal exists for the class


# The tier boundary, stated ONCE so the mapping is auditable and re-runnable rather than negotiated
# per class after the numbers are seen: κ >= 0.60 is RELIABLE, a measured κ below it is WEAK, and a
# class that was never scored against gold is UNMEASURED. 0.60 is Landis & Koch "substantial
# agreement" — the same bar the judge's trust gate uses (`KAPPA_THRESHOLD` in `clearway/eval/kappa.py`),
# restated here rather than imported because the normalizer does not depend on `eval/`.
TRUST_KAPPA_THRESHOLD = 0.60


class ClassKappa(NamedTuple):
    """One class's frozen reading: Cohen's κ against ACT gold, and how many scored cases stand behind
    it. `n` travels with κ because a tier alone hides sample size, and two of these samples are tiny."""

    kappa: float
    n: int


# Per-class κ from the LATEST frozen run scored against W3C ACT expert gold —
# `benchmark/reports/citation_grounding_result.json`, `mechanism[]`. A class ABSENT from this table
# has never been scored against gold. The values are pinned against that artifact by test, so they
# cannot drift from the run they quote, and the artifact they point at has to be the newest scored
# run: a tier derived from a superseded one describes a drafter that no longer ships.
#
# What moved since the pre-injection reading in `benchmark/reports/drafter_kappa_baseline.json`, once
# the resolved referent was injected into the drafter's input and the criterion's normative text was
# carried to the prompt: document-title 0.00 -> 1.00 (its constant classifier broke); label
# 0.13 -> 0.82; link-name 0.21 -> 0.21 (UNMOVED — its referent is the link destination, which is not
# in the DOM the drafter sees, so no in-page grounding reaches it); empty-heading unchanged at 0.675
# (the untouched control).
#
# link-name's reading also shows why the pinned artifact matters: under referent injection alone it
# was 0.05, a net regression, and carrying the normative text recovered it to the pre-injection 0.21.
# Its TIER is WEAK on both readings, so no consumer's behaviour changes — but quoting the superseded
# number would have understated the shipped drafter by a factor of four.
FROZEN_CLASS_KAPPA: dict[str, ClassKappa] = {
    "document-title": ClassKappa(kappa=1.0, n=5),
    "empty-heading": ClassKappa(kappa=0.675, n=13),
    "label": ClassKappa(kappa=0.8197, n=11),
    "link-name": ClassKappa(kappa=0.2105, n=15),
}


def trust_tier(kappa: float | None) -> FindingClassTrust:
    """Apply the threshold rule to one class's κ. `None` means the class was never scored against
    gold — which is NOT the same as scoring badly, so it gets its own tier rather than defaulting to
    WEAK."""
    if kappa is None:
        return FindingClassTrust.UNMEASURED
    return FindingClassTrust.RELIABLE if kappa >= TRUST_KAPPA_THRESHOLD else FindingClassTrust.WEAK


def derive_class_trust(kappa_by_class: Mapping[str, ClassKappa], rules: Iterable[str]) -> dict[str, FindingClassTrust]:
    """The tier table for `rules`, derived by applying `trust_tier` to a frozen run's per-class κ.
    Re-run it against a later frozen run to refresh the tiers without re-litigating the mapping —
    that is the point of deriving them instead of writing them down."""
    return {rule: trust_tier(m.kappa if (m := kappa_by_class.get(rule)) is not None else None) for rule in rules}


# Every class in QUALITY_REVIEW_RULES carries a trust tier (enforced by test): a new rule is
# UNMEASURED until it is scored against gold, so no class ships as an unlabelled peer of a measured
# one. This is the single source of truth for tiers — the prose copies in
# `docs/finding-class-trust.md` and the dashboard panel are mirrors, guarded against it by test.
FINDING_CLASS_TRUST: dict[str, FindingClassTrust] = derive_class_trust(FROZEN_CLASS_KAPPA, QUALITY_REVIEW_RULES)
