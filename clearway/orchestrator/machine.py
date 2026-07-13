"""The durable state machine — checkpointed, retried, resumable execution of the per-finding
pipeline (retrieve -> draft -> validate). ARCHITECTURE §4.6.

`execute()` replaces the ad-hoc loop `orchestrator/run.py` used to run inline: each step is
checkpointed to the `OrchestratorStore`, and a step already marked DONE for this run is REPLAYED
from its cached result rather than recomputed — the same semantic Temporal's event-sourcing replay
and LangGraph's state-checkpointing both rely on (a status-only checkpoint would be a materially
weaker primitive). `run()` / `run_set()` (in `run.py`) call this and stay thin wrappers: scan,
normalize, then one call into `execute(...)`.

Tracing (T2): the run/finding/step nesting is emitted as OTel spans through the `trace` *API*
only — a no-op until the CLI calls `observability.setup_tracing()`, so offline tests still need no
collector. Retries and failures surface as span events + an ERROR status on the step span.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, get_origin

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, TypeAdapter

from clearway.drafter import DraftResult
from clearway.llm import LLMUsage
from clearway.observability.operational import record_llm_call, record_step
from clearway.orchestrator.store import OrchestratorStore
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    CitationCheck,
    CitationVerdict,
    DraftRow,
    Finding,
    NeedsReview,
    Oracle,
    PipelineStep,
    ReviewReason,
    ReviewStatus,
    RunState,
    RunStatus,
    StepState,
    StepStatus,
    Trace,
)
from clearway.validator import validate

_tracer = trace.get_tracer("clearway.orchestrator")

# Placeholder confidence floor for the HITL gate (decision #8). DORMANT until M5 calibration: per
# the M1 weak-spots read, real drafter confidence sits at 0.9–1.0 regardless of correctness, so
# `axe_incomplete` / `unverifiable_judgment` are the effective M2 triggers, not this one.
_LOW_CONFIDENCE_THRESHOLD = 0.5

# The retrieve/draft steps are seams. Production builds the real implementations; offline tests
# inject canned stubs instead. Mirrors the M0/M1 seam already established in run.py.
Retrieve = Callable[[Finding], list[Citation]]
# The draft seam may return a bare `DraftRow` (offline stubs — no LLM call, so no usage) or a
# `DraftResult` carrying the real call's usage; `execute()` normalizes both (see `_run_draft`).
Draft = Callable[[Finding, list[Citation]], "DraftRow | DraftResult"]
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
    with _tracer.start_as_current_span("clearway.run") as run_span:
        run_span.set_attribute("clearway.run_id", run_id)
        run_span.set_attribute("clearway.config_id", config_id)
        run_span.set_attribute("clearway.model", model)
        run_span.set_attribute("clearway.findings.count", len(findings))

        if existing and on_resume is not None:
            # Scoped to THIS call's findings, not every id ever checkpointed under run_id —
            # run_set() calls execute() once per page under one shared run_id, so an unscoped count
            # would leak earlier pages' done-counts into a later page's notice.
            batch_ids = {f.id for f in findings}
            done_ids = {
                fid
                for (fid, step), s in existing.items()
                if step is PipelineStep.VALIDATE and s.status is StepStatus.DONE and fid in batch_ids
            }
            next_finding_id = next((f.id for f in findings if f.id not in done_ids), None)
            on_resume(run_id, len(done_ids), len(findings), next_finding_id)

        store.save_run(RunState(run_id=run_id, config_id=config_id, status=RunStatus.RUNNING, created_at=created_at))

        traces: list[Trace] = []
        for finding in findings:
            trace_row = _process_finding(
                finding,
                store=store,
                existing=existing,
                run_id=run_id,
                config_id=config_id,
                model=model,
                do_retrieve=do_retrieve,
                do_draft=do_draft,
                oracle=oracle,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
                created_at=created_at,
            )
            if trace_row is not None:
                traces.append(trace_row)

        store.save_run(RunState(run_id=run_id, config_id=config_id, status=RunStatus.DONE, created_at=created_at))
        return traces


def _process_finding(
    finding: Finding,
    *,
    store: OrchestratorStore,
    existing: dict[tuple[str, PipelineStep], StepState],
    run_id: str,
    config_id: str,
    model: str,
    do_retrieve: Retrieve,
    do_draft: Draft,
    oracle: Oracle,
    max_attempts: int,
    backoff_seconds: float,
    created_at: datetime,
) -> Trace | None:
    """Drive one finding through retrieve -> draft -> validate under a `clearway.finding` span,
    returning its `Trace` — or None if any step failed (that finding is skipped; the run continues).
    Each seam below is invoked synchronously inside `_step()`, so the loop-closure late-binding
    gotcha does not apply to the captured `finding` / `citations`."""
    with _tracer.start_as_current_span("clearway.finding") as span:
        span.set_attribute("clearway.finding_id", finding.id)
        span.set_attribute("clearway.model", model)

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
            return None

        # Capture the draft call's usage out-of-band: `_step` checkpoints only the `DraftRow`
        # (usage is live telemetry, not durable state), and the box stays empty on replay — an
        # honest `None` quartet, since a replayed step makes no fresh LLM call.
        usage_box: list[LLMUsage] = []

        def _run_draft() -> DraftRow:
            out = do_draft(finding, citations)
            if isinstance(out, DraftResult):
                usage_box.append(out.usage)
                return out.row
            return out  # bare DraftRow: an offline stub with no LLM call, so no usage

        draft_row = _step(
            store,
            existing,
            run_id,
            finding.id,
            PipelineStep.DRAFT,
            _run_draft,
            DraftRow,
            max_attempts,
            backoff_seconds,
            created_at,
        )
        if draft_row is None:
            return None
        usage = usage_box[0] if usage_box else None
        if usage is not None:  # a real LLM call happened (not a replay or a bare-row stub)
            record_llm_call(model=model, usage=usage)

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
            return None

        # HITL gate (T3): evaluated post-validation, once the DraftRow + checks exist. A flagged
        # finding's assembly is interrupted (return None) until a human resolves its NeedsReview
        # record — the rest of the run continues. On a resume that carries a human outcome, the
        # approved/edited row is assembled instead. See ARCHITECTURE §4.6 + decisions #5/#6/#8.
        reason = _review_reason(finding, draft_row, checks)
        if reason is not None:
            gated = _gate(
                finding,
                store=store,
                run_id=run_id,
                draft_row=draft_row,
                checks=checks,
                reason=reason,
                oracle=oracle,
                created_at=created_at,
                span=span,
            )
            if gated is None:
                return None  # still pending / rejected — withheld from the report
            draft_row, checks = gated  # approved (original) or edited row flows into assembly

        return Trace(
            run_id=run_id,
            finding_id=finding.id,
            config_id=config_id,
            model=model,
            retrieved_sc_ids=[c.sc_id for c in citations],
            confidence=draft_row.confidence,
            cost_usd=usage.cost_usd if usage else None,
            tokens_in=usage.tokens_in if usage else None,
            tokens_out=usage.tokens_out if usage else None,
            latency_ms=usage.latency_ms if usage else None,
            checks=checks,
            created_at=created_at,
        )


def _review_reason(finding: Finding, draft_row: DraftRow, checks: list[CitationCheck]) -> Optional[ReviewReason]:
    """Which single review trigger fires for this finding, by precedence `low_confidence` >
    `axe_incomplete` > `unverifiable_judgment` (decision #5) — or None if none apply. The triggers
    overlap (an axe-incomplete finding also yields UNVERIFIABLE citations), so precedence collapses
    them to one stored reason."""
    if draft_row.confidence < _LOW_CONFIDENCE_THRESHOLD:
        return ReviewReason.LOW_CONFIDENCE
    if finding.source_bucket is AxeBucket.INCOMPLETE:
        return ReviewReason.AXE_INCOMPLETE
    if any(c.verdict is CitationVerdict.UNVERIFIABLE for c in checks):
        return ReviewReason.UNVERIFIABLE_JUDGMENT
    return None


def _gate(
    finding: Finding,
    *,
    store: OrchestratorStore,
    run_id: str,
    draft_row: DraftRow,
    checks: list[CitationCheck],
    reason: ReviewReason,
    oracle: Oracle,
    created_at: datetime,
    span: trace.Span,
) -> Optional[tuple[DraftRow, list[CitationCheck]]]:
    """Resolve the HITL gate for one flagged finding. Returns None if the finding is withheld from
    the report (no human outcome yet, or rejected); otherwise the `(draft, checks)` to assemble —
    the original draft on approval, or the human's `edited_draft` (re-validated, since it is new
    input) on an edit. Idempotent across resumes: a still-pending record is left untouched."""
    span.set_attribute("clearway.needs_review", True)
    span.set_attribute("clearway.review_reason", reason.value)

    review = store.load_review(run_id, finding.id)
    if review is None:
        # Fresh flag: persist the durable interrupt and withhold the finding.
        store.save_review(
            NeedsReview(
                run_id=run_id,
                finding_id=finding.id,
                draft=draft_row,
                reason=reason,
                status=ReviewStatus.PENDING,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        span.set_attribute("clearway.review_status", ReviewStatus.PENDING.value)
        return None

    span.set_attribute("clearway.review_status", review.status.value)
    if review.status in (ReviewStatus.PENDING, ReviewStatus.REJECTED):
        # Awaiting a human, or the human rejected the draft — either way it never enters the output.
        return None

    # Approved or edited: the human-approved row assembles. An edit is fresh input, so re-validate
    # it (cheap, no LLM) to produce checks that match what actually ships, not the original draft's.
    approved = review.edited_draft if review.status is ReviewStatus.EDITED and review.edited_draft else review.draft
    approved_checks = validate(approved, finding, oracle) if review.status is ReviewStatus.EDITED else checks
    return approved, approved_checks


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
    """Run one checkpointed step under a `clearway.step.<step>` span: replay a cached DONE result,
    otherwise retry `fn()` with exponential backoff up to `max_attempts`. Each failed attempt is a
    span event; exhaustion sets the span's status to ERROR. Returns None if the step ultimately
    failed — the caller halts that finding's remaining steps and moves to the next finding."""
    with _tracer.start_as_current_span(f"clearway.step.{step.value}") as span:
        span.set_attribute("clearway.finding_id", finding_id)
        span.set_attribute("clearway.step", step.value)

        cached = existing.get((finding_id, step))
        if cached is not None and cached.status is StepStatus.DONE:
            result_json = store.load_step_result(run_id, finding_id, step)
            if result_json is not None:
                span.set_attribute("clearway.replayed", True)
                return _deserialize(result_json, result_type)
            # DONE but no cached result (shouldn't happen in practice) — recompute below, don't crash.

        step_start = time.perf_counter()
        attempts = 0
        last_exc: Exception | None = None
        while attempts < max_attempts:
            attempts += 1
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — deliberately broad; recorded as a span event
                last_exc = exc
                span.add_event(
                    "attempt_failed",
                    {"attempt": attempts, "exception.type": type(exc).__name__, "will_retry": attempts < max_attempts},
                )
                if attempts < max_attempts:
                    time.sleep(backoff_seconds * (2 ** (attempts - 1)))
                continue
            span.set_attribute("clearway.attempts", attempts)
            record_step(step=step.value, attempts=attempts, failed=False, duration_s=time.perf_counter() - step_start)
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

        span.set_attribute("clearway.attempts", attempts)
        record_step(step=step.value, attempts=attempts, failed=True, duration_s=time.perf_counter() - step_start)
        if last_exc is not None:
            span.record_exception(last_exc)
        span.set_status(Status(StatusCode.ERROR, f"{step.value} failed after {attempts} attempts"))
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
