"""The real LLM drafter (M1) — replaces the M0 canned stub in the production spine.

A `Drafter` holds an `LLMClient` and answers per-finding: build a prompt from the finding + its
retrieved citations → ask the model for a small *semantic* shape (`_LLMDraft`: conformance,
which SC ids it cites, remediation, confidence) → **assemble the full `DraftRow` in code**
(we own `finding_id` + `severity`, and resolve cited ids against the retrieved citations so the
citation metadata is corpus-grounded, never model-invented).

Two things this gets right that a naive `litellm.completion(...)` would not:
1. **Provider.** Ollama chat models need the `ollama_chat/` prefix; plain `ollama/` silently
   drops structured output and returns markdown (verified against gemma4/qwen). `response_format`
   + an explicit prompt (exact enum values, decimal confidence) yields strict-schema JSON.
2. **Defensiveness.** LLM output is not guaranteed; the drafter validates, retries once, then
   degrades to a low-confidence fallback `DraftRow` rather than crashing (T3 acceptance).

Grounding note (M1 scope): the retrieved `Citation`s carry sc_id + url but not the SC's normative
text (T2 option A), so the prompt names the *relevant SC ids* and the model supplies their meaning
from its own knowledge. Passing the SC text into the prompt for stronger grounding is a fast-follow.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clearway.schemas.models import AxeBucket, Citation, Conformance, DraftRow, Finding

_DEFAULT_MODEL = "gemma4:31b"
_DEFAULT_BASE_URL = "http://localhost:11434"
_FALLBACK_CONFIDENCE = 0.0  # a draft we could not parse is worth nothing — say so, don't crash


class _LLMDraft(BaseModel):
    """The semantic fields the LLM produces. Code assembles the full `DraftRow` around it, so the
    model never touches identity (`finding_id`) or corpus-grounded citation metadata."""

    model_config = ConfigDict(extra="ignore")  # tolerate stray keys the model may add

    conformance: Conformance
    cited_sc_ids: list[str] = Field(default_factory=list)
    remediation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class LLMClient(Protocol):
    """The seam the drafter depends on. Real (LiteLLM→Ollama) or fake (tests)."""

    @property
    def model(self) -> str: ...

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> str:
        """Return the model's raw JSON content for a system+user prompt under a response schema."""
        ...


class LiteLLMClient:
    """Real chat client: an Ollama model via LiteLLM, structured output at temperature 0."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model: str = model or os.getenv("CLEARWAY_CHAT_MODEL") or _DEFAULT_MODEL
        self._base_url: str = base_url or os.getenv("CLEARWAY_OLLAMA_BASE_URL") or _DEFAULT_BASE_URL

    @property
    def model(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> str:
        import litellm

        response = litellm.completion(
            model=f"ollama_chat/{self._model}",  # ollama_chat/, NOT ollama/ — see module docstring
            api_base=self._base_url,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
            temperature=0.0,
        )
        content: str = response.choices[0].message.content or ""
        return content


class FakeLLMClient:
    """Deterministic offline client for unit tests: returns canned raw strings, never a network
    call. Pass one or more responses; each call yields the next (the last repeats). Drafting
    *quality* is proven by the gated integration test against the real model — the fake only
    exercises drafter mechanics (assembly, citation resolution, retry-then-fallback)."""

    _DEFAULT_RESPONSE = '{"conformance":"does_not_support","cited_sc_ids":[],"remediation":"","confidence":0.5}'

    def __init__(self, *responses: str, model: str = "fake-llm") -> None:
        self._responses = list(responses) or [self._DEFAULT_RESPONSE]
        self._model = model
        self._i = 0

    @property
    def model(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> str:
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return response


class Drafter:
    """Real LLM drafting: `Finding` + retrieved `Citation[]` → `DraftRow`.

    `retries` is the number of *extra* attempts on an unparseable response before falling back.
    """

    def __init__(self, client: LLMClient, retries: int = 1) -> None:
        self._client = client
        self._retries = retries

    def draft(self, finding: Finding, citations: list[Citation]) -> DraftRow:
        system = _system_prompt()
        user = _user_prompt(finding, citations)
        for _ in range(self._retries + 1):
            raw = self._client.complete_json(system, user, _LLMDraft)
            try:
                out = _LLMDraft.model_validate_json(raw)
            except ValidationError:
                continue  # model drifted off-schema; try again, then fall back
            return _assemble(finding, citations, out)
        return _fallback(finding)


def _system_prompt() -> str:
    return (
        "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
        "- cited_sc_ids: only WCAG SC ids from the provided candidates that genuinely apply (may be empty)\n"
        "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
        "- remediation: one concrete sentence on how to fix it\n"
        'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
        '"remediation":"Add a descriptive alt attribute.","confidence":0.9}'
    )


def _user_prompt(finding: Finding, citations: list[Citation]) -> str:
    bucket = (
        "a CONFIRMED failure"
        if finding.source_bucket is AxeBucket.VIOLATIONS
        else "a NEEDS-REVIEW item the scanner could not decide"
    )
    candidates = "\n".join(f"- {c.sc_id} ({c.url})" for c in citations) or "- (none retrieved)"
    return (
        f"Finding ({bucket}): axe rule '{finding.rule_id}' — {finding.help or '(no description)'}\n"
        f"Target element: {finding.target}\n"
        f"HTML: {finding.html or '(not captured)'}\n"
        f"Candidate WCAG success criteria you may cite:\n{candidates}\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )


def _assemble(finding: Finding, citations: list[Citation], out: _LLMDraft) -> DraftRow:
    """Build the full `DraftRow`: identity + severity from code; citations resolved from the
    retrieved set by sc_id (corpus-grounded metadata), falling back to a bare `Citation` for any
    sc_id the model cites that was NOT retrieved — a citation the corpus never supported is exactly
    the hallucination the validator/oracle is built to catch, so we keep it, not drop it."""
    by_id = {c.sc_id: c for c in citations}
    cited = [by_id.get(sc_id) or Citation(sc_id=sc_id) for sc_id in out.cited_sc_ids]
    return DraftRow(
        finding_id=finding.id,
        conformance=out.conformance,
        citations=[c.model_copy() for c in cited],
        remediation=out.remediation,
        severity=finding.impact,
        confidence=out.confidence,
    )


def _fallback(finding: Finding) -> DraftRow:
    """A draft we could not parse after retries: conservative verdict, zero confidence, no
    citations — surfaces as low-trust rather than crashing the run (T3 graceful-degradation)."""
    return DraftRow(
        finding_id=finding.id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=[],
        remediation="(draft unavailable — the model did not return a usable response)",
        severity=finding.impact,
        confidence=_FALLBACK_CONFIDENCE,
    )
