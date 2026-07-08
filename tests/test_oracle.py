"""T6 acceptance: AxeCoreOracle derives correct SCs from axe tags and implements the Oracle seam."""

from __future__ import annotations

import json
from pathlib import Path

from clearway.oracle import VALID_SC_IDS, AxeCoreOracle, tag_to_sc_ids
from clearway.oracle.wcag import SC_LEVELS
from clearway.schemas.models import ConformanceLevel, Finding, Oracle, OracleRegime

FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"


def _finding(rule_id: str, tags: list[str]) -> Finding:
    return Finding(id=f"h:{rule_id}", source_url="file://home.html", rule_id=rule_id, axe_tags=tags, target="x")


# --- the WCAG 2.2 reference set (load-bearing for L0) ---


def test_sc_set_is_wcag_2_2() -> None:
    assert len(VALID_SC_IDS) == 86  # WCAG 2.2 after 4.1.1 removal
    assert "4.1.1" not in VALID_SC_IDS  # Parsing was removed
    assert {"1.1.1", "3.1.1", "4.1.2", "1.4.10", "2.4.11"} <= VALID_SC_IDS


def test_sc_levels() -> None:
    assert SC_LEVELS["1.1.1"] == ConformanceLevel.A
    assert SC_LEVELS["1.4.3"] == ConformanceLevel.AA
    assert SC_LEVELS["1.2.6"] == ConformanceLevel.AAA


# --- tag decoding ---


def test_tag_decode_single_and_double_digit_criteria() -> None:
    assert tag_to_sc_ids(["wcag111"]) == ["1.1.1"]
    assert tag_to_sc_ids(["wcag1410"]) == ["1.4.10"]
    assert tag_to_sc_ids(["wcag2413"]) == ["2.4.13"]


def test_non_sc_tags_are_filtered() -> None:
    assert tag_to_sc_ids(["wcag2a", "wcag21aa", "cat.forms", "best-practice", "ACT", "section508"]) == []


def test_decoded_but_nonexistent_sc_is_dropped() -> None:
    # wcag199 would decode to 1.9.9, which is not a real SC -> must not leak through.
    assert tag_to_sc_ids(["wcag199"]) == []


def test_dedupe_and_sort() -> None:
    assert tag_to_sc_ids(["wcag412", "wcag111", "wcag111"]) == ["1.1.1", "4.1.2"]


# --- the Oracle seam ---


def test_axe_oracle_satisfies_protocol() -> None:
    oracle = AxeCoreOracle()
    assert isinstance(oracle, Oracle)
    assert oracle.regime == OracleRegime.A_DIGITAL
    assert oracle.version


def test_verdict_for_known_finding() -> None:
    oracle = AxeCoreOracle()
    verdict = oracle.verdict_for(_finding("image-alt", ["wcag2a", "wcag111", "cat.text-alternatives"]))
    assert verdict is not None
    assert verdict.success_criteria == ["1.1.1"]
    assert verdict.source == "axe-core"
    assert verdict.confidence == 1.0


def test_verdict_none_when_no_sc_tag() -> None:
    oracle = AxeCoreOracle()
    assert oracle.verdict_for(_finding("region", ["cat.keyboard", "best-practice"])) is None
    assert oracle.verdict_for(_finding("x", [])) is None


def test_fixture_tags_map_to_expected_scs() -> None:
    """Each T1 planted finding's axe tag resolves to the SC documented in expected_m0.json."""
    oracle = AxeCoreOracle()
    manifest = json.loads((FIXTURES / "expected_m0.json").read_text())
    for finding in manifest["pages"][0]["expected_findings"]:
        verdict = oracle.verdict_for(_finding(finding["rule_id"], [finding["axe_tag"]]))
        assert verdict is not None
        assert verdict.success_criteria == [finding["sc"]]
