"""LLM-as-judge: grade drafted judgment items against WCAG on a fixed rubric.

Consumes a `Finding` + its `DraftRow` + the candidates retrieved for the finding, produces a
`JudgeResult`. Used only for no-oracle judgment items and only once the judge is calibrated (κ) — this
package builds the instrument.

`FindingInput` is the finding-side half of that prompt as a value, so a comparison of two
configurations can freeze it once and hand the same bytes to both. `Judge` grades a draft it is shown;
`BlindJudge` never sees one and answers for itself, and code compares the two answers.
"""

from clearway.judge.judge import (
    CANDIDATE_HEADING,
    BlindAnswer,
    BlindJudge,
    FindingInput,
    Judge,
    JudgeError,
    blind_user_prompt,
    citations_agree,
    conformance_agrees,
    finding_input,
    verdict_from,
)

__all__ = [
    "CANDIDATE_HEADING",
    "BlindAnswer",
    "BlindJudge",
    "FindingInput",
    "Judge",
    "JudgeError",
    "blind_user_prompt",
    "citations_agree",
    "conformance_agrees",
    "finding_input",
    "verdict_from",
]
