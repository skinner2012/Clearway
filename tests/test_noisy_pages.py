"""Guard for the noisy-page acceptance cases: each realistic page still mints EXACTLY its declared
focal + noise composition, the two focal labels still hold after embedding (the recorded spot-check,
automated), and every case is directly comparable to a real vendored ACT clean counterpart.

Layers: (1) the manifest is well-formed and versioned off the ACT freeze; (2) each focal derives from
a real ACT case whose outcome/rule matches (clean-vs-noisy comparability); (3) a live re-scan confirms
composition + that the focal + noise build schema-valid `GoldLabel`s with honest provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

from clearway.eval import act_gold, noisy_pages
from clearway.schemas.models import Conformance

FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
NOISY = FIXTURES / "noisy-pages"
MANIFEST = json.loads((NOISY / "expected_noisy_pages.json").read_text())
ACT_MANIFEST = json.loads((FIXTURES / "act-gold" / "expected_act.json").read_text())
ACT_BY_ID = {c["act_testcase_id"]: c for c in ACT_MANIFEST["cases"]}


def test_manifest_is_well_formed_and_versioned() -> None:
    assert MANIFEST["set_id"] == "noisy-pages"
    assert MANIFEST["source"] == "w3c-act"
    # the focal labels come from the ACT freeze, so the version must inherit it
    assert MANIFEST["gold_version"] == act_gold.GOLD_VERSION
    assert len(MANIFEST["pages"]) == 2
    # n=2 is deliberate — one failed focal (miss-under-noise) + one passed focal (cry-wolf-under-noise)
    expected = {c["focal"]["expected"] for c in MANIFEST["pages"]}
    assert expected == {"failed", "passed"}, "the two pages must probe opposite harm axes"


def test_each_focal_matches_a_real_act_clean_counterpart() -> None:
    """The whole point of the noisy tier is a clean-vs-noisy delta, so each focal must be a real
    vendored ACT case whose outcome and rule match — no invented labels."""
    for page in MANIFEST["pages"]:
        focal = page["focal"]
        act = ACT_BY_ID.get(focal["act_testcase_id"])
        assert act is not None, f"{page['page_id']} focal not a vendored ACT case"
        assert act["expected"] == focal["expected"]
        assert act["rule_name"] == focal["rule_name"]
        assert act["gold_success_criteria"] == focal["gold_success_criteria"]
        # the clean counterpart HTML the noisy page is compared against actually exists
        assert (NOISY / focal["clean_counterpart"]).resolve().is_file()


def test_act_certified_noise_points_at_a_vendored_file() -> None:
    for page in MANIFEST["pages"]:
        for n in page["noise"]:
            if n["provenance"].startswith("act:"):
                tid = n["provenance"].split(":", 1)[1]
                assert (FIXTURES / "act-gold" / "html" / f"{tid}.html").is_file(), n


def test_pages_mint_declared_composition_and_build_valid_goldlabels() -> None:
    """Live re-scan (the automated spot-check): both pages mint exactly focal + noise, and every pair
    is a schema-valid GoldLabel with honest provenance — focal/ACT-noise = w3c-act, chrome = self."""
    pairs = noisy_pages.load_noisy_page_pairs()
    # 2 focal + (5 + 7) noise = 14
    assert len(pairs) == 14

    focal = [(f, g) for f, g in pairs if g.notes.startswith("noisy-page focal")]
    assert len(focal) == 2
    for _f, g in focal:
        assert g.source == "w3c-act" and g.act_testcase_id
    # the failed focal must FLAG (does_not_support); the passed focal must be CLEAN (supports)
    confs = {g.gold_conformance for _f, g in focal}
    assert confs == {Conformance.DOES_NOT_SUPPORT, Conformance.SUPPORTS}

    noise = [(f, g) for f, g in pairs if g.notes.startswith("noisy-page noise")]
    assert len(noise) == 12
    # every noise element is clean by construction (a flag on any of them is a false positive)
    assert all(g.gold_conformance is Conformance.SUPPORTS for _f, g in noise)
    # honest provenance: authored-trivial chrome is self-labelled, never dressed up as W3C gold
    self_noise = [g for _f, g in noise if g.source == "self"]
    assert self_noise and all(g.act_testcase_id is None for g in self_noise)
    act_noise = [g for _f, g in noise if g.source == "w3c-act"]
    assert act_noise and all(g.act_testcase_id for g in act_noise)
