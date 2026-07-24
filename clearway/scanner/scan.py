"""Scanner — Playwright + headless Chromium + axe-core → `ScanResult`.

Loads a page, injects a pinned, vendored axe-core (`vendor/axe.min.js`), runs
`axe.run()`, and maps the payload into the typed `ScanResult` (ARCHITECTURE §4.2).

axe-core is our oracle, so its version is pinned and recorded in every
`ScanResult.tool_version` for reproducibility. Bumping it is a deliberate,
reviewed change (swap the vendored file + `AXE_VERSION`, re-run fixtures).

A second `page.evaluate` then captures per-node **referent material** — the context a
judgment about a node needs and that the element snippet cannot carry (`referent.py`).
It runs here, in the same page session, because after `browser.close()` the DOM is gone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from clearway.scanner.referent import extract_referents
from clearway.schemas.models import (
    AxeIncomplete,
    AxeNode,
    AxePass,
    AxeRuleResult,
    AxeViolation,
    NodeReferent,
    ScanResult,
    Severity,
)

_RuleResultT = TypeVar("_RuleResultT", bound=AxeRuleResult)

# Pinned axe-core version — must match vendor/axe.min.js (`axe.version`).
AXE_VERSION = "4.12.1"
_AXE_MIN_JS = Path(__file__).parent / "vendor" / "axe.min.js"

# Explicit, honest User-Agent (scraping ethic, ARCHITECTURE §4.2). M0 scans
# local fixtures via file://, but any real scan should identify itself.
_USER_AGENT = "Clearway-Scanner/0.1 (+https://github.com/skinner2012/Clearway)"


def _to_url(target: str) -> str:
    """Accept an http(s):// or file:// URL, or a local filesystem path → URL."""
    if urlparse(target).scheme in {"http", "https", "file"}:
        return target
    return Path(target).resolve().as_uri()


def _node_target(node: dict) -> list[str]:
    """axe's `node.target` as the flat string list `AxeNode.target` carries. Used for both the
    model and the referent lookup key, so the two can never disagree."""
    return [str(t) for t in node.get("target", [])]


def _to_rule_result(raw: dict, cls: type[_RuleResultT], referents: dict[tuple[str, ...], NodeReferent]) -> _RuleResultT:
    """Map one axe rule-result payload (from either the `violations` or `incomplete`
    bucket — they share a shape) into the given typed model, attaching the referent material
    captured for each node (absent for a node that could not be re-resolved)."""
    impact = raw.get("impact")
    nodes = []
    for node in raw.get("nodes", []):
        target = _node_target(node)
        nodes.append(AxeNode(target=target, html=node.get("html", ""), referent=referents.get(tuple(target))))
    return cls(
        rule_id=raw["id"],
        tags=list(raw.get("tags", [])),
        impact=Severity(impact) if impact else None,
        help=raw.get("help", ""),
        help_url=raw.get("helpUrl", ""),
        nodes=nodes,
    )


def _all_node_targets(results: dict) -> list[list[str]]:
    """Every node target axe reported, across every bucket we consume, in stable scan order."""
    return [
        _node_target(node)
        for bucket in ("violations", "incomplete", "passes")
        for rule in results.get(bucket, [])
        for node in rule.get("nodes", [])
    ]


def scan(target: str) -> ScanResult:
    """Scan one page (URL or local path) with axe-core and return a `ScanResult`."""
    url = _to_url(target)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()
        try:
            page.goto(url, wait_until="load")
            page.add_script_tag(path=str(_AXE_MIN_JS))
            engine_version = page.evaluate("() => axe.version")
            if engine_version != AXE_VERSION:
                raise RuntimeError(
                    f"vendored axe-core reports version {engine_version!r} but AXE_VERSION is {AXE_VERSION!r} — "
                    f"the pinned constant and vendor/axe.min.js have drifted. Every ScanResult.tool_version and "
                    f"the frozen benchmark's axe_core_version would silently record the wrong engine; bump the "
                    f"constant deliberately, don't let provenance rot."
                )
            results: dict = page.evaluate("() => axe.run()")
            # Second evaluate, deliberately after axe.run() has returned: the referent lives in
            # the DOM around the node, and this is the only moment it exists. Once the browser
            # closes it is gone, and re-fetching the page later would break the freeze every
            # downstream number is a pure function of.
            referents = extract_referents(page, _all_node_targets(results))
        finally:
            browser.close()

    return ScanResult(
        url=url,
        scanned_at=datetime.now(timezone.utc),
        tool="axe-core",
        tool_version=AXE_VERSION,
        violations=[_to_rule_result(v, AxeViolation, referents) for v in results.get("violations", [])],
        incomplete=[_to_rule_result(i, AxeIncomplete, referents) for i in results.get("incomplete", [])],
        # Faithful mirror of axe's passes[]; the normalizer surfaces the existence-only subset named
        # by QUALITY_REVIEW_RULES (clearway/normalizer/quality_review.py) as quality-review findings.
        passes=[_to_rule_result(p, AxePass, referents) for p in results.get("passes", [])],
        raw=results,
    )
