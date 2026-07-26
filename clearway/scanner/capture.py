"""Image capture — the picture a node actually rendered, lifted out of the live page session.

axe can say an image *has* an accessible name. It cannot say whether that name describes the
picture, because the picture is not in the DOM. `referent.py` captures the text such a judgment
needs; this captures the pixels — the one piece of referent material in this repo that is not a
string, which is why it gets a module of its own rather than another field on `NodeReferent`.

Where the bytes come from, and why the obvious routes were rejected
------------------------------------------------------------------
Measured before this was built, not reasoned about. A page loaded from `file://` will not hand over
its own subresources:

* an in-page `fetch(img.currentSrc)` is refused outright — `TypeError: Failed to fetch`. A `file://`
  document is an opaque origin and the request never leaves the page.
* a canvas `drawImage` + `toDataURL` does work, and so does an element screenshot, but **both
  re-encode to PNG**. Two of the three images in the derived image set are JPEG, so either route
  would replace an asset's bytes with different bytes of the same picture — and a digest over those
  is no longer comparable with the digest of the file it came from, which is exactly what a frozen
  permutation over image identities has to be checked against.

What does work is reading the **response the browser already fetched** (`ResponseRecorder`). Those
are the asset's own bytes, byte-for-byte, whether they arrived over the network or from the
vendored-asset interceptor — so a capture is content-addressable by the same sha256 the fixture tree
is checksummed with, and "did the right picture arrive" is answerable by comparing two hex strings.

A reference travels, the bytes stay put
---------------------------------------
`AxeNode.image_ref` / `Finding.image_ref` carry the sha256 and nothing else. The bytes go to an
`ImageStore` beside the run, addressed by that same digest, because a base64 payload on a contract
model would be serialized into every frozen artifact that ever carries a node and would make every
artifact diff unreadable. Content addressing also makes the store self-checksumming: a file's name
*is* its hash, and `read` refuses one that has stopped matching.

Two failures that must never be quiet
-------------------------------------
* **An image that did not decode.** `natural_width == 0` is what a broken path, a 404 and an
  undecodable body all look like, and it is invisible to a DOM-only pipeline — the finding is
  identical either way. Captured bytes behind such a node would be bytes the browser itself could
  not render, so capture raises rather than attaching them.
* **A media type taken from a file name.** An image reaches a multimodal model as
  `data:<media-type>;base64,…` and is decoded by that *declared* type. The derived image set names
  JPEG assets `.png` on purpose (the name must carry no information, not even the format), and
  several vendored assets have no extension at all and are served `application/octet-stream`
  upstream. So the type is sniffed from the bytes, always — `served_content_type` is the only
  source that is right for all of them, and a `.png` label on JPEG bytes is a lie told to the model.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any, NamedTuple

from playwright.sync_api import Page, Response


class ImageCaptureError(RuntimeError):
    """A picture that was asked for and could not be captured honestly.

    Raised rather than defaulted, because every alternative is a finding that looks complete while
    the model behind it is shown nothing, or shown something the browser could not decode.
    """


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
    makes it render is the request resolving at all (`scan._vendored_asset_route`).

    It earns its place elsewhere, which is why it lives here: an image sent to a multimodal model
    travels as `data:<media-type>;base64,…` and is decoded by that *declared* type, and several of
    these assets are extensionless and served `application/octet-stream` upstream, so neither the
    file name nor the upstream header can supply it. Sniffing the bytes is the only source that is
    right for all of them. It also keeps the served response truthful, which matters the moment
    anything sends `X-Content-Type-Options: nosniff`.

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


class CapturedImage(NamedTuple):
    """One node's picture, as the browser fetched and decoded it.

    `ref` is the sha256 of `data` and the only part of this that travels on a contract; the rest is
    what the capture-time artifact records so the ref can be audited without opening the store.
    """

    ref: str
    media_type: str
    data: bytes
    natural_width: int
    natural_height: int
    src: str


class ResponseRecorder:
    """The image bodies a page load fetched, kept by URL until the nodes can be matched to them.

    Attached before navigation and read after `axe.run()` returns — the same window `referent.py`
    works in, and for the same reason: once the browser closes, the material is gone, and refetching
    it later would be a second, different render of a page the freeze claims to have measured once.

    Only `image` requests are kept, so a scan does not buffer a page's scripts and stylesheets. A
    body the browser did not retain is skipped rather than raised on here — a response is not yet a
    node, and the failure that matters is a *node* with no bytes, which `capture_images` raises.
    """

    def __init__(self) -> None:
        self._bodies: dict[str, bytes] = {}

    def watch(self, page: Page) -> None:
        page.on("response", self._record)

    def _record(self, response: Response) -> None:
        if response.request.resource_type != "image":
            return
        try:
            body = response.body()
        except Exception:  # noqa: BLE001 — a redirect or a discarded body; the node-level check is the loud one
            return
        self._bodies[response.url] = body

    def body_for(self, url: str) -> bytes | None:
        return self._bodies.get(url)


# Per node: the URL the browser settled on and the size it decoded to. `currentSrc`, not `src` —
# with a `srcset` present they differ, and the bytes to capture are the ones actually chosen.
_IMAGE_NODES_JS = """
(targets) => targets.map((target) => {
  if (!Array.isArray(target) || target.length !== 1 || typeof target[0] !== "string") return null;
  let el = null;
  try { el = document.querySelector(target[0]); } catch (e) { el = null; }
  if (el === null || !(el instanceof HTMLImageElement)) return null;
  return {
    src: el.currentSrc || el.src,
    natural_width: el.naturalWidth,
    natural_height: el.naturalHeight,
  };
})
"""


def capture_images(
    page: Page, targets: list[list[str]], recorder: ResponseRecorder
) -> dict[tuple[str, ...], CapturedImage]:
    """Capture the picture behind each of `targets`, keyed by the node's flattened axe target.

    Must be called on the still-open page. A target that is not an `<img>` is simply absent from the
    result — that is how the caller learns "this node has no picture" rather than being handed an
    empty one. A target that IS an image and cannot be captured honestly raises: an undecoded image
    (`natural_width == 0`) would otherwise attach bytes the browser itself could not render, and an
    image whose response body was never seen would leave a finding pointing at nothing.
    """
    keys = list(dict.fromkeys(tuple(target) for target in targets))
    if not keys:
        return {}
    nodes: list[Any] = page.evaluate(_IMAGE_NODES_JS, [list(key) for key in keys])
    captured: dict[tuple[str, ...], CapturedImage] = {}
    for key, node in zip(keys, nodes, strict=True):
        if node is None:
            continue
        src = str(node["src"])
        if not node["natural_width"] or not node["natural_height"]:
            raise ImageCaptureError(
                f"{key} decoded to natural_width 0 at {src!r} — the picture never arrived. Capturing "
                "it anyway would attach bytes the browser itself could not render, behind a finding "
                "that looks complete."
            )
        data = recorder.body_for(src)
        if data is None:
            raise ImageCaptureError(
                f"{key} rendered {src!r}, but no response body was recorded for it. The bytes are "
                "taken from the response the browser fetched, so a picture with no response — a "
                "`data:` URI, a blob, a cache hit the recorder never saw — cannot be captured here."
            )
        captured[key] = CapturedImage(
            ref=hashlib.sha256(data).hexdigest(),
            media_type=served_content_type(data, src),
            data=data,
            natural_width=int(node["natural_width"]),
            natural_height=int(node["natural_height"]),
            src=src,
        )
    return captured


class ImageStore:
    """Captured image bytes on disk, each file named by its own sha256.

    Content addressing does three jobs at once: identical pictures under different names are stored
    once (four of the current pool's seven findings are the same photograph), the reference on a
    `Finding` is enough to fetch the bytes without a side table, and the store is self-checksumming
    — `read` recomputes the digest and refuses a file that has stopped matching its name.

    **No extension, deliberately.** The format is sniffed from the bytes on the way out
    (`media_type`); a name that claimed one would be the same lie the derived image set's `.png`
    naming exists to demonstrate.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, image: CapturedImage) -> str:
        """Store the bytes and return their reference. Idempotent — the same picture writes once."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / image.ref
        if not path.is_file():
            path.write_bytes(image.data)
        return image.ref

    def read(self, ref: str) -> bytes:
        """The bytes for `ref`, refused unless they still hash to it."""
        path = self.root / ref
        if not path.is_file():
            raise ImageCaptureError(f"no captured image {ref!r} in {self.root} — the reference points at nothing")
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != ref:
            raise ImageCaptureError(
                f"captured image {ref!r} now hashes to {actual!r} — the store is content-addressed, so a "
                "file that no longer matches its name is a picture that changed under a frozen reference"
            )
        return data

    def media_type(self, ref: str) -> str:
        """The media type to declare for `ref`, read from the bytes and never from a name."""
        return served_content_type(self.read(ref))

    def refs(self) -> list[str]:
        """Every reference held, sorted — the store's own inventory, not a manifest to be trusted."""
        return sorted(p.name for p in self.root.iterdir() if p.is_file()) if self.root.is_dir() else []
