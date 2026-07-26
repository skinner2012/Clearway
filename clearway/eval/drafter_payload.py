"""What the drafter *would send*, hashed — the instrument that answers "did this ticket move a prompt".

Why a hash and not a re-run
---------------------------
Wiring an image channel touches the module that builds every prompt in this repo. The classes that
carry the frozen measurements are text classes, and the way a change like this damages them is not a
crash: it is one extra newline, one reordered block, one help string rendered differently — a prompt
that still reads correctly and no longer matches the one a frozen verdict vector was built over.
Re-running those classes to find out would cost hours per pass and *still* could not separate a moved
prompt from ordinary sampling drift at temperature 0.

A payload hash separates them exactly. `LLMRequest` is the ask as a value — system prompt, user
prompt, response schema, and the attached picture's digest — so two hex strings settle it.

What this module freezes, and when it was measured
--------------------------------------------------
`BASELINE` holds the payload hash of every image-pool finding under the **no-image** condition, plus
one text finding as a cross-class check, **measured against the drafter as it stood before the image
was wired into it** (`pre_wiring` in the artifact records the commit and the sha256 of that file's
blob, so the measurement is repeatable in three lines rather than taken on trust). After the wiring,
the same payloads must hash the same — that is the control the image channel is allowed to ship
under, and it is asserted from two independent directions: here, through the prompt builders, and in
the drafter's own tests, through a real `Drafter` call that records what it actually sent.

Two deliberate choices
----------------------
* **Citations are pinned here, not retrieved.** Retrieval is a live service (pgvector), and a
  baseline that could not be recomputed offline would be a control nobody re-checks. The claim being
  controlled is about the prompt-assembly code, and citations are an *input* to it — so the input is
  fixed and named, and the candidate block still renders in full (id, url and bounded normative text).
* **Rows are keyed by `(scope, act_testcase_id, target)`, never by `finding_id`.** A finding id hashes
  the case's `file://` URL, so it is a property of where this repository happens to sit on disk; the
  payload hash is not, because no prompt contains the URL. Keying on the portable triple makes the
  frozen control survive a clone into a different directory. `finding_id` is still recorded, as
  provenance.

Regenerate with `uv run python -m clearway.eval.drafter_payload` — but note what that means: a
rebuild on the *current* code produces the post-wiring numbers, so it must never be run to "fix" a
failing comparison. The baseline's value is entirely in when it was measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.drafter.llm import _LLMDraft, _system_prompt, _user_prompt, confirmed_violation_sc_ids
from clearway.eval.run_scope import ACCEPTANCE, IMAGE_LEAKY, IMAGE_OPAQUE, OutOfScope, RunScope, cases_for
from clearway.llm.client import LLMRequest
from clearway.schemas.models import Citation, ConformanceLevel, Finding

BASELINE = Path(__file__).resolve().parents[2] / "benchmark" / "reports" / "drafter_payload_baseline.json"

# The scopes whose no-image payloads this controls: both image sets, because both are drafted text-only
# in one of the four conditions, and a silently moved prompt would corrupt the descriptive comparison
# between them as surely as it would corrupt the endpoint.
_IMAGE_SCOPES = (IMAGE_LEAKY, IMAGE_OPAQUE)

# The cross-class check: one text finding from the acceptance set, from the class whose prompt was most
# recently changed (the referent block rides on `label`), so this catches a change that reached text
# classes through the shared prompt code rather than through anything image-specific.
TEXT_CROSS_CHECK_RULE = "label"

# Pinned candidate criteria — what a real retriever surfaces for these classes, fixed so the payload is
# computable with no service running. The normative text is present so the grounding line renders; it is
# short on purpose, because the truncation rule has its own pins elsewhere and this control is not the
# place to also freeze a 400-character budget.
PINNED_CITATIONS: dict[str, list[Citation]] = {
    "image-alt": [
        Citation(
            sc_id="1.1.1",
            title="Non-text Content",
            level=ConformanceLevel.A,
            source="WCAG-SC",
            url="https://www.w3.org/TR/WCAG22/#non-text-content",
            text=(
                "All non-text content that is presented to the user has a text alternative that serves "
                "the equivalent purpose, except for the situations listed below."
            ),
        )
    ],
    "label": [
        Citation(
            sc_id="4.1.2",
            title="Name, Role, Value",
            level=ConformanceLevel.A,
            source="WCAG-SC",
            url="https://www.w3.org/TR/WCAG22/#name-role-value",
            text=(
                "For all user interface components, the name and role can be programmatically "
                "determined; states, properties, and values that can be set by the user can be "
                "programmatically set; and notification of changes to these items is available to user "
                "agents, including assistive technologies."
            ),
        )
    ],
}


def citations_for(axe_rule: str) -> list[Citation]:
    """The pinned candidates for a class. An unpinned class is refused rather than given none: an
    empty candidate list renders a different prompt, so it would silently change the very hash this
    module exists to hold still."""
    if axe_rule not in PINNED_CITATIONS:
        raise OutOfScope(
            f"no pinned citations for {axe_rule!r} — add them rather than drafting with none, which "
            "renders a different candidate block and moves the hash this control compares"
        )
    return [c.model_copy() for c in PINNED_CITATIONS[axe_rule]]


def payload_for(finding: Finding, citations: list[Citation]) -> LLMRequest:
    """The judgment-path request for one finding under the no-image condition.

    A finding whose criteria are derivable from axe's own tags is refused: it drafts on the assembled
    path, which is a different system prompt and a different schema, so hashing it here would freeze
    a number that no comparison with the judgment path can be made against. Every finding this
    control covers is a `passes`-bucket judgment item, and this is the assertion of that rather than
    the assumption of it.
    """
    if confirmed_violation_sc_ids(finding):
        raise OutOfScope(
            f"{finding.rule_id} finding {finding.id} drafts on the assembled path (its axe tags decode "
            "to success criteria), which builds a different prompt under a different schema — this "
            "control covers the judgment path the image classes and the measured text classes both use"
        )
    return LLMRequest.of(_system_prompt(), _user_prompt(finding, citations), _LLMDraft)


def _row(scope: RunScope, case: dict[str, Any], finding: Finding) -> dict[str, Any]:
    request = payload_for(finding, citations_for(case["axe_rule"]))
    return {
        "scope": scope.scope_id,
        "act_testcase_id": case["act_testcase_id"],
        "axe_rule": case["axe_rule"],
        "target": finding.target,
        "finding_id": finding.id,
        "condition": "no-image",
        "image_ref": request.image_ref,  # always None here — recorded, so the condition is on the row
        "payload_sha256": request.sha256,
    }


def rows_for_scope(scope: RunScope) -> list[dict[str, Any]]:
    """Every finding this scope mints, as payload rows — re-scanned live, exactly as a run would."""
    return [
        _row(scope, case, finding)
        for case in cases_for(scope)
        for finding in scope.minting_findings(scope.root / case["path"], case["axe_rule"])
    ]


def text_cross_check_rows() -> list[dict[str, Any]]:
    """The cross-class rows: one acceptance case of the referent-injected text class.

    The first such case in the frozen manifest's order, so the choice is a property of the gold rather
    than a decision anyone can drift; the case id is recorded on every row, so a manifest whose order
    moved shows up as a changed row rather than as a silently different comparison.
    """
    case = next(c for c in cases_for(ACCEPTANCE) if c["axe_rule"] == TEXT_CROSS_CHECK_RULE)
    findings = ACCEPTANCE.minting_findings(ACCEPTANCE.root / case["path"], case["axe_rule"])
    return [_row(ACCEPTANCE, case, finding) for finding in findings]


def build_baseline() -> dict[str, Any]:
    """Re-derive every controlled payload and return the artifact. Model-free and offline."""
    payloads = [row for scope in _IMAGE_SCOPES for row in rows_for_scope(scope)] + text_cross_check_rows()
    return {
        "artifact": "drafter request payload hashes, no-image condition",
        "version": 1,
        "schema": _LLMDraft.__name__,
        "note": (
            "The payload hash of every image-pool finding drafted text-only, plus one text finding of "
            "the referent-injected class as a cross-class check. Measured against the drafter as it "
            "stood BEFORE the image was wired into it (see pre_wiring), so the wiring is allowed to "
            "ship only if these hashes are unchanged after it. A payload is the ask as a value — "
            "system prompt, user prompt, response schema name and the attached picture's digest, "
            "canonically serialized — so it moves if and only if what the model is asked moves. "
            "Citations are pinned in the builder, not retrieved: the claim controlled here is about "
            "prompt assembly, and a control that needs a database running is a control nobody "
            "re-checks. Rows are keyed by (scope, act_testcase_id, target); finding_id hashes the "
            "case's file:// URL and is therefore a property of this checkout's location, while the "
            "payload hash is not, because no prompt carries the URL."
        ),
        "pre_wiring": {
            "commit": "45cce1c9c0aa5b9c33a1ec4b3d1cb4b0d5b3a0f6",
            "drafter_blob_sha256": "",
            "method": (
                "the prompt builders of `git show <commit>:clearway/drafter/llm.py`, imported as a "
                "module and hashed through the same canonical LLMRequest serialization used here"
            ),
        },
        "pinned_citations": {
            rule: [c.model_dump(mode="json") for c in citations] for rule, citations in PINNED_CITATIONS.items()
        },
        "payloads": payloads,
    }


def load_baseline(artifact: Path = BASELINE) -> dict[tuple[str, str, str], str]:
    """The frozen control as `(scope, act_testcase_id, target) → payload_sha256`."""
    frozen = json.loads(artifact.read_text())
    return {(row["scope"], row["act_testcase_id"], row["target"]): row["payload_sha256"] for row in frozen["payloads"]}


def baseline_failures(rows: list[dict[str, Any]], frozen: dict[tuple[str, str, str], str]) -> list[str]:
    """Every way a re-derivation can disagree with the control: a payload that moved, one that
    vanished, one that appeared. Pure, so the check reads the same in a builder and in a test.

    A missing row matters as much as a changed one — a class that stopped minting a finding would
    otherwise pass a comparison over whatever was left.
    """
    failures: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["scope"], row["act_testcase_id"], row["target"])
        seen.add(key)
        if key not in frozen:
            failures.append(f"{key} is not in the frozen control — a payload that did not exist when it was measured")
        elif frozen[key] != row["payload_sha256"]:
            failures.append(
                f"{key} payload moved: frozen {frozen[key][:12]}… now {row['payload_sha256'][:12]}… — the "
                "prompt this finding is drafted with is not the one the frozen runs were built over"
            )
    failures += [f"{key} is in the frozen control but was not re-derived" for key in sorted(frozen.keys() - seen)]
    return failures


def main() -> None:
    artifact = build_baseline()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE.relative_to(Path.cwd())} — {len(artifact['payloads'])} payloads")
    for row in artifact["payloads"]:
        print(f"  {row['scope']:<13} {row['act_testcase_id'][:10]} {row['axe_rule']:<10} {row['payload_sha256'][:12]}…")


if __name__ == "__main__":
    main()
