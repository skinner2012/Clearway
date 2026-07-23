"""Eval harness: aggregate traces into the M0 trust metric (ARCHITECTURE §4.5)."""

from clearway.eval.edit_distance import (
    conformance_changed,
    expert_edit_distance,
    mean_expert_edit_distance,
)
from clearway.eval.online import compute_metrics, evaluate

__all__ = [
    "evaluate",
    "compute_metrics",
    "expert_edit_distance",
    "conformance_changed",
    "mean_expert_edit_distance",
]
