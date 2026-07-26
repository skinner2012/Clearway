"""Scanner — Playwright + headless Chromium + axe-core → `ScanResult`.

Loads a page, injects a pinned, vendored axe-core (`vendor/axe.min.js`), runs
`axe.run()`, and maps the payload into the typed `ScanResult` (ARCHITECTURE §4.2).

axe-core is our oracle, so its version is pinned and recorded in every
`ScanResult.tool_version` for reproducibility. Bumping it is a deliberate,
reviewed change (swap the vendored file + `AXE_VERSION`, re-run fixtures).

A second `page.evaluate` then captures per-node **referent material** — the context a
judgment about a node needs and that the element snippet cannot carry (`referent.py`).
It runs here, in the same page session, because after `browser.close()` the DOM is gone.

`asset_root` serves a vendored fixture's sub-resources from disk (`_vendored_asset_route`), which
is what makes an image-bearing fixture actually *render* offline.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, TypeVar
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright

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


# Enough leading bytes to identify the image formats a fixture can carry. Sniffed from CONTENT, not
# from the file name, because the assets that need this most have no extension at all.
_MAGIC_CONTENT_TYPES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def served_content_type(body: bytes, path: str = "") -> str:
    """The honest `Content-Type` for `body`, derived from its magic bytes.

    **Measured, because the obvious justification for this is wrong:** Chromium renders an `<img>`
    from its bytes whatever type it was served under — `application/octet-stream`, `text/plain` and
    a missing header all decode identically — so this is *not* what makes a fixture render. What
    makes it render is the request resolving at all (`_vendored_asset_route`).

    It earns its place elsewhere. The type is what a consumer other than a browser has to be told:
    an image sent to a multimodal model travels as `data:<media-type>;base64,…` and is decoded by
    that declared type, and several of these assets are extensionless and served
    `application/octet-stream` upstream, so neither the file name nor the upstream header can supply
    it. Sniffing the bytes is the only source that is right for all of them. It also keeps the served
    response truthful, which matters the moment anything sends `X-Content-Type-Options: nosniff`.

    Falls back to the file name, then to a truthful `application/octet-stream`, for content whose
    format is not recognised — never a guess dressed as a fact.
    """
    for magic, content_type in _MAGIC_CONTENT_TYPES:
        if body.startswith(magic):
            return content_type
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body.lstrip()[:5] in (b"<svg ", b"<svg>", b"<?xml"):
        return "image/svg+xml"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _vendored_asset_route(asset_root: Path) -> Callable[[Route], None]:
    """Serve a request from the vendored asset tree when that tree mirrors its URL path.

    ACT case HTML references its images site-absolutely (`/test-assets/…`), which under `file://`
    resolves to the filesystem root and loads nothing — the reason image-bearing fixtures have been
    rendering blank. This repairs it at the request layer, which is the only place that leaves both
    the vendored bytes and the identity of the finding untouched: rewriting the HTML would mutate
    expert-authored ACT bytes, and a local HTTP server would put a port number inside every
    `Finding.id` and break reproducibility across runs.

    Anything the tree does not mirror continues to the browser unchanged, so this can only ever add
    a response where there was a failure.
    """
    root = asset_root.resolve()

    def handle(route: Route) -> None:
        candidate = (root / urlparse(route.request.url).path.lstrip("/")).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            route.continue_()
            return
        body = candidate.read_bytes()
        route.fulfill(status=200, body=body, headers={"Content-Type": served_content_type(body, candidate.name)})

    return handle


class RenderedImage(NamedTuple):
    """One `<img>` as the browser actually resolved it: the URL it settled on and the decoded size.

    `natural_width == 0` is the whole reason this exists — it is what a broken `src`, a 404 and an
    undecodable `Content-Type` all look like, and it is invisible to a DOM-only pipeline. A fixture
    whose gold presumes a rendered image is only valid if this is non-zero.
    """

    src: str
    natural_width: int
    natural_height: int


_RENDERED_IMAGES_JS = """
() => Array.from(document.images).map((i) => [i.currentSrc || i.src, i.naturalWidth, i.naturalHeight])
"""


def image_render_report(target: str, asset_root: Path | None = None) -> list[RenderedImage]:
    """Load a page the same way `scan` does and report how every `<img>` on it resolved.

    Separate from `scan` on purpose: this answers a *validity* question about a fixture (did the
    picture arrive?), not a conformance question about a page, and it must be runnable over a
    derived set that has no gold of its own.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(user_agent=_USER_AGENT).new_page()
        try:
            if asset_root is not None:
                page.route("**/*", _vendored_asset_route(asset_root))
            page.goto(_to_url(target), wait_until="load")
            images = page.evaluate(_RENDERED_IMAGES_JS)
            return [RenderedImage(str(src), int(width), int(height)) for src, width, height in images]
        finally:
            browser.close()


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


def scan(target: str, asset_root: Path | None = None) -> ScanResult:
    """Scan one page (URL or local path) with axe-core and return a `ScanResult`.

    `asset_root` is an optional vendored asset tree to serve the page's sub-resources from (see
    `_vendored_asset_route`). Default `None` leaves every request exactly as it was, so a page that
    needs no local assets scans identically with and without the argument.
    """
    url = _to_url(target)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()
        try:
            if asset_root is not None:
                page.route("**/*", _vendored_asset_route(asset_root))
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
