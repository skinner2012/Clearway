"""T2 acceptance: scanning the T1 fixture with real axe-core returns the planted violations.

This is a real-browser integration test — it launches headless Chromium and runs the
pinned, vendored axe-core against the fixture. It requires `playwright install chromium`.
It is the authoritative confirmation of the axe rule_ids / tags / impacts that the rest
of M0 (fixtures manifest, oracle) assumes (ARCHITECTURE §4.2, §4.8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clearway.scanner import AXE_VERSION, scan
from clearway.schemas.models import AxeIncomplete, ScanResult, Severity

PAGES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages"
FIXTURE = PAGES / "home.html"

# The two synthetic needs-review fixtures, each confirmed against axe-core 4.12.1 to raise
# exactly one `incomplete` item (and zero violations).
INCOMPLETE_FIXTURES = {
    "contrast-gradient": {
        "rule_id": "color-contrast",
        "impact": Severity.SERIOUS,
        "wcag_tag": "wcag143",
        "target": "p",
    },
    "video-no-captions": {
        "rule_id": "video-caption",
        "impact": Severity.CRITICAL,
        "wcag_tag": "wcag122",
        "target": "video",
    },
}

# The planted defects (fixtures/expected_m0.json), confirmed against axe-core 4.12.1.
EXPECTED = {
    "image-alt": {"sc_tag": "wcag111", "impact": Severity.CRITICAL},
    "html-has-lang": {"sc_tag": "wcag311", "impact": Severity.SERIOUS},
    "label": {"sc_tag": "wcag412", "impact": Severity.CRITICAL},
}


def _scan() -> ScanResult:
    return scan(str(FIXTURE))


def test_scan_returns_typed_result_with_pinned_version() -> None:
    result = _scan()
    assert isinstance(result, ScanResult)
    assert result.tool == "axe-core"
    assert result.tool_version == AXE_VERSION == "4.12.1"
    assert result.url.startswith("file://") and result.url.endswith("home.html")
    assert result.raw, "full axe payload should be passed through in .raw"
    assert result.incomplete == [], "home.html has no needs-review items; incomplete stays distinct + empty"


def test_scan_finds_exactly_the_planted_violations() -> None:
    result = _scan()
    found = {v.rule_id for v in result.violations}
    assert found == set(EXPECTED), f"expected the 3 planted rules, got {sorted(found)}"


def test_each_violation_carries_expected_sc_tag_and_impact() -> None:
    by_rule = {v.rule_id: v for v in _scan().violations}
    for rule_id, want in EXPECTED.items():
        violation = by_rule[rule_id]
        assert want["sc_tag"] in violation.tags, f"{rule_id} missing tag {want['sc_tag']}: {violation.tags}"
        assert violation.impact is want["impact"]
        assert violation.nodes, f"{rule_id} should carry at least one offending node"
        assert violation.nodes[0].target, f"{rule_id} node should have a target selector"


@pytest.mark.parametrize("page,want", list(INCOMPLETE_FIXTURES.items()), ids=list(INCOMPLETE_FIXTURES))
def test_incomplete_fixture_lands_in_incomplete_bucket(page: str, want: dict) -> None:
    """The synthetic needs-review fixtures populate `incomplete` (typed `AxeIncomplete`),
    kept distinct from `violations` — the source of the eval unverifiable bucket."""
    result = scan(str(PAGES / f"{page}.html"))
    assert result.violations == [], f"{page} should be clean of violations (needs-review only)"
    assert len(result.incomplete) == 1, f"{page} should raise exactly one incomplete item"
    item = result.incomplete[0]
    assert isinstance(item, AxeIncomplete)
    assert item.rule_id == want["rule_id"]
    assert item.impact is want["impact"]
    assert want["wcag_tag"] in item.tags
    assert item.nodes and item.nodes[0].target == [want["target"]]
