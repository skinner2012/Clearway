"""The per-class trust tiers: a DERIVED signal, not a hand-assigned table and not the model's own
confidence.

Three things are guarded here, because each is a way the tiers could quietly stop meaning anything:

- the **rule** (κ ≥ 0.60 → reliable, measured-and-below → weak, never-scored → unmeasured) is applied
  by a function, so it can be re-run against a later frozen run rather than re-negotiated per class;
- the **inputs** (`FROZEN_CLASS_KAPPA`) match the frozen artifact they claim to quote, so the code
  cannot cite a number the run does not contain;
- the **mirrors** (the doc table and the dashboard panel) agree with `FINDING_CLASS_TRUST`, so the
  single source of truth stays single.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clearway.normalizer.quality_review import (
    FINDING_CLASS_TRUST,
    FROZEN_CLASS_KAPPA,
    QUALITY_REVIEW_RULES,
    TRUST_KAPPA_THRESHOLD,
    ClassKappa,
    FindingClassTrust,
    derive_class_trust,
)

_REPO = Path(__file__).resolve().parent.parent
_REPORTS = _REPO / "benchmark" / "reports"
_LATEST_RUN = _REPORTS / "citation_grounding_result.json"
_EARLIER_RUN = _REPORTS / "drafter_kappa_baseline.json"

_DOC = _REPO / "docs" / "finding-class-trust.md"
_DASHBOARD = _REPO / "stack" / "grafana" / "dashboards" / "citation_hallucination.json"


def _latest() -> dict:
    return json.loads(_LATEST_RUN.read_text())


def _mechanism() -> dict[str, dict]:
    return {m["axe_rule"]: m for m in _latest()["mechanism"]}


# --- the inputs are the frozen run's, unaltered -------------------------------


def test_frozen_kappa_matches_the_artifact_it_quotes() -> None:
    """Every κ and n in `FROZEN_CLASS_KAPPA` is the frozen run's own, to the precision it is written
    at. A drifted constant would let the tiers claim evidence that does not exist."""
    mechanism = _mechanism()
    assert set(FROZEN_CLASS_KAPPA) == set(mechanism)
    for rule, frozen in FROZEN_CLASS_KAPPA.items():
        m = mechanism[rule]
        assert frozen.kappa == pytest.approx(m["kappa"], abs=5e-5), rule
        assert frozen.n == m["tp"] + m["fp"] + m["fn"] + m["tn"], rule


def test_one_kappa_per_class_is_honest_because_the_run_was_deterministic() -> None:
    """The run is three passes; quoting a single κ per class is only legitimate because every pass
    produced the same one."""
    assert _latest()["determinism"]["per_class_kappa_identical"] is True


def test_unmeasured_classes_are_absent_from_every_scored_artifact() -> None:
    """UNMEASURED means "never scored against gold", not "scored badly" — so the classes carrying it
    must not appear in either frozen scoring."""
    scored = set(_mechanism()) | {c["axe_rule"] for c in json.loads(_EARLIER_RUN.read_text())["classes"]}
    unmeasured = {r for r, t in FINDING_CLASS_TRUST.items() if t is FindingClassTrust.UNMEASURED}
    assert unmeasured == {"image-alt", "frame-title"}
    assert not (unmeasured & scored)


# --- the rule ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kappa", "expected"),
    [
        (1.0, FindingClassTrust.RELIABLE),
        (0.60, FindingClassTrust.RELIABLE),  # the boundary is inclusive
        (0.5999, FindingClassTrust.WEAK),
        (0.0, FindingClassTrust.WEAK),
        (-1.0, FindingClassTrust.WEAK),  # worse than chance is still MEASURED
        (None, FindingClassTrust.UNMEASURED),
    ],
)
def test_the_threshold_rule_decides_the_tier(kappa: float | None, expected: FindingClassTrust) -> None:
    measured = {} if kappa is None else {"r": ClassKappa(kappa=kappa, n=1)}
    assert derive_class_trust(measured, ["r"])["r"] is expected


def test_the_threshold_is_the_substantial_agreement_bar() -> None:
    assert TRUST_KAPPA_THRESHOLD == 0.60


def test_the_rule_re_applies_to_a_later_run_without_re_litigating_the_mapping() -> None:
    """The point of deriving: a future frozen run refreshes the tiers by being passed in. Here a
    hypothetical run where link-name is fixed and label regresses — both tiers follow the κ, and a
    class dropped from the run falls back to UNMEASURED rather than keeping a stale tier."""
    later = {"link-name": ClassKappa(0.71, 15), "label": ClassKappa(0.31, 11)}
    tiers = derive_class_trust(later, ["link-name", "label", "empty-heading"])
    assert tiers == {
        "link-name": FindingClassTrust.RELIABLE,
        "label": FindingClassTrust.WEAK,
        "empty-heading": FindingClassTrust.UNMEASURED,
    }


# --- the shipped tiers -------------------------------------------------------


def test_shipped_tiers_are_the_rule_applied_to_the_frozen_run() -> None:
    """Not a re-statement of the table: it asserts the shipped dict IS the derivation, so a hand-edit
    of a tier fails here."""
    assert FINDING_CLASS_TRUST == derive_class_trust(FROZEN_CLASS_KAPPA, QUALITY_REVIEW_RULES)
    assert FINDING_CLASS_TRUST == {
        "image-alt": FindingClassTrust.UNMEASURED,
        "link-name": FindingClassTrust.WEAK,
        "label": FindingClassTrust.RELIABLE,
        "frame-title": FindingClassTrust.UNMEASURED,
        "empty-heading": FindingClassTrust.RELIABLE,
        "document-title": FindingClassTrust.RELIABLE,
    }


def test_the_low_n_caveat_travels_with_the_tier() -> None:
    """⚠️ document-title is RELIABLE on five cases. The rule stands, but a reader must not meet the
    tick without the n — so the sample size is carried in the data and the caveat is stated where the
    tier is defined, not only in a document nobody opens."""
    assert FROZEN_CLASS_KAPPA["document-title"].n == 5
    assert FINDING_CLASS_TRUST["document-title"] is FindingClassTrust.RELIABLE
    doc = FindingClassTrust.__doc__ or ""
    assert "n = 5" in doc and "p = 0.125" in doc
    assert "n=5" in _DOC.read_text()


# --- the mirrors cannot drift from the code ----------------------------------


def _tier_rows(lines: list[str], rule: str) -> list[str]:
    return [ln for ln in lines if ln.strip().startswith(f"| `{rule}` |")]


def _assert_mirrors(where: str, lines: list[str]) -> None:
    for rule, tier in FINDING_CLASS_TRUST.items():
        rows = _tier_rows(lines, rule)
        assert rows, f"{where}: no table row for {rule}"
        stale = {t.value for t in FindingClassTrust} - {tier.value}
        assert any(tier.value in row for row in rows), f"{where}: {rule} is not shown as {tier.value}"
        for row in rows:
            assert not [s for s in stale if s in row], f"{where}: a {rule} row names a stale tier"


def test_the_doc_table_mirrors_the_code() -> None:
    _assert_mirrors("docs/finding-class-trust.md", _DOC.read_text().splitlines())


def test_the_dashboard_panel_mirrors_the_code() -> None:
    dashboard = json.loads(_DASHBOARD.read_text())
    panels = [p for p in dashboard["panels"] if "per-class trust" in p.get("title", "")]
    assert len(panels) == 1
    _assert_mirrors("the per-class trust panel", panels[0]["options"]["content"].splitlines())
