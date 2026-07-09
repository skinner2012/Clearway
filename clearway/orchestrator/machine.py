"""The durable state machine — checkpointed, retried, resumable execution of the per-finding
pipeline (retrieve -> draft -> validate). ARCHITECTURE §4.6.

`execute()` replaces the ad-hoc loop `orchestrator/run.py` used to run inline: each step is
checkpointed to the `OrchestratorStore`, and a step already marked DONE for this run is REPLAYED
from its cached result rather than recomputed — the same semantic Temporal's event-sourcing replay
and LangGraph's state-checkpointing both rely on (a status-only checkpoint would be a materially
weaker primitive). `run()` / `run_set()` (in `run.py`) call this and stay thin wrappers: scan,
normalize, then one call into `execute(...)`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, get_origin

from pydantic import BaseModel, TypeAdapter

from clearway.orchestrator.store import OrchestratorStore
from clearway.schemas.models import (
    Citation,
    CitationCheck,
    DraftRow,
    Finding,
    Oracle,
    PipelineStep,
    RunState,
    RunStatus,
    StepState,
    StepStatus,
    Trace,
)
from clearway.validator import validate

# The retrieve/draft steps are seams. Production builds the real implementations; offline tests
# inject canned stubs instead. Mirrors the M0/M1 seam already established in run.py.
Retrieve = Callable[[Finding], list[Citation]]
Draft = Callable[[Finding, list[Citation]], DraftRow]
# Called once, only when resuming: (run_id, done_count, total_count, next_finding_id | None).
OnResume = Callable[[str, int, int, Optional[str]], None]


def execute(
    findings: list[Finding],
    *,
    run_id: str,
    config_id: str,
    model: str,
    created_at: datetime,
    do_retrieve: Retrieve,
    do_draft: Draft,
    oracle: Oracle,
    store: OrchestratorStore,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    on_resume: Optional[OnResume] = None,
) -> list[Trace]:
    """Drive every finding through retrieve -> draft -> validate, checkpointing each step to
    `store`. A step already checkpointed DONE for this `run_id` is replayed from its cached
    result, not recomputed. A step that exhausts `max_attempts` is marked FAILED and that
    finding's pipeline stops there — the run continues with the next finding, it never crashes."""
    existing = {(s.finding_id, s.step): s for s in store.load_steps(run_id)}
    if existing and on_resume is not None:
        done_ids = {
            fid for (fid, step), s in existing.items() if step is PipelineStep.VALIDATE and s.status is StepStatus.DONE
        }
        next_finding_id = next((f.id for f in findings if f.id not in done_ids), None)
        on_resume(run_id, len(done_ids), len(findings), next_finding_id)

    store.save_run(RunState(run_id=run_id, config_id=config_id, status=RunStatus.RUNNING, created_at=created_at))

    traces: list[Trace] = []
    for finding in findings:
        # Each lambda below is invoked synchronously inside `_step()` before the next `finding`
        # is bound — the classic loop-closure-late-binding gotcha does not apply here.
        citations = _step(
            store,
            existing,
            run_id,
            finding.id,
            PipelineStep.RETRIEVE,
            lambda: do_retrieve(finding),
            list[Citation],
            max_attempts,
            backoff_seconds,
            created_at,
        )
        if citations is None:
            continue

        draft_row = _step(
            store,
            existing,
            run_id,
            finding.id,
            PipelineStep.DRAFT,
            lambda: do_draft(finding, citations),
            DraftRow,
            max_attempts,
            backoff_seconds,
            created_at,
        )
        if draft_row is None:
            continue

        checks = _step(
            store,
            existing,
            run_id,
            finding.id,
            PipelineStep.VALIDATE,
            lambda: validate(draft_row, finding, oracle),
            list[CitationCheck],
            max_attempts,
            backoff_seconds,
            created_at,
        )
        if checks is None:
            continue

        traces.append(
            Trace(
                run_id=run_id,
                finding_id=finding.id,
                config_id=config_id,
                model=model,
                retrieved_sc_ids=[c.sc_id for c in citations],
                confidence=draft_row.confidence,
                checks=checks,
                created_at=created_at,
            )
        )

    store.save_run(RunState(run_id=run_id, config_id=config_id, status=RunStatus.DONE, created_at=created_at))
    return traces


def _step(
    store: OrchestratorStore,
    existing: dict[tuple[str, PipelineStep], StepState],
    run_id: str,
    finding_id: str,
    step: PipelineStep,
    fn: Callable[[], Any],
    result_type: Any,
    max_attempts: int,
    backoff_seconds: float,
    updated_at: datetime,
) -> Any:
    """Run one checkpointed step: replay a cached DONE result, otherwise retry `fn()` with
    exponential backoff up to `max_attempts`. Returns None if the step ultimately failed —
    the caller halts that finding's remaining steps and moves to the next finding."""
    cached = existing.get((finding_id, step))
    if cached is not None and cached.status is StepStatus.DONE:
        result_json = store.load_step_result(run_id, finding_id, step)
        if result_json is not None:
            return _deserialize(result_json, result_type)
        # DONE but no cached result (shouldn't happen in practice) — recompute below rather than crash.

    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        try:
            result = fn()
        except Exception:  # noqa: BLE001 — deliberately broad; T2 records retry/failure detail
            if attempts < max_attempts:
                time.sleep(backoff_seconds * (2 ** (attempts - 1)))
            continue
        store.save_step(
            StepState(
                run_id=run_id,
                finding_id=finding_id,
                step=step,
                status=StepStatus.DONE,
                attempts=attempts,
                updated_at=updated_at,
            ),
            result_json=_serialize(result, result_type),
        )
        return result

    store.save_step(
        StepState(
            run_id=run_id,
            finding_id=finding_id,
            step=step,
            status=StepStatus.FAILED,
            attempts=attempts,
            updated_at=updated_at,
        ),
        result_json=None,
    )
    return None


def _serialize(result: Any, result_type: Any) -> str:
    if get_origin(result_type) is list:
        return TypeAdapter(result_type).dump_json(result).decode()
    assert isinstance(result, BaseModel)
    return result.model_dump_json()


def _deserialize(result_json: str, result_type: Any) -> Any:
    if get_origin(result_type) is list:
        return TypeAdapter(result_type).validate_json(result_json)
    return result_type.model_validate_json(result_json)
