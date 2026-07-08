"""T3 acceptance: the real LLM `Drafter` assembles a valid `DraftRow` from a finding + citations.

Two layers, mirroring the retriever/corpus seams:
- **offline** (default): drive `Drafter` with `FakeLLMClient` to prove the *mechanics* — code owns
  finding_id/severity, citations resolve against the retrieved set (hallucinated ids kept as bare
  citations), and bad model output retries then degrades to a low-confidence fallback (no crash).
- **gated** (`ollama_up`): the real path — `LiteLLMClient` → Ollama `gemma4:31b` — proves the model
  honors the structured-output contract and cites the retrieved SC. Skips when Ollama is down.
"""

from __future__ import annotations

import urllib.request

import pytest

from clearway.drafter import Drafter, FakeLLMClient, LiteLLMClient
from clearway.schemas.models import Citation, Conformance, Finding, Severity

_GOOD = '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"Add alt text.","confidence":0.9}'
_BAD = "sorry, here is your row: **Conformance:** fail"  # markdown, not JSON → ValidationError


def _finding(rule_id: str = "image-alt", impact: Severity | None = None) -> Finding:
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://home.html",
        rule_id=rule_id,
        target="img",
        help="Images must have alternate text",
        impact=impact,
    )


def _cite(sc_id: str, url: str = "") -> Citation:
    return Citation(sc_id=sc_id, url=url, source="WCAG-SC")


# --- Drafter mechanics (offline: FakeLLMClient) ------------------------------


def test_assembles_draftrow_with_code_owned_identity_and_severity() -> None:
    finding = _finding(impact=Severity.SERIOUS)
    row = Drafter(FakeLLMClient(_GOOD)).draft(
        finding, [_cite("1.1.1", "https://www.w3.org/TR/WCAG22/#non-text-content")]
    )
    assert row.finding_id == finding.id  # identity comes from code, never the model
    assert row.severity == Severity.SERIOUS  # carried from the finding, not the model
    assert row.conformance == Conformance.DOES_NOT_SUPPORT
    assert row.remediation == "Add alt text."
    assert row.confidence == 0.9


def test_cited_ids_resolve_to_retrieved_citations_metadata() -> None:
    # a cited id present in the retrieved set gets that citation's corpus-grounded url.
    row = Drafter(FakeLLMClient(_GOOD)).draft(_finding(), [_cite("1.1.1", "https://example/1.1.1")])
    (citation,) = row.citations
    assert citation.sc_id == "1.1.1"
    assert citation.url == "https://example/1.1.1"  # grounded from retrieval, not invented


def test_hallucinated_citation_is_kept_as_bare_citation() -> None:
    # the model cites an SC that was NOT retrieved -> kept (no url) so the validator can catch it.
    resp = '{"conformance":"does_not_support","cited_sc_ids":["9.9.9"],"remediation":"x","confidence":0.7}'
    row = Drafter(FakeLLMClient(resp)).draft(_finding(), [_cite("1.1.1", "https://example/1.1.1")])
    (citation,) = row.citations
    assert citation.sc_id == "9.9.9"
    assert citation.url == ""  # corpus never supported it — bare citation, surfaced not hidden


def test_retries_once_then_succeeds() -> None:
    # first response is unparseable, second is valid -> assembled draft, not the fallback.
    row = Drafter(FakeLLMClient(_BAD, _GOOD)).draft(_finding(), [_cite("1.1.1")])
    assert row.confidence == 0.9
    assert [c.sc_id for c in row.citations] == ["1.1.1"]


def test_degrades_to_fallback_when_output_never_parses() -> None:
    row = Drafter(FakeLLMClient(_BAD, _BAD)).draft(_finding(impact=Severity.CRITICAL), [_cite("1.1.1")])
    assert row.confidence == 0.0  # zero confidence signals "do not trust"
    assert row.conformance == Conformance.DOES_NOT_SUPPORT
    assert row.citations == []
    assert row.severity == Severity.CRITICAL  # still carries what code knows
    assert row.finding_id == "h:image-alt"


def test_out_of_range_confidence_is_rejected_then_falls_back() -> None:
    bad_conf = '{"conformance":"supports","cited_sc_ids":[],"remediation":"x","confidence":9}'
    row = Drafter(FakeLLMClient(bad_conf, bad_conf)).draft(_finding(), [])
    assert row.confidence == 0.0  # 9 is out of [0,1] -> ValidationError -> fallback


def test_empty_retrieval_degrades_gracefully() -> None:
    resp = '{"conformance":"not_applicable","cited_sc_ids":[],"remediation":"n/a","confidence":0.2}'
    row = Drafter(FakeLLMClient(resp)).draft(_finding(), [])  # nothing retrieved
    assert row.citations == []
    assert row.conformance == Conformance.NOT_APPLICABLE
    assert row.confidence == 0.2  # low, but a real row — not a crash


# --- gated integration: real Ollama ------------------------------------------


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


ollama_up = pytest.mark.skipif(not _ollama_up(), reason="Ollama not running (need `ollama serve` + gemma4:31b)")


@ollama_up
def test_real_drafter_returns_schema_valid_row_citing_the_retrieved_sc() -> None:
    """The T3 acceptance: gemma4 via LiteLLM returns a schema-valid DraftRow whose conformance is a
    real enum, confidence is in range, and which cites the retrieved SC (1.1.1) for an image-alt
    finding. Deterministic-ish at temp 0; asserts the contract, not exact wording."""
    row = Drafter(LiteLLMClient()).draft(_finding(), [_cite("1.1.1", "https://www.w3.org/TR/WCAG22/#non-text-content")])
    assert isinstance(row.conformance, Conformance)
    assert 0.0 <= row.confidence <= 1.0
    assert "1.1.1" in [c.sc_id for c in row.citations]
