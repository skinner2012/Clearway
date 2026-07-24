"""T2 acceptance: scanning the T1 fixture with real axe-core returns the planted violations.

This is a real-browser integration test — it launches headless Chromium and runs the
pinned, vendored axe-core against the fixture. It requires `playwright install chromium`.
It is the authoritative confirmation of the axe rule_ids / tags / impacts that the rest
of M0 (fixtures manifest, oracle) assumes (ARCHITECTURE §4.2, §4.8).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from clearway.scanner import AXE_VERSION, scan
from clearway.schemas.models import AxeIncomplete, AxePass, ReferentSource, ScanResult, Severity

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


def test_scan_rejects_a_version_drift_between_the_constant_and_the_vendored_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If vendor/axe.min.js and AXE_VERSION drift, every tool_version + the frozen benchmark's
    axe_core_version would silently record the wrong engine. scan() refuses instead of stamping a lie."""
    monkeypatch.setattr(sys.modules["clearway.scanner.scan"], "AXE_VERSION", "0.0.0-wrong")
    with pytest.raises(RuntimeError, match="drifted"):
        scan(str(FIXTURE))


def test_scan_finds_exactly_the_planted_violations() -> None:
    result = _scan()
    found = {v.rule_id for v in result.violations}
    assert found == set(EXPECTED), f"expected the 3 planted rules, got {sorted(found)}"


def test_scan_captures_the_passes_bucket_faithfully() -> None:
    """scan() mirrors axe's passes[] into typed AxePass — the raw bucket the normalizer draws
    quality-review judgment findings from. home.html passes many rules (it has a <title>, a
    named <button>, a non-empty <h1>, a <main> landmark), so passes[] is populated. Two of those
    passes (document-title, empty-heading) are in QUALITY_REVIEW_RULES, so home does mint
    PASSES judgment findings (see the normalizer/orchestrator tests) — this scanner test only
    asserts the raw bucket is captured faithfully, before any rule set is applied."""
    result = _scan()
    assert result.passes, "home.html passes many axe rules; passes[] must be captured, not dropped"
    assert all(isinstance(p, AxePass) for p in result.passes)
    assert "document-title" in {p.rule_id for p in result.passes}  # home.html has a <title>


def test_each_violation_carries_expected_sc_tag_and_impact() -> None:
    by_rule = {v.rule_id: v for v in _scan().violations}
    for rule_id, want in EXPECTED.items():
        violation = by_rule[rule_id]
        assert want["sc_tag"] in violation.tags, f"{rule_id} missing tag {want['sc_tag']}: {violation.tags}"
        assert violation.impact is want["impact"]
        assert violation.nodes, f"{rule_id} should carry at least one offending node"
        assert violation.nodes[0].target, f"{rule_id} node should have a target selector"


def test_scan_captures_referent_material_alongside_the_element_snippet() -> None:
    """The scan captures the context a node-level judgment needs, in the same page session —
    after the browser closes the DOM is gone, and re-fetching would break the freeze every
    downstream number is a pure function of. It rides `AxeNode.referent`, next to `html`, and
    it does not disturb what axe reported."""
    result = _scan()
    nodes = [node for rule in result.violations + result.incomplete + result.passes for node in rule.nodes]
    assert nodes and all(node.referent is not None for node in nodes), "every same-document node resolves"

    title_rule = next(p for p in result.passes if p.rule_id == "document-title")
    referent = title_rule.nodes[0].referent
    assert referent is not None and referent.document_title is not None
    assert referent.document_title.text == "Clearway fixture — home"
    assert referent.document_title.source is ReferentSource.DOCUMENT_TITLE
    assert not referent.document_title.truncated


def test_scan_leaves_the_axe_engine_torn_down_so_extraction_cannot_wedge_a_scan() -> None:
    """Extraction sets axe up a second time to borrow its accessible-name computation. `setup()`
    re-entry throws, so it tears down first and always tears down after — otherwise a partial
    prior state would wedge the scan rather than degrade it. Two scans in one process is the
    cheapest evidence that the guard holds."""
    first, second = _scan(), _scan()
    assert {v.rule_id for v in first.violations} == {v.rule_id for v in second.violations} == set(EXPECTED)


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
