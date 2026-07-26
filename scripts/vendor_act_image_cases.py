"""Vendor the ACT test cases for the three IMAGE rules — the HTML **and** the images it references.

Why a second vendored set instead of extending `act-gold/`
----------------------------------------------------------
`act-gold/html/` holds the 67 files of the five *descriptiveness* rules, and its manifest, checksum
list and scope constants are asserted at those counts. The image rules are a different scope with a
different reachability story, so they get their own directory, their own NOTICE and their own
checksums. The case *metadata* is not re-fetched: it is read from the already-frozen
`act-gold/testcases.json` (the full published export, all 1134 cases), so both sets carry the same
freeze id and no second export can drift from the first.

What is fetched, and why all of it
----------------------------------
**Every published case of the three image rules** — passed, failed and inapplicable alike — matching
the rule `act-gold/NOTICE` already states: the vendored set is the complete rule set, never a
favorable subset. Which of them mint a finding, and which are unreachable and why, is then a
*measured* property recorded in the reachability artifact rather than a choice made while fetching.

The assets are the point
------------------------
ACT case HTML references its images at the site-absolute path `/test-assets/…`, which under a
`file://` render resolves to the filesystem root and loads nothing. Vendoring alone does not fix
that. So each referenced asset is stored **at its upstream path** under `assets/`, and the scanner
serves it from there through a `page.route()` interceptor (`scanner/scan.py`) — the ACT bytes are
never rewritten, and no local HTTP port leaks into a `Finding.id`.

`assets.json` records the upstream `Content-Type` beside the one the interceptor will serve. It is
not bookkeeping: several of these assets are extensionless and are served `application/octet-stream`
upstream, which a browser will not decode as an image, so the difference between the two columns is
exactly what the interceptor has to repair.

Scraping ethic (CLAUDE.md): robots.txt is checked before anything is fetched, requests are spaced by
`_REQUEST_INTERVAL_S`, and every request carries the scanner's explicit User-Agent.

Run deliberately, not on every test run — it makes one network request per file:

    uv run python scripts/vendor_act_image_cases.py
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from clearway.eval.act_gold import _EXPORT  # the frozen export both vendored sets read
from clearway.eval.image_reachability import ACT_IMAGE, ARTIFACT, ASSETS, HTML, IMAGE_RULE_IDS
from clearway.scanner.scan import _USER_AGENT, served_content_type

_SITE = "https://act-rules.github.io"
# One request per this many seconds. The whole set is ~60 small static files on GitHub Pages; the
# spacing is politeness, not throughput management.
_REQUEST_INTERVAL_S = 1.0
_TIMEOUT_S = 30.0

# Attributes that can carry a sub-resource URL in these cases. `srcset` is comma-separated
# candidates with optional descriptors and is split accordingly.
_URL_ATTRS = frozenset({"src", "href", "poster"})
_SRCSET_ATTRS = frozenset({"srcset"})


class _AssetRefParser(HTMLParser):
    """Collect every sub-resource URL referenced by a case's markup, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name in _URL_ATTRS:
                self.refs.append(value.strip())
            elif name in _SRCSET_ATTRS:
                self.refs.extend(candidate.split()[0] for candidate in value.split(",") if candidate.split())


@dataclass(frozen=True)
class _Fetched:
    body: bytes
    content_type: str


def _get(url: str) -> _Fetched:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310  # fixed https host
        return _Fetched(response.read(), response.headers.get("Content-Type", ""))


def _assert_allowed(urls: list[str]) -> str:
    """Check every URL against the site's robots.txt before fetching any of it.

    A site with no robots.txt disallows nothing (RFC 9309: an unavailable file means full access), so
    a 4xx is an *allow-all*, not a failure — but it is recorded in the NOTICE rather than assumed, so
    a later robots.txt appearing upstream is a visible change and not a silent one.
    """
    robots_url = f"{_SITE}/robots.txt"
    robots = RobotFileParser()
    try:
        fetched = _get(robots_url)
    except urllib.error.HTTPError as error:
        return f"{robots_url} → HTTP {error.code} (absent; nothing disallowed)"
    robots.parse(fetched.body.decode("utf-8", "replace").splitlines())
    disallowed = [url for url in urls if not robots.can_fetch(_USER_AGENT, url)]
    if disallowed:
        raise SystemExit(f"robots.txt disallows {len(disallowed)} URL(s) for {_USER_AGENT!r}, e.g. {disallowed[0]}")
    return f"{robots_url} → fetched and checked; all {len(urls)} URLs allowed"


def _image_cases() -> list[dict[str, object]]:
    """Every published case of the three image rules, from the frozen export, in export order."""
    export = json.loads(_EXPORT.read_text())
    return [t for t in export["testcases"] if t["ruleId"] in IMAGE_RULE_IDS]


def _asset_paths(html: str, page_url: str) -> list[str]:
    """The site-absolute paths of the assets one case references, de-duplicated, in document order.

    Off-site references are dropped (there are none in this set, and vendoring a third party's asset
    is not this script's business); relative references are resolved against the page URL so the
    stored path always mirrors what the browser will request.
    """
    parser = _AssetRefParser()
    parser.feed(html)
    paths: list[str] = []
    for ref in parser.refs:
        absolute = urljoin(page_url, ref)
        parsed = urlparse(absolute)
        if f"{parsed.scheme}://{parsed.netloc}" != _SITE or parsed.path in paths:
            continue
        paths.append(parsed.path)
    return paths


def main() -> None:
    cases = _image_cases()
    case_urls = [str(case["url"]) for case in cases]
    robots_note = _assert_allowed(case_urls)
    print(robots_note)

    HTML.mkdir(parents=True, exist_ok=True)
    asset_paths: list[str] = []
    for case in cases:
        fetched = _get(str(case["url"]))
        (HTML / f"{case['testcaseId']}.html").write_bytes(fetched.body)
        for path in _asset_paths(fetched.body.decode("utf-8", "replace"), str(case["url"])):
            if path not in asset_paths:
                asset_paths.append(path)
        time.sleep(_REQUEST_INTERVAL_S)
    print(f"fetched {len(cases)} case files → {HTML.relative_to(Path.cwd())}")

    assets: list[dict[str, object]] = []
    for path in asset_paths:
        try:
            fetched = _get(f"{_SITE}{path}")
        except urllib.error.HTTPError as error:
            # Not a vendoring failure: ACT publishes cases that reference a deliberately missing
            # image, because "the image request did not complete" is one of the states its rules are
            # written about. Recorded with its status so the artifact shows the gap was measured, and
            # left absent from `assets/` so the interceptor lets the request fail exactly as upstream.
            assets.append({"path": path, "http_status": error.code, "bytes": None})
            time.sleep(_REQUEST_INTERVAL_S)
            continue
        destination = ASSETS / path.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fetched.body)
        assets.append(
            {
                "path": path,
                "http_status": 200,
                "bytes": len(fetched.body),
                "sha256": hashlib.sha256(fetched.body).hexdigest(),
                "upstream_content_type": fetched.content_type,
                "served_content_type": served_content_type(fetched.body, Path(path).name),
            }
        )
        time.sleep(_REQUEST_INTERVAL_S)
    (ACT_IMAGE / "assets.json").write_text(json.dumps(assets, indent=2) + "\n", encoding="utf-8")
    served = [a for a in assets if a["http_status"] == 200]
    repaired = [a for a in served if a["upstream_content_type"] != a["served_content_type"]]
    print(
        f"fetched {len(served)}/{len(assets)} assets → {ASSETS.relative_to(Path.cwd())} "
        f"({len(repaired)} need a repaired Content-Type, {len(assets) - len(served)} absent upstream)"
    )

    _write_checksums()
    print(f"wrote {(ACT_IMAGE / 'checksums.sha256').relative_to(Path.cwd())}")


def _write_checksums() -> None:
    """One `shasum -a 256 -c`-compatible line per vendored file, sorted, paths relative to the set.

    The freeze covers what was FETCHED — the case HTML, the assets, the NOTICE and the fetch receipt.
    `image_reachability.json` is derived from those bytes by a separate module and is regenerated, not
    pinned, exactly as `act-gold/`'s manifest is left out of its checksum list.
    """
    derived = {"checksums.sha256", ARTIFACT.name}
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ACT_IMAGE)}"
        for path in sorted(p for p in ACT_IMAGE.rglob("*") if p.is_file() and p.name not in derived)
    ]
    (ACT_IMAGE / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
