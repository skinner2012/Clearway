"""Eval aggregation — fold per-finding `CitationCheck`s into the M0 trust metric.

M0 computes exactly one quality metric, `citation_hallucination_rate`, and wraps
it in a reproducible `EvalReport` (ARCHITECTURE §4.5). The checks are read from
each `Trace.checks` (the authoritative per-finding record), not a side list.

`evaluate` reads `run_id` / `config_id` off the traces (they live there); the
report labels — `eval_set_id`, `oracle_regime`, `oracle_version`, `created_at` —
are passed in by the caller (the orchestrator, T10), since the oracle has already
done its job by this point and `eval/` holds no oracle of its own.
"""

from __future__ import annotations

from datetime import datetime

from clearway.schemas.models import (
    CitationVerdict,
    EvalMetrics,
    EvalReport,
    OracleRegime,
    Trace,
)


def compute_metrics(traces: list[Trace]) -> EvalMetrics:
    """Count citations and hallucinations across all traces → `EvalMetrics`."""
    citations_total = sum(len(t.checks) for t in traces)
    hallucinations_total = sum(1 for t in traces for c in t.checks if c.verdict is CitationVerdict.HALLUCINATED)
    rate = hallucinations_total / citations_total if citations_total else 0.0
    return EvalMetrics(
        citation_hallucination_rate=rate,
        findings_total=len(traces),
        citations_total=citations_total,
        hallucinations_total=hallucinations_total,
    )


def evaluate(
    traces: list[Trace],
    *,
    eval_set_id: str,
    oracle_regime: OracleRegime,
    oracle_version: str,
    created_at: datetime,
) -> EvalReport:
    """Aggregate one run's traces into an `EvalReport`.

    `run_id` / `config_id` are read off the traces (all traces in a run share them;
    a mismatch means the traces are from different runs, which is an error).
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
        metrics=compute_metrics(traces),
        trace_ids=[t.finding_id for t in traces],
    )
