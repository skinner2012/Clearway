"""T1 stability guard: fixtures exist, the manifest is valid, and each planted violation is present.

axe-core is NOT run here (that is T2). These checks assert the fixture *shape* only — that the
deliberately planted defects stay planted and the manifest stays in sync with the HTML.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
EXPECTED_RULES = {"image-alt", "html-has-lang", "label"}


class _TagCollector(HTMLParser):
    """Collects every (tag_name, attrs_dict) as the document is parsed."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def _load_manifest() -> dict:
    return json.loads((FIXTURES / "expected_m0.json").read_text())


def _load_m1_manifest() -> dict:
    return json.loads((FIXTURES / "expected_m1.json").read_text())


# The two synthetic needs-review fixtures and the axe rule each is confirmed to raise as `incomplete`.
M1_EXPECTED_INCOMPLETE = {
    "pages/contrast-gradient.html": "color-contrast",
    "pages/video-no-captions.html": "video-caption",
}


def _collect(path: Path) -> list[tuple[str, dict[str, str | None]]]:
    collector = _TagCollector()
    collector.feed(path.read_text())
    return collector.tags


def test_manifest_valid_and_pages_exist() -> None:
    manifest = _load_manifest()
    assert manifest["set_id"] == "m0-core"
    assert manifest["version"] == 1
    assert manifest["pages"], "at least one fixture page expected"
    for page in manifest["pages"]:
        assert (FIXTURES / page["path"]).is_file(), f"missing fixture page: {page['path']}"
        assert page["expected_findings"], f"no expected findings for {page['path']}"


def test_home_page_has_exactly_the_planted_violations() -> None:
    manifest = _load_manifest()
    page = manifest["pages"][0]
    assert {f["rule_id"] for f in page["expected_findings"]} == EXPECTED_RULES

    tags = _collect(FIXTURES / page["path"])
    names = {name for name, _ in tags}
    imgs = [attrs for name, attrs in tags if name == "img"]
    htmls = [attrs for name, attrs in tags if name == "html"]
    inputs = [attrs for name, attrs in tags if name == "input"]
    label_fors = {attrs.get("for") for name, attrs in tags if name == "label"}

    # planted #1 — an <img> with no alt attribute
    assert any("alt" not in attrs for attrs in imgs), "expected an <img> with no alt"
    # planted #2 — the <html> element has no lang attribute
    assert htmls and all("lang" not in attrs for attrs in htmls), "expected <html> without lang"
    # planted #3 — an <input> whose id has no matching <label for=...>
    input_ids = {attrs.get("id") for attrs in inputs if attrs.get("id")}
    assert input_ids - label_fors, "expected an unlabeled input"

    # hygiene — title/h1/main present so no incidental document-title/region/bypass findings
    assert {"title", "h1", "main"} <= names, "fixture must stay clean apart from the planted defects"


def test_m1_manifest_valid_and_pages_exist() -> None:
    manifest = _load_m1_manifest()
    assert manifest["eval_set_id"] == "m1-core@1"
    paths = {p["path"] for p in manifest["pages"]}
    assert "pages/home.html" in paths, "the m1 set carries the verifiable home page too"
    for page in manifest["pages"]:
        assert (FIXTURES / page["path"]).is_file(), f"missing fixture page: {page['path']}"
    # each synthetic fixture declares exactly its expected incomplete rule and no violations
    for path, rule in M1_EXPECTED_INCOMPLETE.items():
        page = next(p for p in manifest["pages"] if p["path"] == path)
        assert page["expected_findings"] == [], f"{path} should carry only incomplete, no violations"
        assert {i["rule_id"] for i in page["expected_incomplete"]} == {rule}


def test_incomplete_fixtures_keep_their_planted_structure() -> None:
    # contrast-gradient — a <p> carrying a background gradient (contrast undeterminable),
    # inside a clean main/h1 document so nothing else fires.
    cc = _collect(FIXTURES / "pages/contrast-gradient.html")
    assert {"main", "h1"} <= {name for name, _ in cc}, "contrast fixture must stay clean apart from the planted item"
    assert any(name == "p" and "background-image" in (attrs.get("style") or "") for name, attrs in cc), (
        "expected a <p> with a background-image gradient"
    )

    # video-no-captions — a <video> with NO <track> element.
    vid = _collect(FIXTURES / "pages/video-no-captions.html")
    names_vid = {name for name, _ in vid}
    assert {"main", "h1", "video"} <= names_vid, "video fixture must stay clean apart from the planted item"
    assert "track" not in names_vid, "expected no <track> (captions absent)"
