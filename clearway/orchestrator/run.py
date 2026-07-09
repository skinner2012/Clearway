"""Orchestrator — wire the forward path over one page (or a whole eval set) into a trust-metric
report.

`run()` / `run_set()` are thin wrappers: scan → normalize, then hand the findings to the durable
state machine (`orchestrator/machine.py`'s `execute()`) for the checkpointed, resumable
retrieve → draft → validate pass (ARCHITECTURE §4.6), then aggregate the resulting traces into an
`EvalReport`. They are deliberately **pure** — no OTel emission here; the CLI owns that side effect
(so the whole pipeline is testable offline, without the stack running).

The scan keeps its own minimal retry (the headless-browser step is the only external/flaky part
upstream of the durable machine); everything from `normalize()` onward is checkpointed, retried,
and resumable via `execute()`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from clearway.eval import evaluate
from clearway.normalizer import normalize
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator.machine import Draft, Retrieve, execute
from clearway.orchestrator.store import OrchestratorStore
from clearway.scanner import scan
from clearway.schemas.models import EvalReport, Oracle, ScanResult, Trace

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


def _default_store() -> OrchestratorStore:
    """Build the real Postgres checkpoint store (schema created if absent — cheap, idempotent
    DDL, so `clearway run`/`clearway eval` work against a fresh database with no separate setup
    step). Constructed lazily so Postgres is required only when a run actually checkpoints —
    offline tests inject `InMemoryOrchestratorStore` instead."""
    from clearway.orchestrator.store import PgOrchestratorStore

    store = PgOrchestratorStore()
    store.ensure_schema()
    return store


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


def _trace_page(
    target: str,
    *,
    run_id: str,
    created_at: datetime,
    do_retrieve: Retrieve,
    do_draft: Draft,
    oracle: Oracle,
    store: OrchestratorStore,
) -> list[Trace]:
    """Scan one page and produce one `Trace` per finding via the durable state machine —
    checkpointed retrieve → draft → validate, replayed (not recomputed) if this `run_id` was
    already partway through. Shared by the single-page `run` and the set-level `run_set`, so both
    stamp identical trace provenance; the caller owns `run_id`/`created_at` so a whole set lands
    under one run."""
    scan_result = _scan_with_retry(target)
    findings = normalize(scan_result)
    return execute(
        findings,
        run_id=run_id,
        config_id=_CONFIG_ID,
        model=_MODEL,
        created_at=created_at,
        do_retrieve=do_retrieve,
        do_draft=do_draft,
        oracle=oracle,
        store=store,
    )


def run(
    target: str,
    *,
    retrieve: Retrieve | None = None,
    draft: Draft | None = None,
    store: OrchestratorStore | None = None,
) -> RunResult:
    """Run the forward path over one page and aggregate a trust-metric report.

    `retrieve` and `draft` are the two model-facing seams: `None` (production) builds the real
    implementations — retrieval needs the corpus stack, drafting needs Ollama — so the reported
    `citation_hallucination_rate` is the *honest, emergent* rate. Tests inject canned stubs to
    exercise the spine offline (there is no planting lever — that M0 scaffold was retired at T3).
    `store` is the durable-checkpoint seam (`None` → real Postgres; tests inject
    `InMemoryOrchestratorStore`).
    """
    do_retrieve = retrieve if retrieve is not None else _default_retrieve()
    do_draft = draft if draft is not None else _default_draft()
    do_store = store if store is not None else _default_store()
    oracle: Oracle = AxeCoreOracle()
    run_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    traces = _trace_page(
        target,
        run_id=run_id,
        created_at=now,
        do_retrieve=do_retrieve,
        do_draft=do_draft,
        oracle=oracle,
        store=do_store,
    )
    report = evaluate(
        traces,
        eval_set_id=_EVAL_SET_ID,
        oracle_regime=oracle.regime,
        oracle_version=oracle.version,
        created_at=now,
    )
    return RunResult(report=report, traces=traces)


def run_set(
    targets: list[str],
    *,
    eval_set_id: str,
    retrieve: Retrieve | None = None,
    draft: Draft | None = None,
    store: OrchestratorStore | None = None,
) -> RunResult:
    """Run the forward path over every page in an eval set and aggregate ONE report.

    This is the M1 exit-criterion runner: all pages score under a single `run_id`, so their traces
    fold into one `EvalReport` labelled with the caller's `eval_set_id` (e.g. `m1-core@1`). The two
    incomplete-bucket fixtures contribute the UNVERIFIABLE citations that make `unverifiable_share`
    non-trivial — the honest headline the single-page `run` can't show on the verifiable-only home
    page. The real retriever/drafter/store are built once and reused across every page (not per
    page)."""
    if not targets:
        raise ValueError("run_set() needs at least one target")
    do_retrieve = retrieve if retrieve is not None else _default_retrieve()
    do_draft = draft if draft is not None else _default_draft()
    do_store = store if store is not None else _default_store()
    oracle: Oracle = AxeCoreOracle()
    run_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    traces: list[Trace] = []
    for target in targets:
        traces.extend(
            _trace_page(
                target,
                run_id=run_id,
                created_at=now,
                do_retrieve=do_retrieve,
                do_draft=do_draft,
                oracle=oracle,
                store=do_store,
            )
        )
    report = evaluate(
        traces,
        eval_set_id=eval_set_id,
        oracle_regime=oracle.regime,
        oracle_version=oracle.version,
        created_at=now,
    )
    return RunResult(report=report, traces=traces)
