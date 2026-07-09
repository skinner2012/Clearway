"""Eval folds trace checks into the trust metrics: overall rate + M1 stratification."""

from __future__ import annotations

from datetime import datetime

import pytest
from stubs import canned_draft, canned_retrieve

from clearway.eval import compute_metrics, evaluate
from clearway.oracle import AxeCoreOracle
from clearway.schemas.models import (
    CitationCheck,
    CitationVerdict,
    Conformance,
    DraftRow,
    Finding,
    L1Status,
    NeedsReview,
    OracleRegime,
    ReviewReason,
    ReviewStatus,
    Trace,
)
from clearway.validator import validate

ORACLE = AxeCoreOracle()
_AT = datetime(2026, 7, 7, 12, 0, 0)


def _check(sc_id: str, verdict: CitationVerdict) -> CitationCheck:
    return CitationCheck(sc_id=sc_id, l0_valid=True, l1_status=L1Status.MATCH, verdict=verdict)


def _trace(finding_id: str, checks: list[CitationCheck], *, run_id: str = "run-1", config: str = "cfg-1") -> Trace:
    return Trace(
        run_id=run_id,
        finding_id=finding_id,
        config_id=config,
        model="stub",
        checks=checks,
        created_at=_AT,
    )


# --- compute_metrics ----------------------------------------------------------


def test_rate_is_hallucinations_over_citations() -> None:
    traces = [
        _trace("f1", [_check("1.1.1", CitationVerdict.VERIFIED)]),
        _trace("f2", [_check("1.1.1", CitationVerdict.HALLUCINATED)]),
        _trace("f3", [_check("9.9.9", CitationVerdict.HALLUCINATED)]),
    ]
    m = compute_metrics(traces)
    assert m.findings_total == 3
    assert m.citations_total == 3
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == pytest.approx(2 / 3)


def test_empty_traces_give_zero_rate_no_division_error() -> None:
    m = compute_metrics([])
    assert m.citation_hallucination_rate == 0.0
    assert (m.findings_total, m.citations_total, m.hallucinations_total) == (0, 0, 0)


def test_multiple_citations_per_trace_are_all_counted() -> None:
    traces = [
        _trace(
            "f1",
            [
                _check("1.1.1", CitationVerdict.VERIFIED),
                _check("9.9.9", CitationVerdict.HALLUCINATED),
            ],
        ),
    ]
    m = compute_metrics(traces)
    assert (m.findings_total, m.citations_total, m.hallucinations_total) == (1, 2, 1)
    assert m.citation_hallucination_rate == pytest.approx(0.5)


# --- M1 stratification: verifiable rate + unverifiable share ------------------


def test_stratifies_citations_by_oracle_verifiability() -> None:
    # 4 citations: 1 verified + 1 hallucinated (both verifiable) + 2 unverifiable.
    traces = [
        _trace("f1", [_check("1.1.1", CitationVerdict.VERIFIED)]),
        _trace("f2", [_check("9.9.9", CitationVerdict.HALLUCINATED)]),
        _trace("f3", [_check("1.4.3", CitationVerdict.UNVERIFIABLE)]),
        _trace("f4", [_check("2.4.7", CitationVerdict.UNVERIFIABLE)]),
    ]
    m = compute_metrics(traces)
    assert m.citations_total == 4
    assert m.citations_verifiable_total == 2
    assert m.citations_unverifiable_total == 2
    assert m.citations_verifiable_total + m.citations_unverifiable_total == m.citations_total  # invariant
    assert m.hallucinations_total == 1
    # overall rate divides by all 4; the verifiable rate divides by only the 2 verifiable.
    assert m.citation_hallucination_rate == pytest.approx(1 / 4)
    assert m.citation_hallucination_rate_verifiable == pytest.approx(1 / 2)
    assert m.unverifiable_share == pytest.approx(2 / 4)


def test_all_unverifiable_gives_zero_verifiable_rate_no_division_error() -> None:
    traces = [
        _trace("f1", [_check("1.4.3", CitationVerdict.UNVERIFIABLE)]),
        _trace("f2", [_check("1.2.2", CitationVerdict.UNVERIFIABLE)]),
    ]
    m = compute_metrics(traces)
    assert m.citations_verifiable_total == 0
    assert m.citation_hallucination_rate_verifiable == 0.0  # 0/0 guarded, not a crash
    assert m.unverifiable_share == pytest.approx(1.0)


def test_empty_traces_zero_all_stratified_fields() -> None:
    m = compute_metrics([])
    assert (m.citations_verifiable_total, m.citations_unverifiable_total) == (0, 0)
    assert m.citation_hallucination_rate_verifiable == 0.0
    assert m.unverifiable_share == 0.0


# --- evaluate: report labels + provenance ------------------------------------


def test_report_wires_labels_and_ids() -> None:
    traces = [
        _trace("h:image-alt", [_check("1.1.1", CitationVerdict.VERIFIED)]),
        _trace("h:label", [_check("9.9.9", CitationVerdict.HALLUCINATED)]),
    ]
    report = evaluate(
        traces,
        eval_set_id="m0-core@1",
        oracle_regime=OracleRegime.A_DIGITAL,
        oracle_version="wcag2.2-sc@1",
        created_at=_AT,
    )
    assert report.run_id == "run-1"
    assert report.config_id == "cfg-1"
    assert report.eval_set_id == "m0-core@1"
    assert report.oracle_regime is OracleRegime.A_DIGITAL
    assert report.oracle_version == "wcag2.2-sc@1"
    assert report.created_at == _AT
    assert report.trace_ids == ["h:image-alt", "h:label"]
    assert report.metrics.citation_hallucination_rate == pytest.approx(0.5)


def test_evaluate_rejects_empty_traces() -> None:
    with pytest.raises(ValueError, match="at least one trace"):
        evaluate([], eval_set_id="m0-core@1", oracle_regime=OracleRegime.A_DIGITAL, oracle_version="v", created_at=_AT)


def test_evaluate_rejects_traces_from_different_runs() -> None:
    traces = [
        _trace("f1", [_check("1.1.1", CitationVerdict.VERIFIED)], run_id="run-1"),
        _trace("f2", [_check("1.1.1", CitationVerdict.VERIFIED)], run_id="run-2"),
    ]
    with pytest.raises(ValueError, match="multiple runs"):
        evaluate(
            traces,
            eval_set_id="m0-core@1",
            oracle_regime=OracleRegime.A_DIGITAL,
            oracle_version="v",
            created_at=_AT,
        )


# --- end-to-end: real stub pipeline -> traces -> report (the acceptance case) -

_FIXTURE_TAGS = {
    "image-alt": ["wcag2a", "wcag111"],
    "html-has-lang": ["wcag2a", "wcag311"],
    "label": ["wcag2a", "wcag412"],
}


def _pipeline_trace(rule_id: str, axe_tags: list[str]) -> Trace:
    finding = Finding(id=f"h:{rule_id}", source_url="file://home.html", rule_id=rule_id, axe_tags=axe_tags, target="x")
    row = canned_draft(finding, canned_retrieve(finding))
    return _trace(finding.id, validate(row, finding, ORACLE))


def test_fixture_pipeline_report_has_two_thirds_rate() -> None:
    traces = [_pipeline_trace(rule_id, tags) for rule_id, tags in _FIXTURE_TAGS.items()]
    report = evaluate(
        traces,
        eval_set_id="m0-core@1",
        oracle_regime=ORACLE.regime,
        oracle_version=ORACLE.version,
        created_at=_AT,
    )
    m = report.metrics
    assert m.findings_total == 3
    assert m.citations_total == 3
    assert m.hallucinations_total == 2
    assert m.citation_hallucination_rate == pytest.approx(2 / 3)
    # all three fixture rules are confirmed `violations` → every citation is oracle-verifiable, so
    # the verifiable rate equals the overall rate and nothing is unverifiable. (The unverifiable
    # share only becomes non-trivial once the `incomplete`-bucket fixtures enter, on the real run.)
    assert m.citations_verifiable_total == 3
    assert m.citations_unverifiable_total == 0
    assert m.citation_hallucination_rate_verifiable == pytest.approx(2 / 3)
    assert m.unverifiable_share == 0.0


# --- expert_edit_distance plumbing (M2 T4) ------------------------------------


def _edited_review(finding_id: str, original: str, edited: str) -> NeedsReview:
    draft = DraftRow(
        finding_id=finding_id, conformance=Conformance.PARTIALLY_SUPPORTS, remediation=original, confidence=1.0
    )
    return NeedsReview(
        finding_id=finding_id,
        run_id="run-1",
        draft=draft,
        reason=ReviewReason.UNVERIFIABLE_JUDGMENT,
        status=ReviewStatus.EDITED,
        edited_draft=draft.model_copy(update={"remediation": edited}),
        created_at=_AT,
        updated_at=_AT,
    )


def test_reviews_populate_expert_edit_distance() -> None:
    traces = [_trace("f1", [_check("1.1.1", CitationVerdict.VERIFIED)])]
    reviews = [_edited_review("f1", "aaaaaa", "ZZZZZZ")]  # disjoint text → distance 1.0
    report = evaluate(
        traces,
        eval_set_id="m0-core@1",
        oracle_regime=ORACLE.regime,
        oracle_version=ORACLE.version,
        created_at=_AT,
        reviews=reviews,
    )
    assert report.metrics.expert_edit_distance == pytest.approx(1.0)


def test_no_reviews_leaves_expert_edit_distance_zero() -> None:
    traces = [_trace("f1", [_check("1.1.1", CitationVerdict.VERIFIED)])]
    report = evaluate(
        traces,
        eval_set_id="m0-core@1",
        oracle_regime=ORACLE.regime,
        oracle_version=ORACLE.version,
        created_at=_AT,
    )
    assert report.metrics.expert_edit_distance == 0.0
