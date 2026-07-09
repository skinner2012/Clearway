"""Eval aggregation — fold per-finding `CitationCheck`s into the trust metrics.

M1 wraps a stratified set of trust metrics in a reproducible `EvalReport` (ARCHITECTURE §4.5):
the overall `citation_hallucination_rate` plus its split by oracle-verifiability — the verifiable
rate (~0 by construction) and the `unverifiable_share` (the honest headline). The checks are read
from each `Trace.checks` (the authoritative per-finding record), not a side list.

`evaluate` reads `run_id` / `config_id` off the traces (they live there); the
report labels — `eval_set_id`, `oracle_regime`, `oracle_version`, `created_at` —
are passed in by the caller (the orchestrator, T10), since the oracle has already
done its job by this point and `eval/` holds no oracle of its own.
"""

from __future__ import annotations

from datetime import datetime

from clearway.eval.edit_distance import mean_expert_edit_distance
from clearway.schemas.models import (
    CitationVerdict,
    EvalMetrics,
    EvalReport,
    NeedsReview,
    OracleRegime,
    Trace,
)


def compute_metrics(traces: list[Trace], reviews: list[NeedsReview] | None = None) -> EvalMetrics:
    """Count citations and hallucinations across all traces → `EvalMetrics`.

    The M1 stratification splits citations by whether an automated oracle could verify them:
    UNVERIFIABLE (no oracle verdict) vs verifiable (VERIFIED | HALLUCINATED). `hallucinations_total`
    is the numerator for BOTH rates — UNVERIFIABLE is never a hallucination, so all hallucinations
    live in the verifiable subset. `unverifiable_share` is the honest headline (what M5 must target).

    `reviews` is the M2 HITL signal: the run's `NeedsReview` records, whose EDITED entries yield
    `expert_edit_distance` (the run mean). Omitted (the M1 offline path) → the metric stays 0.0.
    """
    checks = [c for t in traces for c in t.checks]
    citations_total = len(checks)
    hallucinations_total = sum(1 for c in checks if c.verdict is CitationVerdict.HALLUCINATED)
    unverifiable_total = sum(1 for c in checks if c.verdict is CitationVerdict.UNVERIFIABLE)
    verifiable_total = citations_total - unverifiable_total
    return EvalMetrics(
        citation_hallucination_rate=hallucinations_total / citations_total if citations_total else 0.0,
        findings_total=len(traces),
        citations_total=citations_total,
        hallucinations_total=hallucinations_total,
        citation_hallucination_rate_verifiable=(hallucinations_total / verifiable_total if verifiable_total else 0.0),
        unverifiable_share=unverifiable_total / citations_total if citations_total else 0.0,
        citations_verifiable_total=verifiable_total,
        citations_unverifiable_total=unverifiable_total,
        expert_edit_distance=mean_expert_edit_distance(reviews or []),
    )


def evaluate(
    traces: list[Trace],
    *,
    eval_set_id: str,
    oracle_regime: OracleRegime,
    oracle_version: str,
    created_at: datetime,
    reviews: list[NeedsReview] | None = None,
) -> EvalReport:
    """Aggregate one run's traces into an `EvalReport`.

    `run_id` / `config_id` are read off the traces (all traces in a run share them;
    a mismatch means the traces are from different runs, which is an error). `reviews` are this
    run's HITL `NeedsReview` records, scoped to `run_id` by the caller — their EDITED entries feed
    `expert_edit_distance` (M2 T4). None (the M1 offline path) → the metric stays 0.0.
    """
    if not traces:
        raise ValueError("evaluate() needs at least one trace to report on")

    run_ids = {t.run_id for t in traces}
    if len(run_ids) != 1:
        raise ValueError(f"traces span multiple runs: {sorted(run_ids)}")
    config_ids = {t.config_id for t in traces}
    if len(config_ids) != 1:
        raise ValueError(f"traces span multiple configs: {sorted(config_ids)}")

    return EvalReport(
        run_id=run_ids.pop(),
        config_id=config_ids.pop(),
        eval_set_id=eval_set_id,
        oracle_regime=oracle_regime,
        oracle_version=oracle_version,
        created_at=created_at,
        metrics=compute_metrics(traces, reviews),
        trace_ids=[t.finding_id for t in traces],
    )
