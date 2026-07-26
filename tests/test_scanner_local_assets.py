"""Guard for the vendored-asset interceptor: a fixture that references an absolute asset path
renders its images offline.

The bug this closes is silent by construction. A page whose `<img src="/test-assets/…">` resolves to
nothing still parses, still scans, and still mints exactly the same finding — the only observable
difference is `naturalWidth == 0`, which a DOM-only pipeline never looks at. So the first test asserts
the failure as well as the fix: the same page, same scanner, with and without an asset root.

The last test pins a *negative* result, deliberately. The served `Content-Type` was expected to be a
second cause of blank renders, since several vendored assets are extensionless and served
`application/octet-stream` upstream. It is not — Chromium decodes an `<img>` from its bytes whatever
type it arrives under. That is worth a test rather than a deleted assumption: it is the reason the
interceptor's type sniffing is justified by the multimodal request and not by the render.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from playwright.sync_api import Route, sync_playwright

from clearway.scanner.scan import _vendored_asset_route, image_render_report, served_content_type

# A 1x1 PNG, and the leading bytes of a JPEG. Literal so the test states its own inputs.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF"

_PAGE = '<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><img src="{src}" alt="a"></body></html>'


class _StubRoute:
    """The two calls the handler can make on a Playwright `Route`, recorded rather than performed."""

    def __init__(self, url: str) -> None:
        self.request = type("_Request", (), {"url": url})()
        self.fulfilled: dict[str, Any] | None = None
        self.continued = False

    def fulfill(self, **kwargs: Any) -> None:
        self.fulfilled = kwargs

    def continue_(self) -> None:
        self.continued = True


def _asset_root(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    (root / "test-assets" / "shared").mkdir(parents=True)
    (root / "test-assets" / "shared" / "logo").write_bytes(PNG)  # deliberately extensionless
    return root


def test_served_content_type_reads_the_bytes_not_the_file_name() -> None:
    """The assets that need this most have no extension, so the name is the fallback, never the
    first answer — and an unrecognised body is reported honestly rather than guessed at."""
    assert served_content_type(PNG, "logo") == "image/png"
    assert served_content_type(JPEG_HEADER, "nyhavn") == "image/jpeg"
    assert served_content_type(b"<svg xmlns='...'></svg>") == "image/svg+xml"
    assert served_content_type(b"not an image", "x.png") == "image/png"  # unrecognised body → the name
    assert served_content_type(b"not an image") == "application/octet-stream"


def test_an_absolute_asset_path_renders_only_with_an_asset_root(tmp_path: Path) -> None:
    """The whole point of the interceptor, stated as a before/after on one page."""
    page = tmp_path / "case.html"
    page.write_text(_PAGE.format(src="/test-assets/shared/logo"), encoding="utf-8")

    broken = image_render_report(str(page))
    assert [image.natural_width for image in broken] == [0], "an absolute path must not resolve under file://"

    served = image_render_report(str(page), _asset_root(tmp_path))
    assert [image.natural_width for image in served] == [1]
    assert [image.natural_height for image in served] == [1]


def test_a_page_needing_no_assets_scans_identically_with_and_without_a_root(tmp_path: Path) -> None:
    """`asset_root` may only ever ADD a response: a request the tree does not mirror is passed
    through untouched, so an unrelated page is unaffected by the argument."""
    page = tmp_path / "plain.html"
    page.write_text(_PAGE.format(src="data:image/gif;base64,R0lGODlhAQABAAAAACw="), encoding="utf-8")
    assert image_render_report(str(page)) == image_render_report(str(page), _asset_root(tmp_path))


def test_a_request_the_tree_does_not_mirror_is_passed_through(tmp_path: Path) -> None:
    handler = _vendored_asset_route(_asset_root(tmp_path))
    route = _StubRoute("file:///test-assets/shared/missing.png")
    handler(route)  # type: ignore[arg-type]  # the stub implements the two methods the handler uses
    assert route.continued and route.fulfilled is None


def test_a_path_escaping_the_asset_root_is_never_served(tmp_path: Path) -> None:
    """The handler joins a request path onto a local directory, so the containment check is what
    keeps an unrelated file on this machine from being served into a page."""
    (tmp_path / "outside.txt").write_text("not part of the vendored set", encoding="utf-8")
    handler = _vendored_asset_route(_asset_root(tmp_path))
    route = _StubRoute("file:///../outside.txt")
    handler(route)  # type: ignore[arg-type]
    assert route.continued and route.fulfilled is None


def test_a_mirrored_request_is_served_with_a_decodable_type(tmp_path: Path) -> None:
    handler = _vendored_asset_route(_asset_root(tmp_path))
    route = _StubRoute("file:///test-assets/shared/logo")
    handler(route)  # type: ignore[arg-type]
    assert route.fulfilled == {"status": 200, "body": PNG, "headers": {"Content-Type": "image/png"}}
    assert not route.continued


def test_the_served_type_is_not_what_makes_an_image_render(tmp_path: Path) -> None:
    """The measured negative: the same bytes decode under a wrong type and under none at all, so the
    render depends on the request resolving, never on the header. Pinned rather than assumed, because
    the interceptor's justification changes if a browser bump ever stops sniffing."""
    page = tmp_path / "case.html"
    page.write_text(_PAGE.format(src="/test-assets/shared/logo"), encoding="utf-8")

    widths: dict[str | None, tuple[int, ...]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        tab = browser.new_context().new_page()
        try:
            for content_type in ("image/png", "application/octet-stream", "text/plain", None):

                def serve(route: Route, served_as: str | None = content_type) -> None:
                    route.fulfill(status=200, body=PNG, headers={"Content-Type": served_as} if served_as else {})

                tab.route("**/test-assets/**", serve)
                tab.goto(page.resolve().as_uri(), wait_until="load")
                widths[content_type] = tuple(tab.evaluate("() => [...document.images].map((i) => i.naturalWidth)"))
                tab.unroute("**/test-assets/**", serve)
        finally:
            browser.close()
    assert set(widths.values()) == {(1,)}, widths
