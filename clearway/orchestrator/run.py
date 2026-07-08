"""M0 orchestrator — wire the forward path over one page into a trust-metric report.

This is the spine T2–T9 were built for: scan → normalize → (stub) retrieve → draft →
validate → eval. It assembles one `Trace` per finding and aggregates them into an
`EvalReport`. It is deliberately **pure** — no OTel emission here; the CLI owns that
side effect (so the whole pipeline is testable offline, without the stack running).

M0 orchestration is intentionally thin: a straight pass over findings with one retry on
the scan. Durable primitives (checkpoint, idempotent resume, HITL) are M2 (ARCHITECTURE §4.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from clearway.drafter import draft
from clearway.eval import evaluate
from clearway.normalizer import normalize
from clearway.oracle import AxeCoreOracle
from clearway.scanner import scan
from clearway.schemas.models import Citation, EvalReport, Finding, Oracle, ScanResult, Trace
from clearway.validator import validate

# The retrieve step is a seam: `Finding -> Citation[]`. Production builds the real RAG retriever
# (needs the corpus stack); offline spine tests inject a canned stub instead.
Retrieve = Callable[[Finding], list[Citation]]

# Frozen run identity for M0. config_id/eval_set_id are METRIC LABELS, so they are stable
# and low-cardinality by design (the T9 discipline); run_id is per-invocation and is NOT a
# label (it only ties a run's traces together for eval's single-run guard).
_CONFIG_ID = "m0-single@1"  # frozen routing config: one stub model in M0
_MODEL = "stub-m0"  # no real LLM in M0
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


def run(target: str, *, plant: bool = True, retrieve: Retrieve | None = None) -> RunResult:
    """Run the forward path over one page and aggregate a trust-metric report.

    `plant=True` (default) keeps the drafter's intentional citation faults, so the run scores
    a non-zero `citation_hallucination_rate`. `plant=False` is the `--clean` lever: the drafter
    cites the retrieved (correct) SCs, scoring 0 — two runs then draw a *moving* line on the panel.

    `retrieve` is the retrieval seam: `None` (production) builds the real RAG retriever, which
    needs the corpus stack up; tests inject a canned stub to exercise the spine offline.
    """
    do_retrieve = retrieve if retrieve is not None else _default_retrieve()
    oracle: Oracle = AxeCoreOracle()
    scan_result = _scan_with_retry(target)
    findings = normalize(scan_result)

    run_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    traces: list[Trace] = []
    for finding in findings:
        citations = do_retrieve(finding)
        draft_row = draft(finding, citations, plant=plant)
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
