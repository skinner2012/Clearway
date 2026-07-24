"""Referent extraction — the deterministic, bounded context a node-level judgment needs.

axe reports the offending element and nothing around it. That is enough to say *the check
failed*; it is not enough to say *whether this title describes the page*, *whether this label
names the field*, or *what this link is for*. Those judgments need the thing being judged
against — the **referent** — and it lives outside the element snippet.

This module captures that material **inside the live page session, immediately after
`axe.run()` returns**, because after the scan the DOM is gone and re-fetching the page would
break the freeze the whole benchmark rests on. It is plain deterministic code: same DOM in,
same strings out, no model anywhere.

Design rules every extractor here obeys, and the reason for each:

* **A named source.** Each excerpt records the DOM source it was read from
  (`ReferentSource`), so a fallback tier can never be mistaken for the primary one.
* **A pinned character budget.** Constants below, each justified in its own comment. The
  fixtures this project scores against have rendered bodies of 2-220 characters, so an
  unbounded extractor scores perfectly here and is useless on a real page. The budgets, not
  the fixtures, are what bound the output — see the vendored real-page review fixture.
* **A deterministic truncation rule.** Prefix truncation everywhere except the surrounding
  context, which is windowed *around the node* — on a large page a prefix would return the
  masthead instead of the node's neighbourhood.
* **Absent is not empty.** A source that does not exist yields `None`; a source that exists
  and holds no text yields an excerpt with `text=""`. Collapsing the two would hide the
  difference between "this page has no heading" and "the heading is blank".

Budgets are counted in **UTF-16 code units** (JavaScript string length) — the DOM's own unit.
A cut that would split a surrogate pair drops the orphan half, so the output is always a
valid string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from clearway.schemas.models import NodeReferent

# --------------------------------------------------------------------------------------
# Pinned budgets. Changing one changes the drafter's input, so each carries its reason.
# --------------------------------------------------------------------------------------

# An accessible name is an identifying *label*, not prose: the longest legitimate name across
# the whole acceptance set is 23 characters ("Go to the main content."). The cap is not for
# those — it is for the pathological case. `accessibleText` concatenates a subtree, so a
# container carrying role="link" can return an entire section. 300 is ~4x the longest
# full-sentence aria-label anyone writes deliberately, so truncation never fires on a
# well-formed name and always fires before a subtree dump reaches a prompt.
ACCESSIBLE_NAME_CHARS = 300

# Browser tabs and search results truncate titles around 60-70 characters, so real titles are
# authored to that length (the vendored real page's is 71). 300 is ~4x that: truncation only
# fires on titles nobody wrote on purpose.
DOCUMENT_TITLE_CHARS = 300

# A heading is the same kind of object as an accessible name — a short identifying phrase —
# so it gets the same number deliberately. One rule to remember, and no implicit claim that
# headings run longer or shorter than names.
SECTION_HEADING_CHARS = 300

# The topic signal answers one question: what is this page about. A heading, a meta
# description or a lead paragraph settles it. Meta descriptions are themselves authored to
# ~155 characters (the real page's is 120); 500 is ~3x that, i.e. ~80 English words, a lead
# paragraph. It is also 5% of the real page's 10,192-character rendered body, which is what
# stops the last-resort body tier from degenerating into "dump the page".
PAGE_TOPIC_CHARS = 500

# The context must hold the smallest self-contained neighbourhood that can decide a link's
# purpose: a table row with its header, a list item, or the sentence containing the link.
# Same order as the topic budget, and the same 5% of a real page's body.
SURROUNDING_CONTEXT_CHARS = 500

# From a link: one step reaches the inline container (<td>, <li>, <p>), two the row / list /
# paragraph group, three the section. Past three the window stops being "surrounding" and
# becomes "the page" — which is what the topic tier is for. Capped rather than unbounded
# because on a real page the fourth ancestor is routinely <main> or <body>.
CONTEXT_ANCESTOR_MAX_DEPTH = 3

BUDGETS: dict[str, int] = {
    "accessible_name": ACCESSIBLE_NAME_CHARS,
    "document_title": DOCUMENT_TITLE_CHARS,
    "page_topic": PAGE_TOPIC_CHARS,
    "section_heading": SECTION_HEADING_CHARS,
    "surrounding_context": SURROUNDING_CONTEXT_CHARS,
    "context_ancestor_max_depth": CONTEXT_ANCESTOR_MAX_DEPTH,
}

# The real-page review artifacts. Extraction reviewed only against this repo's fixtures would
# be reviewed against 2-220 character bodies; these two files are what make the review
# auditable rather than attested. See their NOTICE for URL, retrieval date and licence.
_REAL_PAGE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real-page"
REAL_PAGE_SNAPSHOT = _REAL_PAGE_DIR / "w3c-wai-accessibility-intro.html"
REAL_PAGE_REFERENTS = _REAL_PAGE_DIR / "w3c-wai-accessibility-intro.referents.json"


# --------------------------------------------------------------------------------------
# The in-page extractor.
# --------------------------------------------------------------------------------------
#
# Why `axe.setup()` / `axe.teardown()` at all: the accessible name is computed by axe itself
# (`axe.commons.text.accessibleText`) rather than reimplemented here. Reimplementing ARIA name
# resolution would mean two subtly different answers to the same question, and the one that
# matters is axe's — it is the engine whose verdict we are contextualising.
#
# Entry point, pinned with its reason: `accessibleText(el)` takes a **real element**, which is
# what we have (we re-query axe's own selectors against the live DOM). The vnode-shaped
# `accessibleTextVirtual(vnode)` would require hand-building a virtual node, and a hand-built
# vnode is a second, divergent model of the tree — the exact thing this choice avoids.
# `accessibleText` throws without `axe.setup()`, hence the setup; it also throws if handed a
# vnode, which is why the element form is the only one used here.
#
# The setup guard is measured behaviour, not defensive habit: `axe.setup()` after `axe.run()`
# has *completed* does not throw, but `axe.setup()` **re-entry** while a tree is already set up
# does. A prior partial state must therefore not be able to wedge the scan, so teardown is
# attempted before setup and always attempted after.
_EXTRACT_JS = """
(payload) => {
  const { targets, budgets } = payload;

  // One pinned normalization, applied to every source before its budget is measured, so the
  // budget counts characters that can actually appear in a prompt rather than layout
  // whitespace. Collapse every run of whitespace (incl. NBSP) to one space, then trim.
  const norm = (value) => (value == null ? "" : String(value)).replace(/\\s+/g, " ").trim();

  // A cut at an arbitrary index can split a surrogate pair. Drop the orphan half at either
  // end so the result is always a valid string. Deterministic: same cut, same drop.
  const dropOrphanSurrogates = (text) => {
    let out = text;
    if (out.length && out.charCodeAt(0) >= 0xdc00 && out.charCodeAt(0) <= 0xdfff) out = out.slice(1);
    const last = out.length ? out.charCodeAt(out.length - 1) : 0;
    if (last >= 0xd800 && last <= 0xdbff) out = out.slice(0, -1);
    return out;
  };

  const excerpt = (raw, source, budget, extra) => {
    if (raw == null) return null;                      // source absent -> not available
    const text = norm(raw);
    const truncated = text.length > budget;
    return {
      text: truncated ? dropOrphanSurrogates(text.slice(0, budget)) : text,
      source: source,
      truncated: truncated,
      in_accessibility_tree: extra && "inTree" in extra ? extra.inTree : null,
      ancestor_depth: extra && "depth" in extra ? extra.depth : null,
    };
  };

  // innerText forces layout, so cache per element: ancestors are shared across nodes and a
  // real page has far more nodes than distinct ancestors.
  const textCache = new Map();
  const renderedText = (el) => {
    if (!textCache.has(el)) textCache.set(el, norm(el.innerText));
    return textCache.get(el);
  };

  const screenReaderVisible = (el) => {
    try { return axe.commons.dom.isVisibleToScreenReaders(el); } catch (e) { return null; }
  };

  // ---- page-level material (resolved once; carried on every node) ----------------------

  // Element presence, not the property: document.title is "" both for a page with no <title>
  // and for a page with an empty one, and those are different facts.
  const titleEl = document.querySelector("title");
  const documentTitle = titleEl === null
    ? null
    : excerpt(document.title, "document_title", budgets.document_title);

  // Fixed tier order. Rendered text (innerText), never textContent: a <title> placed inside
  // <body> is display:none per the UA stylesheet, so innerText cannot leak it into the topic
  // signal — and one vendored ACT fixture does exactly that, which would otherwise hand a
  // document-title case its own answer.
  const topicTiers = [
    ["h1", () => { const el = document.querySelector("h1"); return el ? renderedText(el) : null; }],
    ["main", () => {
      const el = document.querySelector("main, [role='main']");   // native or ARIA landmark
      return el ? renderedText(el) : null;
    }],
    ["meta_description", () => {
      const el = document.querySelector("meta[name='description']");
      return el ? norm(el.getAttribute("content")) : null;
    }],
    ["rendered_body_text", () => (document.body ? renderedText(document.body) : null)],
  ];
  let pageTopic = null;
  let emptyTierTopic = null;    // a tier that existed but held nothing — still a fact worth keeping
  for (const [source, read] of topicTiers) {
    const value = read();
    if (value === null) continue;                                    // that source is not on this page
    if (value !== "") { pageTopic = excerpt(value, source, budgets.page_topic); break; }
    if (emptyTierTopic === null) emptyTierTopic = excerpt(value, source, budgets.page_topic);
  }
  if (pageTopic === null) pageTopic = emptyTierTopic;

  const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role='heading']"));

  // ---- per-node material ---------------------------------------------------------------

  // Nearest heading preceding the node in document order. `headings` is already in document
  // order, so the last one that still precedes the node is the nearest; once one does not,
  // none after it will either. An ancestor heading counts as preceding (CONTAINS|PRECEDING),
  // which is right — a node inside a section is described by that section's heading. The node
  // itself is skipped, so a heading-targeted finding gets the *previous* heading, not itself.
  const nearestHeading = (el) => {
    let found = null;
    for (const heading of headings) {
      if (heading === el) continue;
      if (el.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_PRECEDING) found = heading;
      else break;
    }
    return found;
  };

  // Climb at most CONTEXT_ANCESTOR_MAX_DEPTH levels and take the OUTERMOST ancestor whose
  // rendered text still fits the budget — the most context available without cutting. Text
  // only grows going up, so the first ancestor that overflows ends the climb. If even the
  // immediate parent overflows we keep it and window the text instead, which is the real-page
  // case: parent may be <body> with 10,000 characters.
  const surroundingContext = (el) => {
    const budget = budgets.surrounding_context;
    const chain = [];
    let current = el.parentElement;
    let depth = 1;
    while (current !== null && depth <= budgets.context_ancestor_max_depth) {
      chain.push({ el: current, depth: depth });
      current = current.parentElement;
      depth += 1;
    }
    if (chain.length === 0) return null;              // the node is the document element
    let chosen = null;
    for (const candidate of chain) {
      if (renderedText(candidate.el).length <= budget) chosen = candidate;
      else break;
    }
    if (chosen === null) chosen = chain[0];
    const text = renderedText(chosen.el);
    if (text.length <= budget) {
      return { text: text, source: "ancestor_text", truncated: false,
               in_accessibility_tree: null, ancestor_depth: chosen.depth };
    }
    // Window centred on the node's own text. Prefix truncation here would return the top of
    // the page instead of the neighbourhood that decides the judgment.
    const own = renderedText(el);
    const at = own === "" ? -1 : text.indexOf(own);
    const centre = (at < 0 ? 0 : at) + Math.floor(own.length / 2);
    const start = Math.max(0, Math.min(centre - Math.floor(budget / 2), text.length - budget));
    return {
      text: dropOrphanSurrogates(text.slice(start, start + budget)),
      source: "ancestor_text",
      truncated: true,
      in_accessibility_tree: null,
      ancestor_depth: chosen.depth,
    };
  };

  try { axe.teardown(); } catch (e) { /* no tree was set up; that is the normal case */ }
  axe.setup(document.documentElement);
  try {
    return targets.map((target) => {
      // Only same-document, single-selector targets can be re-resolved from here. A frame or
      // shadow path is reported as unavailable rather than guessed at.
      if (!Array.isArray(target) || target.length !== 1 || typeof target[0] !== "string") return null;
      let el = null;
      try { el = document.querySelector(target[0]); } catch (e) { el = null; }
      if (el === null) return null;
      let accessibleName = null;
      try {
        accessibleName = excerpt(axe.commons.text.accessibleText(el), "accessible_name",
                                 budgets.accessible_name);
      } catch (e) { accessibleName = null; }
      const heading = nearestHeading(el);
      return {
        accessible_name: accessibleName,
        document_title: documentTitle,
        page_topic: pageTopic,
        section_heading: heading === null ? null : excerpt(
          renderedText(heading), "nearest_section_heading", budgets.section_heading,
          { inTree: screenReaderVisible(heading) },
        ),
        surrounding_context: surroundingContext(el),
      };
    });
  } finally {
    try { axe.teardown(); } catch (e) { /* never let cleanup mask the result */ }
  }
}
"""


def extract_referents(page: Page, targets: list[list[str]]) -> dict[tuple[str, ...], NodeReferent]:
    """Extract referent material for `targets`, keyed by the node's flattened axe target.

    Must be called on the still-open page, **after** `axe.run()` has returned: it is a second
    `page.evaluate` that re-queries axe's own selectors against the live DOM. One round trip
    for the whole page, and duplicate targets (the same element reported by several rules) are
    extracted once — a target names a *place*, and a place has one referent.

    A target that cannot be re-resolved is simply absent from the result, which is how the
    caller learns "no material for this node" rather than being handed an empty one.
    """
    keys = list(dict.fromkeys(tuple(target) for target in targets))
    if not keys:
        return {}
    payload = {"targets": [list(key) for key in keys], "budgets": BUDGETS}
    extracted: list[Any] = page.evaluate(_EXTRACT_JS, payload)
    return {key: NodeReferent.model_validate(raw) for key, raw in zip(keys, extracted, strict=True) if raw is not None}
