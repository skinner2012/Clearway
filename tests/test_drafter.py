"""T3 acceptance: the real LLM `Drafter` assembles a valid `DraftRow` from a finding + citations.

Two layers, mirroring the retriever/corpus seams:
- **offline** (default): drive `Drafter` with `FakeLLMClient` to prove the *mechanics* — code owns
  finding_id/severity, citations resolve against the retrieved set (hallucinated ids kept as bare
  citations), and bad model output retries then degrades to a low-confidence fallback (no crash).
- **gated** (`ollama_up`): the real path — `LocalLLMClient` → Ollama `gemma4:31b` — proves the model
  honors the structured-output contract and cites the retrieved SC. Skips when Ollama is down.
"""

from __future__ import annotations

import urllib.request

import pytest

from clearway.drafter import Drafter, is_fallback_draft
from clearway.drafter.llm import _user_prompt
from clearway.llm import FakeLLMClient, LLMUsage, LocalLLMClient
from clearway.schemas.models import AxeBucket, Citation, Conformance, Finding, Severity

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


def test_is_fallback_draft_identifies_only_the_degraded_row() -> None:
    """The acceptance benchmark aborts on a fallback, so it must be detected precisely — a real draft,
    even a genuine does_not_support @ 0.0 with its own remediation, must NOT read as a fallback."""
    fallback = Drafter(FakeLLMClient(_BAD, _BAD)).draft(_finding(), [_cite("1.1.1")])
    assert is_fallback_draft(fallback) is True
    assert is_fallback_draft(Drafter(FakeLLMClient(_GOOD)).draft(_finding(), [_cite("1.1.1")])) is False
    real_zero = '{"conformance":"does_not_support","cited_sc_ids":[],"remediation":"Add a real fix.","confidence":0.0}'
    assert is_fallback_draft(Drafter(FakeLLMClient(real_zero)).draft(_finding(), [])) is False


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


# --- prompt framing by provenance --------------------------------------------


def test_passes_finding_is_framed_as_a_quality_review_task_not_a_pass() -> None:
    """A PASSES finding must be drafted as a quality-review task — otherwise the model reads
    'a name exists' as conformant and drafts `supports`, and the whole gold set is non-issues.
    The prompt must say so, and must NOT reuse the 'could not decide' framing (that's INCOMPLETE)."""
    passes_finding = _finding().model_copy(update={"source_bucket": AxeBucket.PASSES})
    prompt = _user_prompt(passes_finding, [_cite("1.1.1")])
    assert "QUALITY-REVIEW" in prompt
    assert "never supports" in prompt  # present-but-inadequate is not a pass
    assert "could not decide" not in prompt  # that framing belongs to INCOMPLETE, not PASSES


def test_violation_and_incomplete_framings_are_unchanged() -> None:
    """The new branch is additive: violations and incomplete keep their existing framing."""
    violation = _user_prompt(_finding(), [_cite("1.1.1")])  # default bucket = VIOLATIONS
    assert "a CONFIRMED failure" in violation
    incomplete = _finding().model_copy(update={"source_bucket": AxeBucket.INCOMPLETE})
    assert "could not decide" in _user_prompt(incomplete, [_cite("1.1.1")])


# --- Usage seam (T2: complete_json returns content + usage) -------------------


def test_draft_with_usage_returns_row_and_the_calls_usage() -> None:
    usage = LLMUsage(tokens_in=120, tokens_out=34, cost_usd=0.0, latency_ms=42.0)
    result = Drafter(FakeLLMClient(_GOOD, usage=usage)).draft_with_usage(
        _finding(), [_cite("1.1.1", "https://example/1.1.1")]
    )
    assert result.row.confidence == 0.9  # the same row draft() would return
    assert result.usage == usage  # the successful call's usage, threaded out for the Trace


def test_fallback_draft_carries_empty_usage() -> None:
    # never-parses → fallback row, and no usage attributed to a row we're discarding.
    spent = LLMUsage(tokens_in=99, tokens_out=99, cost_usd=0.0, latency_ms=5.0)
    result = Drafter(FakeLLMClient(_BAD, _BAD, usage=spent)).draft_with_usage(_finding(), [_cite("1.1.1")])
    assert result.row.confidence == 0.0  # fallback
    assert result.usage == LLMUsage()  # empty, not the spent-on-failure usage


def test_draft_is_a_thin_row_only_view_of_draft_with_usage() -> None:
    client = FakeLLMClient(_GOOD, usage=LLMUsage(tokens_in=1, tokens_out=1))
    assert Drafter(client).draft(_finding(), [_cite("1.1.1")]).finding_id == "h:image-alt"


def test_confirmed_violation_threads_usage_the_same_way() -> None:
    """The remediation-only branch is a second call site, so the `Trace` quartet must be filled from
    it too — a cheaper prompt that silently stopped reporting tokens would hide its own saving."""
    usage = LLMUsage(tokens_in=60, tokens_out=12, cost_usd=0.0, latency_ms=21.0)
    confirmed = _finding().model_copy(update={"axe_tags": ["wcag2a", "wcag111"]})
    result = Drafter(FakeLLMClient('{"remediation":"Add alt text."}', usage=usage)).draft_with_usage(
        confirmed, [_cite("1.1.1", "https://example/1.1.1")]
    )
    assert result.usage == usage
    assert result.row.remediation == "Add alt text."


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
    row = Drafter(LocalLLMClient()).draft(
        _finding(), [_cite("1.1.1", "https://www.w3.org/TR/WCAG22/#non-text-content")]
    )
    assert isinstance(row.conformance, Conformance)
    assert 0.0 <= row.confidence <= 1.0
    assert "1.1.1" in [c.sc_id for c in row.citations]


@ollama_up
def test_real_drafter_honors_the_remediation_only_contract_on_a_confirmed_violation() -> None:
    """The remediation-only branch against the real model: a one-field response schema is a different
    structured-output ask than the four-field one, so the contract has to be proven, not assumed.
    Asserts the shape and that the row is not the fallback — never the wording."""
    confirmed = _finding(impact=Severity.CRITICAL).model_copy(update={"axe_tags": ["wcag2a", "wcag111"]})
    row = Drafter(LocalLLMClient()).draft(confirmed, [_cite("1.1.1", "https://www.w3.org/TR/WCAG22/#non-text-content")])
    assert is_fallback_draft(row) is False  # the model produced a real, parseable remediation
    assert row.remediation.strip() != ""
    assert row.conformance == Conformance.DOES_NOT_SUPPORT  # code's, from axe's confirmation
    assert [c.sc_id for c in row.citations] == ["1.1.1"]  # code's, from the wcag111 tag
    assert row.confidence == 1.0
