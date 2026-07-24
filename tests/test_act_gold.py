"""Guard for the vendored W3C ACT acceptance gold: the frozen bytes stay pinned, the manifest is
well-formed and in sync with the converter's mapping, and sampled cases still mint findings that
build valid `GoldLabel`s.

Layers: (1) the vendored files match their pinned sha256 (fast, no browser); (2) the manifest is
well-formed, versioned, and maps each case cleanly (no scan); (3) exclusions + honest misses are
recorded; (4) a per-rule SAMPLE is re-scanned to confirm minting + GoldLabel construction. The full
40-case scan is exercised by `python -m clearway.eval.act_gold` (regeneration) and the benchmark
runner — axe is pinned (4.12.1), so per-case drift only happens on a deliberate, fully-rerun bump.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from clearway.eval import act_gold
from clearway.schemas.models import Conformance, GoldLabel

ACT_GOLD = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "act-gold"
MANIFEST = json.loads((ACT_GOLD / "expected_act.json").read_text())

EXPECTED_EXCLUSIONS = {
    "Image accessible name is descriptive",
    "Image not in the accessibility tree is decorative",
    "Links with identical accessible names have equivalent purpose",
    "Links with identical accessible names and same context serve equivalent purpose",
    "Error message describes invalid form field value",
    "Link is descriptive",  # scoped out on conformance level: SC 2.4.9 only — Level AAA
}


def test_vendored_files_match_pinned_checksums() -> None:
    """Every vendored file (the export + all HTML) matches the sha256 recorded in checksums.sha256 —
    the freeze the benchmark's reproducibility rests on."""
    checked = 0
    for line in (ACT_GOLD / "checksums.sha256").read_text().splitlines():
        want, rel = line.split(maxsplit=1)
        got = hashlib.sha256((ACT_GOLD / rel).read_bytes()).hexdigest()
        assert got == want, rel
        checked += 1
    assert checked == 68, "1 export + 67 vendored HTML files expected"
    # and the freeze id is derived from the export hash
    export_sha = hashlib.sha256((ACT_GOLD / "testcases.json").read_bytes()).hexdigest()
    assert MANIFEST["gold_version"] == f"act-gold@{export_sha[:8]}"
    assert MANIFEST["export_sha256"] == export_sha


def test_manifest_is_well_formed_and_versioned() -> None:
    assert MANIFEST["set_id"] == "act-gold"
    assert MANIFEST["source"] == "w3c-act"
    assert MANIFEST["labeller"] == "ACT Rules Community Group"
    tn = [c for c in MANIFEST["cases"] if c["expected"] == "passed"]
    tp = [c for c in MANIFEST["cases"] if c["expected"] == "failed"]
    # the scored acceptance set: 24 true negatives + 16 true positives (see the feasibility report)
    assert (len(tn), len(tp)) == (24, 16)
    assert len(MANIFEST["cases"]) == 40


def test_every_case_maps_cleanly_to_gold() -> None:
    """No scan: each case has a stable id, a binary conformance consistent with ACT's outcome, and a
    non-empty WCAG-SC list with no technique/ARIA keys leaked through the filter."""
    for case in MANIFEST["cases"]:
        assert case["act_testcase_id"], case
        assert (ACT_GOLD / case["path"]).is_file(), case["path"]
        assert case["axe_rule"] in set(act_gold.RULE_TO_AXE.values())
        # passed → supports, failed → does_not_support
        expected_conf = "supports" if case["expected"] == "passed" else "does_not_support"
        assert case["gold_conformance"] == expected_conf, case
        assert case["expected_finding_count"] >= 1
        scs = case["gold_success_criteria"]
        assert scs, case  # at least one SC
        assert all(re.fullmatch(r"\d+\.\d+\.\d+", sc) for sc in scs), scs  # dotted ids only


def test_exclusions_and_honest_misses_are_recorded() -> None:
    assert set(MANIFEST["excluded_rules"]) == EXPECTED_EXCLUSIONS
    assert all(reason for reason in MANIFEST["excluded_rules"].values()), "every exclusion needs a reason"
    # the 4 honest misses (aria-hidden headings + role=link pseudo-links) mint nothing, recorded not dropped
    assert len(MANIFEST["honest_misses"]) == 4
    assert all(m["expected_finding_count"] == 0 for m in MANIFEST["honest_misses"])


def test_sampled_cases_mint_and_build_valid_goldlabels() -> None:
    """Re-scan one passed + one failed case per axe rule: the finding count matches the manifest and
    each finding builds a complete, schema-valid `GoldLabel` (finding_id derived from the live scan)."""
    seen: set[tuple[str, str]] = set()
    sampled = 0
    for case in MANIFEST["cases"]:
        key = (case["axe_rule"], case["expected"])
        if key in seen:
            continue
        seen.add(key)
        findings = act_gold._minting_findings(ACT_GOLD / case["path"], case["axe_rule"])
        assert len(findings) == case["expected_finding_count"], case["act_testcase_id"]
        for finding in findings:
            label = GoldLabel(
                finding_id=finding.id,
                gold_success_criteria=case["gold_success_criteria"],
                gold_conformance=Conformance(case["gold_conformance"]),
                labeller=MANIFEST["labeller"],
                gold_version=MANIFEST["gold_version"],
                source=MANIFEST["source"],
                act_testcase_id=case["act_testcase_id"],
            )
            assert label.source == "w3c-act"
            assert label.act_testcase_id == case["act_testcase_id"]
        sampled += 1
    # 4 axe rules × {passed, failed} = up to 8 sampled cases
    assert sampled >= 7


def test_conformance_levels_behind_the_scoping_come_from_the_export() -> None:
    """The link scoping rests on conformance level, so the level is derived from the frozen export
    rather than restated: the excluded rule carries a AAA-only criterion, the retained one a Level A."""
    assert act_gold.rule_success_criteria("Link is descriptive") == ["2.4.9"]  # 2.4.9 is Level AAA
    assert "2.4.4" in act_gold.rule_success_criteria("Link in context is descriptive")  # Level A


def test_no_two_in_scope_cases_share_a_fixture_with_opposite_gold() -> None:
    """Byte-identical fixtures carrying opposite ACT outcomes give the drafter one input and two
    answers, so one of the pair is permanently wrong. The scoping removed both such pairs — the AAA-only
    rule carried them — and this asserts none survives."""
    assert act_gold.contradictory_gold_twins() == {}


def test_every_in_scope_case_belongs_to_a_currently_scored_rule() -> None:
    for case in MANIFEST["cases"] + MANIFEST["honest_misses"]:
        assert case["rule_name"] in act_gold.RULE_TO_AXE, case["act_testcase_id"]
        assert case["rule_name"] not in act_gold.EXCLUDED_RULES
