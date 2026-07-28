"""Eval harness: aggregate traces into the M0 trust metric (ARCHITECTURE §4.5).

**"Endpoint" in this package means an experiment's pre-registered outcome measure — the one statistic
a result is read off — and never an HTTP route.** It is a term of art borrowed from trial design, and
it is load-bearing here: an endpoint is fixed in a milestone spec together with its null, its
thresholds and its verdicts *before* a single model call is spent, so the reading cannot be chosen
after the number is seen. `PooledEndpoint`, `endpoint_d` and `endpoint_a` are all that kind of thing.

The gloss is here because the other meaning is live in this same repository —
`clearway.observability.tracing.setup_tracing(endpoint=…)` is an OTLP collector URL — and because a
reader of a Python monorepo reaches for that one first.
"""

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
