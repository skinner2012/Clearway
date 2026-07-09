"""T1: `OrchestratorStore` persists durable run/step checkpoints, and caches each step's result
so a resumed run can replay it instead of recomputing.

Two layers, mirroring the `corpus/store.py` seam-testing precedent (test_corpus.py):
- **offline** (default): `InMemoryOrchestratorStore` — proves the checkpoint/replay *mechanics*.
- **gated** (`postgres_up`): the real path — `PgOrchestratorStore` against Postgres. Skips
  cleanly when the DB is down, so the offline suite stays green.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clearway.orchestrator.store import InMemoryOrchestratorStore, OrchestratorStore, PgOrchestratorStore
from clearway.schemas.models import (
    Conformance,
    DraftRow,
    NeedsReview,
    PipelineStep,
    ReviewReason,
    ReviewStatus,
    RunState,
    RunStatus,
    StepState,
    StepStatus,
)

_AT = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def _draft(finding_id: str = "f1", remediation: str = "add alt text") -> DraftRow:
    return DraftRow(
        finding_id=finding_id,
        conformance=Conformance.DOES_NOT_SUPPORT,
        remediation=remediation,
        confidence=0.9,
    )


# --- InMemoryOrchestratorStore (offline) --------------------------------------


def test_save_and_load_run_state() -> None:
    store = InMemoryOrchestratorStore()
    run = RunState(run_id="r1", config_id="m2-single@1", status=RunStatus.RUNNING, created_at=_AT)
    store.save_run(run)
    assert store.load_run("r1") == run


def test_load_run_returns_none_for_unknown_run_id() -> None:
    assert InMemoryOrchestratorStore().load_run("nope") is None


def test_save_and_load_step_state_with_cached_result() -> None:
    store = InMemoryOrchestratorStore()
    step = StepState(run_id="r1", finding_id="f1", step=PipelineStep.RETRIEVE, status=StepStatus.DONE, updated_at=_AT)
    store.save_step(step, result_json='[{"sc_id": "1.1.1"}]')
    assert store.load_steps("r1") == [step]
    assert store.load_step_result("r1", "f1", PipelineStep.RETRIEVE) == '[{"sc_id": "1.1.1"}]'


def test_load_steps_scopes_by_run_id() -> None:
    store = InMemoryOrchestratorStore()
    store.save_step(
        StepState(run_id="r1", finding_id="f1", step=PipelineStep.RETRIEVE, status=StepStatus.DONE, updated_at=_AT),
        result_json="[]",
    )
    store.save_step(
        StepState(run_id="r2", finding_id="f1", step=PipelineStep.RETRIEVE, status=StepStatus.DONE, updated_at=_AT),
        result_json="[]",
    )
    assert len(store.load_steps("r1")) == 1
    assert len(store.load_steps("r2")) == 1


def test_save_step_upserts_on_repeat() -> None:
    """Re-checkpointing the same (run_id, finding_id, step) updates in place, not duplicates —
    the idempotency key the durable machine relies on."""
    store = InMemoryOrchestratorStore()
    pending = StepState(
        run_id="r1", finding_id="f1", step=PipelineStep.DRAFT, status=StepStatus.PENDING, attempts=1, updated_at=_AT
    )
    store.save_step(pending, result_json=None)
    done = pending.model_copy(update={"status": StepStatus.DONE, "attempts": 2})
    store.save_step(done, result_json='{"finding_id": "f1"}')

    steps = store.load_steps("r1")
    assert len(steps) == 1
    assert steps[0].status is StepStatus.DONE
    assert steps[0].attempts == 2


def test_load_step_result_is_none_for_a_failed_step() -> None:
    """A step that exhausted retries has no cached result — there is nothing to replay."""
    store = InMemoryOrchestratorStore()
    step = StepState(run_id="r1", finding_id="f1", step=PipelineStep.DRAFT, status=StepStatus.FAILED, updated_at=_AT)
    store.save_step(step, result_json=None)
    assert store.load_step_result("r1", "f1", PipelineStep.DRAFT) is None


def test_in_memory_store_satisfies_the_protocol() -> None:
    assert isinstance(InMemoryOrchestratorStore(), OrchestratorStore)


# --- NeedsReview persistence (offline) ----------------------------------------


def test_save_and_load_review() -> None:
    store = InMemoryOrchestratorStore()
    review = NeedsReview(
        run_id="r1",
        finding_id="f1",
        draft=_draft("f1"),
        reason=ReviewReason.AXE_INCOMPLETE,
        created_at=_AT,
        updated_at=_AT,
    )
    store.save_review(review)
    assert store.load_review("r1", "f1") == review


def test_load_review_returns_none_for_unknown_key() -> None:
    assert InMemoryOrchestratorStore().load_review("r1", "nope") is None


def test_save_review_upserts_the_human_outcome() -> None:
    """Approving/editing a review updates the same `(run_id, finding_id)` row in place, carrying
    the `edited_draft` — the durable interrupt the resume gate later reads back."""
    store = InMemoryOrchestratorStore()
    pending = NeedsReview(
        run_id="r1",
        finding_id="f1",
        draft=_draft("f1"),
        reason=ReviewReason.UNVERIFIABLE_JUDGMENT,
        created_at=_AT,
        updated_at=_AT,
    )
    store.save_review(pending)
    edited = pending.model_copy(
        update={"status": ReviewStatus.EDITED, "edited_draft": _draft("f1", "add a descriptive alt attribute")}
    )
    store.save_review(edited)

    loaded = store.load_review("r1", "f1")
    assert loaded is not None
    assert loaded.status is ReviewStatus.EDITED
    assert loaded.edited_draft is not None
    assert loaded.edited_draft.remediation == "add a descriptive alt attribute"


def test_load_reviews_filters_by_status() -> None:
    store = InMemoryOrchestratorStore()
    store.save_review(
        NeedsReview(
            run_id="r1",
            finding_id="f1",
            draft=_draft("f1"),
            reason=ReviewReason.AXE_INCOMPLETE,
            created_at=_AT,
            updated_at=_AT,
        )
    )
    store.save_review(
        NeedsReview(
            run_id="r1",
            finding_id="f2",
            draft=_draft("f2"),
            reason=ReviewReason.AXE_INCOMPLETE,
            status=ReviewStatus.APPROVED,
            created_at=_AT,
            updated_at=_AT,
        )
    )
    assert len(store.load_reviews()) == 2
    assert len(store.load_reviews(status=ReviewStatus.PENDING)) == 1
    assert store.load_reviews(status=ReviewStatus.PENDING)[0].finding_id == "f1"


# --- PgOrchestratorStore (gated: real Postgres) -------------------------------


def _postgres_up() -> bool:
    try:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", connect_timeout=1):
            return True
    except Exception:
        return False


postgres_up = pytest.mark.skipif(not _postgres_up(), reason="Postgres not running (`docker compose up -d postgres`)")


@postgres_up
def test_real_pg_store_roundtrips_run_and_step_with_cached_result() -> None:
    store = PgOrchestratorStore()
    store.ensure_schema()
    run_id = "pytest-t1-store"
    try:
        run = RunState(run_id=run_id, config_id="pytest@1", status=RunStatus.RUNNING, created_at=_AT)
        store.save_run(run)
        assert store.load_run(run_id) == run

        step = StepState(
            run_id=run_id, finding_id="f1", step=PipelineStep.DRAFT, status=StepStatus.DONE, updated_at=_AT
        )
        store.save_step(step, result_json='{"finding_id": "f1"}')
        assert store.load_steps(run_id) == [step]
        assert store.load_step_result(run_id, "f1", PipelineStep.DRAFT) == '{"finding_id": "f1"}'
    finally:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", autocommit=True) as conn:
            conn.execute("DELETE FROM step_state WHERE run_id = %s", (run_id,))
            conn.execute("DELETE FROM run_state WHERE run_id = %s", (run_id,))


@postgres_up
def test_real_pg_store_roundtrips_a_review_with_an_edit() -> None:
    store = PgOrchestratorStore()
    store.ensure_schema()
    run_id = "pytest-t3-review"
    try:
        pending = NeedsReview(
            run_id=run_id,
            finding_id="f1",
            draft=_draft("f1"),
            reason=ReviewReason.AXE_INCOMPLETE,
            created_at=_AT,
            updated_at=_AT,
        )
        store.save_review(pending)
        assert store.load_review(run_id, "f1") == pending

        edited = pending.model_copy(
            update={"status": ReviewStatus.EDITED, "edited_draft": _draft("f1", "reworded remediation")}
        )
        store.save_review(edited)
        loaded = store.load_review(run_id, "f1")
        assert loaded is not None
        assert loaded.status is ReviewStatus.EDITED
        assert loaded.edited_draft is not None
        assert loaded.edited_draft.remediation == "reworded remediation"
    finally:
        import psycopg

        with psycopg.connect("postgresql://clearway:clearway@localhost:5432/clearway", autocommit=True) as conn:
            conn.execute("DELETE FROM needs_review WHERE run_id = %s", (run_id,))
