"""T3 acceptance: normalize a ScanResult into deduplicated, deterministic Findings."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from clearway.normalizer import normalize
from clearway.scanner import scan
from clearway.schemas.models import AxeBucket, AxeIncomplete, AxeNode, AxeViolation, ScanResult, Severity

PAGES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages"
FIXTURE = PAGES / "home.html"


def _scan_result(
    *violations: AxeViolation,
    incomplete: list[AxeIncomplete] | None = None,
    url: str = "file://home.html",
) -> ScanResult:
    return ScanResult(
        url=url,
        scanned_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
        tool_version="4.12.1",
        violations=list(violations),
        incomplete=incomplete or [],
    )


def _violation(
    rule_id: str,
    *targets: list[str],
    tags: list[str] | None = None,
    impact: Severity | None = None,
) -> AxeViolation:
    return AxeViolation(
        rule_id=rule_id,
        tags=tags or [],
        impact=impact,
        nodes=[AxeNode(target=t, html=f"<x>{t}</x>") for t in targets],
    )


def _incomplete(
    rule_id: str,
    *targets: list[str],
    tags: list[str] | None = None,
    impact: Severity | None = None,
) -> AxeIncomplete:
    return AxeIncomplete(
        rule_id=rule_id,
        tags=tags or [],
        impact=impact,
        nodes=[AxeNode(target=t, html=f"<x>{t}</x>") for t in targets],
    )


# --- explosion + dedup (unit, no browser) ------------------------------------


def test_each_node_becomes_its_own_finding() -> None:
    result = _scan_result(_violation("image-alt", ["img.a"], ["img.b"]))
    findings = normalize(result)
    assert [f.target for f in findings] == ["img.a", "img.b"]
    assert len({f.id for f in findings}) == 2  # distinct places -> distinct ids


def test_same_rule_same_target_is_deduped() -> None:
    result = _scan_result(_violation("image-alt", ["img.a"], ["img.a"]))
    findings = normalize(result)
    assert len(findings) == 1


def test_nested_target_path_is_flattened_and_kept_distinct() -> None:
    # same trailing selector in two different frames must NOT collapse together
    result = _scan_result(_violation("label", ["#f1", "#btn"], ["#f2", "#btn"]))
    findings = normalize(result)
    assert [f.target for f in findings] == ["#f1 >>> #btn", "#f2 >>> #btn"]
    assert len({f.id for f in findings}) == 2


def test_tags_and_impact_are_carried() -> None:
    result = _scan_result(_violation("label", ["#email"], tags=["wcag2a", "wcag412"], impact=Severity.CRITICAL))
    (finding,) = normalize(result)
    assert finding.axe_tags == ["wcag2a", "wcag412"]
    assert finding.impact is Severity.CRITICAL


# --- the id scheme ------------------------------------------------------------


def test_id_matches_the_documented_sha256_scheme() -> None:
    result = _scan_result(_violation("image-alt", ["img"]), url="file://home.html")
    (finding,) = normalize(result)
    expected = hashlib.sha256(b"file://home.html|image-alt|img").hexdigest()[:16]
    assert finding.id == expected
    assert len(finding.id) == 16


def test_ids_are_stable_across_calls() -> None:
    result = _scan_result(_violation("image-alt", ["img"]))
    assert [f.id for f in normalize(result)] == [f.id for f in normalize(result)]


# --- bucket provenance (violations vs incomplete) ----------------------------


def test_violation_findings_default_to_the_violations_bucket() -> None:
    (finding,) = normalize(_scan_result(_violation("image-alt", ["img"])))
    assert finding.source_bucket is AxeBucket.VIOLATIONS


def test_incomplete_items_become_findings_tagged_incomplete_after_violations() -> None:
    result = _scan_result(
        _violation("image-alt", ["img"]),
        incomplete=[_incomplete("color-contrast", ["p"], tags=["wcag143"])],
    )
    findings = normalize(result)
    # violations first, then incomplete — stable order
    assert [f.rule_id for f in findings] == ["image-alt", "color-contrast"]
    assert [f.source_bucket for f in findings] == [AxeBucket.VIOLATIONS, AxeBucket.INCOMPLETE]


def test_source_bucket_is_not_part_of_the_id() -> None:
    # the SAME place reported under either bucket hashes to the same id — provenance is an
    # attribute of the place, not part of its identity.
    from_violation = normalize(_scan_result(_violation("color-contrast", ["p"])))[0]
    from_incomplete = normalize(_scan_result(incomplete=[_incomplete("color-contrast", ["p"])]))[0]
    assert from_violation.id == from_incomplete.id
    assert from_violation.source_bucket is not from_incomplete.source_bucket


# --- end-to-end: real scan -> normalize (the acceptance case) ----------------


def test_fixture_scan_normalizes_to_three_deterministic_findings() -> None:
    result = scan(str(FIXTURE))
    findings = normalize(result)

    by_rule = {f.rule_id: f for f in findings}
    assert set(by_rule) == {"image-alt", "html-has-lang", "label"}
    assert by_rule["image-alt"].target == "img"
    assert by_rule["html-has-lang"].target == "html"
    assert by_rule["label"].target == "#email"
    # tags carried so the oracle can derive SCs downstream
    assert "wcag412" in by_rule["label"].axe_tags

    # idempotency: normalizing the same scan again yields identical ids
    assert [f.id for f in findings] == [f.id for f in normalize(result)]


def test_incomplete_fixture_normalizes_to_an_unverifiable_finding() -> None:
    """The synthetic needs-review fixture flows scan -> normalize as a single finding
    tagged INCOMPLETE, and the oracle refuses to ground it (no verdict) even though it
    carries a real WCAG tag — the mechanism behind eval's `unverifiable_share`."""
    from clearway.oracle import AxeCoreOracle

    result = scan(str(PAGES / "contrast-gradient.html"))
    findings = normalize(result)

    assert len(findings) == 1
    (finding,) = findings
    assert finding.rule_id == "color-contrast"
    assert finding.source_bucket is AxeBucket.INCOMPLETE
    assert "wcag143" in finding.axe_tags  # carries a real SC tag...
    assert AxeCoreOracle().verdict_for(finding) is None  # ...yet the oracle gives no verdict
