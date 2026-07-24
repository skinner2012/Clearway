"""Capture the vendored real-page snapshot the referent extractors are reviewed against.

Referent extraction reviewed only against this repo's fixtures would be reviewed against
rendered bodies of 2-220 characters, where "dump the whole body" scores perfectly and is
useless on a real page. So the review runs against a snapshot of a named, live page, and the
snapshot plus the extracted output are both committed — the review is auditable, not attested.

Run deliberately, not on every test run: it makes one network request.

    uv run python scripts/capture_real_page_snapshot.py

Scraping ethic (CLAUDE.md): one request, no crawl, explicit User-Agent, and the path is
checked against the site's robots.txt before fetching.

What the snapshot is, precisely: the DOM **after** load, serialized, with same-origin
stylesheets inlined and all `<script>` elements removed. Inlining the CSS is what makes the
file render — and therefore extract — the same offline as it did live, since every extractor
here reads *rendered* text. Scripts are removed after they have already run, so the DOM they
built is preserved while the file stays static and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from playwright.sync_api import sync_playwright

from clearway.normalizer.normalize import normalize
from clearway.scanner.referent import BUDGETS, REAL_PAGE_REFERENTS, REAL_PAGE_SNAPSHOT
from clearway.scanner.scan import _USER_AGENT, AXE_VERSION, scan

# A W3C WAI page: a real, content-heavy production page in this project's own domain, on a
# site whose material this repo already vendors under the same licence (see act-gold/NOTICE).
SOURCE_URL = "https://www.w3.org/WAI/fundamentals/accessibility-intro/"

_INLINE_STYLESHEETS_JS = """
async () => {
  const links = [...document.querySelectorAll('link[rel="stylesheet"]')];
  for (const link of links) {
    try {
      const response = await fetch(link.href);
      if (!response.ok) continue;
      const style = document.createElement('style');
      style.textContent = await response.text();
      link.replaceWith(style);
    } catch (e) { /* leave the link in place; the NOTICE records what was inlined */ }
  }
  document.querySelectorAll('script').forEach((s) => s.remove());
  return {
    inlined: links.length,
    html_chars: document.documentElement.outerHTML.length,
    rendered_body_chars: document.body.innerText.replace(/\\s+/g, ' ').trim().length,
  };
}
"""


def _assert_allowed(url: str) -> None:
    parsed = urlparse(url)
    robots = RobotFileParser()
    request = urllib.request.Request(
        f"{parsed.scheme}://{parsed.netloc}/robots.txt", headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # fixed https URL
        robots.parse(response.read().decode("utf-8", "replace").splitlines())
    if not robots.can_fetch(_USER_AGENT, url):
        raise SystemExit(f"robots.txt disallows {url} for {_USER_AGENT!r} — not fetching")


def main() -> None:
    _assert_allowed(SOURCE_URL)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_context(user_agent=_USER_AGENT).new_page()
        try:
            page.goto(SOURCE_URL, wait_until="load")
            stats = page.evaluate(_INLINE_STYLESHEETS_JS)
            html = page.evaluate("() => '<!DOCTYPE html>\\n' + document.documentElement.outerHTML")
        finally:
            browser.close()

    REAL_PAGE_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    REAL_PAGE_SNAPSHOT.write_text(html, encoding="utf-8")

    # Second half of the artifact: the extracted output, committed next to its input so the
    # review is something a reader can check rather than something they have to take on trust.
    findings = normalize(scan(str(REAL_PAGE_SNAPSHOT)))
    page = {
        "url": SOURCE_URL,
        "retrieved": date.today().isoformat(),
        "snapshot_sha256": hashlib.sha256(REAL_PAGE_SNAPSHOT.read_bytes()).hexdigest(),
        "axe_core_version": AXE_VERSION,
        "budgets": BUDGETS,
        "stylesheets_inlined": stats["inlined"],
        "html_chars": stats["html_chars"],
        "rendered_body_chars": stats["rendered_body_chars"],
        "findings": len(findings),
    }
    referents = {
        f"{f.rule_id} {f.target}": (f.referent.model_dump(mode="json") if f.referent else None) for f in findings
    }
    REAL_PAGE_REFERENTS.write_text(
        json.dumps({"page": page, "referents": referents}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(page, indent=2))


if __name__ == "__main__":
    main()
