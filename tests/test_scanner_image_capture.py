"""Guard for the image channel: the picture a node rendered, carried to the finding as a reference.

Three properties this holds down, each of which has a way of being wrong that nothing else notices:

* **The bytes are the asset's own.** A capture that re-encoded — a canvas `toDataURL`, an element
  screenshot — would still produce a plausible image, and a digest over it would still be stable,
  and it would no longer be comparable with the digest of the file it came from. The pool's frozen
  permutation is authored over image identities, so that comparison is the whole check.
* **The media type comes from the bytes.** The derived image set names JPEG assets `.png` on
  purpose. An implementation that read the extension would hand a multimodal model
  `data:image/png;base64,<JPEG>` and be wrong in the one place nothing downstream can detect.
* **The id does not move.** `Finding.image_ref` rides outside `Finding.id` deliberately; if it ever
  entered the hash, every frozen per-case comparison in this repo would silently stop pairing.

The two refusals are exercised on real failures rather than asserted in prose: an image that never
arrived (`natural_width == 0` — what a broken path, a 404 and an undecodable body all look like) and
an image the browser never fetched over the wire (a `data:` URI, which decodes fine and emits no
response at all). No model call anywhere.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from clearway.eval.act_image_gold import assets_for
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE
from clearway.normalizer import normalize
from clearway.scanner.capture import ImageCaptureError, ImageStore
from clearway.scanner.scan import scan

# The bread: a JPEG, deliberately named `.png` by the ablation, and the pool's only image that
# appears once — so a capture that silently substituted another picture would be visible here.
BREAD_CASE = ACT_IMAGE_OPAQUE / "html" / "607ad4964aa69e78a663cf993a28cedd6a1dc39e.html"
BREAD_ASSET = ACT_IMAGE_OPAQUE / "assets" / "img" / "c.png"

# A 1x1 PNG, literal so the test states its own input.
_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PAGE = '<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><img src="{src}" alt="a"></body></html>'


def _page(tmp_path: Path, src: str) -> Path:
    (tmp_path / "html").mkdir(exist_ok=True)
    (tmp_path / "assets").mkdir(exist_ok=True)
    case = tmp_path / "html" / "case.html"
    case.write_text(_PAGE.format(src=src), encoding="utf-8")
    return case


def test_the_captured_bytes_are_the_assets_own_bytes(tmp_path: Path) -> None:
    """Not a re-encoding of the same picture: the digest is the digest of the file on disk."""
    store = ImageStore(tmp_path / "captured")
    findings = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE), store))

    image_finding = next(f for f in findings if f.rule_id == "image-alt")
    assert image_finding.image_ref == hashlib.sha256(BREAD_ASSET.read_bytes()).hexdigest()
    assert store.read(image_finding.image_ref) == BREAD_ASSET.read_bytes()


def test_the_media_type_is_sniffed_from_the_bytes_not_from_the_png_name(tmp_path: Path) -> None:
    """The trap the derived set exists to demonstrate: `/img/c.png` holds JPEG bytes."""
    store = ImageStore(tmp_path / "captured")
    findings = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE), store))

    ref = next(f.image_ref for f in findings if f.rule_id == "image-alt")
    assert ref is not None
    assert BREAD_ASSET.name.endswith(".png")  # the name says PNG …
    assert store.media_type(ref) == "image/jpeg"  # … and the bytes are what gets declared


def test_capture_is_opt_in_and_leaves_the_ids_where_they_were(tmp_path: Path) -> None:
    """No store, no capture — and the same finding ids either way, because `image_ref` is
    deliberately outside `Finding.id`. If it ever entered the hash, every frozen per-case
    comparison in this repo would stop pairing and nothing would say so."""
    with_capture = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE), ImageStore(tmp_path / "captured")))
    without_capture = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE)))

    assert all(f.image_ref is None for f in without_capture)
    assert any(f.image_ref for f in with_capture)
    assert [f.id for f in with_capture] == [f.id for f in without_capture]


def test_a_finding_on_a_node_that_is_not_an_image_carries_no_reference(tmp_path: Path) -> None:
    """`document-title` fires on the page, not on a picture — absent, never a blank reference."""
    store = ImageStore(tmp_path / "captured")
    findings = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE), store))

    assert next(f for f in findings if f.rule_id == "document-title").image_ref is None
    assert {f.rule_id for f in findings if f.image_ref} == {"region", "image-alt"}  # both target the <img>


def test_an_image_that_never_arrived_refuses_to_be_captured(tmp_path: Path) -> None:
    """The failure with no finding-level trace: the same finding is minted either way, so the only
    place it can be caught is here."""
    case = _page(tmp_path, "/img/does-not-exist.png")
    with pytest.raises(ImageCaptureError, match="natural_width 0"):
        scan(str(case), tmp_path / "assets", ImageStore(tmp_path / "captured"))


def test_an_image_the_browser_never_fetched_refuses_to_be_captured(tmp_path: Path) -> None:
    """A `data:` URI decodes perfectly and emits no response, so there are no wire bytes to take.
    Refused loudly rather than left as a finding pointing at nothing."""
    case = _page(tmp_path, _PNG_DATA_URI)
    with pytest.raises(ImageCaptureError, match="no response body was recorded"):
        scan(str(case), tmp_path / "assets", ImageStore(tmp_path / "captured"))


def test_the_store_refuses_bytes_that_stopped_matching_their_name(tmp_path: Path) -> None:
    """Content addressing is the checksum, so it has to be enforced on the way out, not assumed."""
    store = ImageStore(tmp_path / "captured")
    findings = normalize(scan(str(BREAD_CASE), assets_for(BREAD_CASE), store))
    ref = next(f.image_ref for f in findings if f.rule_id == "image-alt")
    assert ref is not None

    (store.root / ref).write_bytes(b"a different picture entirely")
    with pytest.raises(ImageCaptureError, match="no longer matches its name"):
        store.read(ref)
    with pytest.raises(ImageCaptureError, match="points at nothing"):
        store.read("0" * 64)
