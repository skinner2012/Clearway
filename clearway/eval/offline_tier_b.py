"""The realistic-page (noisy) smoke test — an ILLUSTRATION, never a headline rate.

Each of the two noisy pages embeds one ACT judgment snippet intact as the FOCAL case, surrounded by
clean-by-construction noise. The question is only whether the pipeline survives real-page noise: does
the focal verdict that was correct on the clean counterpart stay correct once buried in noise, and does
the noise induce any false positive? At n = 2 no CI attaches, so this reports the clean − noisy delta as
a demonstration and stays out of the headline scorecard.

Noise-region scoring (per the page design): the noise is built from ACT passed snippets + trivially-
descriptive authored chrome, so a noise finding that is flagged AND cites one of its tested properties
is a false positive; a flag citing an unrelated SC is excluded, not auto-scored. This module is the
pure delta/formatting math; the live drafting of the pages lives in the builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_METHOD_AND_LIMITS = (
    "Each ACT snippet is embedded INTACT as the focal case, preserving its local context; the noise is "
    "built from ACT passed snippets plus trivially-descriptive authored chrome (clean by construction), "
    "so a noise-region flag citing a tested property counts as a false positive while a flag citing an "
    "unrelated SC is excluded. Scored exactly like the bare ACT cases (deterministic vs gold), but n=2 "
    "is illustrative, not a rate — no confidence interval attaches to two points, and the methodology is "
    "preliminary."
)


@dataclass(frozen=True)
class NoisyFocalResult:
    """One noisy page's outcome: the focal verdict on the clean counterpart vs embedded in noise, plus
    the count of noise-region false positives (flagged noise findings citing a tested property)."""

    page_id: str
    focal_rule: str
    focal_expected: str  # "failed" | "passed"
    flagged_clean: bool
    flagged_noisy: bool
    noise_fp: int


def _correct(expected: str, flagged: bool) -> bool:
    """A verdict is correct when it flags a failed case / stays clean on a passed one."""
    return flagged == (expected == "failed")


def _page_line(r: NoisyFocalResult) -> str:
    clean = "correct" if _correct(r.focal_expected, r.flagged_clean) else "wrong"
    noisy = "correct" if _correct(r.focal_expected, r.flagged_noisy) else "wrong"
    focal = f"focal {r.focal_rule} [{r.focal_expected}]"
    return f"{r.page_id} ({focal}): clean={clean}, noisy={noisy}, {r.noise_fp} noise-region FP"


def tier_b_smoke(results: list[NoisyFocalResult]) -> dict[str, Any]:
    """The `TierBSmoke` payload: per-page clean-vs-noisy lines, the number of focal verdicts that
    changed under noise (the cost of real-page messiness), and the mandatory method/limits statement."""
    changed = sum(1 for r in results if r.flagged_clean != r.flagged_noisy)
    noise_fp = sum(r.noise_fp for r in results)
    lines = " | ".join(_page_line(r) for r in results)
    note = (
        f"{lines}. Focal verdicts changed under noise: {changed}/{len(results)}; "
        f"total noise-region false positives: {noise_fp}. The clean − noisy delta is the cost of real-page "
        "noise, reported as illustration (n=2, no CI)."
    )
    return {
        "n": len(results),
        "instance_ids": [r.page_id for r in results],
        "clean_vs_noisy_note": note,
        "method_and_limits": _METHOD_AND_LIMITS,
    }
