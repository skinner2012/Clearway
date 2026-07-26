"""The opaque derived set — the image pool with every path cue ablated — and the frozen permutation.

What this removes, and why a filename rewrite is not enough
-----------------------------------------------------------
The vendored cases carry the answer in their URLs. Two cues survive a rewrite that only renames the
file, and both are gold-relevant: one case's `srcset` still offers the literal tokens `nyhavn` and
`paris`, and the directory component
`/test-assets/image-filename-as-accessible-name-9eb3f6/` **spells out the deprecated rule's own
deciding criterion** on five of the seven cases while partitioning the pool by rule. So the whole
path goes — `src`, `srcset` and the directory alike — and what remains is checked by name rather
than by eye (`ablation_failures`).

The naming scheme is pinned, and it is pinned *per asset*
---------------------------------------------------------
All seven cases share one neutral directory and take a name per **distinct image**, not per case:
`/img/a.png`, `/img/b.png`, `/img/c.png`. A per-case index would manufacture a distinguishing token
the original never had, and would defeat the prompt-level twin rule outright — two prompts that are
informationally identical would differ by one digit and a byte-comparison would call them distinct.
The letters are *derived*: first appearance of each distinct image across the pool in manifest order,
so the scheme is a function of the measurement rather than of an author's preference.

**The `.png` extension is decorative, and two of the three images are JPEG.** That is the point — the
name carries no information at all, not even the format — and it is harmless because nothing reads
it: the browser sniffs the bytes, and `scanner.served_content_type` sniffs them too. The trap it
creates is real and belongs to the ticket that captures the image: **never derive a media type from
these names.** A `.png` label on JPEG bytes inside a `data:` URI is a lie told to the model.

What the ablation does NOT touch, and what that costs
-----------------------------------------------------
Everything else is byte-exact: the `alt`, the descriptors, the `lang`, the whitespace. So the gold
survives in the sense that matters here — the judgment scored over this set is the WCAG 1.1.1 call
(*does this accessible name describe this image?*), the alt text is unchanged and the rendered pixels
are unchanged, so neither side of that question moved. What does **not** survive is the deprecated
rule's own applicability: `9eb3f6` is about an accessible name that *is* the filename, and after
ablation no name is a filename any more. That rule's outcome is a property of the page ACT published,
and it is not what this set scores.

The permutation
---------------
`MISMATCHED_IMAGE` is a pre-registration: the wrong image each case is shown behind a byte-identical
prompt, fixed here before any verdict exists. It is authored over `act_testcase_id`s and image
labels; resolving it to bytes belongs to the capture ticket. Every case receives an image that is not
its own — asserted, not intended — and the four cells that can actually move are marked `live`, which
*describes* the power without narrowing the statistic: the endpoint is defined over all seven cells,
including the specificity control that should not move.

Regenerate with `uv run python -m clearway.eval.image_opaque` (re-derives every file, then re-scans).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import _EXPORT_SHA256, GOLD_VERSION, LABELLER, SOURCE
from clearway.eval.act_image_gold import DEPRECATED_RULE_ID, DEPRECATION, _minting_findings, assets_for
from clearway.eval.act_image_gold import MANIFEST as LEAKY_MANIFEST
from clearway.eval.image_reachability import ACT_IMAGE, IMAGE_AXE_RULE, prompt_key, twin_exclusions
from clearway.eval.image_reachability import ASSETS as LEAKY_ASSETS
from clearway.scanner.scan import AXE_VERSION, image_render_report

ACT_IMAGE_OPAQUE = Path(__file__).resolve().parents[1] / "fixtures" / "act-image-opaque"
HTML = ACT_IMAGE_OPAQUE / "html"
ASSETS = ACT_IMAGE_OPAQUE / "assets"
MANIFEST = ACT_IMAGE_OPAQUE / "expected_image_opaque.json"
PERMUTATION = ACT_IMAGE_OPAQUE / "permutation.json"
CHECKSUMS = ACT_IMAGE_OPAQUE / "checksums.sha256"

SET_ID = "act-image-opaque@1"  # a derived set gets its own id; the vendored one keeps `act-image-leaky@1`

# The pinned scheme, spelled out once. `_EXTENSION` is deliberately uniform and deliberately wrong for
# two of the three images — see the module docstring.
_DIRECTORY = "img"
_EXTENSION = ".png"
_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_OPAQUE_URL = re.compile(rf"^/{_DIRECTORY}/[a-z]\{_EXTENSION}$")

# The three distinct images the pool resolves to, labelled once so the permutation can be authored in
# words rather than in digests. The digests are the measured ones; `build_set` asserts the pool still
# resolves to exactly these, so a label set that drifts from the fixtures fails loudly.
POOL_IMAGES: dict[str, str] = {
    "w3c-logo": "083d533eb45c69231ca633a4fe6ad908324d8330902f29cf8397ae0499bcd45a",
    "nyhavn": "c5cc0db745a1435fe7acffb9d63f9f346f42562bbbfa70bf00d99788b4d96dae",
    "bread": "bfd6e7326241f417b352867b52d03c97f74eab7b20b8a85041b44ba06b8e6c9d",
}

# THE PRE-REGISTRATION. The wrong image each pool case is shown behind a byte-identical prompt, fixed
# before any verdict for this set exists. Frozen as a mapping over ACT testcase ids; the bytes are
# resolved by the capture ticket, which asserts the derangement again on what was actually attached.
MISMATCHED_IMAGE: dict[str, str] = {
    "be6b29e220d6afbd827625c602ec49027e73fdf1": "bread",
    "530266c6116fcfad12561e9e1a407fa0a0da3435": "nyhavn",
    "cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e": "w3c-logo",
    "607ad4964aa69e78a663cf993a28cedd6a1dc39e": "w3c-logo",
    "1ff696703e7e7393a5d05cdcd3229cb050594998": "bread",
    "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4": "bread",
    "a2333ec76e676624212dcd616ed11ae576ab775e": "w3c-logo",
}

# Which cells can move, and why the other three cannot. Descriptive only: the endpoint is defined over
# all seven cells, and a cell that should not move is evidence when it does.
CELL_POWER: dict[str, tuple[bool, str]] = {
    "be6b29e220d6afbd827625c602ec49027e73fdf1": (True, "alt 'W3C' is true of the true image and false of the bread"),
    "530266c6116fcfad12561e9e1a407fa0a0da3435": (
        False,
        "dead: alt 'ERCIM' is wrong for the W3C logo and wrong for every other pool image, so the "
        "correct verdict does not move when the picture does",
    ),
    "cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e": (True, "alt 'Nyhavn' is true of the photograph and false of the logo"),
    "607ad4964aa69e78a663cf993a28cedd6a1dc39e": (True, "alt 'pain' is true of the bread and false of the logo"),
    "1ff696703e7e7393a5d05cdcd3229cb050594998": (True, "alt 'Nyhavn' is true of the photograph and false of the bread"),
    "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4": (False, "dead: alt 'Paris' is wrong under any image in this pool"),
    "a2333ec76e676624212dcd616ed11ae576ab775e": (
        False,
        "dead by design — the specificity control: a hex-digest name describes nothing whatever is "
        "attached, so a disagreement here means the manipulation moved something other than perception",
    ),
}

_PATH_ATTRIBUTES = ("src", "srcset", "sizes")

# Any site-absolute reference into the vendored asset tree. Matched over the whole file rather than
# over parsed attributes so that a path hiding somewhere the parser does not look — a second element,
# a style rule — is rewritten too, or fails loudly as an unmapped URL.
_VENDORED_PATH = re.compile(r"/test-assets/[A-Za-z0-9._/-]+")


class _ImageAttributes(HTMLParser):
    """Every `<img>`'s attributes, in document order — the material both the ablation and the
    check-that-nothing-else-changed read."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.images.append(dict(attrs))


def image_attributes(html: str) -> list[dict[str, str | None]]:
    """The attributes of every `<img>` in `html`."""
    parser = _ImageAttributes()
    parser.feed(html)
    return parser.images


def referenced_urls(html: str) -> list[str]:
    """Every URL the path-bearing attributes of every `<img>` carry, in document order.

    `srcset` is a comma-separated candidate list whose first token is the URL; `sizes` carries media
    conditions and lengths rather than URLs, and is read for tokens rather than for links.
    """
    urls: list[str] = []
    for image in image_attributes(html):
        src = image.get("src")
        if src:
            urls.append(src.strip())
        for candidate in (image.get("srcset") or "").split(","):
            url = candidate.split()[0] if candidate.split() else ""
            if url:
                urls.append(url)
    return urls


def path_attribute_values(html: str) -> list[tuple[str, str]]:
    """The raw `(attribute, value)` pairs of every path-bearing attribute — checked *by name*, which
    is what makes the ablation gate readable against the ticket that specifies it."""
    return [
        (name, value)
        for image in image_attributes(html)
        for name, value in image.items()
        if name in _PATH_ATTRIBUTES and value is not None
    ]


def gold_relevant_tokens(urls: Iterable[str]) -> frozenset[str]:
    """The words a URL leaks: its path components, their stems, and the words inside them.

    Derived from the originals rather than hand-listed, so a cue nobody thought of is still banned —
    the directory `image-filename-as-accessible-name-9eb3f6` contributes `filename`, `accessible` and
    `name`, which is precisely the leak a filename-only rewrite leaves behind. Tokens the pinned
    scheme itself contains are removed: `img` and `png` name no image and are the same on all seven.
    """
    tokens: set[str] = set()
    for url in urls:
        for part in url.strip("/").split("/"):
            tokens.add(part.lower())
            tokens.add(part.rsplit(".", 1)[0].lower())
            tokens.update(word for word in re.split(r"[-_.]", part.lower()) if len(word) > 2)
    scheme_tokens = {_DIRECTORY, _EXTENSION.lstrip(".")}
    return frozenset(token for token in tokens if token and token not in scheme_tokens)


def ablation_failures(html: str, banned: frozenset[str]) -> list[str]:
    """THE ABLATION GATE. Every way a gold-relevant cue could still be reachable from a minted prompt.

    Two checks, because either alone is too weak: every URL must be exactly the pinned scheme (which
    catches a rewrite that invented its own name), and no banned token may appear anywhere inside a
    path-bearing attribute's value (which catches a scheme that happens to look right while carrying
    a leak in a descriptor or a `sizes` list). Offline and model-free by construction — a model-based
    gate passes when a real cue survives but the model ignores it, and fires when a perfect ablation
    meets a drafter that never read filenames anyway.

    **Scoped to the path attributes by name, and that is the whole check, not a shortcut.** Scanning
    the rest of the prompt for the same tokens would fire on things that are not leaks and cannot be
    removed: the `alt` is the material being judged and is preserved deliberately (one case's name IS
    a hex digest — that case is decided by its text and is the specificity control), while the rule
    id, the `target` and the help text carry `image` and `filename` on all seven cases in both
    conditions alike, which is a declared tension in the help rather than a per-case cue. A leak is
    something that distinguishes one case from another; only the paths did that.
    """
    failures: list[str] = []
    for url in referenced_urls(html):
        if not _OPAQUE_URL.match(url):
            failures.append(f"{url!r} is not the pinned scheme /{_DIRECTORY}/<letter>{_EXTENSION}")
    for name, value in path_attribute_values(html):
        for token in sorted(banned):
            if token in value.lower():
                failures.append(f"{name}={value.strip()!r} still carries the gold-relevant token {token!r}")
    return failures


def ablate(html: str, opaque_url_for: Mapping[str, str]) -> str:
    """Replace every vendored asset path with its opaque name. Nothing else is touched.

    A path with no mapping is an error rather than a passthrough: it means the pool references an
    asset the letter assignment never saw, and leaving it in place would ship a leak.
    """

    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        if url not in opaque_url_for:
            raise RuntimeError(f"no opaque name for {url!r} — the pool references an asset the mapping never saw")
        return opaque_url_for[url]

    ablated = _VENDORED_PATH.sub(replace, html)
    if "/test-assets/" in ablated:
        raise RuntimeError(f"a vendored path survived the ablation: {ablated!r}")
    return ablated


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _leaky_cases() -> list[dict[str, Any]]:
    return list(json.loads(LEAKY_MANIFEST.read_text())["cases"])


def assign_letters(cases: list[dict[str, Any]]) -> dict[str, str]:
    """`url → opaque url`, one name per DISTINCT IMAGE, lettered by first appearance across the pool.

    Two cases that render the same picture therefore get the same name, which is what keeps two
    informationally identical prompts byte-identical instead of one digit apart.
    """
    letter_for_digest: dict[str, str] = {}
    opaque_url_for: dict[str, str] = {}
    for case in cases:
        for url in referenced_urls((ACT_IMAGE / case["path"]).read_text(encoding="utf-8")):
            asset = LEAKY_ASSETS / url.lstrip("/")
            if not asset.is_file():
                raise RuntimeError(f"case {case['act_testcase_id']} references {url!r}, which is not vendored")
            digest = _digest(asset)
            letter = letter_for_digest.setdefault(digest, _LETTERS[len(letter_for_digest)])
            opaque_url_for[url] = f"/{_DIRECTORY}/{letter}{_EXTENSION}"
    return opaque_url_for


def _labels_by_letter(opaque_url_for: Mapping[str, str]) -> dict[str, str]:
    """`letter → label`, resolved through the digests, and refused if the pool no longer resolves to
    exactly the three labelled images."""
    by_digest = {digest: label for label, digest in POOL_IMAGES.items()}
    letters: dict[str, str] = {}
    for url, opaque in opaque_url_for.items():
        digest = _digest(LEAKY_ASSETS / url.lstrip("/"))
        if digest not in by_digest:
            raise RuntimeError(f"{url!r} resolves to {digest[:8]}…, which no POOL_IMAGES label names")
        letters[opaque] = by_digest[digest]
    if set(letters.values()) != set(POOL_IMAGES):
        raise RuntimeError(f"the pool resolves to {sorted(set(letters.values()))}, not to {sorted(POOL_IMAGES)}")
    return letters


def permutation(cases: list[dict[str, Any]], opaque_url_for: Mapping[str, str]) -> dict[str, Any]:
    """The frozen permutation, with the derangement asserted rather than assumed.

    The true image is *measured* — it is whatever the case's own `src` resolves to — and the
    mismatched one is *authored* above, so this is a real check and not a restatement: an authored
    row that names a case's own image is refused here, before any verdict exists.
    """
    label_of = _labels_by_letter(opaque_url_for)
    rows: list[dict[str, Any]] = []
    for case in cases:
        tid = case["act_testcase_id"]
        source = (ACT_IMAGE / case["path"]).read_text(encoding="utf-8")
        true_url = opaque_url_for[referenced_urls(source)[0]]
        true_label = label_of[true_url]
        mismatched = MISMATCHED_IMAGE[tid]
        if mismatched == true_label:
            raise RuntimeError(f"{tid} would be shown its own image ({true_label}) — the mapping is not a derangement")
        live, note = CELL_POWER[tid]
        rows.append(
            {
                "act_testcase_id": tid,
                "alt": image_attributes(source)[0].get("alt"),
                "true_image": true_label,
                "true_image_asset": true_url,
                "mismatched_image": mismatched,
                "mismatched_image_asset": next(url for url, label in label_of.items() if label == mismatched),
                "live": live,
                "note": note,
            }
        )
    if len(MISMATCHED_IMAGE) != len(rows) or set(MISMATCHED_IMAGE) != {row["act_testcase_id"] for row in rows}:
        raise RuntimeError("the permutation and the pool name different cases")
    return {
        "set_id": SET_ID,
        "version": 1,
        "note": (
            "THE PRE-REGISTRATION for the mismatched-image condition: the wrong image each pool case is "
            "shown behind a byte-identical prompt. Frozen as a mapping over ACT testcase ids before any "
            "verdict over this set exists; resolving it to bytes, and re-asserting the derangement on "
            "what was actually attached, belongs to the capture ticket. `true_image` is measured from "
            "the case's own src, `mismatched_image` is authored, and no case receives its own image. "
            "`live` describes which cells can move and is NOT a filter — the endpoint is defined over "
            "all seven cells, and the control that should not move is evidence when it does."
        ),
        "images": {
            label: {
                "sha256": POOL_IMAGES[label],
                "opaque_asset": next(url for url, name in label_of.items() if name == label),
                "cases_showing_it": sum(1 for row in rows if row["true_image"] == label),
            }
            for label in POOL_IMAGES
        },
        "live_cells": sum(1 for row in rows if row["live"]),
        "mapping": rows,
    }


def _minted_records(root: Path, cases: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The findings each ablated case mints, in the shape the twin check reads."""
    return {
        case["act_testcase_id"]: [
            {
                "html": finding.html,
                "prompt_key": prompt_key(
                    finding.rule_id, finding.source_bucket.value, finding.help, finding.target, finding.html
                ),
            }
            for finding in _minting_findings(root / case["path"])
        ]
        for case in cases
    }


def twin_failures(cases: list[dict[str, Any]], minted: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    """THE EXCLUSION RULE, RE-RUN ON THE ABLATED SET. Byte-identity is blind to the failure that
    matters — an ablation that numbered files per case would leave two informationally identical
    prompts differing by one digit — so the same prompt-level check that built the pool is run again
    on what the ablation actually produced, rather than trusted from the originals."""
    return twin_exclusions(
        [
            {
                "act_testcase_id": case["act_testcase_id"],
                "expected": case["expected"],
                "minted": minted[case["act_testcase_id"]],
            }
            for case in cases
        ]
    )


def _case_entry(case: dict[str, Any], root: Path, opaque_url_for: Mapping[str, str], label: str) -> dict[str, Any]:
    path = root / case["path"]
    rendered = image_render_report(str(path), assets_for(path))
    blank = [image.src for image in rendered if image.natural_width == 0 or image.natural_height == 0]
    if blank:
        raise RuntimeError(
            f"{case['act_testcase_id']} renders nothing at {blank} — the ablation moved the assets out from "
            "under the pages, and this set's gold presumes the picture arrived"
        )
    return {
        "act_testcase_id": case["act_testcase_id"],
        "act_rule_id": case["act_rule_id"],
        "rule_name": case["rule_name"],
        "rule_deprecated": case["rule_deprecated"],
        "axe_rule": IMAGE_AXE_RULE,
        "path": case["path"],
        "derived_from": f"{ACT_IMAGE.name}/{case['path']}",
        "expected": case["expected"],
        "gold_conformance": case["gold_conformance"],
        "gold_success_criteria": case["gold_success_criteria"],
        "expected_finding_count": len(_minting_findings(path)),
        "expected_rendered_images": len(rendered),
        "image": label,
        "image_asset": opaque_url_for[referenced_urls((ACT_IMAGE / case["path"]).read_text(encoding="utf-8"))[0]],
    }


def build_set(root: Path = ACT_IMAGE_OPAQUE) -> dict[str, Any]:
    """Derive the whole opaque set into `root`: the ablated pages, the three assets under their pinned
    names, the gold manifest, the frozen permutation and the checksums — then gate it.

    Deterministic: the same vendored inputs produce byte-identical outputs, which a test asserts by
    rebuilding into a scratch directory. Both acceptance gates run HERE as well as in the tests, so a
    regeneration cannot quietly ship a set that leaks.
    """
    cases = _leaky_cases()
    opaque_url_for = assign_letters(cases)
    label_of = _labels_by_letter(opaque_url_for)
    banned = gold_relevant_tokens(opaque_url_for)

    (root / "html").mkdir(parents=True, exist_ok=True)
    for url, opaque in sorted(opaque_url_for.items()):
        asset = root / "assets" / opaque.lstrip("/")
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes((LEAKY_ASSETS / url.lstrip("/")).read_bytes())

    for case in cases:
        source = (ACT_IMAGE / case["path"]).read_text(encoding="utf-8")
        ablated = ablate(source, opaque_url_for)
        failures = ablation_failures(ablated, banned)
        if failures:
            raise RuntimeError(f"ablation gate failed on {case['act_testcase_id']}: {'; '.join(failures)}")
        (root / case["path"]).write_text(ablated, encoding="utf-8")

    frozen = permutation(cases, opaque_url_for)
    (root / PERMUTATION.name).write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    entries = [
        _case_entry(case, root, opaque_url_for, label_of[row["true_image_asset"]])
        for case, row in zip(cases, frozen["mapping"], strict=True)
    ]
    twins = twin_failures(cases, _minted_records(root, cases))
    if twins:
        raise RuntimeError(f"the ablation created prompt-level twins with opposite gold: {twins}")

    manifest = {
        "set_id": SET_ID,
        "version": 1,
        "gold_version": GOLD_VERSION,
        "source": SOURCE,
        "labeller": LABELLER,
        "export_sha256": _EXPORT_SHA256,
        "axe_core_version": AXE_VERSION,
        "derived_from": {"set_id": json.loads(LEAKY_MANIFEST.read_text())["set_id"], "manifest": LEAKY_MANIFEST.name},
        "ablation": {
            "removed": ["src", "srcset", "the directory component"],
            "scheme": f"/{_DIRECTORY}/<letter>{_EXTENSION}, one letter per DISTINCT IMAGE, never per case",
            "letters": {opaque: label for opaque, label in sorted(label_of.items())},
            "extension_is_decorative": (
                f"every asset is named {_EXTENSION} and two of the three are JPEG. The uniform name is the "
                "point — it carries no information, not even the format — and it is safe only because "
                "nothing reads it: the browser sniffs the bytes and so does the scanner. NEVER derive a "
                "media type from these names; a .png label on JPEG bytes in a data: URI is a lie told to "
                "the model."
            ),
        },
        "note": (
            "The image pool with every path cue ablated: src, srcset and the directory alike. A "
            "filename-only rewrite is not enough — one case's srcset retains the tokens `nyhavn` and "
            "`paris`, and the directory spells out the deprecated rule's own deciding criterion on five "
            "of the seven cases. Nothing else changes: the alt text, the descriptors, the lang and the "
            "whitespace are byte-exact, and the rendered pixels are the same bytes under a new name. The "
            "judgment scored over this set is therefore unmoved — WCAG 1.1.1, does this accessible name "
            "describe this image, with both sides of the question untouched. What does NOT survive is the "
            "deprecated rule's own applicability: 9eb3f6 is about a name that IS the filename, and after "
            "ablation no name is a filename. That is a property of the page ACT published and is not what "
            "this set scores. Scored deterministically against gold, never by the judge."
        ),
        "rules": {
            rule_id: {
                "rule_name": next(c["rule_name"] for c in entries if c["act_rule_id"] == rule_id),
                "deprecated": rule_id == DEPRECATED_RULE_ID,
                "pool_cases": sum(1 for c in entries if c["act_rule_id"] == rule_id),
                **({"deprecation": DEPRECATION} if rule_id == DEPRECATED_RULE_ID else {}),
            }
            for rule_id in dict.fromkeys(c["act_rule_id"] for c in entries)
        },
        "cases": entries,
    }
    (root / MANIFEST.name).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / CHECKSUMS.name).write_text(_checksums(root), encoding="utf-8")
    return manifest


def _checksums(root: Path) -> str:
    """One line per DERIVED byte: the ablated pages and the three assets, in the format
    `shasum -a 256 -c` reads. The manifest and the permutation are excluded, as the other derived
    manifests in this repo are — they are regenerated from these bytes, and pinned by review."""
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in (".html", ".png"))
    return "".join(f"{_digest(p)}  {p.relative_to(root).as_posix()}\n" for p in files)


def main() -> None:
    manifest = build_set()
    frozen = json.loads(PERMUTATION.read_text())
    print(f"wrote {ACT_IMAGE_OPAQUE.relative_to(Path.cwd())}/ — set_id {manifest['set_id']}")
    print(f"  {len(manifest['cases'])} ablated cases, {len(manifest['ablation']['letters'])} distinct images")
    for opaque, label in manifest["ablation"]["letters"].items():
        print(f"    {opaque} = {label} ({frozen['images'][label]['cases_showing_it']} cases)")
    print(f"  permutation: {frozen['live_cells']} live cells of {len(frozen['mapping'])}")
    for row in frozen["mapping"]:
        flag = "live" if row["live"] else "dead"
        shown = f"{row['true_image']} → {row['mismatched_image']}"
        print(f"    {row['act_testcase_id'][:10]} alt={row['alt']!r:<12} {shown:<22} [{flag}]")


if __name__ == "__main__":
    main()
