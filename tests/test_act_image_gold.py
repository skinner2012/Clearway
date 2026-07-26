"""Guard for the image gold manifest: the pool is admitted as its own set, and admitting it leaves
the acceptance scope untouched.

The image cases are deliberately NOT added to `act_gold.RULE_TO_AXE`. That mapping is the global
scope for the acceptance benchmark and its offline gate, which asserts the scoped case set is
exactly 44; admitting two image rules there takes it to 60 and three takes it to 71, so the gate
would go red on runs that are already frozen. The separation is the point of this file: one test
asserts the image manifest exists and maps cleanly to gold, another asserts the acceptance scope is
still the same 44 cases it was before.

The deprecated rule carries five of the seven pool cases, so its deprecation is recorded on the
manifest in ACT's own words rather than paraphrased, and it is named in `act_gold.EXCLUDED_RULES` —
where it had never appeared, because a rule that was never vendored is merely absent from the
acceptance gold, not excluded from it.

The last test pins the failure that voids the set rather than its numbers: a scan without the
vendored asset tree mints the identical finding over an image that never arrived, so the loader
threads the asset root and the render check is what makes the difference audible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clearway.eval import act_gold, act_image_gold
from clearway.eval.dry_gate import case_set_failures
from clearway.eval.image_reachability import ACT_IMAGE, ARTIFACT, HTML
from clearway.scanner.scan import image_render_report
from clearway.schemas.models import Conformance

MANIFEST = json.loads(act_image_gold.MANIFEST.read_text())
CASES = MANIFEST["cases"]
REACHABILITY = json.loads(ARTIFACT.read_text())

ACT_GOLD = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "act-gold"
REPORTS = Path(__file__).resolve().parent.parent / "benchmark" / "reports"

# The deprecated rule's name as the frozen export spells it, em-dash included. Restated here because
# it is the exact string `act_gold.EXCLUDED_RULES` must be keyed on.
DEPRECATED_RULE_NAME = "DEPRECATED — Image filename is accessible name for image"


def test_the_manifest_is_the_reachability_pool_and_nothing_else() -> None:
    """The pool is derived once, by the reachability measurement; this manifest admits exactly it."""
    assert [case["act_testcase_id"] for case in CASES] == REACHABILITY["pool"]
    assert len(CASES) == 7


def test_the_manifest_is_well_formed_and_versioned() -> None:
    assert MANIFEST["set_id"] == "act-image-leaky@1"
    assert MANIFEST["source"] == "w3c-act"
    assert MANIFEST["labeller"] == "ACT Rules Community Group"
    assert MANIFEST["gold_version"] == act_gold.GOLD_VERSION
    assert MANIFEST["export_sha256"] == act_gold._EXPORT_SHA256
    assert MANIFEST["axe_core_version"] == REACHABILITY["axe_core_version"]


def test_every_case_maps_cleanly_to_gold() -> None:
    """No scan: each case has a file, a binary conformance consistent with ACT's outcome, the Level A
    criterion all three image rules carry, and a finding count and image count to assert at load."""
    for case in CASES:
        assert (ACT_IMAGE / case["path"]).is_file(), case["path"]
        assert case["axe_rule"] == "image-alt"
        expected_conf = "supports" if case["expected"] == "passed" else "does_not_support"
        assert case["gold_conformance"] == expected_conf, case
        assert case["gold_success_criteria"] == ["1.1.1"], case
        assert case["expected_finding_count"] == 1
        assert case["expected_rendered_images"] == 1


def test_the_rule_names_come_from_the_frozen_export_verbatim() -> None:
    """Read from the export rather than restated, so a rule renamed upstream cannot silently
    mismatch — and the deprecated rule's em-dash prefix survives the round trip."""
    export = json.loads((ACT_GOLD / "testcases.json").read_text())
    names = {t["ruleId"]: t["ruleName"] for t in export["testcases"]}
    for case in CASES:
        assert case["rule_name"] == names[case["act_rule_id"]], case["act_testcase_id"]
    assert MANIFEST["rules"]["9eb3f6"]["rule_name"] == DEPRECATED_RULE_NAME


def test_the_deprecated_rule_carries_five_of_the_seven_pool_cases() -> None:
    """The share is measured, not assumed: every report over this set has to state that most of it
    rests on a rule ACT no longer maintains."""
    by_rule = {rule: [c for c in CASES if c["act_rule_id"] == rule] for rule in ("qt1vmo", "9eb3f6")}
    assert (len(by_rule["qt1vmo"]), len(by_rule["9eb3f6"])) == (2, 5)
    assert MANIFEST["rules"]["qt1vmo"]["pool_cases"] == 2
    assert MANIFEST["rules"]["9eb3f6"]["pool_cases"] == 5
    assert all(case["rule_deprecated"] for case in by_rule["9eb3f6"])
    assert not any(case["rule_deprecated"] for case in by_rule["qt1vmo"])


def test_the_deprecation_is_recorded_in_acts_own_words() -> None:
    """Quoted, never softened, and with the trace: superseded by the live rule, decided in the
    record, with no dispute about expected outcomes — which is what keeps the set usable at all."""
    deprecation = MANIFEST["rules"]["9eb3f6"]["deprecation"]
    assert deprecation["upstream_notice"] == "This rule is not maintained anymore and should not be used."
    assert deprecation["superseded_by"] == "qt1vmo"
    assert "2021-01-14" in deprecation["decided"] and "1538" in deprecation["decided"]
    assert deprecation["expected_outcomes_disputed"] is False
    assert MANIFEST["rules"]["qt1vmo"].get("deprecation") is None


def test_the_deprecated_rule_is_excluded_from_the_acceptance_gold() -> None:
    """It was never in `EXCLUDED_RULES` — it was merely absent, because it was never vendored. Now
    that its cases are in the repo, absence and exclusion stop being the same thing."""
    assert DEPRECATED_RULE_NAME in act_gold.EXCLUDED_RULES
    assert act_gold.EXCLUDED_RULES[DEPRECATED_RULE_NAME]
    for rule in MANIFEST["rules"].values():
        assert rule["rule_name"] in act_gold.EXCLUDED_RULES
        assert rule["rule_name"] not in act_gold.RULE_TO_AXE


def test_admitting_the_image_cases_leaves_the_acceptance_scope_at_44() -> None:
    """The gate's third check, offline: the scoped case set must still equal the frozen baseline's.
    Scope is `RULE_TO_AXE`, so a separate manifest is what keeps this green — extending the mapping
    in place would make it 60 (two live image rules) or 71 (all three)."""
    acceptance = json.loads((ACT_GOLD / "expected_act.json").read_text())
    scoped = {
        case["act_testcase_id"]
        for case in [*acceptance["cases"], *acceptance["honest_misses"]]
        if case["rule_name"] in act_gold.RULE_TO_AXE
    }
    baseline = {c["act_testcase_id"] for c in json.loads((REPORTS / "verdict_vector.json").read_text())["cases"]}
    assert case_set_failures(scoped, baseline) == []
    assert len(scoped) == 44
    assert not scoped & {case["act_testcase_id"] for case in CASES}


def test_the_act_export_hash_the_gate_pins_is_unchanged() -> None:
    """The gate's fourth check reads this hash off the frozen baseline, so admitting a new set must
    not touch the export it is derived from — the image cases come out of the same frozen export."""
    live = hashlib.sha256((ACT_GOLD / "testcases.json").read_bytes()).hexdigest()
    baseline = json.loads((REPORTS / "drafter_kappa_baseline.json").read_text())
    assert live == act_gold._EXPORT_SHA256 == baseline["act_export_hash"]


def test_the_loader_yields_one_gold_label_per_pool_case_over_a_rendered_image() -> None:
    """The live check, over all seven: each case mints exactly the finding the manifest expects, its
    image actually arrived, and the label carries the ACT provenance a score is read against."""
    pairs = act_image_gold.load_image_gold_pairs()
    assert len(pairs) == 7
    assert len({finding.id for finding, _ in pairs}) == 7
    for (finding, gold), case in zip(pairs, CASES, strict=True):
        assert finding.rule_id == "image-alt" and finding.html.startswith("<img")
        assert gold.finding_id == finding.id
        assert gold.act_testcase_id == case["act_testcase_id"]
        assert gold.gold_conformance is Conformance(case["gold_conformance"])
        assert gold.source == "w3c-act" and gold.gold_version == act_gold.GOLD_VERSION
        assert case["rule_name"] in gold.notes


def test_an_image_that_never_arrived_is_a_loud_failure_not_a_silent_one() -> None:
    """The path that voids the set rather than its numbers. A scan without the vendored asset tree
    mints the IDENTICAL finding over a blank image, and the gold of an image rule presumes the image
    rendered — so the loader threads the asset root and this check is what makes a miss audible."""
    case = CASES[0]
    unserved = image_render_report(str(HTML / f"{case['act_testcase_id']}.html"))
    assert [image.natural_width for image in unserved] == [0]

    failures = act_image_gold.render_failures(case, unserved)
    assert len(failures) == 1
    assert case["act_testcase_id"] in failures[0] and "natural_width" in failures[0]
