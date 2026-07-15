"""T3 acceptance: normalize a ScanResult into deduplicated, deterministic Findings."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from clearway.normalizer import normalize
from clearway.normalizer.quality_review import FINDING_CLASS_TRUST, QUALITY_REVIEW_RULES, FindingClassTrust
from clearway.scanner import scan
from clearway.schemas.models import (
    AxeBucket,
    AxeIncomplete,
    AxeNode,
    AxePass,
    AxeViolation,
    ScanResult,
    Severity,
)

PAGES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures" / "pages"
FIXTURE = PAGES / "home.html"
QUALITY = PAGES / "quality"


def _scan_result(
    *violations: AxeViolation,
    incomplete: list[AxeIncomplete] | None = None,
    passes: list[AxePass] | None = None,
    url: str = "file://home.html",
) -> ScanResult:
    return ScanResult(
        url=url,
        scanned_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
        tool_version="4.12.1",
        violations=list(violations),
        incomplete=incomplete or [],
        passes=passes or [],
    )


def _pass(
    rule_id: str,
    *targets: list[str],
    tags: list[str] | None = None,
    impact: Severity | None = None,
) -> AxePass:
    return AxePass(
        rule_id=rule_id,
        tags=tags or [],
        impact=impact,
        help="Images must have alternate text",  # axe's rule-level help — the misleading one
        nodes=[AxeNode(target=t, html=f"<x>{t}</x>") for t in targets],
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


def test_whitelisted_pass_becomes_a_reframed_quality_review_finding() -> None:
    """A whitelisted existence-only pass mints a PASSES finding whose help is reframed to the
    quality-review task — NOT axe's rule-level help, which reads as already-conformant."""
    (finding,) = normalize(_scan_result(passes=[_pass("image-alt", ["img"], tags=["wcag111"])]))
    assert finding.source_bucket is AxeBucket.PASSES
    assert finding.rule_id == "image-alt"
    assert finding.help == QUALITY_REVIEW_RULES["image-alt"]
    assert finding.help != "Images must have alternate text"  # the misleading rule-level help is dropped


def test_non_whitelisted_pass_is_not_a_finding() -> None:
    """axe's passes[] is large; only whitelisted existence-only rules become findings. A pass for
    any other rule (here a heading check) is ignored."""
    assert normalize(_scan_result(passes=[_pass("heading-order", ["h2"])])) == []


def test_passes_findings_come_after_violations_and_incomplete() -> None:
    result = _scan_result(
        _violation("label", ["#email"]),
        incomplete=[_incomplete("color-contrast", ["p"])],
        passes=[_pass("link-name", ["a"])],
    )
    assert [f.source_bucket for f in normalize(result)] == [
        AxeBucket.VIOLATIONS,
        AxeBucket.INCOMPLETE,
        AxeBucket.PASSES,
    ]


def test_source_bucket_is_not_part_of_the_id() -> None:
    # the SAME place reported under either bucket hashes to the same id — provenance is an
    # attribute of the place, not part of its identity.
    from_violation = normalize(_scan_result(_violation("color-contrast", ["p"])))[0]
    from_incomplete = normalize(_scan_result(incomplete=[_incomplete("color-contrast", ["p"])]))[0]
    assert from_violation.id == from_incomplete.id
    assert from_violation.source_bucket is not from_incomplete.source_bucket


# --- end-to-end: real scan -> normalize (the acceptance case) ----------------


def test_fixture_scan_normalizes_home_deterministically() -> None:
    result = scan(str(FIXTURE))
    findings = normalize(result)

    by_rule = {f.rule_id: f for f in findings if f.source_bucket is AxeBucket.VIOLATIONS}
    assert set(by_rule) == {"image-alt", "html-has-lang", "label"}
    assert by_rule["image-alt"].target == "img"
    assert by_rule["html-has-lang"].target == "html"
    assert by_rule["label"].target == "#email"
    # tags carried so the oracle can derive SCs downstream
    assert "wcag412" in by_rule["label"].axe_tags
    # home also has a <title> and a non-empty <h1>, so the global quality-review whitelist mints
    # two existence-only judgment findings (measured against ACT gold in the acceptance benchmark).
    assert {f.rule_id for f in findings if f.source_bucket is AxeBucket.PASSES} == {"document-title", "empty-heading"}

    # idempotency: normalizing the same scan again yields identical ids
    assert [f.id for f in findings] == [f.id for f in normalize(result)]


def test_every_whitelisted_class_carries_a_trust_tier() -> None:
    """A new quality-review rule must declare how far its judgment is trusted — so no finding class
    ships as an unlabelled peer of a measured one. The benchmark showed the classes differ sharply:
    empty-heading reliable, document-title ~100% cry-wolf, image-alt never measured."""
    assert set(FINDING_CLASS_TRUST) == set(QUALITY_REVIEW_RULES)
    assert FINDING_CLASS_TRUST["empty-heading"] is FindingClassTrust.RELIABLE
    assert FINDING_CLASS_TRUST["document-title"] is FindingClassTrust.WEAK
    assert FINDING_CLASS_TRUST["image-alt"] is FindingClassTrust.UNMEASURED


def test_incomplete_fixture_normalizes_to_an_unverifiable_finding() -> None:
    """The synthetic needs-review fixture flows scan -> normalize as a single finding
    tagged INCOMPLETE, and the oracle refuses to ground it (no verdict) even though it
    carries a real WCAG tag — the mechanism behind eval's `unverifiable_share`."""
    from clearway.oracle import AxeCoreOracle

    result = scan(str(PAGES / "contrast-gradient.html"))
    findings = normalize(result)

    # the page also has a <title>/<h1>, so scope to the incomplete bucket (the whitelist mints
    # two judgment findings alongside — see the home normalizer test).
    incomplete = [f for f in findings if f.source_bucket is AxeBucket.INCOMPLETE]
    assert len(incomplete) == 1
    (finding,) = incomplete
    assert finding.rule_id == "color-contrast"
    assert finding.source_bucket is AxeBucket.INCOMPLETE
    assert "wcag143" in finding.axe_tags  # carries a real SC tag...
    assert AxeCoreOracle().verdict_for(finding) is None  # ...yet the oracle gives no verdict


# --- the planted judgment-item fixtures (each yields reframed passes[] items) -

# Each quality fixture plants three present-but-poor values on a gradient (inadequate ->
# borderline -> adequate) so that axe PASSES the existence check while the quality stays a
# judgment call. Map: fixture -> (whitelisted rule it exercises, planted judgment items).
QUALITY_FIXTURES = {
    "alt-product.html": ("image-alt", 3),
    "alt-article.html": ("image-alt", 3),
    "alt-gallery.html": ("image-alt", 3),
    "link-article.html": ("link-name", 3),
    "link-nav.html": ("link-name", 3),
    "link-footer.html": ("link-name", 3),
    "frame-embeds.html": ("frame-title", 3),
    "frame-media.html": ("frame-title", 3),
    "frame-widgets.html": ("frame-title", 3),
}


def test_quality_fixtures_yield_only_reframed_passes_judgment_items() -> None:
    """Each planted quality fixture lands in axe's passes[] under exactly its whitelisted rule —
    present enough to pass existence, never a hard violation — and every minted finding is a
    reframed quality-review task (risk #1), not axe's already-conformant rule help. The 27 findings
    across the set (scoped to each page's own rule) are the gold floor (>= 25). Each page also has a
    <title>/<h1>, so the global whitelist mints document-title/empty-heading judgment findings too;
    those are validated against ACT gold, not this set, so we scope to the page's planted rule."""
    total = 0
    for page, (rule, count) in QUALITY_FIXTURES.items():
        findings = normalize(scan(str(QUALITY / page)))
        passes = [f for f in findings if f.source_bucket is AxeBucket.PASSES and f.rule_id == rule]

        # every planted item passed on existence under exactly the expected whitelisted rule
        assert [f.rule_id for f in passes] == [rule] * count, page
        # reframed to the quality-review task — NOT axe's rule-level "…has alternate text" help
        assert all(f.help == QUALITY_REVIEW_RULES[rule] for f in passes), page
        # present enough to pass: the planted values must not hard-fail as violations
        assert not any(f.source_bucket is AxeBucket.VIOLATIONS for f in findings), page
        total += len(passes)

    assert total == 27
