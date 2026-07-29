"""Judging without the pixels: does a drafted row ever say so, and where does the marking fire?

Two model-free measurements of one defect. Both are pure, offline and spend no model call; the first
reads rows that are already frozen, the second drives the real drafter with a canned client.

**The baseline — did any blind row ever report the absence?**
A question about pixels answered confidently with no pixels is a product defect of the same family as
a confidence number that does not move with correctness, and the first thing to establish is whether
the drafter already reports it. That is a measurement, not a reading, so the rule is written down
*before* the rows are read through it: `DETECTOR_PHRASES` is fixed in code, deliberately high-recall,
and hand-checked. The expected answer is zero, which is exactly why the rule must be too wide rather
than too narrow — the failure that would matter here is a rule so tight it misses a signal that was
there, while a false positive costs one row read by eye and named in the artifact.

It reads the one field a drafted row has to carry it: `remediation`. `DraftRow` has no rationale, and
the frozen conditions record `conformance`, `cited_sc_ids`, `confidence` and `remediation` — so a row
that reported an absence at all reported it there.

Frozen so a later measurement of the same thing is the *same* measurement: the identical rule run over
later rows makes the before and the after one number rather than two that happen to be comparable.

**The blast radius — where does the marking fire, and what would the guard refuse?**
Counted over every scope `run_scope` defines (`ALL_SCOPES`), never over the seven image cases the
marking was designed for: a guard measured only where it was built to fire is not measured. Two
sweeps, because the two things being counted are reachable under different conditions:

* **as production ships it** — no picture attached, no announcement — which is where the marking's
  `False` rows are counted, and where the contradiction guard is *structurally unreachable*: the
  shipped response shape has no field for a claim to be made in.
* **as the announced path would run** — the adversarial upper bound, what a flip of `announce_image`
  would refuse at worst, which is a number to have before the flip rather than after it.

Both sweeps hand the drafter the identical answer, one claiming `seen` on every row, so the two
counts differ in the *ask* alone: the shipped zero is that claim being dropped by the shape, measured,
rather than the absence of a claim to drop.

The same sweep carries a third count, of the one thing a reader actually meets: the report's per-row
trust label. `oracle-verified` grades citation verification and human review, neither of which says
anything about pixels, so a blind judgment could render under the strongest label this product has.
The label now refuses it, and the refusal is counted in both directions — the rows it downgrades, and
the rows it downgrades **too far**, since the marking is keyed by the rule and a text-decidable
instance of that rule is marked with the rest. Over-firing is the conservative direction, and it is
reported as a number.

Regenerate with `uv run python -m clearway.eval.blind_judgment` — it re-scans every scoped case
(no model, no network).
"""

from __future__ import annotations

import json
from typing import Any

from clearway.cli import _TRUST_BLIND_JUDGED, _TRUST_ORACLE_VERIFIED, _trust_label
from clearway.drafter import Drafter, DraftResult, is_fallback_draft
from clearway.drafter.llm import PIXEL_DECIDED_RULES, confirmed_violation_sc_ids
from clearway.eval.image_conditions import CONDITIONS, Condition
from clearway.eval.image_opaque import specificity_control_row
from clearway.eval.image_pass import load_pass, pass_failures
from clearway.eval.offline_build import _REPORTS_DIR
from clearway.eval.run_scope import ALL_SCOPES, OutOfScope, RunScope, cases_for
from clearway.llm import FakeLLMClient
from clearway.schemas.models import CitationCheck, CitationVerdict, Finding, L1Status

REPORT = _REPORTS_DIR / "blind_judgment.json"

# The rule, pinned before the rows are read through it. Substring-matched on the case-folded
# remediation, because a drafted sentence is prose and a signal in it is a phrase rather than a field.
DETECTOR_PHRASES: tuple[str, ...] = (
    "cannot see",
    "can't see",
    "unable to see",
    "not able to see",
    "cannot view",
    "unable to view",
    "without seeing",
    "not shown the image",
    "no image was provided",
    "image is not provided",
    "image not provided",
    "no visual",
    "cannot verify the image",
)

DETECTOR_RULE = (
    "a drafted row signals that the visual evidence was unavailable iff its `remediation`, "
    f"case-folded, contains any of the {len(DETECTOR_PHRASES)} pinned phrases in DETECTOR_PHRASES. "
    "Deliberately high-recall: the expected answer is zero, so the failure that would matter is a "
    "rule too narrow to catch a signal that was there, and a false positive costs one row read by "
    "eye and named in `signalling` below."
)

# What BOTH sweeps hand the model: one answer, claiming on every row that it saw a picture. Handing
# the two sweeps the same adversarial content is what makes their difference readable — the only thing
# that varies between them is the ask, so a claim that lands in one and vanishes in the other is a
# property of the shape rather than of the answer. It is valid under all three response shapes at
# once: the ones that do not declare `visual_evidence` ignore it, which is precisely the drop the
# shipped sweep measures.
_CANNED_CLAIMS_SEEN = (
    '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"x","confidence":0.5,'
    '"visual_evidence":"seen"}'
)

# The citation state the trust label's refusal is visible from: every criterion the row cites
# confirmed by the oracle, and no human signature. `oracle-verified` is reachable from that state and
# from no other, so it is the state that asks what the refusal actually costs. The sweep retrieves no
# candidates — see `sweep_rows` — so a row's own checks are empty and every row would read as the
# floor for a reason with nothing to do with pixels, which would report the refusal as free.
_EVERY_CITATION_VERIFIED = [
    CitationCheck(sc_id="1.1.1", l0_valid=True, l1_status=L1Status.MATCH, verdict=CitationVerdict.VERIFIED)
]


# --- the baseline: did any blind row report the absence? ---------------------


def matched_phrase(remediation: str) -> str | None:
    """The pinned phrase this remediation contains, or `None` — the whole detector.

    Returns the phrase rather than a boolean so a hit is *named* in the artifact: a rule this wide
    exists to be audited, and "one row matched" is not auditable while "one row matched `no visual`"
    is.
    """
    folded = remediation.casefold()
    return next((phrase for phrase in DETECTOR_PHRASES if phrase in folded), None)


def detector_rows(condition: Condition, artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Every drafted row of one frozen condition, read through the pinned rule.

    `blind` is taken from the **condition**, not from the row: what makes a row blind is the
    condition's picture rule, which is frozen and pre-registered, and reading it off each row's own
    receipt would key the measurement to the data's surface instead of to the set's boundary. The two
    agree — `image_pass.pass_failures` asserts a text-only condition attached nothing on every row —
    and this module refuses an artifact where they do not.
    """
    rows = []
    for sample in artifact["samples"]:
        for row in sample["rows"]:
            attached = row["receipt"]["image_sha256"] is not None
            if attached != condition.carries_image:
                raise OutOfScope(
                    f"{condition.condition_id} attaches {condition.attaches!r} but a row of sample "
                    f"{sample['sample']} says otherwise — the blind set is defined by the condition, "
                    "so a row disagreeing with it makes the denominator unreadable"
                )
            phrase = matched_phrase(row["draft"]["remediation"])
            rows.append(
                {
                    "condition": condition.condition_id,
                    "sample": sample["sample"],
                    "act_testcase_id": row["receipt"]["act_testcase_id"],
                    "blind": not condition.carries_image,
                    "signals_unavailability": phrase is not None,
                    "matched_phrase": phrase,
                }
            )
    return rows


def baseline(conditions: tuple[Condition, ...] = CONDITIONS) -> dict[str, Any]:
    """The detector run over every frozen condition — the number a later measurement moves from.

    Refuses an unsound pass for the same reason every other reader here does: a condition missing a
    sample would shrink the denominator, and 0 of 21 reads exactly like 0 of 28.
    """
    rows: list[dict[str, Any]] = []
    per_condition = []
    for condition in conditions:
        artifact = load_pass(condition)
        failures = pass_failures(artifact)
        if failures:
            raise OutOfScope(f"{condition.condition_id} is not a sound pass: {'; '.join(failures)}")
        condition_rows = detector_rows(condition, artifact)
        rows += condition_rows
        per_condition.append(
            {
                "condition": condition.condition_id,
                "attaches": condition.attaches,
                "blind": not condition.carries_image,
                "rows": len(condition_rows),
                "signalling": sum(1 for row in condition_rows if row["signals_unavailability"]),
            }
        )

    blind = [row for row in rows if row["blind"]]
    sighted = [row for row in rows if not row["blind"]]
    return {
        "rule": DETECTOR_RULE,
        "phrases": list(DETECTOR_PHRASES),
        "field_read": "draft.remediation",
        "rows": len(rows),
        "blind_rows": len(blind),
        "blind_rows_signalling": sum(1 for row in blind if row["signals_unavailability"]),
        "sighted_rows": len(sighted),
        "sighted_rows_signalling": sum(1 for row in sighted if row["signals_unavailability"]),
        "conditions": per_condition,
        # Every hit, named, so a rule this wide can be audited by eye rather than trusted.
        "signalling": [row for row in rows if row["signals_unavailability"]],
        "note": (
            "The rule was written into code before these rows were read through it, and it reads the "
            "one field a drafted row has to carry the signal — `DraftRow` has no rationale. A blind "
            "row is one drafted under a condition that attaches no picture, taken from the frozen "
            "condition rather than from the row, so the denominator is the pre-registered set."
        ),
    }


# --- the blast radius: where the marking fires, what the guard would refuse ---


def text_decided_cases() -> frozenset[str]:
    """The cases whose finding is decidable from the text alone — a **lower bound**, and named as one.

    Exactly one is known: the case the frozen permutation names as its specificity control, whose
    `alt` is a hex digest and so describes nothing whatever is attached. It is read from the frozen
    artifact rather than transcribed, and it is the only member because it is the only one anybody
    labelled — there is no predicate that decides "decidable from the text" in general, and inventing
    one here would be a second definition of a set the experiment already fixed by hand. So the
    over-firing count below is a floor: a case nobody looked at is not counted as text-decided.
    """
    return frozenset({specificity_control_row()["act_testcase_id"]})


def _sweep_row(
    scope: RunScope,
    case: dict[str, Any],
    finding: Finding,
    shipped: DraftResult,
    claimed: DraftResult,
    text_decided: frozenset[str],
) -> dict[str, Any]:
    """One finding under both sweeps, keyed portably.

    `finding_id` is deliberately absent: it hashes the case's absolute `file://` URL, so a row carrying
    one would make this artifact a property of where the repository happens to sit. `(scope,
    act_testcase_id, target)` is the same portable triple the payload control uses.

    `visual_evidence` is read off the **shipped** draft, where it is expected empty on every row of
    the corpus: the answer claimed `seen`, the shipped shape has nowhere to put it, and the column
    records that the claim was dropped rather than honoured.

    `trust_label` is the label the **report renderer itself** would print for the shipped row, driven
    rather than re-derived for the same reason the drafter is: a count over a re-implemented predicate
    measures the copy, and the copy is what drifts.
    """
    return {
        "scope": scope.scope_id,
        "act_testcase_id": case["act_testcase_id"],
        "axe_rule": finding.rule_id,
        "target": finding.target,
        "pixel_decided": finding.rule_id in PIXEL_DECIDED_RULES,
        "text_decided": case["act_testcase_id"] in text_decided,
        "path": "assembled" if confirmed_violation_sc_ids(finding) else "judgment",
        "visually_verified": shipped.row.visually_verified,
        "visual_evidence": shipped.row.visual_evidence.value if shipped.row.visual_evidence else None,
        "trust_label": _trust_label(shipped.row, _EVERY_CITATION_VERIFIED, None),
        "degraded_as_shipped": is_fallback_draft(shipped.row),
        "degraded_when_claiming_seen": is_fallback_draft(claimed.row),
    }


def sweep_rows(scopes: tuple[RunScope, ...] = ALL_SCOPES) -> list[dict[str, Any]]:
    """Every finding every scope mints, drafted twice against a canned client — no model, no network.

    The real `Drafter` is driven rather than its predicates re-implemented, because what is being
    counted is what the production path *does*: dispatch, prompt assembly, validation, the retry loop
    and the degradation are all the shipped code, and only the model is canned.

    Citations are empty on purpose. They are an input to the *answer*, and neither the marking nor the
    guard reads one — passing pinned candidates instead would restrict this sweep to the two classes
    that have them and leave two thirds of the corpus uncounted, which is the failure this sweep
    exists to avoid.

    The two drafts differ in exactly one argument. Same finding, same canned answer, same everything
    else — so whatever the second does that the first does not is the announcement's doing.
    """
    rows = []
    text_decided = text_decided_cases()
    for scope in scopes:
        for case in cases_for(scope):
            for finding in scope.minting_findings(scope.root / case["path"], case["axe_rule"]):
                shipped = Drafter(FakeLLMClient(_CANNED_CLAIMS_SEEN)).draft_with_usage(finding, [])
                claimed = Drafter(FakeLLMClient(_CANNED_CLAIMS_SEEN)).draft_with_usage(finding, [], announce_image=True)
                rows.append(_sweep_row(scope, case, finding, shipped, claimed, text_decided))
    return rows


def blast_radius(scopes: tuple[RunScope, ...] = ALL_SCOPES) -> dict[str, Any]:
    """What the marking touches, what the guard would refuse, and what the report stops claiming —
    over the whole scoped corpus."""
    rows = sweep_rows(scopes)
    degraded = [row for row in rows if row["degraded_when_claiming_seen"]]
    downgraded = [row for row in rows if row["trust_label"] == _TRUST_BLIND_JUDGED]
    over = [row for row in downgraded if row["text_decided"]]
    return {
        "scopes": [
            {
                "scope": scope.scope_id,
                "eval_set_id": scope.eval_set_id,
                "axe_rules": list(scope.axe_rules),
                "cases": len(cases_for(scope)),
                "findings": sum(1 for row in rows if row["scope"] == scope.scope_id),
            }
            for scope in scopes
        ],
        "findings": len(rows),
        "pixel_decided": sum(1 for row in rows if row["pixel_decided"]),
        "assembled_path": sum(1 for row in rows if row["path"] == "assembled"),
        "marking": {
            "visually_verified_false": sum(1 for row in rows if row["visually_verified"] is False),
            "visually_verified_true": sum(1 for row in rows if row["visually_verified"] is True),
            "visually_verified_none": sum(1 for row in rows if row["visually_verified"] is None),
            "note": (
                "Counted as production drafts: no picture attached, no announcement. `True` is "
                "therefore not exercised by this sweep — it is the same predicate's other branch, "
                "reached wherever a picture is sent — and `None` is the answer for every class no "
                "picture decides, which is what keeps the marking from labelling the text classes "
                "unverified."
            ),
        },
        "contradiction_guard": {
            "degraded_as_shipped": sum(1 for row in rows if row["degraded_as_shipped"]),
            "degraded_when_claiming_seen": len(degraded),
            "degraded_cases": sorted({row["act_testcase_id"] for row in degraded}),
            "note": (
                "Both sweeps hand the drafter the SAME answer, one claiming `seen` on every row, so "
                "the two counts differ in the ask alone. As shipped the guard is then structurally "
                "unreachable: `announce_image` defaults off, the response shape carries no field for "
                "the claim, and the claim is dropped rather than contradicted — a zero measured off "
                "the shape, not the absence of anything to catch. The second count is the adversarial "
                "upper bound, what flipping the announcement on would refuse against a model that "
                "claimed `seen` everywhere. Only a pixel-decided finding drafted without pixels is "
                "refused; every other row ships unchanged, because the announcement and the schema "
                "are both gated by class."
            ),
        },
        "trust_label": {
            "refused": _TRUST_ORACLE_VERIFIED,
            "renders_as": _TRUST_BLIND_JUDGED,
            "counted_under": (
                "every citation VERIFIED and no human review — the one state `oracle-verified` is "
                "reachable from, so the count is what the refusal actually costs rather than what it "
                "costs a row that was on the floor anyway"
            ),
            "rows_downgraded": len(downgraded),
            "rows_downgraded_correctly": len(downgraded) - len(over),
            "rows_over_downgraded": len(over),
            "over_downgraded_cases": sorted({row["act_testcase_id"] for row in over}),
            "text_decided_cases": sorted(text_decided_cases()),
            "rows_unmoved": len(rows) - len(downgraded),
            "note": (
                "`PIXEL_DECIDED_RULES` is keyed by the RULE, so an instance of that rule which its own "
                "text decides — an `alt` that is a hex digest describes nothing whatever the pixels "
                "hold — is marked blind and downgraded too. That over-firing is expected and it is the "
                "conservative direction: the failure it prevents is a judgment made without the "
                "evidence it needed shipping under the report's strongest label, and the cost is a "
                "text-decidable row reading one label lower than it could. It is reported as a number "
                "rather than as a sentence, and the number is a FLOOR — the text-decided set is the one "
                "case the frozen permutation names, because that is the one anybody labelled. "
                "`Conformance` is untouched throughout: the row keeps the verdict the model gave, and "
                "only what the report claims stands behind it moves."
            ),
        },
        "rows": rows,
    }


def build_report() -> dict[str, Any]:
    """Both measurements, re-derived. Pure: no model, no network."""
    return {
        "artifact": "judging without the pixels: the reporting baseline, and the marking's blast radius",
        "version": 2,
        "note": (
            "Two model-free measurements. The baseline reads every already-frozen image-condition row "
            "through a rule pinned in code before the rows were read through it, and asks whether a "
            "blind draft ever reported that the picture was unavailable. The blast radius drives the "
            "real drafter over every case of every scope `run_scope` defines, and counts where the "
            "system's own marking fires, what the contradiction guard would refuse, and what the "
            "report's trust label stops claiming — over the whole corpus rather than over the cases "
            "each was designed for. Version 2 adds the trust-label counts; every earlier number is "
            "unchanged, and re-derived rather than carried over."
        ),
        "baseline": baseline(),
        "blast_radius": blast_radius(),
    }


def main() -> None:
    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    base, radius = report["baseline"], report["blast_radius"]
    print(f"wrote {REPORT.relative_to(REPORT.parents[2])}")
    print(f"  baseline: {base['blind_rows_signalling']} of {base['blind_rows']} blind rows report the absence")
    print(f"            {base['sighted_rows_signalling']} of {base['sighted_rows']} sighted rows do")
    print(f"  corpus:   {radius['findings']} findings over {len(radius['scopes'])} scopes")
    marking = radius["marking"]
    print(
        f"  marking:  visually_verified False {marking['visually_verified_false']} / "
        f"True {marking['visually_verified_true']} / None {marking['visually_verified_none']}"
    )
    guard = radius["contradiction_guard"]
    print(
        f"  guard:    {guard['degraded_as_shipped']} rows degrade as shipped, "
        f"{guard['degraded_when_claiming_seen']} would if announced and every row claimed `seen`"
    )
    label = radius["trust_label"]
    print(
        f"  label:    {label['rows_downgraded']} rows lose {label['refused']} "
        f"({label['rows_downgraded_correctly']} correctly, {label['rows_over_downgraded']} over-fired)"
    )


if __name__ == "__main__":
    main()
