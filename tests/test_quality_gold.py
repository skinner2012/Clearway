"""Gold-set guard: the self-built digital judgment gold set stays valid, versioned, and in
lockstep with the fixtures it labels.

Three layers: (1) the manifest is well-formed and versioned; (2) every value it labels is still
present in its fixture (no axe); (3) it maps one-to-one onto the scanned passes[] judgment
findings and every item builds a complete, schema-valid GoldLabel (runs axe)."""

from __future__ import annotations

import json
from pathlib import Path

from clearway.normalizer import normalize
from clearway.scanner import scan
from clearway.schemas.models import AxeBucket, Conformance, GoldLabel, Severity

FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
MANIFEST = FIXTURES / "expected_quality.json"

# the residual quality criterion per whitelisted rule (see the manifest note for why link-name
# is 2.4.4 and not 4.1.2)
RULE_SC = {"image-alt": "1.1.1", "link-name": "2.4.4", "frame-title": "4.1.2"}


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_is_well_formed_and_versioned() -> None:
    m = _manifest()
    assert m["set_id"] == "quality-gold"
    assert m["gold_version"] == "quality-gold@1"
    assert m["labeller"], "a single labeller must be named — kappa is judge-vs-this-one-labeller"
    assert len(m["pages"]) == 9
    for page in m["pages"]:
        assert page["sc"] == RULE_SC[page["rule_id"]], page["path"]
        for item in page["items"]:
            assert item["target"].startswith("#")
            # conformance is binary for these single-element quality calls
            assert item["conformance"] in {"supports", "does_not_support"}
            assert item["notes"], f"{page['path']} {item['target']}: labelling basis required"


def test_planted_values_stay_in_their_fixtures() -> None:
    """No axe: each labelled value is still present in its fixture, so the gold never drifts
    from the HTML it describes."""
    m = _manifest()
    for page in m["pages"]:
        html = (FIXTURES / page["path"]).read_text()
        for item in page["items"]:
            assert item["value"] in html, f"{page['path']}: missing planted value {item['value']!r}"


def test_gold_maps_one_to_one_onto_findings_and_every_label_validates() -> None:
    """Runs axe: the gold set is a bijection with the scanned passes[] judgment findings, and
    every item builds a complete, schema-valid GoldLabel (finding_id derived from the scan, since
    it hashes an absolute file:// URL and is not portable enough to store)."""
    m = _manifest()
    total = 0
    conformances: set[str] = set()
    for page in m["pages"]:
        findings = normalize(scan(str(FIXTURES / page["path"])))
        passes = {f.target: f for f in findings if f.source_bucket is AxeBucket.PASSES}
        item_targets = {item["target"] for item in page["items"]}

        # one-to-one: no uncovered finding, no orphan label
        assert set(passes) == item_targets, page["path"]

        for item in page["items"]:
            finding = passes[item["target"]]
            assert finding.rule_id == page["rule_id"]
            label = GoldLabel(
                finding_id=finding.id,
                gold_success_criteria=[page["sc"]],
                gold_conformance=Conformance(item["conformance"]),
                gold_severity=Severity(item["severity"]) if item["severity"] else None,
                labeller=m["labeller"],
                gold_version=m["gold_version"],
                notes=item["notes"],
            )
            assert label.finding_id == finding.id
            conformances.add(label.gold_conformance.value)
            total += 1

    assert total == 27  # >= the 25 gold floor
    # both polarities present -> a balanced calibration draft set is constructible in calibration
    assert conformances == {"supports", "does_not_support"}
