"""Judge calibration — the trust-metric math that decides whether the LLM-judge may score models.

The load-bearing question of the milestone: does the judge agree with a human? We answer it with
Cohen's κ between two aligned verdict streams — the judge's verdicts and the *human-derived*
verdicts on the same drafts. The human verdict is derived MECHANICALLY from each draft against its
`GoldLabel`, through `verdict_from` — the exact rule the judge uses — so the two streams live on one
categorical scale and κ compares like with like.

This module is pure: no LLM, no network. It takes verdict streams (built live and frozen elsewhere)
and computes κ, raw agreement, and per-class counts. Kept pure on purpose — κ must be reproducible
from a checked-in artifact, never re-derived by calling a non-deterministic cloud model.

κ lives in `[-1, 1]`. A NEGATIVE κ (judge worse than chance) is the single most important red flag,
so nothing here clamps it to 0 — see `cohen_kappa`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

from clearway.judge import verdict_from
from clearway.schemas.models import DraftRow, GoldLabel, JudgeVerdict

# The trust bar, PRE-COMMITTED here before any live κ is computed: κ >= 0.6 is "substantial"
# agreement (Landis & Koch). Fixed in code first so the number cannot be moved to fit the result —
# the whole point of the calibration gate.
KAPPA_THRESHOLD = 0.6


def human_verdict(draft: DraftRow, gold: GoldLabel) -> JudgeVerdict:
    """Derive the human ground-truth verdict for one draft, mechanically, from its `GoldLabel`.

    `citation_correct` = the drafted SC(s) are exactly the gold SC(s) — an extra or missing SC is
    wrong, mirroring the judge rubric ("wrong or irrelevant, or a clearly-required SC missing").
    `conformance_correct` = the drafted conformance equals the gold conformance. The 3-way verdict
    then comes from `verdict_from`, the same rule the judge applies to its own two booleans.
    """
    citation_correct = {c.sc_id for c in draft.citations} == set(gold.gold_success_criteria)
    conformance_correct = draft.conformance is gold.gold_conformance
    return verdict_from(citation_correct, conformance_correct)


def is_correct(verdict: JudgeVerdict) -> bool:
    """Binary collapse for the 2-class κ: `correct` vs not — `partial` and `incorrect` both fold to
    not-correct. Reported alongside the 3-way κ because a small n makes the 3-way estimate fragile."""
    return verdict is JudgeVerdict.CORRECT


def raw_agreement(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """Proportion of paired ratings that match — the honest number reported beside κ (κ can be low
    even at high agreement when one class dominates, which is exactly the natural-pass story)."""
    _require_aligned(a, b)
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """Cohen's κ between two aligned categorical streams — chance-corrected agreement in `[-1, 1]`.

    κ = (p_o - p_e) / (1 - p_e): observed agreement minus agreement expected if the two raters were
    independent, normalised by the room above chance. Negative when the raters agree LESS than chance
    — surfaced, never clamped, because "judge worse than chance" is the key red flag.

    Edge case: when 1 - p_e == 0 both raters are constant on one class, so κ is undefined (a rater
    with no variance carries no discriminative signal). We report 0.0 and let raw agreement + the
    per-class counts tell the real story, rather than emit a κ that overstates a no-variance stream.
    """
    _require_aligned(a, b)
    n = len(a)
    p_o = sum(1 for x, y in zip(a, b) if x == y) / n
    count_a = Counter(a)
    count_b = Counter(b)
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in set(count_a) | set(count_b))
    denom = 1.0 - p_e
    if denom == 0.0:
        return 0.0
    return (p_o - p_e) / denom


@dataclass(frozen=True)
class Agreement:
    """Judge-vs-human agreement over one aligned pair of verdict streams: everything the calibration
    report needs from a stream pair. `kappa` (3-way) is the trust gate when this is the balanced set;
    `kappa_binary` and the per-class counts are the honesty context reported alongside it."""

    n: int
    kappa: float
    kappa_binary: float
    agreement: float
    human_counts: dict[JudgeVerdict, int]
    judge_counts: dict[JudgeVerdict, int]
    agree_by_class: dict[JudgeVerdict, int]


def analyze(human: Sequence[JudgeVerdict], judge: Sequence[JudgeVerdict]) -> Agreement:
    """Compute the full agreement picture for one aligned pair of verdict streams."""
    _require_aligned(human, judge)
    human_binary = [is_correct(v) for v in human]
    judge_binary = [is_correct(v) for v in judge]
    return Agreement(
        n=len(human),
        kappa=cohen_kappa(human, judge),
        kappa_binary=cohen_kappa(human_binary, judge_binary),
        agreement=raw_agreement(human, judge),
        human_counts={c: sum(1 for v in human if v is c) for c in JudgeVerdict},
        judge_counts={c: sum(1 for v in judge if v is c) for c in JudgeVerdict},
        agree_by_class={c: sum(1 for h, j in zip(human, judge) if h is c and j is c) for c in JudgeVerdict},
    )


def _require_aligned(a: Sequence[Hashable], b: Sequence[Hashable]) -> None:
    if len(a) != len(b):
        raise ValueError(f"rater streams must be aligned, got lengths {len(a)} and {len(b)}")
    if not a:
        raise ValueError("need at least one paired rating")
