"""The quality-review whitelist: which axe `passes[]` rules the normalizer surfaces as
judgment findings, and the task-honest help each one carries.

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
them too. The normalizer therefore mints a judgment `Finding` (`AxeBucket.PASSES`) for each
whitelisted pass.

Why these four rules — and why two are deliberately deferred
------------------------------------------------------------
Each rule below was **empirically confirmed** (against pinned axe 4.12.1) to PASS on a
present-but-poor value, so it yields a real judgment finding. Two further existence-only rules,
`document-title` and `button-name`, are **deferred**, for two compounding reasons:
  1. They were NOT confirmed to pass on poor content — a page title or button with any text
     usually reads as adequate, so a clean "present-but-inadequate" case is hard to plant.
  2. Enabling them would mint findings on the existing frozen regression fixtures (every fixture
     has a `<title>`; `home.html` has a named `<button>`), disturbing versioned anchors for the
     two weakest categories.
Scoping to the confirmed four gives a smaller but *more valid* judge calibration: every gold
item is a clean, DOM-decidable judgment call, and the set the judge calibrates on is exactly
the set the pipeline surfaces in production (same whitelist), so κ never overstates the judge's
reliability on its real workload. `document-title` / `button-name` (and the alt/name variants
`svg-img-alt`, `object-alt`, `role-img-alt`, `input-image-alt`, `select-name`) can be added
later — each behind a fixture version bump — once a fixture confirms it passes on poor content
and the product's judgment scope calls for it.

The reframe (the VALUES)
------------------------
The KEYS are the whitelist. The VALUES REPLACE axe's rule-level help — which for a pass reads
misleadingly, e.g. "Images must have alternate text" — with the actual quality-review task, so
the finding is self-describing to the drafter and the judge. Without this, a passes-sourced
finding reads as already-conformant and the drafter would draft "supports", producing a gold
set of non-issues.
"""

from __future__ import annotations

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
}
