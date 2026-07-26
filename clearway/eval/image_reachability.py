"""Which vendored ACT image cases the pipeline can actually reach — measured, and frozen.

The image rules are not a scope decision waiting to be made; they are a *reachability* question with
a measurable answer, and this module answers it with the real scanner and the real normalizer over
every published case of the three image rules. No model runs here, and nothing in this module reads
a drafter artifact.

What it records per case, and why each field is load-bearing
------------------------------------------------------------
* **the minting rule and bucket** — an image case only becomes a judgment item if axe's `image-alt`
  lands it in `passes[]`; a missing `alt` is a *confirmed violation* instead, which is a different
  kind of row and must not be counted as reachable judgment.
* **the exact `finding.html`** — this is what the drafter is shown, so it is the thing twins are
  detected on and the thing an ablation has to be checked against.
* **whether the deciding fact is in the snippet** — the classification is stated in
  `accessible_name_form`, not asserted case by case, so a reader can disagree with the rule rather
  than with seven separate judgments.
* **the rendered size of every `<img>`** — `natural_width == 0` is what a broken path, a 404 and an
  undecodable `Content-Type` all look like, and the image rules' gold presumes the image rendered.
  A case that mints a finding but renders nothing is invalid, not merely unlucky.

Why unreachable cases are recorded rather than dropped
------------------------------------------------------
The interesting number is not the pool, it is the pool over the candidates: most usable cases in
this scope cannot mint anything because axe's `image-alt` selector is `img` alone — `<svg>`,
`<canvas>` and `<input type="image">` cases are unreachable no matter how good the drafter is. Every
one of them stays in the artifact with the reason it is out, so the share the pool covers is read off
the artifact instead of being taken on trust.

The two exclusion rules, and the asymmetry between them
--------------------------------------------------------
1. **Prompt-level twins.** Two cases whose minted prompts are identical but whose ACT outcomes are
   opposite give the drafter one input and two answers, so exactly one is permanently wrong and no
   change to what the drafter *receives* can reach it. **Both halves are excluded, never one** —
   keeping the half a text-only drafter happens to score correctly would flatter the pool. This is a
   strictly stronger check than a byte-level fixture comparison (`act_gold.contradictory_gold_twins`,
   which hashes files): these pairs differ in markup the snippet does not carry, so they are twins at
   prompt level and distinct at file level.
2. **Retracted rules** (`RETRACTED_RULES`) are excluded by an argument recorded here in full, made
   before any verdict exists and checkable with no model calls.

Regenerate with `uv run python -m clearway.eval.image_reachability` (re-scans every vendored case).
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import _EXPORT, GOLD_VERSION
from clearway.normalizer import normalize
from clearway.scanner.scan import AXE_VERSION, image_render_report, scan
from clearway.schemas.models import AxeBucket

ACT_IMAGE = Path(__file__).resolve().parents[1] / "fixtures" / "act-image"
HTML = ACT_IMAGE / "html"
ASSETS = ACT_IMAGE / "assets"
ARTIFACT = ACT_IMAGE / "image_reachability.json"

SET_ID = "act-image-leaky@1"  # the vendored cases as ACT publishes them; a derived set gets its own id

# The three ACT rules whose judgment is about an image. Their names are read from the frozen export
# rather than restated here, so a rule that is renamed upstream cannot silently mismatch.
IMAGE_RULE_IDS: tuple[str, ...] = ("qt1vmo", "e88epe", "9eb3f6")

# The one axe rule that mints a judgment finding on an image, and the bucket that makes it one.
IMAGE_AXE_RULE = "image-alt"
JUDGMENT_BUCKET = AxeBucket.PASSES

# Rules whose minting cases are excluded as a class, with the ground stated in full. Recorded in the
# artifact so the exclusion travels with the numbers it changes.
RETRACTED_RULES: dict[str, str] = {
    "e88epe": (
        "reachability is perfectly correlated with gold in this rule's minting set: both passed cases "
        "are decided by an adjacent paragraph that finding.html does not carry, and both failed cases "
        "are decided by the image. Any aggregate movement is therefore uninterpretable — an improvement "
        "on the reachable half and a coin flip on the unreachable half are indistinguishable"
    )
}

# Elements that can carry an image, and what axe can reach on each (measured against the vendored
# axe-core 4.12.1 bundle): `image-alt` selects `img` alone, `svg-img-alt` needs a qualifying role,
# `<canvas>` has no alt rule at all, and the `input[type=image]` / `object` variants are deferred
# from QUALITY_REVIEW_RULES on the empirical bar that module states.
_IMAGE_TAGS = frozenset({"img", "svg", "canvas", "object", "input"})
_VOID_TAGS = frozenset({"img", "input", "br", "hr", "meta", "link", "source", "area", "base"})

# The forms an accessible name can take, and whether that form settles the judgment on its own.
# Stated as a rule over forms rather than as seven per-case verdicts, so the rule is what gets
# reviewed. The default is False: for an image rule, not being able to see the image is the norm.
_NAME_FORM_NOTES: dict[str, tuple[bool, str]] = {
    "hex-digest": (
        True,
        "a hex digest describes nothing whatever the image shows, so the snippet alone settles it",
    ),
    "filename": (
        False,
        "a filename-shaped name is only wrong if it names the file that actually renders, and which "
        "file renders is fixed outside the <img> snippet — a <picture>/<source> can change it",
    ),
    "empty": (
        False,
        "an empty name claims the image is decorative, which the snippet cannot confirm",
    ),
    "phrase": (
        False,
        "whether the phrase describes the image requires seeing the image",
    ),
    "absent": (
        False,
        "the snippet carries no alt attribute at all, so the element is named — or excluded — by "
        "something else such as role=presentation, which the snippet alone does not settle either",
    ),
}

_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]{16,}$")
_FILENAME = re.compile(r"^[^\s/\\]+\.[A-Za-z0-9]{2,4}$")


def accessible_name_form(alt: str | None) -> str:
    """Classify an `alt` value into one of `_NAME_FORM_NOTES`' forms."""
    if alt is None:
        return "absent"
    name = alt.strip()
    if not name:
        return "empty"
    if _HEX_DIGEST.fullmatch(name):
        return "hex-digest"
    if _FILENAME.fullmatch(name):
        return "filename"
    return "phrase"


class _ImageCensus(HTMLParser):
    """The image-bearing elements a case's markup contains, each with the attributes that decide
    whether axe can reach it: its tag, its `role`, its `alt`, and whether `aria-hidden` on itself or
    on any ancestor takes it out of the accessibility tree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict[str, Any]] = []
        self._hidden = False
        self._stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value for name, value in attrs}
        hidden = self._hidden or attributes.get("aria-hidden") == "true"
        if tag in _IMAGE_TAGS and not (tag == "input" and (attributes.get("type") or "").lower() != "image"):
            self.elements.append(
                {
                    "tag": tag if tag != "input" else "input[type=image]",
                    "role": attributes.get("role"),
                    "alt": attributes.get("alt"),
                    "src": attributes.get("src"),
                    "aria_hidden": hidden,
                }
            )
        if tag not in _VOID_TAGS:
            self._stack.append(self._hidden)
            self._hidden = hidden

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID_TAGS and self._stack:
            self._hidden = self._stack.pop()


def prompt_key(rule_id: str, bucket: str, help_text: str, target: str, html: str) -> str:
    """The sha256 of everything about a finding that reaches the drafter's prompt.

    `_user_prompt` renders exactly these five things plus the candidate criteria, and the candidates
    are a function of the rule, so two findings sharing this key are shown byte-identical prompts.
    Computed here rather than by calling the drafter so the check stays offline and model-free —
    building a real prompt would require retrieval, and therefore a database, for a question that is
    settled by the finding alone.
    """
    return hashlib.sha256("\n".join([rule_id, bucket, help_text, target, html]).encode()).hexdigest()


def _usable(case: dict[str, Any]) -> bool:
    """ACT's `inapplicable` cases mint nothing by their own definition, so the candidate denominator
    is the passed/failed cases — the same rule `act_gold` applies to the descriptiveness rules."""
    return bool(case["expected"] in ("passed", "failed"))


def twin_exclusions(cases: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each minting case whose prompt key is shared by another minting case carrying the OPPOSITE ACT
    outcome, mapped to those counterparts. Both halves appear, so excluding the keys of this mapping
    removes whole pairs."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        for minted in case["minted"]:
            by_key.setdefault(minted["prompt_key"], []).append(case)
    return {
        case["act_testcase_id"]: sorted(c["act_testcase_id"] for c in group if c["expected"] != case["expected"])
        for group in by_key.values()
        if len({c["expected"] for c in group}) > 1
        for case in group
    }


def pool(cases: list[dict[str, Any]]) -> list[str]:
    """The cases that survive every exclusion: usable, minting a judgment finding, not one half of a
    prompt-level twin pair, and not a member of a retracted rule."""
    excluded = set(twin_exclusions(cases))
    return [
        case["act_testcase_id"]
        for case in cases
        if case["minted"] and case["act_testcase_id"] not in excluded and case["rule_id"] not in RETRACTED_RULES
    ]


def _unreachable_reason(case_elements: list[dict[str, Any]], buckets: dict[str, list[str]]) -> str:
    """Why a usable case mints no judgment finding — derived from what the case contains and where
    axe put it, never from a hand-written per-case note."""
    images = [element for element in case_elements if element["tag"] == "img"]
    if not images:
        others = ", ".join(sorted({element["tag"] for element in case_elements})) or "(no image element)"
        return f"matcher-limited: axe's {IMAGE_AXE_RULE} selector is `img`, and this case's image is {others}"
    if all(image["aria_hidden"] for image in images):
        return "hidden from the accessibility tree by aria-hidden, so axe reports no result for it"
    for bucket, rules in buckets.items():
        if IMAGE_AXE_RULE in rules and bucket != JUDGMENT_BUCKET.value:
            return f"axe put {IMAGE_AXE_RULE} in `{bucket}`, not `{JUDGMENT_BUCKET.value}` — not a judgment item"
    return f"no {IMAGE_AXE_RULE} result in any bucket"


def _minted_record(finding: Any) -> dict[str, Any]:
    """One judgment finding as the drafter will meet it, plus the reading of its accessible name.

    The name is parsed back out of `finding.html` rather than off the page, because the question the
    flag answers is about the SNIPPET: is what the drafter is shown enough to settle the call?
    """
    snippet = _ImageCensus()
    snippet.feed(finding.html)
    name_form = accessible_name_form(snippet.elements[0]["alt"] if snippet.elements else None)
    in_snippet, note = _NAME_FORM_NOTES[name_form]
    return {
        "axe_rule": finding.rule_id,
        "bucket": finding.source_bucket.value,
        "target": finding.target,
        "html": finding.html,
        "help": finding.help,
        "accessible_name_form": name_form,
        "deciding_fact_in_snippet": in_snippet,
        "deciding_fact_note": note,
        "prompt_key": prompt_key(
            finding.rule_id, finding.source_bucket.value, finding.help, finding.target, finding.html
        ),
    }


def _case_record(case: dict[str, Any]) -> dict[str, Any]:
    """One case, scanned and rendered for real."""
    path = HTML / f"{case['testcaseId']}.html"
    result = scan(str(path), ASSETS)
    findings = normalize(result)
    buckets = {
        AxeBucket.VIOLATIONS.value: [r.rule_id for r in result.violations],
        AxeBucket.INCOMPLETE.value: [r.rule_id for r in result.incomplete],
        AxeBucket.PASSES.value: [r.rule_id for r in result.passes],
    }
    elements = _ImageCensus()
    elements.feed(path.read_text(encoding="utf-8"))
    minted = [
        _minted_record(finding)
        for finding in findings
        if finding.rule_id == IMAGE_AXE_RULE and finding.source_bucket is JUDGMENT_BUCKET
    ]
    rendered = image_render_report(str(path), ASSETS) if any(e["tag"] == "img" for e in elements.elements) else []
    return {
        "act_testcase_id": case["testcaseId"],
        "rule_id": case["ruleId"],
        "rule_name": case["ruleName"],
        "expected": case["expected"],
        "usable": _usable(case),
        "path": f"html/{case['testcaseId']}.html",
        "url": case["url"],
        "image_elements": elements.elements,
        "axe_rules_by_bucket": buckets,
        "minted": minted,
        "unreachable_reason": None if minted or not _usable(case) else _unreachable_reason(elements.elements, buckets),
        "rendered_images": [image._asdict() for image in rendered],
    }


def build_artifact() -> dict[str, Any]:
    """Scan every vendored image case and derive the pool from what was measured."""
    export = json.loads(_EXPORT.read_text())
    cases = [_case_record(t) for t in export["testcases"] if t["ruleId"] in IMAGE_RULE_IDS]
    usable = [case for case in cases if case["usable"]]
    minting = [case for case in usable if case["minted"]]
    twins = twin_exclusions(usable)
    surviving = pool(usable)
    in_pool = set(surviving)
    return {
        "set_id": SET_ID,
        "version": 1,
        "gold_version": GOLD_VERSION,
        "source": "w3c-act",
        "axe_core_version": AXE_VERSION,
        "note": (
            "Reachability of the ACT image rules, measured with the real scanner and normalizer over "
            "every published case of the three rules — no model runs. `pool` is what survives: usable, "
            "minting a judgment finding, not one half of a prompt-level twin pair, and not a member of "
            "a retracted rule. Unreachable cases are kept with their reason so the pool can be read as "
            "a share of the candidates rather than taken on trust."
        ),
        "rules": {
            rule_id: {
                "rule_name": next(case["rule_name"] for case in cases if case["rule_id"] == rule_id),
                "published": sum(1 for case in cases if case["rule_id"] == rule_id),
                "usable": sum(1 for case in usable if case["rule_id"] == rule_id),
                "minting": sum(1 for case in minting if case["rule_id"] == rule_id),
                "in_pool": sum(1 for c in minting if c["rule_id"] == rule_id and c["act_testcase_id"] in in_pool),
            }
            for rule_id in IMAGE_RULE_IDS
        },
        "totals": {
            "published": len(cases),
            "usable": len(usable),
            "minting": len(minting),
            "twin_excluded": len(twins),
            "retracted_excluded": sum(1 for case in minting if case["rule_id"] in RETRACTED_RULES),
            "pool": len(surviving),
        },
        "pool": surviving,
        "twin_exclusions": twins,
        "retracted_rules": RETRACTED_RULES,
        "cases": cases,
    }


def main() -> None:
    artifact = build_artifact()
    ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    totals = artifact["totals"]
    print(f"wrote {ARTIFACT.relative_to(Path.cwd())}")
    print(f"  published {totals['published']} → usable {totals['usable']} → minting {totals['minting']}")
    print(f"  excluded: {totals['twin_excluded']} prompt-level twins, {totals['retracted_excluded']} retracted")
    print(f"  pool: {totals['pool']} of {totals['usable']} usable candidates")
    for case_id in artifact["pool"]:
        case = next(c for c in artifact["cases"] if c["act_testcase_id"] == case_id)
        widths = ", ".join(str(image["natural_width"]) for image in case["rendered_images"])
        print(f"    {case_id[:10]} {case['rule_id']} {case['expected']:<7} naturalWidth={widths}")


if __name__ == "__main__":
    main()
