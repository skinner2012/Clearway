"""The ACT image pool as gold: its own manifest, its own builder, its own loader.

Why this is a separate set rather than four more entries in `act_gold.RULE_TO_AXE`
---------------------------------------------------------------------------------
`RULE_TO_AXE` is not just a converter mapping — it is the global scope every consumer of the
acceptance gold reads, and the offline gate asserts that scope is exactly the 44 cases the frozen
baseline verdict vector was built over. Admitting the two live image rules there makes it 60, and
all three makes it 71, so an in-place extension would turn the gate red on runs that are already
frozen and cannot be re-run. The image cases therefore get a manifest of their own, built from the
same frozen export (`export_sha256` is unchanged) and pointed at the same expert labels, and the
acceptance scope is left exactly as it was.

Where the pool comes from
-------------------------
Nowhere in this module. The pool is *measured* by `image_reachability` — usable, minting a judgment
finding, not one half of a prompt-level twin pair, not a member of a retracted rule — and this
manifest admits exactly the ids that measurement produced, in its order. A pool that drifts shows up
as a failing test rather than as a quietly different denominator.

The deprecated rule, recorded rather than absorbed
--------------------------------------------------
Five of the seven pool cases come from a rule ACT deprecated as superseded, and ACT's own words for
it are carried verbatim on the manifest so that no report over this set can state its result without
also stating what it rests on. The same rule is now named in `act_gold.EXCLUDED_RULES`: it had never
appeared there, because a rule whose cases were never vendored is merely *absent* from the acceptance
gold, and absence and exclusion look identical until the cases exist.

Why the loader threads the asset root
-------------------------------------
A scan without the vendored asset tree mints the IDENTICAL finding — same id, same html, same count —
over an image that never arrived, and the image rules' gold presumes the image rendered. That failure
has no finding-level signal at all, so the loader both serves the assets and asserts the render
(`render_failures`), and a missing picture stops the load instead of quietly invalidating it. The
tree is *derived* from where a case lives (`assets_for`) rather than passed in, so the derived opaque
set — a second set of exactly this shape — inherits the same guarantee without a second argument that
could be forgotten.

Regenerate the manifest with `uv run python -m clearway.eval.act_image_gold` (re-scans the pool).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import (
    _EXPORT,
    _EXPORT_SHA256,
    GOLD_VERSION,
    LABELLER,
    SOURCE,
    _conformance,
    _success_criteria,
)
from clearway.eval.image_reachability import (
    ACT_IMAGE,
    ARTIFACT,
    HTML,
    IMAGE_AXE_RULE,
    JUDGMENT_BUCKET,
    SET_ID,
)
from clearway.normalizer import normalize
from clearway.scanner.scan import AXE_VERSION, RenderedImage, image_render_report, scan
from clearway.schemas.models import Conformance, Finding, GoldLabel

MANIFEST = ACT_IMAGE / "expected_image.json"

# The rule ACT no longer maintains, and its deprecation traced to the record rather than paraphrased.
# `expected_outcomes_disputed` is the field that decides whether the set is usable at all: a
# deprecation that came with a dispute about which cases pass would take the gold with it.
DEPRECATED_RULE_ID = "9eb3f6"
DEPRECATION: dict[str, Any] = {
    "upstream_notice": "This rule is not maintained anymore and should not be used.",
    "superseded_by": "qt1vmo",
    "decided": "ACT Rules Community Group call 2021-01-14, PR #1538",
    "expected_outcomes_disputed": False,
    "consequence": (
        "most of this pool rests on a rule ACT tells implementers not to use, so every report over "
        "the set states the share it carries alongside the result"
    ),
}


def assets_for(case_path: Path) -> Path:
    """The asset tree that belongs to this case's OWN set — derived from where the case lives, never
    passed in.

    Every image set in this repo has the same two-directory shape, `<root>/html/<case>.html` beside
    `<root>/assets/`, so the tree a case needs is a function of the case. That is deliberate rather
    than convenient: an asset root that can be supplied can be forgotten, and a scan that forgets it
    mints identical findings — same ids, same html, same count — over pictures that never arrived. The
    derived set gets the same guarantee as the vendored one for free, and pairing one set's pages with
    another set's assets stops being expressible.
    """
    from clearway.eval.run_scope import OutOfScope  # the scope sits above the gold it scopes

    root = case_path.resolve().parent.parent
    assets = root / "assets"
    if case_path.resolve().parent.name != "html" or not assets.is_dir():
        raise OutOfScope(
            f"{case_path} is not an image-set case: an image set is `<root>/html/<case>.html` beside "
            "`<root>/assets/`, and the assets are what make the picture arrive. Scanning it here would "
            "mint the identical finding over an image that never loaded, with no finding-level trace."
        )
    return assets


def _minting_findings(case_path: Path) -> list[Finding]:
    """The judgment findings the image rule mints on this case, scanned WITH its own asset tree.

    The asset root is not optional here and is not a parameter — see `assets_for`.
    """
    findings = normalize(scan(str(case_path), assets_for(case_path)))
    return [f for f in findings if f.rule_id == IMAGE_AXE_RULE and f.source_bucket is JUDGMENT_BUCKET]


def render_failures(case: dict[str, Any], rendered: Sequence[RenderedImage]) -> list[str]:
    """The ways one case's images failed to arrive: a count the manifest does not expect, or an
    `<img>` the browser never decoded. Pure, so the check reads the same in the loader and in a test."""
    tid = case["act_testcase_id"]
    failures: list[str] = []
    if len(rendered) != case["expected_rendered_images"]:
        failures.append(f"{tid}: {len(rendered)} <img> rendered, manifest expects {case['expected_rendered_images']}")
    failures += [
        f"{tid}: {image.src} decoded to natural_width 0 — the image never arrived"
        for image in rendered
        if image.natural_width == 0 or image.natural_height == 0
    ]
    return failures


def _case_entry(testcase: dict[str, Any]) -> dict[str, Any]:
    tid = testcase["testcaseId"]
    path = HTML / f"{tid}.html"
    return {
        "act_testcase_id": tid,
        "act_rule_id": testcase["ruleId"],
        "rule_name": testcase["ruleName"],
        "rule_deprecated": testcase["ruleId"] == DEPRECATED_RULE_ID,
        "axe_rule": IMAGE_AXE_RULE,
        "path": f"html/{tid}.html",
        "expected": testcase["expected"],
        "gold_conformance": _conformance(testcase["expected"]).value,  # type: ignore[union-attr]  # non-None: the pool is passed/failed
        "gold_success_criteria": _success_criteria(testcase["ruleAccessibilityRequirements"]),
        "expected_finding_count": len(_minting_findings(path)),
        "expected_rendered_images": len(image_render_report(str(path), assets_for(path))),
    }


def build_manifest() -> dict[str, Any]:
    """Admit the measured pool: re-scan and re-render each case, and record what a load must find."""
    pool = json.loads(ARTIFACT.read_text())["pool"]
    export = {t["testcaseId"]: t for t in json.loads(_EXPORT.read_text())["testcases"]}
    cases = [_case_entry(export[tid]) for tid in pool]
    rules = {
        rule_id: {
            "rule_name": next(c["rule_name"] for c in cases if c["act_rule_id"] == rule_id),
            "deprecated": rule_id == DEPRECATED_RULE_ID,
            "pool_cases": sum(1 for c in cases if c["act_rule_id"] == rule_id),
            **({"deprecation": DEPRECATION} if rule_id == DEPRECATED_RULE_ID else {}),
        }
        for rule_id in dict.fromkeys(c["act_rule_id"] for c in cases)
    }
    return {
        "set_id": SET_ID,
        "version": 1,
        "gold_version": GOLD_VERSION,
        "source": SOURCE,
        "labeller": LABELLER,
        "export_sha256": _EXPORT_SHA256,
        "axe_core_version": AXE_VERSION,
        "derived_from": ARTIFACT.name,
        "note": (
            "The ACT image pool as gold, converted from the same frozen testcases.json the acceptance "
            "gold uses (export_sha256 above). Admitted as a SEPARATE set, never through "
            "act_gold.RULE_TO_AXE: that mapping is the acceptance benchmark's global scope and its "
            "offline gate asserts exactly 44 cases, so extending it in place would go red on runs that "
            "are already frozen. The cases are the pool measured in derived_from — usable, minting a "
            "judgment finding, not one half of a prompt-level twin pair, not from a retracted rule. "
            "Every case is loaded with the vendored asset tree served and its render asserted: an "
            "image rule's gold presumes the image arrived, and a scan without the assets mints the "
            "identical finding over a blank picture. Scored deterministically against gold, never by "
            "the judge."
        ),
        "rules": rules,
        "cases": cases,
    }


def load_image_gold_pairs(manifest_path: Path = MANIFEST) -> list[tuple[Finding, GoldLabel]]:
    """Load an image gold set as `(Finding, GoldLabel)` pairs by re-scanning each pool case with its
    assets served. A finding count that drifted from the manifest, or an image that did not render,
    is raised — the first means axe-core moved, the second means the set is invalid.

    Parameterised by manifest because the derived set is a second set of exactly this shape: its cases
    resolve against the manifest's own directory, and its assets against those cases, so no call site
    can pair one set's pages with another's gold or another's pictures."""
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent
    pairs: list[tuple[Finding, GoldLabel]] = []
    for case in manifest["cases"]:
        path = root / case["path"]
        findings = _minting_findings(path)
        if len(findings) != case["expected_finding_count"]:
            raise RuntimeError(
                f"ACT image gold drift: case {case['act_testcase_id']} minted {len(findings)} findings, "
                f"manifest expects {case['expected_finding_count']} (axe-core changed?)"
            )
        failures = render_failures(case, image_render_report(str(path), assets_for(path)))
        if failures:
            raise RuntimeError(f"ACT image gold invalid — the gold presumes a rendered image: {'; '.join(failures)}")
        for finding in findings:
            pairs.append(
                (
                    finding,
                    GoldLabel(
                        finding_id=finding.id,
                        gold_success_criteria=case["gold_success_criteria"],
                        gold_conformance=Conformance(case["gold_conformance"]),
                        labeller=manifest["labeller"],
                        gold_version=manifest["gold_version"],
                        source=manifest["source"],
                        act_testcase_id=case["act_testcase_id"],
                        notes=f"ACT '{case['rule_name']}' [{case['expected']}]",
                    ),
                )
            )
    return pairs


def main() -> None:
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tp = sum(1 for c in manifest["cases"] if c["expected"] == "failed")
    tn = sum(1 for c in manifest["cases"] if c["expected"] == "passed")
    print(f"wrote {MANIFEST.relative_to(Path.cwd())}")
    print(f"  cases: {len(manifest['cases'])}  ({tn} passed/TN + {tp} failed/TP)  set_id {manifest['set_id']}")
    for rule_id, rule in manifest["rules"].items():
        flag = " [DEPRECATED upstream]" if rule["deprecated"] else ""
        print(f"    {rule_id}: {rule['pool_cases']} of {len(manifest['cases'])} pool cases{flag}")


if __name__ == "__main__":
    main()
