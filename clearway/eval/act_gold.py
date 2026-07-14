"""Convert the vendored W3C ACT test cases into `GoldLabel`s, and load them for scoring.

External, expert-authored gold: each ACT case carries W3C's expected outcome (passed / failed)
and its WCAG success criteria. This module converts ONLY the five ACT *descriptiveness* rules
whose judgment axe can actually surface (confirmed empirically — see `docs/act-feasibility.md`),
and loads them as `(Finding, GoldLabel)` pairs for a deterministic comparison against gold. No
LLM scores anything here.

Design (mirrors the self-built quality gold in `calibration_build.load_gold_pairs`):
  - The `finding_id` is NOT stored — it hashes an absolute `file://` URL and is not portable, so
    it is derived at load time by re-scanning the vendored case HTML.
  - The join key is the case FILE (its `source_url`) + the tested axe rule. Each ACT case is
    homogeneous — all same-type elements share the tested property — so the page-level gold label
    applies uniformly to every finding the rule mints on the page. `expected_finding_count` records
    how many; the loader asserts it, so axe-core drift fails loudly instead of mislabelling.
  - A case that mints ZERO findings is an honest MISS (the pipeline never got to judge it), recorded
    in the manifest's `honest_misses`, never silently dropped.

Regenerate the manifest with `uv run python -m clearway.eval.act_gold` (scans the vendored HTML).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from clearway.normalizer import normalize
from clearway.scanner import scan
from clearway.schemas.models import AxeBucket, Conformance, Finding, GoldLabel

_ACT_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "act-gold"
_EXPORT = _ACT_GOLD / "testcases.json"
_MANIFEST = _ACT_GOLD / "expected_act.json"

# Set-level freeze id: the vendored export's content hash (see act-gold/NOTICE + checksums.sha256).
_EXPORT_SHA256 = "a805d865d61ae2418e56a6a9d303fe60c85089c792b897eb9472ea5513156293"
GOLD_VERSION = f"act-gold@{_EXPORT_SHA256[:8]}"
LABELLER = "ACT Rules Community Group"
SOURCE = "w3c-act"

# The five ACT judgment rules whose call axe can surface, and the axe rule that mints the Finding.
RULE_TO_AXE: dict[str, str] = {
    "Link in context is descriptive": "link-name",
    "Link is descriptive": "link-name",
    "Form field label is descriptive": "label",
    "Heading is descriptive": "empty-heading",
    "HTML page title is descriptive": "document-title",
}

# Explicitly excluded ACT rules, each with the reason recorded here and in the feasibility report.
EXCLUDED_RULES: dict[str, str] = {
    "Image accessible name is descriptive": (
        "image content is invisible to a DOM-only pipeline; the ACT filename leaks the answer, so we "
        "would measure filename-matching, not image-text-correspondence judgment — it does not transfer"
    ),
    "Image not in the accessibility tree is decorative": (
        "same — the pipeline cannot see the image; needs a multimodal drafter (a future iteration)"
    ),
    "Links with identical accessible names have equivalent purpose": (
        "the ACT outcome is defined over a SET of links; Clearway mints one independent per-element "
        "Finding and judges each link in isolation, so it structurally cannot represent the judgment"
    ),
    "Links with identical accessible names and same context serve equivalent purpose": (
        "same cross-element reason — a set-level judgment a per-element Finding cannot carry"
    ),
    "Error message describes invalid form field value": (
        "no axe rule confirms the error message EXISTS, so it never mints a Finding"
    ),
}

_WCAG_SC_KEY = re.compile(r"^wcag2\d:")  # wcag20:/wcag21:/wcag22: — drop wcag-technique:/aria11:/…


def _conformance(expected: str) -> Conformance | None:
    """Map ACT's outcome to Clearway conformance. `inapplicable` mints no finding → None (skip)."""
    return {"failed": Conformance.DOES_NOT_SUPPORT, "passed": Conformance.SUPPORTS}.get(expected)


def _success_criteria(requirements: dict[str, Any]) -> list[str]:
    """ACT `ruleAccessibilityRequirements` → the WCAG SC ids only, dotted (`wcag20:2.4.4` → `2.4.4`),
    kept as a list (several rules carry two SCs). Technique/ARIA keys are dropped."""
    return [key.split(":", 1)[1] for key in requirements if _WCAG_SC_KEY.match(key)]


def _minting_findings(case_path: Path, axe_rule: str) -> list[Finding]:
    """The PASSES-bucket findings the tested rule mints on this case (re-scanned, so `finding_id` is
    derived from the live `file://` URL)."""
    findings = normalize(scan(str(case_path)))
    return [f for f in findings if f.rule_id == axe_rule and f.source_bucket is AxeBucket.PASSES]


def _case_entry(t: dict[str, Any], finding_count: int) -> dict[str, Any]:
    tid = t["testcaseId"]
    return {
        "act_testcase_id": tid,
        "rule_name": t["ruleName"],
        "axe_rule": RULE_TO_AXE[t["ruleName"]],
        "path": f"html/{tid}.html",
        "expected": t["expected"],
        "gold_conformance": _conformance(t["expected"]).value,  # type: ignore[union-attr]  # non-None: caller skipped inapplicable
        "gold_success_criteria": _success_criteria(t["ruleAccessibilityRequirements"]),
        "expected_finding_count": finding_count,
    }


def build_manifest() -> dict[str, Any]:
    """Scan every surviving passed/failed case in the vendored export and emit the manifest:
    minting cases (with their finding count) + honest misses + the recorded exclusions."""
    export = json.loads(_EXPORT.read_text())
    cases: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    for t in export["testcases"]:
        if t["ruleName"] not in RULE_TO_AXE or _conformance(t["expected"]) is None:
            continue  # not a survivor, or inapplicable (mints nothing)
        findings = _minting_findings(_ACT_GOLD / "html" / f"{t['testcaseId']}.html", RULE_TO_AXE[t["ruleName"]])
        (cases if findings else misses).append(_case_entry(t, len(findings)))
    return {
        "set_id": "act-gold",
        "version": 1,
        "gold_version": GOLD_VERSION,
        "source": SOURCE,
        "labeller": LABELLER,
        "export_sha256": _EXPORT_SHA256,
        "note": (
            "External W3C ACT expert gold. Converted from the vendored testcases.json (frozen by the "
            "export_sha256 above; see act-gold/NOTICE). Only the five descriptiveness rules axe can "
            "surface are converted; each case expands to expected_finding_count GoldLabels (the label "
            "applies uniformly — ACT cases are homogeneous). honest_misses are cases that mint no "
            "finding (recorded, not dropped); excluded_rules are dropped by analysis with reasons. "
            "Scored deterministically against gold, never by the judge."
        ),
        "cases": cases,
        "honest_misses": misses,
        "excluded_rules": EXCLUDED_RULES,
    }


def load_act_gold_pairs() -> list[tuple[Finding, GoldLabel]]:
    """Load the acceptance gold as `(Finding, GoldLabel)` pairs by re-scanning each vendored case.
    Each case yields `expected_finding_count` labels (asserted); a mismatch means axe-core drifted
    from the frozen manifest and is raised, never silently mislabelled."""
    manifest = json.loads(_MANIFEST.read_text())
    pairs: list[tuple[Finding, GoldLabel]] = []
    for case in manifest["cases"]:
        findings = _minting_findings(_ACT_GOLD / case["path"], case["axe_rule"])
        if len(findings) != case["expected_finding_count"]:
            raise RuntimeError(
                f"ACT gold drift: case {case['act_testcase_id']} minted {len(findings)} findings, "
                f"manifest expects {case['expected_finding_count']} (axe-core changed?)"
            )
        for finding in findings:
            gold = GoldLabel(
                finding_id=finding.id,
                gold_success_criteria=case["gold_success_criteria"],
                gold_conformance=Conformance(case["gold_conformance"]),
                labeller=manifest["labeller"],
                gold_version=manifest["gold_version"],
                source=manifest["source"],
                act_testcase_id=case["act_testcase_id"],
                notes=f"ACT '{case['rule_name']}' [{case['expected']}]",
            )
            pairs.append((finding, gold))
    return pairs


def main() -> None:
    manifest = build_manifest()
    _MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    tp = sum(1 for c in manifest["cases"] if c["expected"] == "failed")
    tn = sum(1 for c in manifest["cases"] if c["expected"] == "passed")
    findings = sum(c["expected_finding_count"] for c in manifest["cases"])
    print(f"wrote {_MANIFEST.relative_to(Path.cwd())}")
    print(f"  cases: {len(manifest['cases'])}  ({tn} passed/TN + {tp} failed/TP)  -> {findings} GoldLabels")
    print(f"  honest misses: {len(manifest['honest_misses'])}   excluded rules: {len(manifest['excluded_rules'])}")


if __name__ == "__main__":
    main()
