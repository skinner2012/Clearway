"""Parse W3C's machine-readable WCAG 2.2 serialization into `CorpusChunk`s.

Source: `https://www.w3.org/WAI/WCAG22/wcag.json` — W3C's official monthly JSON build
(`principles[] → guidelines[] → successcriteria[]`). Usable with attribution, unaltered;
we process it for retrieval and load it into the DB — we do **not** commit the corpus dump
(W3C Document License + the milestone's "no verbatim dumps" rule). The repo holds the
*recipe*; the built corpus lives in pgvector.

Chunking is **structure-aware, by success criterion**: WCAG is already segmented into SCs,
each with a stable id, level, and short normative paragraph — so one SC = one chunk, and the
chunk carries its exact `sc_id` (the retrieval grounding key). No blind fixed-size splitting;
that tool is for unstructured prose, which this is not. (The longer *Understanding* prose is a
later, separate source that will need a heading-aware splitter.)
"""

from __future__ import annotations

import json
import urllib.request
from html.parser import HTMLParser

from clearway.schemas.models import CorpusChunk

WCAG_JSON_URL = "https://www.w3.org/WAI/WCAG22/wcag.json"
SOURCE_WCAG_SC = "WCAG-SC"
_SC_ANCHOR = "https://www.w3.org/TR/WCAG22/#"

# The JSON still carries SCs from older versions (e.g. 4.1.1 "Parsing", obsoleted & removed in
# 2.2, tagged versions ['2.0','2.1']). We keep only SCs applicable to 2.2 so the corpus matches
# the oracle's 86-SC reference set — otherwise retrieval could surface an SC that L0 rejects.
WCAG_VERSION = "2.2"

# Courtesy identification + attribution when fetching a public W3C document.
_USER_AGENT = "Clearway/0.1 (accessibility evidence pipeline; +https://www.w3.org/WAI/WCAG22/)"


class _TextExtractor(HTMLParser):
    """Collapse an HTML fragment to its visible text (the normative `content` is HTML)."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self._parts).split())


def _strip_html(fragment: str) -> str:
    parser = _TextExtractor()
    parser.feed(fragment)
    return parser.text()


def fetch_wcag_json(url: str = WCAG_JSON_URL) -> dict:
    """Fetch the published WCAG 2.2 JSON. Network call — used by the ingest CLI, not by tests
    (tests parse a committed fixture excerpt instead)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed, trusted W3C URL
        data: dict = json.load(response)
    return data


def parse_wcag_json(data: dict, corpus_version: str) -> list[CorpusChunk]:
    """Flatten the WCAG JSON into one `CorpusChunk` per success criterion (embedding unset).

    `chunk_id` is `sc:<num>` — stable across rebuilds of the same corpus_version. The chunk
    text is `<handle>. <normative text>` so retrieval matches on both the SC name and its body.
    """
    chunks: list[CorpusChunk] = []
    for principle in data.get("principles", []):
        for guideline in principle.get("guidelines", []):
            for sc in guideline.get("successcriteria", []):
                if WCAG_VERSION not in sc.get("versions", []):
                    continue  # drop SCs not applicable to WCAG 2.2 (e.g. the removed 4.1.1)
                num = sc["num"]
                handle = sc.get("handle", "")
                body = _strip_html(sc.get("content", ""))
                text = f"{handle}. {body}".strip(". ").strip() if handle else body
                chunks.append(
                    CorpusChunk(
                        chunk_id=f"sc:{num}",
                        sc_ids=[num],
                        text=text,
                        source=SOURCE_WCAG_SC,
                        url=f"{_SC_ANCHOR}{sc['id']}",
                        corpus_version=corpus_version,
                    )
                )
    return chunks
