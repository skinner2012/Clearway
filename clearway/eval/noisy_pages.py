"""Noisy-page acceptance cases: ACT judgment snippets embedded intact into realistic, noisy pages.

Two hand-built pages (`fixtures/noisy-pages/`), each embedding ONE ACT snippet VERBATIM as the
*focal* case — the label travels with the snippet, so these are scored exactly like the bare ACT
cases: a deterministic comparison against ACT gold, never the judge. The noise around each focal
snippet is HYBRID:

  - `w3c-act`   — real ACT *passed* snippets, embedded intact, W3C-certified true negatives.
  - `self`      — trivially-descriptive authored chrome (nav / heading / a descriptive <title>).
                  Human-certified as passing; NOT externally certified. Honest limitation, recorded.

`n = 2` is a SMOKE TEST — illustrative, not a measured rate. It shows the pipeline survives real-page
noise; it does NOT enter the headline scorecard (no CI attaches to two points). Page A measures
*miss-under-noise* (a `failed` focal — does noise cause a miss?); Page B measures *cry-wolf-under-
noise* (a `passed` focal on an all-clean page — does noise induce a false positive?). These are the
"realistic pages" tier of the acceptance benchmark (M5 spec).

Design mirrors `act_gold`: the focal/noise composition is DECLARED here, `build_manifest()` scans the
pages and asserts the live findings match it EXACTLY (extra or missing → loud failure, never a silent
mislabel), and `load_noisy_page_pairs()` rebuilds `(Finding, GoldLabel)` pairs from the vendored
pages. Regenerate with `uv run python -m clearway.eval.noisy_pages`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import GOLD_VERSION
from clearway.normalizer import normalize
from clearway.scanner import scan
from clearway.schemas.models import AxeBucket, Conformance, Finding, GoldLabel

_NOISY = Path(__file__).resolve().parents[1] / "fixtures" / "noisy-pages"
_MANIFEST = _NOISY / "expected_noisy_pages.json"

_ACT_LABELLER = "ACT Rules Community Group"
_SELF_LABELLER = "Clearway (authored-trivial noise)"

# passed → clean (a true negative), failed → a real problem the drafter must flag.
_CONFORMANCE = {"passed": Conformance.SUPPORTS, "failed": Conformance.DOES_NOT_SUPPORT}


# The declared design. `build_manifest()` asserts each page's live passes-bucket findings are EXACTLY
# focal + noise (by axe_rule + target) — so an axe-core bump that shifts a selector fails loudly.
PAGES: list[dict[str, Any]] = [
    {
        "page_id": "page-a-title",
        "path": "page-a-title.html",
        "measures": "miss-under-noise: does real-page noise make the drafter MISS a real problem (recall)?",
        "focal": {
            "act_testcase_id": "64ad3868e9022dcfa3f8ba5a3ac1943fd1a9a240",
            "clean_counterpart": "../act-gold/html/64ad3868e9022dcfa3f8ba5a3ac1943fd1a9a240.html",
            "rule_name": "HTML page title is descriptive",
            "axe_rule": "document-title",
            "target": "html",
            "expected": "failed",
            "gold_success_criteria": ["2.4.2"],
            "spot_check": (
                "Title 'Apple harvesting season' still fails to describe a page whose <main> is about "
                "clementine harvesting; the nav/aside/footer noise is peripheral and topically neutral, "
                "so it does not rescue the title. Focal label ('failed') holds after embedding."
            ),
        },
        "noise": [
            {
                "axe_rule": "empty-heading",
                "target": "h1",
                "provenance": "self",
                "tested_sc": ["2.4.6"],
                "note": "descriptive heading 'Clementine harvesting season'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href="/"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Home'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="growing-guides"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Growing guides'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="contact"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Contact us'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="#desc"]',
                "provenance": "act:16d451321559dc35b8c33f0d21b2c7f49175914e",
                "tested_sc": ["2.4.9"],
                "note": "ACT 'Link is descriptive' [passed], intact with #desc context",
            },
        ],
    },
    {
        "page_id": "page-b-label",
        "path": "page-b-label.html",
        "measures": "cry-wolf-under-noise: does noise induce a FALSE POSITIVE on an all-clean page?",
        "focal": {
            "act_testcase_id": "90d77d3e5b2fdc19bce47f9f9362283861d3903b",
            "clean_counterpart": "../act-gold/html/90d77d3e5b2fdc19bce47f9f9362283861d3903b.html",
            "rule_name": "Form field label is descriptive",
            "axe_rule": "label",
            "target": "#fname",
            "expected": "passed",
            "gold_success_criteria": ["2.4.6"],
            "spot_check": (
                "Label 'First name:' clearly identifies its field; wrapping it in a realistic form with "
                "nav/heading/aside noise does not change the association or the accessible name. Focal "
                "label ('passed') holds; the whole page is clean, so any flag anywhere is a false positive."
            ),
        },
        "noise": [
            {
                "axe_rule": "document-title",
                "target": "html",
                "provenance": "self",
                "tested_sc": ["2.4.2"],
                "note": "descriptive title 'Create your Northwind Books account'",
            },
            {
                "axe_rule": "empty-heading",
                "target": "h1",
                "provenance": "self",
                "tested_sc": ["2.4.6"],
                "note": "descriptive heading 'Create your account'",
            },
            {
                "axe_rule": "label",
                "target": "#email",
                "provenance": "self",
                "tested_sc": ["2.4.6"],
                "note": "descriptive label 'Email address'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href="/"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Home'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="catalog"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Browse the catalog'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="help"]',
                "provenance": "self",
                "tested_sc": ["2.4.4", "2.4.9"],
                "note": "nav link 'Help centre'",
            },
            {
                "axe_rule": "link-name",
                "target": 'a[href$="#desc"]',
                "provenance": "act:16d451321559dc35b8c33f0d21b2c7f49175914e",
                "tested_sc": ["2.4.9"],
                "note": "ACT 'Link is descriptive' [passed], intact with #desc context",
            },
        ],
    },
]


def _page_findings(path: Path) -> list[Finding]:
    """The whitelisted judgment findings a page mints (passes bucket only — the drafter's real domain)."""
    return [f for f in normalize(scan(str(path))) if f.source_bucket is AxeBucket.PASSES]


def _key(axe_rule: str, target: str) -> tuple[str, str]:
    return (axe_rule, target)


def _assert_composition(page: dict[str, Any], findings: list[Finding]) -> None:
    """The live findings must be EXACTLY the declared focal + noise — no extra, none missing."""
    declared = {_key(page["focal"]["axe_rule"], page["focal"]["target"])}
    declared |= {_key(n["axe_rule"], n["target"]) for n in page["noise"]}
    live = {_key(f.rule_id, f.target) for f in findings}
    if declared != live:
        raise RuntimeError(
            f"noisy-page composition drift on {page['page_id']}: "
            f"declared-only={declared - live}  live-only={live - declared} (axe-core changed?)"
        )


def build_manifest() -> dict[str, Any]:
    """Scan both pages, assert each matches its declared composition, and emit the manifest with the
    focal conformance resolved. `gold_version` inherits the ACT freeze the focal labels come from."""
    pages: list[dict[str, Any]] = []
    for page in PAGES:
        findings = _page_findings(_NOISY / page["path"])
        _assert_composition(page, findings)
        focal = {**page["focal"], "gold_conformance": _CONFORMANCE[page["focal"]["expected"]].value}
        noise = [{**n, "gold_conformance": Conformance.SUPPORTS.value} for n in page["noise"]]
        pages.append({**page, "focal": focal, "noise": noise})
    return {
        "set_id": "noisy-pages",
        "version": 1,
        "gold_version": GOLD_VERSION,
        "source": "w3c-act",
        "note": (
            "Realistic noisy pages — 2 pages, each embedding one ACT judgment snippet intact as the "
            "FOCAL case (scored deterministically vs ACT gold, never the judge). Noise is HYBRID: real "
            "ACT passed snippets (provenance 'act:<id>') + trivially-descriptive authored chrome "
            "(provenance 'self', human-certified, NOT ACT-certified) + neutral non-finding prose. n=2 "
            "is a SMOKE TEST — illustrative, not a measured rate; it does not enter the headline "
            "scorecard. Methodology preliminary (see the M5 spec, realistic-pages tier)."
        ),
        "pages": pages,
    }


def load_noisy_page_pairs() -> list[tuple[Finding, GoldLabel]]:
    """Rebuild `(Finding, GoldLabel)` pairs by re-scanning both pages. The focal + ACT-certified noise
    carry `source='w3c-act'`; authored-trivial noise carries `source='self'` (self-built WCAG gold —
    the honest provenance). A composition mismatch is raised, never silently mislabelled."""
    manifest = json.loads(_MANIFEST.read_text())
    pairs: list[tuple[Finding, GoldLabel]] = []
    for page in manifest["pages"]:
        findings = _page_findings(_NOISY / page["path"])
        _assert_composition(page, findings)
        by_key = {_key(f.rule_id, f.target): f for f in findings}

        focal = page["focal"]
        f = by_key[_key(focal["axe_rule"], focal["target"])]
        pairs.append(
            (
                f,
                GoldLabel(
                    finding_id=f.id,
                    gold_success_criteria=focal["gold_success_criteria"],
                    gold_conformance=Conformance(focal["gold_conformance"]),
                    labeller=_ACT_LABELLER,
                    gold_version=manifest["gold_version"],
                    source="w3c-act",
                    act_testcase_id=focal["act_testcase_id"],
                    notes=f"noisy-page focal — ACT '{focal['rule_name']}' [{focal['expected']}] in noise",
                ),
            )
        )

        for n in page["noise"]:
            f = by_key[_key(n["axe_rule"], n["target"])]
            is_act = n["provenance"].startswith("act:")
            pairs.append(
                (
                    f,
                    GoldLabel(
                        finding_id=f.id,
                        gold_success_criteria=n["tested_sc"],
                        gold_conformance=Conformance(n["gold_conformance"]),
                        labeller=_ACT_LABELLER if is_act else _SELF_LABELLER,
                        gold_version=manifest["gold_version"] if is_act else "noisy-authored@1",
                        source="w3c-act" if is_act else "self",
                        act_testcase_id=n["provenance"].split(":", 1)[1] if is_act else None,
                        notes=f"noisy-page noise ({n['provenance']}) — {n['note']}",
                    ),
                )
            )
    return pairs


def main() -> None:
    manifest = build_manifest()
    _MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {_MANIFEST.relative_to(Path.cwd())}")
    for page in manifest["pages"]:
        act = sum(1 for n in page["noise"] if n["provenance"].startswith("act:"))
        print(
            f"  {page['page_id']}: focal={page['focal']['axe_rule']}[{page['focal']['expected']}] "
            f"+ {len(page['noise'])} noise ({act} ACT-certified, {len(page['noise']) - act} authored-trivial)"
        )


if __name__ == "__main__":
    main()
