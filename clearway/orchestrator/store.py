"""The `OrchestratorStore` seam — persists durable run/step checkpoints (ARCHITECTURE §4.6).

`PgOrchestratorStore` is the real store (Postgres — the same `clearway` database `corpus/store.py`
uses, new tables); `InMemoryOrchestratorStore` is its offline stand-in for unit tests, required so
the whole pipeline stays testable without a real Postgres connection (the `corpus/store.py`
precedent).

Each checkpointed step also carries a cached `result_json` — the step's actual output
(`list[Citation]` / `DraftRow` / `list[CitationCheck]`, depending on `step`), so a resumed run can
**replay** a completed step instead of recomputing it: the same semantic Temporal's event-sourcing
replay and LangGraph's state-checkpointing both rely on (persisting output, not just a status
flag). This cache is store-internal — it is deliberately not part of the `StepState` contract in
CONTRACTS.md, since nothing outside `orchestrator/` ever reads it directly; only `machine.py`'s own
resume logic does, deserializing it using the type implied by `step`.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, runtime_checkable

from clearway.schemas.models import PipelineStep, RunState, RunStatus, StepState, StepStatus

_DEFAULT_DB_URL = "postgresql://clearway:clearway@localhost:5432/clearway"
_RUN_TABLE = "run_state"
_STEP_TABLE = "step_state"


@runtime_checkable
class OrchestratorStore(Protocol):
    """The seam `orchestrator/` depends on for durable checkpointing."""

    def ensure_schema(self) -> None:
        """Create the tables if absent (idempotent)."""
        ...

    def save_run(self, run: RunState) -> None:
        """Insert/update one run's checkpoint (by run_id)."""
        ...

    def load_run(self, run_id: str) -> Optional[RunState]:
        """The run's checkpoint, or None if this run_id is unknown."""
        ...

    def save_step(self, step: StepState, result_json: Optional[str]) -> None:
        """Insert/update one (run_id, finding_id, step) checkpoint, with its cached result
        (None if the step failed — there is nothing to replay)."""
        ...

    def load_steps(self, run_id: str) -> list[StepState]:
        """Every step checkpointed so far for a run — what resume needs to know what's done."""
        ...

    def load_step_result(self, run_id: str, finding_id: str, step: PipelineStep) -> Optional[str]:
        """The cached result for one completed step, or None if there isn't one."""
        ...


class InMemoryOrchestratorStore:
    """Offline stand-in for `PgOrchestratorStore`: dicts keyed by run_id / (run_id, finding_id,
    step). Exercises checkpoint + resume mechanics without a DB."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._steps: dict[tuple[str, str, PipelineStep], StepState] = {}
        self._results: dict[tuple[str, str, PipelineStep], str] = {}

    def ensure_schema(self) -> None:
        return None  # nothing to create in memory; kept for seam parity with PgOrchestratorStore

    def save_run(self, run: RunState) -> None:
        self._runs[run.run_id] = run

    def load_run(self, run_id: str) -> Optional[RunState]:
        return self._runs.get(run_id)

    def save_step(self, step: StepState, result_json: Optional[str]) -> None:
        key = (step.run_id, step.finding_id, step.step)
        self._steps[key] = step
        if result_json is not None:
            self._results[key] = result_json

    def load_steps(self, run_id: str) -> list[StepState]:
        return [s for (rid, _, _), s in self._steps.items() if rid == run_id]

    def load_step_result(self, run_id: str, finding_id: str, step: PipelineStep) -> Optional[str]:
        return self._results.get((run_id, finding_id, step))


class PgOrchestratorStore:
    """Real store: Postgres. Uses a plain psycopg connection (no ORM) — the DDL and queries are
    written out explicitly, in keeping with the repo's hand-rolled ethos (`corpus/store.py`)."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url: str = db_url or os.getenv("CLEARWAY_DB_URL") or _DEFAULT_DB_URL

    def _connect(self):  # type: ignore[no-untyped-def]
        import psycopg

        return psycopg.connect(self._db_url, autocommit=True)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_RUN_TABLE} ("
                "  run_id     text PRIMARY KEY,"
                "  config_id  text NOT NULL,"
                "  status     text NOT NULL,"
                "  created_at timestamptz NOT NULL"
                ")"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_STEP_TABLE} ("
                "  run_id      text NOT NULL,"
                "  finding_id  text NOT NULL,"
                "  step        text NOT NULL,"
                "  status      text NOT NULL,"
                "  attempts    integer NOT NULL DEFAULT 0,"
                "  updated_at  timestamptz NOT NULL,"
                "  result_json text,"
                "  PRIMARY KEY (run_id, finding_id, step)"
                ")"
            )

    def save_run(self, run: RunState) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {_RUN_TABLE} (run_id, config_id, status, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (run_id) DO UPDATE SET status = EXCLUDED.status",
                (run.run_id, run.config_id, run.status.value, run.created_at),
            )

    def load_run(self, run_id: str) -> Optional[RunState]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT run_id, config_id, status, created_at FROM {_RUN_TABLE} WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return RunState(run_id=row[0], config_id=row[1], status=RunStatus(row[2]), created_at=row[3])

    def save_step(self, step: StepState, result_json: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {_STEP_TABLE} "
                "(run_id, finding_id, step, status, attempts, updated_at, result_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id, finding_id, step) DO UPDATE SET "
                "status = EXCLUDED.status, attempts = EXCLUDED.attempts, "
                "updated_at = EXCLUDED.updated_at, result_json = EXCLUDED.result_json",
                (
                    step.run_id,
                    step.finding_id,
                    step.step.value,
                    step.status.value,
                    step.attempts,
                    step.updated_at,
                    result_json,
                ),
            )

    def load_steps(self, run_id: str) -> list[StepState]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT run_id, finding_id, step, status, attempts, updated_at FROM {_STEP_TABLE} WHERE run_id = %s",
                (run_id,),
            ).fetchall()
            return [
                StepState(
                    run_id=r[0],
                    finding_id=r[1],
                    step=PipelineStep(r[2]),
                    status=StepStatus(r[3]),
                    attempts=r[4],
                    updated_at=r[5],
                )
                for r in rows
            ]

    def load_step_result(self, run_id: str, finding_id: str, step: PipelineStep) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT result_json FROM {_STEP_TABLE} WHERE run_id = %s AND finding_id = %s AND step = %s",
                (run_id, finding_id, step.value),
            ).fetchone()
            return row[0] if row else None
