"""Guard for the frozen capture set: the pictures the pool rendered, and the permutation on bytes.

Both of this ticket's acceptances are discharged here against the artifact that shipped, and both
gates are additionally shown to **fire** — a check that has never failed is a check nobody has
tested. The multiplicity gate is fed a pool that lost an image and a pool whose renaming collided;
the derangement gate is fed a row that hands a case its own bytes back.

The permutation is transcribed independently below rather than read from the file it is checking.
That is deliberate and it is the same habit the derived set uses: the frozen mapping is a
pre-registration, so the thing worth testing is that it still says what the specification says, not
that a file equals itself.

No model call anywhere.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clearway.eval.image_capture import (
    ARTIFACT,
    EXPECTED_MULTIPLICITY,
    STORE_DIR,
    capture_pool,
    derangement_failures,
    load_capture,
    multiplicity_failures,
)
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE, POOL_IMAGES
from clearway.scanner.capture import ImageStore

FROZEN = json.loads(ARTIFACT.read_text())
STORE = ImageStore(ACT_IMAGE_OPAQUE / STORE_DIR)

# The specification's own table, transcribed by hand: case → (the picture it shows, the picture the
# manipulation attaches instead). Four cases show one photograph, two the logo, one the bread.
SPEC_PERMUTATION = {
    "be6b29e220d6afbd827625c602ec49027e73fdf1": ("w3c-logo", "bread"),
    "530266c6116fcfad12561e9e1a407fa0a0da3435": ("w3c-logo", "nyhavn"),
    "cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e": ("nyhavn", "w3c-logo"),
    "607ad4964aa69e78a663cf993a28cedd6a1dc39e": ("bread", "w3c-logo"),
    "1ff696703e7e7393a5d05cdcd3229cb050594998": ("nyhavn", "bread"),
    "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4": ("nyhavn", "bread"),
    "a2333ec76e676624212dcd616ed11ae576ab775e": ("nyhavn", "w3c-logo"),
}


def test_acceptance_1_the_capture_set_is_three_images_at_four_two_one() -> None:
    """One check covering the interceptor, the ablation's renaming and the permutation's premise."""
    refs = [capture["image_ref"] for capture in FROZEN["captures"]]

    assert len(refs) == 7
    assert multiplicity_failures(refs) == []
    assert FROZEN["distinct_images"] == 3
    assert tuple(FROZEN["multiplicity"]) == EXPECTED_MULTIPLICITY == (4, 2, 1)


def test_the_multiplicity_gate_fires() -> None:
    """Both ways the set can break, and they are reported as the different faults they are: an image
    that stopped decoding leaves too few pictures, while a renaming that redistributed them leaves
    three pictures in the wrong proportions."""
    lost_an_image = ["a"] * 5 + ["b"] * 2
    redistributed = ["a"] * 3 + ["b"] * 3 + ["c"]

    assert multiplicity_failures(lost_an_image) == [
        "2 distinct captured images, expected 3 — an image that stopped decoding, or an ablation "
        "whose renaming collided",
        "multiplicity (5, 2), expected (4, 2, 1)",
    ]
    assert multiplicity_failures(redistributed) == ["multiplicity (3, 3, 1), expected (4, 2, 1)"]


def test_acceptance_2_the_resolved_permutation_is_a_derangement_on_bytes() -> None:
    """Label-level derangement is not enough: four of the seven cases are the same photograph."""
    rows = FROZEN["resolved_permutation"]

    assert len(rows) == 7
    assert derangement_failures(rows) == []
    assert all(row["with_image_ref"] != row["mismatched_image_ref"] for row in rows)


def test_the_derangement_gate_fires() -> None:
    doctored = [{"act_testcase_id": "x", "with_image_ref": "ref", "mismatched_image_ref": "ref"}]

    assert derangement_failures(doctored) == [
        "x would be shown its own bytes (ref…) — the resolved mapping is not a derangement"
    ]


def test_the_frozen_mapping_still_says_what_the_specification_says() -> None:
    """Resolved to bytes, and checked against an independent transcription of the pre-registration."""
    resolved = {row["act_testcase_id"]: row for row in FROZEN["resolved_permutation"]}

    assert set(resolved) == set(SPEC_PERMUTATION)
    for tid, (true_image, mismatched) in SPEC_PERMUTATION.items():
        assert (resolved[tid]["true_image"], resolved[tid]["mismatched_image"]) == (true_image, mismatched)
        assert resolved[tid]["with_image_ref"] == POOL_IMAGES[true_image]
        assert resolved[tid]["mismatched_image_ref"] == POOL_IMAGES[mismatched]


def test_the_capture_is_keyed_by_finding_id_because_target_is_not_unique() -> None:
    """Every pool case's finding sits on the selector `img`; only the ids tell them apart."""
    captures = FROZEN["captures"]

    assert {capture["target"] for capture in captures} == {"img"}
    assert len({capture["finding_id"] for capture in captures}) == 7
    assert [row["finding_id"] for row in FROZEN["resolved_permutation"]] == [c["finding_id"] for c in captures]


def test_the_stored_bytes_are_the_vendored_assets_own_bytes() -> None:
    """Not a re-encoding of the same picture — the captures hash to the asset files themselves."""
    assets = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(STORE.root.parent.glob("assets/img/*.png"))
    }

    assert sorted(assets.values()) == sorted(POOL_IMAGES.values())
    assert sorted(STORE.refs()) == sorted(POOL_IMAGES.values())


def test_the_store_is_its_own_checksum_and_declares_types_from_the_bytes() -> None:
    """Each file's name IS its digest, and two of the three `.png` names hold JPEG bytes."""
    for ref in STORE.refs():
        assert hashlib.sha256(STORE.read(ref)).hexdigest() == ref

    types = {STORE.media_type(ref) for ref in STORE.refs()}
    assert types == {"image/png", "image/jpeg"}
    assert STORE.media_type(POOL_IMAGES["nyhavn"]) == "image/jpeg"
    assert STORE.media_type(POOL_IMAGES["bread"]) == "image/jpeg"
    assert STORE.media_type(POOL_IMAGES["w3c-logo"]) == "image/png"


def test_loading_the_capture_verifies_every_reference_against_the_store() -> None:
    loaded = load_capture()

    assert len(loaded) == 7
    assert set(loaded.values()) == set(POOL_IMAGES.values())
    assert loaded == {c["finding_id"]: c["image_ref"] for c in FROZEN["captures"]}


def test_recapturing_the_pool_reproduces_the_frozen_artifact(tmp_path: Path) -> None:
    """The capture is a measurement, so it has to come out the same twice — including the ids, which
    would move if `image_ref` had ever leaked into the finding hash."""
    rebuilt = capture_pool(root=tmp_path)

    assert rebuilt == FROZEN
    assert sorted(ImageStore(tmp_path / STORE_DIR).refs()) == sorted(STORE.refs())
