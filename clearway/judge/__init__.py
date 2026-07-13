"""LLM-as-judge: grade drafted judgment items against WCAG on a fixed rubric.

Consumes a `Finding` + its `DraftRow`, produces a `JudgeResult`. Used only for no-oracle judgment
items and only once the judge is calibrated (κ) — this package builds the instrument.
"""

from clearway.judge.judge import Judge, JudgeError, verdict_from

__all__ = ["Judge", "JudgeError", "verdict_from"]
