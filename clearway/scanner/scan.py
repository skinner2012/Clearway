"""Scanner — Playwright + headless Chromium + axe-core → `ScanResult`.

Loads a page, injects a pinned, vendored axe-core (`vendor/axe.min.js`), runs
`axe.run()`, and maps the payload into the typed `ScanResult` (ARCHITECTURE §4.2).

axe-core is our oracle, so its version is pinned and recorded in every
`ScanResult.tool_version` for reproducibility. Bumping it is a deliberate,
reviewed change (swap the vendored file + `AXE_VERSION`, re-run fixtures).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from clearway.schemas.models import AxeIncomplete, AxeNode, AxeRuleResult, AxeViolation, ScanResult, Severity

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


def _to_rule_result(raw: dict, cls: type[_RuleResultT]) -> _RuleResultT:
    """Map one axe rule-result payload (from either the `violations` or `incomplete`
    bucket — they share a shape) into the given typed model."""
    impact = raw.get("impact")
    return cls(
        rule_id=raw["id"],
        tags=list(raw.get("tags", [])),
        impact=Severity(impact) if impact else None,
        help=raw.get("help", ""),
        help_url=raw.get("helpUrl", ""),
        nodes=[
            AxeNode(target=[str(t) for t in node.get("target", [])], html=node.get("html", ""))
            for node in raw.get("nodes", [])
        ],
    )


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
            results: dict = page.evaluate("() => axe.run()")
        finally:
            browser.close()

    return ScanResult(
        url=url,
        scanned_at=datetime.now(timezone.utc),
        tool="axe-core",
        tool_version=AXE_VERSION,
        violations=[_to_rule_result(v, AxeViolation) for v in results.get("violations", [])],
        incomplete=[_to_rule_result(i, AxeIncomplete) for i in results.get("incomplete", [])],
        raw=results,
    )
