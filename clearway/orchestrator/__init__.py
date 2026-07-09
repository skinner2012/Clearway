"""Orchestrator: wire the forward path into a trust-metric report — one page (`run`) or a whole
eval set (`run_set`), the M1 exit-criterion runner (ARCHITECTURE §4.6)."""

from clearway.orchestrator.run import RunResult, run, run_set
from clearway.orchestrator.store import InMemoryOrchestratorStore, OrchestratorStore, PgOrchestratorStore

__all__ = [
    "InMemoryOrchestratorStore",
    "OrchestratorStore",
    "PgOrchestratorStore",
    "RunResult",
    "run",
    "run_set",
]
