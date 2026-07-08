"""Orchestrator — wire the forward path over one page into a trust-metric report.

This is the spine T2–T9 were built for: scan → normalize → retrieve → draft → validate → eval.
It assembles one `Trace` per finding and aggregates them into an `EvalReport`. It is deliberately
**pure** — no OTel emission here; the CLI owns that side effect (so the whole pipeline is testable
offline, without the stack running).

Orchestration is intentionally thin: a straight pass over findings with one retry on the scan.
Durable primitives (checkpoint, idempotent resume, HITL) are M2 (ARCHITECTURE §4.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from clearway.eval import evaluate
from clearway.normalizer import normalize
from clearway.oracle import AxeCoreOracle
from clearway.scanner import scan
from clearway.schemas.models import Citation, DraftRow, EvalReport, Finding, Oracle, ScanResult, Trace
from clearway.validator import validate

# The retrieve/draft steps are seams. Production builds the real implementations (which need the
# corpus stack / Ollama); offline spine tests inject canned stubs instead.
Retrieve = Callable[[Finding], list[Citation]]
Draft = Callable[[Finding, list[Citation]], DraftRow]

# Frozen run identity for M1. config_id/eval_set_id are METRIC LABELS, so they are stable and
# low-cardinality by design (the T9 discipline); run_id is per-invocation and is NOT a label (it
# only ties a run's traces together for eval's single-run guard). config_id forks from M0's
# "m0-single@1" so the real-LLM metric series is never blended with the M0 stub runs.
_CONFIG_ID = "m1-single@1"  # frozen routing config: one real model, no routing (routing is M4)
_MODEL = "gemma4:31b"  # the pinned M1 chat model (recorded per trace; swappable at M4)
_EVAL_SET_ID = "m0-core@1"  # the fixture set under test
_SCAN_RETRIES = 1  # minimal retry: the scan is the only external/flaky step


@dataclass(frozen=True)
class RunResult:
    """Everything one `clearway run` produced: the aggregated report + its per-finding traces."""

    report: EvalReport
    traces: list[Trace]


def _default_retrieve() -> Retrieve:
    """Build the real RAG retriever (real embedder + pgvector, at the frozen corpus_version) and
    return its bound `retrieve`. Constructed lazily so the corpus stack is required only when a
    run actually retrieves — offline tests inject their own retriever and never reach this."""
    from clearway.corpus import LiteLLMEmbedder, PgCorpusStore, build_corpus_version
    from clearway.retriever import Retriever

    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    return Retriever(embedder, store, build_corpus_version(embedder)).retrieve


def _default_draft() -> Draft:
    """Build the real LLM drafter (LiteLLM → Ollama gemma4:31b) and return its bound `draft`.
    Constructed lazily so Ollama is required only when a run actually drafts — offline tests
    inject their own drafter and never reach this."""
    from clearway.drafter import Drafter, LiteLLMClient

    return Drafter(LiteLLMClient()).draft


def _scan_with_retry(target: str) -> ScanResult:
    """Scan with one retry. The headless-browser scan is the only external/flaky step;
    everything downstream is deterministic local code, so this is the whole 'minimal retry'."""
    for attempt in range(_SCAN_RETRIES + 1):
        try:
            return scan(target)
        except Exception:
            if attempt == _SCAN_RETRIES:
                raise
    raise AssertionError("unreachable")  # the loop always returns or raises


def run(target: str, *, retrieve: Retrieve | None = None, draft: Draft | None = None) -> RunResult:
    """Run the forward path over one page and aggregate a trust-metric report.

    `retrieve` and `draft` are the two model-facing seams: `None` (production) builds the real
    implementations — retrieval needs the corpus stack, drafting needs Ollama — so the reported
    `citation_hallucination_rate` is the *honest, emergent* rate. Tests inject canned stubs to
    exercise the spine offline (there is no planting lever — that M0 scaffold was retired at T3).
    """
    do_retrieve = retrieve if retrieve is not None else _default_retrieve()
    do_draft = draft if draft is not None else _default_draft()
    oracle: Oracle = AxeCoreOracle()
    scan_result = _scan_with_retry(target)
    findings = normalize(scan_result)

    run_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    traces: list[Trace] = []
    for finding in findings:
        citations = do_retrieve(finding)
        draft_row = do_draft(finding, citations)
        checks = validate(draft_row, finding, oracle)
        traces.append(
            Trace(
                run_id=run_id,
                finding_id=finding.id,
                config_id=_CONFIG_ID,
                model=_MODEL,
                retrieved_sc_ids=[c.sc_id for c in citations],
                confidence=draft_row.confidence,
                checks=checks,
                created_at=now,
            )
        )

    report = evaluate(
        traces,
        eval_set_id=_EVAL_SET_ID,
        oracle_regime=oracle.regime,
        oracle_version=oracle.version,
        created_at=now,
    )
    return RunResult(report=report, traces=traces)
