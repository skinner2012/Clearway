"""Guard for the vendored ACT image set and the reachability artifact derived from it.

The pool this artifact produces is what every later image measurement is defined over, so the ids are
pinned here as an expectation rather than read back out of the artifact — a change in what the
pipeline can reach then shows up as a failing test, not as a quietly different denominator.

Layers, cheapest first: (1) the vendored bytes match their pinned sha256; (2) the artifact reproduces
the pool and the twin exclusions exactly; (3) the pool is re-derived from the recorded cases by the
same functions the builder used, so the derivation lives in code and not in the JSON; (4) a sampled
case is re-scanned and re-rendered for real. The full 51-case rebuild is
`uv run python -m clearway.eval.image_reachability`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clearway.eval import image_reachability
from clearway.eval.image_reachability import ACT_IMAGE, ARTIFACT, ASSETS, HTML

ARTEFACT = json.loads(ARTIFACT.read_text())
CASES = ARTEFACT["cases"]
BENCHMARK = Path(__file__).resolve().parent.parent / "benchmark"

# The pool, pinned. Two cases from the live rule and five from the deprecated one; the four that
# survive nothing else are named in TWINS below.
POOL = (
    "be6b29e220d6afbd827625c602ec49027e73fdf1",  # qt1vmo passed — W3C logo, alt "W3C"
    "530266c6116fcfad12561e9e1a407fa0a0da3435",  # qt1vmo failed — W3C logo, alt "ERCIM"
    "cfd1636ab41c1418d1ad510eb9802c31fb2c5c5e",  # 9eb3f6 passed — Nyhavn, alt "Nyhavn"
    "607ad4964aa69e78a663cf993a28cedd6a1dc39e",  # 9eb3f6 passed — bread, alt "pain"
    "1ff696703e7e7393a5d05cdcd3229cb050594998",  # 9eb3f6 passed — Nyhavn, alt "Nyhavn", with a srcset
    "f7406b89f8e6769c01da5c305e3e6c921fd7c1e4",  # 9eb3f6 failed — Nyhavn, alt "Paris"
    "a2333ec76e676624212dcd616ed11ae576ab775e",  # 9eb3f6 failed — Nyhavn, alt a hex digest
)

# The two prompt-level twin pairs: same minted prompt, opposite ACT outcome. Both halves are listed,
# because both halves are excluded.
TWINS = {
    "499be2117059dba5f38526df06b711d0125eccd7": ["556be1533c3f4388dc6c8dd1c8bce9c0e9c4f06c"],
    "556be1533c3f4388dc6c8dd1c8bce9c0e9c4f06c": ["499be2117059dba5f38526df06b711d0125eccd7"],
    "28d908a951edb6fe7768d69b10460c7cfff251b1": ["f636f815cba63087a142086b3b9791fe464300cc"],
    "f636f815cba63087a142086b3b9791fe464300cc": ["28d908a951edb6fe7768d69b10460c7cfff251b1"],
}

# Why each usable case that mints nothing mints nothing, as a count per kind of reason.
UNREACHABLE = {"svg": 4, "canvas": 4, "input[type=image]": 2, "aria-hidden": 2}


def _case(case_id: str) -> dict:
    return next(case for case in CASES if case["act_testcase_id"] == case_id)


def test_vendored_files_match_pinned_checksums() -> None:
    """The freeze the whole set rests on: 51 case files + 10 assets + the NOTICE + the fetch receipt."""
    checked = 0
    for line in (ACT_IMAGE / "checksums.sha256").read_text().splitlines():
        want, rel = line.split(maxsplit=1)
        assert hashlib.sha256((ACT_IMAGE / rel).read_bytes()).hexdigest() == want, rel
        checked += 1
    assert checked == 63
    assert len(list(HTML.glob("*.html"))) == 51


def test_the_artifact_reproduces_the_pool_and_the_twin_exclusions() -> None:
    assert tuple(ARTEFACT["pool"]) == POOL
    assert ARTEFACT["twin_exclusions"] == TWINS
    assert ARTEFACT["totals"] == {
        "published": 51,
        "usable": 27,
        "minting": 15,
        "twin_excluded": 4,
        "retracted_excluded": 4,
        "pool": 7,
    }
    # 7 of 27 candidates — the share the channel can reach, stated wherever the pool is
    assert ARTEFACT["totals"]["pool"] / ARTEFACT["totals"]["usable"] < 0.27


def test_the_pool_is_re_derived_from_the_recorded_cases() -> None:
    """The derivation is code, not a hand-maintained list in the JSON: re-running it over the
    artifact's own case records has to give back the frozen pool and the frozen exclusions."""
    usable = [case for case in CASES if case["usable"]]
    assert image_reachability.twin_exclusions(usable) == TWINS
    assert image_reachability.pool(usable) == list(POOL)


def test_prompt_level_twins_are_invisible_to_the_file_level_check() -> None:
    """These pairs share a prompt but not a file, which is exactly why hashing fixture bytes
    (`act_gold.contradictory_gold_twins`) cannot find them and this check is the stronger one."""
    for case_id, counterparts in TWINS.items():
        mine = hashlib.sha256((ACT_IMAGE / _case(case_id)["path"]).read_bytes()).hexdigest()
        for other in counterparts:
            assert hashlib.sha256((ACT_IMAGE / _case(other)["path"]).read_bytes()).hexdigest() != mine
            assert _case(case_id)["expected"] != _case(other)["expected"]
            assert _case(case_id)["minted"][0]["prompt_key"] == _case(other)["minted"][0]["prompt_key"]


def test_every_pool_case_records_what_the_drafter_will_be_shown() -> None:
    for case_id in POOL:
        case = _case(case_id)
        assert case["usable"] and case["unreachable_reason"] is None
        assert len(case["minted"]) == 1, case_id
        minted = case["minted"][0]
        assert (minted["axe_rule"], minted["bucket"]) == ("image-alt", "passes")
        assert minted["html"].startswith("<img"), minted["html"]
        assert minted["help"] and minted["prompt_key"]
        assert isinstance(minted["deciding_fact_in_snippet"], bool)
        assert minted["deciding_fact_note"]


def test_only_the_hex_digest_case_is_decided_by_the_snippet_alone() -> None:
    """Six of the seven are image-decided; the seventh is named by a hex digest, which describes
    nothing whatever the image shows. It stays in the pool as a within-experiment control."""
    decided_by_text = [c for c in POOL if _case(c)["minted"][0]["deciding_fact_in_snippet"]]
    assert decided_by_text == ["a2333ec76e676624212dcd616ed11ae576ab775e"]
    assert _case(decided_by_text[0])["minted"][0]["accessible_name_form"] == "hex-digest"


def test_the_deciding_fact_flag_is_a_rule_over_name_forms() -> None:
    assert image_reachability.accessible_name_form("94251e110d24a4c2b6e6ce76e7203374") == "hex-digest"
    assert image_reachability.accessible_name_form("nyhavn.jpeg") == "filename"
    assert image_reachability.accessible_name_form("Nyhavn") == "phrase"
    assert image_reachability.accessible_name_form("") == "empty"
    assert image_reachability.accessible_name_form(None) == "absent"
    # only the digest form settles the call without seeing the image
    assert [form for form, (settles, _) in image_reachability._NAME_FORM_NOTES.items() if settles] == ["hex-digest"]


def test_every_pool_case_rendered_its_image() -> None:
    """The image rules' gold presumes the image rendered, so a pool case whose picture never arrived
    is invalid rather than merely unlucky. Four of these are served `application/octet-stream`
    upstream and decode only because the interceptor repairs the type."""
    for case_id in POOL:
        images = _case(case_id)["rendered_images"]
        assert images, case_id
        assert all(image["natural_width"] > 0 and image["natural_height"] > 0 for image in images), case_id


def test_unreachable_cases_are_recorded_with_a_reason() -> None:
    """The ten matcher-limited cases are not a scoping choice — axe's `image-alt` selector is `img`,
    so an `<svg>`, a `<canvas>` and an `<input type=image>` case cannot mint whatever the drafter is."""
    reasons = [c["unreachable_reason"] for c in CASES if c["usable"] and not c["minted"]]
    assert len(reasons) == 12 and all(reasons)
    for kind, count in UNREACHABLE.items():
        assert sum(1 for reason in reasons if kind in reason) == count, kind


def test_the_retraction_is_recorded_with_its_ground_and_costs_four_minting_cases() -> None:
    assert set(ARTEFACT["retracted_rules"]) == {"e88epe"}
    assert "perfectly correlated with gold" in ARTEFACT["retracted_rules"]["e88epe"]
    retracted = [c for c in CASES if c["rule_id"] == "e88epe" and c["usable"] and c["minted"]]
    assert len(retracted) == 4
    assert not any(c["act_testcase_id"] in POOL for c in retracted)


def test_no_drafter_output_for_the_retracted_rule_exists_in_this_repo() -> None:
    """The precondition that makes the retraction a pre-registration amendment rather than a post-hoc
    one: if this rule's cases had ever been drafted, the retraction would be contaminated and its
    prediction would have to be scored as written. Verified, not assumed."""
    ids = {c["act_testcase_id"] for c in CASES if c["rule_id"] == "e88epe"} | {"e88epe"}
    for artifact in BENCHMARK.rglob("*.json"):
        text = artifact.read_text()
        assert not any(case_id in text for case_id in ids), artifact


def test_the_asset_receipt_records_both_content_types_and_the_absent_one() -> None:
    """Five vendored assets are extensionless and served `application/octet-stream` upstream; a
    browser decodes none of them under that type. One more is deliberately absent upstream — a case
    about an image request that does not complete — and is recorded rather than silently missing."""
    assets = json.loads((ACT_IMAGE / "assets.json").read_text())
    served = [a for a in assets if a["http_status"] == 200]
    assert len(assets) == 11 and len(served) == 10
    absent = [a for a in assets if a["http_status"] != 200]
    assert [a["path"] for a in absent] == ["/test-assets/does-not-exist.png"]
    repaired = [a for a in served if a["upstream_content_type"] != a["served_content_type"]]
    assert len(repaired) == 5
    assert all(a["upstream_content_type"] == "application/octet-stream" for a in repaired)
    assert all(a["served_content_type"].startswith("image/") for a in repaired)
    for asset in served:
        path = ASSETS / asset["path"].lstrip("/")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"], asset["path"]


def test_sampled_pool_cases_still_mint_and_still_render() -> None:
    """One pool case per rule, re-scanned and re-rendered for real: the frozen artifact still
    describes what the live scanner does."""
    for case_id in ("be6b29e220d6afbd827625c602ec49027e73fdf1", "a2333ec76e676624212dcd616ed11ae576ab775e"):
        case = _case(case_id)
        live = image_reachability._case_record(
            {
                "testcaseId": case_id,
                "ruleId": case["rule_id"],
                "ruleName": case["rule_name"],
                "expected": case["expected"],
                "url": case["url"],
            }
        )
        assert live["minted"] == case["minted"]
        assert live["rendered_images"] == case["rendered_images"]
        assert all(image["natural_width"] > 0 for image in live["rendered_images"])
