"""Guard for the opaque derived set and its frozen permutation.

Three things are asserted here that the builder cannot assert about itself.

**The ablation gate, run on the minted prompt.** The check that matters is not what the derived file
looks like but what reaches the drafter, so the findings are minted for real and the gate is run over
`finding.html`. It is also shown to *fire*: a filename-only rewrite and a per-case naming scheme are
both put through it, because a gate that passes everything and a gate that passes a good ablation are
indistinguishable from one green test.

**The exclusion rule, re-run on the ablated set.** The originals' twin pairs were removed before the
pool existed; the question here is whether the ablation *created* a new one, and byte-identity is
blind to it — a per-case index would leave two informationally identical prompts one digit apart. So
the same prompt-level check runs again on what was actually produced, and is shown to fire on a
doctored set.

**That nothing else moved.** The gold carries over only because the `alt` text and the pixels are
untouched, so that is checked attribute by attribute rather than asserted in a note.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from clearway.eval import act_image_gold, image_opaque
from clearway.eval.image_reachability import ACT_IMAGE
from clearway.eval.run_scope import OutOfScope
from clearway.schemas.models import Conformance, Finding

LEAKY = json.loads(act_image_gold.MANIFEST.read_text())
MANIFEST = json.loads(image_opaque.MANIFEST.read_text())
PERMUTATION = json.loads(image_opaque.PERMUTATION.read_text())
CASES = MANIFEST["cases"]

BANNED = image_opaque.gold_relevant_tokens(image_opaque.assign_letters(LEAKY["cases"]))

# A rewrite that renames the file and keeps the directory — the ablation this ticket rejects, kept
# here as the gate's negative control.
FILENAME_ONLY = (
    '<img src="/test-assets/image-filename-as-accessible-name-9eb3f6/a.png"'
    ' srcset="/test-assets/image-filename-as-accessible-name-9eb3f6/b.png 1.5x"'
    ' alt="Nyhavn" />'
)
# A scheme that numbers per case rather than per image — the one that would defeat the twin rule.
PER_CASE = '<img src="/img/case-1ff696703e.png" alt="Nyhavn" />'


@pytest.fixture(scope="module")
def minted() -> list[tuple[Finding, Any]]:
    """The seven opaque findings as the drafter would meet them — minted for real, with the derived
    set's own assets served and every render asserted by the loader."""
    return act_image_gold.load_image_gold_pairs(image_opaque.MANIFEST)


@pytest.fixture(scope="module")
def records() -> dict[str, list[dict]]:
    """The same seven findings in the shape the twin check reads, through the builder's own function."""
    return image_opaque._minted_records(image_opaque.ACT_IMAGE_OPAQUE, CASES)


def test_the_derived_set_is_the_pool_and_nothing_else() -> None:
    assert [c["act_testcase_id"] for c in CASES] == [c["act_testcase_id"] for c in LEAKY["cases"]]
    assert len(CASES) == 7
    assert MANIFEST["set_id"] == "act-image-opaque@1" != LEAKY["set_id"]
    assert MANIFEST["derived_from"] == {"set_id": LEAKY["set_id"], "manifest": act_image_gold.MANIFEST.name}
    assert MANIFEST["export_sha256"] == LEAKY["export_sha256"]


def test_the_gold_is_carried_over_unaltered() -> None:
    """The ablation touches no `alt` and no pixel, so both sides of the 1.1.1 question are unmoved and
    the labels are the vendored set's own — copied, never re-derived from the ablated page."""
    for opaque, leaky in zip(CASES, LEAKY["cases"], strict=True):
        for field in ("expected", "gold_conformance", "gold_success_criteria", "rule_name", "act_rule_id"):
            assert opaque[field] == leaky[field], (opaque["act_testcase_id"], field)
        assert opaque["derived_from"] == f"{ACT_IMAGE.name}/{leaky['path']}"


def test_the_naming_scheme_is_per_asset_not_per_case() -> None:
    """One name per DISTINCT IMAGE — which is what keeps two informationally identical prompts
    byte-identical instead of one digit apart — at the measured multiplicity 4 / 2 / 1."""
    names = [case["image_asset"] for case in CASES]
    assert set(names) == {"/img/a.png", "/img/b.png", "/img/c.png"}
    assert sorted((names.count(n) for n in set(names)), reverse=True) == [4, 2, 1]
    assert MANIFEST["ablation"]["letters"] == {"/img/a.png": "w3c-logo", "/img/b.png": "nyhavn", "/img/c.png": "bread"}
    # The two W3C cases and the four Nyhavn cases each share one name, per asset, never per case.
    by_image = {
        label: {c["act_testcase_id"] for c in CASES if c["image"] == label} for label in image_opaque.POOL_IMAGES
    }
    assert {label: len(ids) for label, ids in by_image.items()} == {"w3c-logo": 2, "nyhavn": 4, "bread": 1}


def test_the_assets_are_the_vendored_bytes_under_a_neutral_name() -> None:
    """Renamed, never re-encoded: the pixels the model will be shown are the pixels ACT published,
    and two of the three carry a `.png` name over JPEG bytes deliberately."""
    for label, digest in image_opaque.POOL_IMAGES.items():
        asset = image_opaque.ASSETS / PERMUTATION["images"][label]["opaque_asset"].lstrip("/")
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == digest, label
    assert image_opaque.ASSETS.joinpath("img/b.png").read_bytes()[:3] == b"\xff\xd8\xff"  # JPEG, named .png
    assert image_opaque.ASSETS.joinpath("img/a.png").read_bytes()[:4] == b"\x89PNG"


def test_nothing_but_the_paths_changed() -> None:
    """Blank out every URL on both sides and the two files are the same bytes — so the `alt`, the
    `srcset` descriptors, the `lang`, the doctype and every tab and newline are untouched. Exact,
    where an end-to-end round trip could not be: four names collapse onto one image, so restoring a
    path is ambiguous by design."""
    for case in CASES:
        source = (ACT_IMAGE / f"html/{case['act_testcase_id']}.html").read_text(encoding="utf-8")
        derived = (image_opaque.ACT_IMAGE_OPAQUE / case["path"]).read_text(encoding="utf-8")
        assert re.sub(r"/img/[a-z]\.png", "<PATH>", derived) == image_opaque._VENDORED_PATH.sub("<PATH>", source)

        before, after = image_opaque.image_attributes(source), image_opaque.image_attributes(derived)
        assert [set(image) for image in before] == [set(image) for image in after]
        for original, ablated in zip(before, after, strict=True):
            for name, value in original.items():
                if name not in ("src", "srcset"):
                    assert ablated[name] == value, (case["act_testcase_id"], name)


def test_the_ablation_gate_passes_on_every_minted_prompt(minted: list[tuple[Finding, Any]]) -> None:
    """ACCEPTANCE 1, on the thing that actually reaches the model: no gold-relevant token survives in
    `src`, `srcset` or `sizes`, and every URL is exactly the pinned scheme."""
    assert len(minted) == 7
    for finding, _ in minted:
        assert image_opaque.ablation_failures(finding.html, BANNED) == [], finding.html
        assert "/test-assets/" not in finding.html


def test_the_banned_token_set_is_the_cues_that_decide_cases() -> None:
    """The gate is only as good as what it bans, so what it bans is asserted: the two `srcset` tokens
    a filename-only rewrite leaves behind, and the directory that spells out the deprecated rule's own
    deciding criterion. `img` and `png` are excluded — they name no image and are the same on all seven."""
    assert {"nyhavn", "paris", "pain", "filename", "accessible", "name", "9eb3f6", "test-assets"} <= BANNED
    assert "94251e110d24a4c2b6e6ce76e7203374" in BANNED
    assert not {"img", "png"} & BANNED


def test_the_ablation_gate_fires_on_the_rewrites_this_ticket_rejects() -> None:
    """A gate that never fails is not a gate. A filename-only rewrite keeps the directory, and a
    per-case index invents a distinguishing token — both are refused, for different reasons."""
    filename_only = image_opaque.ablation_failures(FILENAME_ONLY, BANNED)
    assert any("filename" in failure for failure in filename_only)
    assert any("not the pinned scheme" in failure for failure in filename_only)

    per_case = image_opaque.ablation_failures(PER_CASE, BANNED)
    assert [f for f in per_case if "not the pinned scheme" in f]


def test_the_exclusion_rule_re_run_on_the_ablated_set_finds_no_new_twin(records: dict[str, list[dict]]) -> None:
    """ACCEPTANCE 2. The pool's own twins were removed before the pool existed; this asks whether the
    ablation *created* one. It did not: all seven minted prompts stay distinct, and the only pair whose
    accessible name the ablation leaves matching — the two `Nyhavn` cases, now both `/img/b.png` —
    shares the gold `passed`, so it is not the one-input-two-answers shape the rule excludes."""
    assert image_opaque.twin_failures(CASES, records) == {}
    assert len({row["prompt_key"] for rows in records.values() for row in rows}) == 7

    alts = [row["alt"] for row in PERMUTATION["mapping"]]
    repeated = {alt for alt in alts if alts.count(alt) > 1}
    assert repeated == {"Nyhavn"}
    nyhavn = [case for case, alt in zip(CASES, alts, strict=True) if alt == "Nyhavn"]
    assert {case["expected"] for case in nyhavn} == {"passed"}


def test_the_exclusion_rule_would_fire_if_the_ablation_had_created_a_twin(records: dict[str, list[dict]]) -> None:
    """The same check, shown to work rather than assumed: give a `failed` case the minted prompt of a
    `passed` one — the collision a per-case naming scheme could plausibly produce — and both halves are
    named, which is what excluding a pair means here."""
    doctored = {
        **records,
        "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4": records["cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e"],
    }
    assert set(image_opaque.twin_failures(CASES, doctored)) == {
        "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4",
        "cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e",
    }


def test_the_permutation_is_the_pre_registered_table() -> None:
    """A second, independent transcription of the pre-registration — `(case, alt, true → attached)` as
    the ticket writes it. Redundant on purpose: everything else about the mapping is derived or
    asserted structurally, so a row copied wrong would satisfy the derangement check and still be the
    wrong experiment, and nothing but a restatement can catch that."""
    assert [
        (row["act_testcase_id"][:10], row["alt"], row["true_image"], row["mismatched_image"], row["live"])
        for row in PERMUTATION["mapping"]
    ] == [
        ("be6b29e220", "W3C", "w3c-logo", "bread", True),
        ("530266c611", "ERCIM", "w3c-logo", "nyhavn", False),
        ("cfd1636ab4", "Nyhavn", "nyhavn", "w3c-logo", True),
        ("607ad4964a", "pain", "bread", "w3c-logo", True),
        ("1ff696703e", "Nyhavn", "nyhavn", "bread", True),
        ("f7406b89f8", "Paris", "nyhavn", "bread", False),
        ("a2333ec76e", "94251e110d24a4c2b6e6ce76e7203374", "nyhavn", "w3c-logo", False),
    ]


def test_the_permutation_is_frozen_over_testcase_ids_and_is_a_derangement() -> None:
    """The pre-registration. Every case is shown an image that is not its own, over the full 40-character
    ids, and the frozen file says exactly what the module's authored mapping says."""
    mapping = {row["act_testcase_id"]: row["mismatched_image"] for row in PERMUTATION["mapping"]}
    assert mapping == image_opaque.MISMATCHED_IMAGE
    assert all(len(tid) == 40 for tid in mapping)
    assert {c["act_testcase_id"] for c in CASES} == set(mapping)
    for row in PERMUTATION["mapping"]:
        assert row["mismatched_image"] != row["true_image"], row["act_testcase_id"]
        assert row["mismatched_image"] in image_opaque.POOL_IMAGES
        assert row["true_image"] == next(c["image"] for c in CASES if c["act_testcase_id"] == row["act_testcase_id"])


def test_the_permutation_records_which_cells_can_move_without_narrowing_the_statistic() -> None:
    """`live` is description, not a filter: four cells can move, and the three that cannot include the
    specificity control that must not — a disagreement there means something other than perception moved."""
    live = {row["act_testcase_id"][:10] for row in PERMUTATION["mapping"] if row["live"]}
    assert live == {"be6b29e220", "cfd1636ab4", "1ff696703e", "607ad4964a"}
    assert PERMUTATION["live_cells"] == 4 and len(PERMUTATION["mapping"]) == 7
    control = next(row for row in PERMUTATION["mapping"] if row["act_testcase_id"].startswith("a2333ec76e"))
    assert not control["live"] and "specificity control" in control["note"]


def test_the_permutation_names_three_images_at_multiplicity_four_two_one() -> None:
    """The premise the mismatched condition rests on, checked at the identity level here and again on
    the captured bytes later: three distinct images, and the four Nyhavn cases really are one picture."""
    images = PERMUTATION["images"]
    assert len({entry["sha256"] for entry in images.values()}) == 3
    assert sorted((entry["cases_showing_it"] for entry in images.values()), reverse=True) == [4, 2, 1]


def test_the_derived_bytes_are_checksummed_and_intact() -> None:
    """One line per derived byte — and the listing covers every derived file, so an unlisted page
    cannot ride along unpinned."""
    listed = {}
    for line in image_opaque.CHECKSUMS.read_text().splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    on_disk = {
        p.relative_to(image_opaque.ACT_IMAGE_OPAQUE).as_posix()
        for p in image_opaque.ACT_IMAGE_OPAQUE.rglob("*")
        if p.is_file() and p.suffix in (".html", ".png")
    }
    assert set(listed) == on_disk and len(listed) == 10
    for name, digest in listed.items():
        assert hashlib.sha256((image_opaque.ACT_IMAGE_OPAQUE / name).read_bytes()).hexdigest() == digest, name


def test_the_derivation_is_deterministic(tmp_path: Path) -> None:
    """Same inputs, same bytes: the pages, the assets and the permutation are re-derived from the
    vendored set into a scratch directory and compared byte for byte with what is committed."""
    opaque_url_for = image_opaque.assign_letters(LEAKY["cases"])
    for case in LEAKY["cases"]:
        source = (ACT_IMAGE / case["path"]).read_text(encoding="utf-8")
        rebuilt = image_opaque.ablate(source, opaque_url_for)
        assert rebuilt == (image_opaque.ACT_IMAGE_OPAQUE / case["path"]).read_text(encoding="utf-8")
    rebuilt_permutation = image_opaque.permutation(LEAKY["cases"], opaque_url_for)
    assert json.dumps(rebuilt_permutation, indent=2, ensure_ascii=False) + "\n" == image_opaque.PERMUTATION.read_text()
    (tmp_path / "checksums").write_text(image_opaque._checksums(image_opaque.ACT_IMAGE_OPAQUE))
    assert (tmp_path / "checksums").read_text() == image_opaque.CHECKSUMS.read_text()


def test_the_loader_yields_the_pools_gold_over_the_ablated_pages(minted: list[tuple[Finding, Any]]) -> None:
    """The live check: seven findings, each over an image that actually arrived (the loader raises
    otherwise), carrying the vendored set's labels — with the ablated page's own finding ids."""
    assert len({finding.id for finding, _ in minted}) == 7
    leaky_ids = {finding.id for finding, _ in act_image_gold.load_image_gold_pairs()}
    assert not leaky_ids & {finding.id for finding, _ in minted}
    for (finding, gold), case in zip(minted, CASES, strict=True):
        assert finding.rule_id == "image-alt" and finding.html.startswith("<img")
        assert gold.act_testcase_id == case["act_testcase_id"]
        assert gold.gold_conformance is Conformance(case["gold_conformance"])
        assert gold.source == "w3c-act"


def test_the_derived_set_inherits_the_asset_guarantee_by_construction() -> None:
    """The asset tree is derived from where a case lives, so the derived set gets the same protection
    as the vendored one with no second argument to forget — and a page that is not an image-set case
    is refused rather than scanned over pictures that cannot arrive."""
    case = image_opaque.ACT_IMAGE_OPAQUE / CASES[0]["path"]
    assert act_image_gold.assets_for(case) == image_opaque.ASSETS
    with pytest.raises(OutOfScope):
        act_image_gold.assets_for(ACT_IMAGE / "image_reachability.json")
