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

from enum import Enum

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
    """Per-class trust status from the held-out acceptance benchmark, so a specialist can tell a
    measured-reliable class from a measured-weak or a never-measured one instead of receiving them as
    indistinguishable peers. Qualitative by design — the exact per-rule numbers live in
    `docs/acceptance-analysis.md` / `docs/finding-class-trust.md`, not duplicated here where they
    could drift."""

    RELIABLE = "reliable"  # measured vs ACT gold, decent (empty-heading: recall 4/5, FP 1/8)
    WEAK = "weak"  # measured, high cry-wolf (document-title ~100% FP; label / link-name ~50%)
    UNMEASURED = "unmeasured"  # never validated against gold — no trust signal exists for the class


# Every class in QUALITY_REVIEW_RULES MUST carry a trust tier (enforced by test): a new rule has to
# state how far its judgment is trusted, so no class ships as an unlabelled peer of a measured one.
FINDING_CLASS_TRUST: dict[str, FindingClassTrust] = {
    "empty-heading": FindingClassTrust.RELIABLE,
    "document-title": FindingClassTrust.WEAK,
    "label": FindingClassTrust.WEAK,
    "link-name": FindingClassTrust.WEAK,
    "image-alt": FindingClassTrust.UNMEASURED,
    "frame-title": FindingClassTrust.UNMEASURED,
}
