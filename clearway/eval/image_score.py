"""What the frozen image conditions say — scored deterministically against ACT gold, never by a judge.

The first thing this scores is the **secondary descriptive finding**: the difference between the two
text-only conditions, `leaky/no-image` (the pages ACT published) and `opaque/no-image` (the same pages
with every path cue ablated). It is descriptive rather than an endpoint, and it is deliberately *not*
the ablation gate — that gate is offline and model-free, and it already ran when the set was derived.

Why a model-based reading could not be the gate
-----------------------------------------------
It fails in both directions. It passes when one case moves for an irrelevant reason while a real cue
survives, and it fires when a perfect ablation meets a drafter that simply does not use filenames —
which is a finding about the drafter, not a defect in the set. So a difference of zero here is a
measured property of the text-only pipeline, and the only thing it licenses is re-verifying the real
gate before spending the endpoint's conditions.

What is also computed here, because the difference cannot be read without it
-----------------------------------------------------------------------------
* **The filename cue, measured.** In the vendored condition several cases carry an `alt` that *is*
  their own filename, and the help text says a filename does not describe. Against that, part of any
  leaky→opaque movement is a property of how a deprecated rule's fixtures were authored rather than
  of a page anyone would ship. The count is measured from the frozen reachability artifact under a
  rule stated in the report, and both readings of "≈" are given, because they disagree.
* **Within-condition stability.** Three samples of one condition share a byte-identical ask, so a
  disagreement between them is the stack, not the question — the null replicates the endpoint's null
  rate is estimated from. A one-sample condition reports this as *not measured*, never as zero.

This report survives a clone at a different path, and the other image artifacts do not
------------------------------------------------------------------------------------
`capture.json` and the dry receipt map `finding.id → a picture`, and a finding id hashes the case's
absolute `file://` URI, so both are bound to the working copy that built them. Nothing here recomputes
a finding id: the pairing is on `act_testcase_id`, and the ids that do appear are read back out of the
frozen passes rather than derived. So `build_report()` reproduces byte-identically wherever the repo
sits, and the byte-identity test is a determinism check rather than a check on this directory.

Regenerate with `uv run python -m clearway.eval.image_score` once both text-only conditions are
frozen. Pure: no model, no network.
"""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from clearway.eval.image_conditions import LEAKY_NO_IMAGE, OPAQUE_NO_IMAGE, Condition, condition_by_id
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE
from clearway.eval.image_pass import CANONICAL_SAMPLE, canonical_rows, load_pass, pass_failures, pass_path
from clearway.eval.image_reachability import ARTIFACT as REACHABILITY
from clearway.eval.offline_build import _REPORTS_DIR
from clearway.eval.run_scope import OutOfScope
from clearway.eval.stats import COLLAPSE_RULE, is_flag
from clearway.schemas.models import Conformance

REPORT = _REPORTS_DIR / "image_text_only_difference.json"

# How "the alt is the filename" is decided, stated so the count is reproducible rather than asserted.
# The primary rule compares the last path segment of `src` verbatim; the variant strips one extension.
# They disagree on exactly one case, and the report prints both rather than picking the flattering one.
CUE_RULE = (
    "the last path segment of `src`, compared case-insensitively to `alt` verbatim; the reported "
    "variant strips one trailing extension from that segment first"
)


def flagged(row: dict[str, Any]) -> bool:
    """Does this drafted row raise an alarm, under the collapse every acceptance number uses?"""
    return is_flag(Conformance(row["draft"]["conformance"]))


def _should_flag(row: dict[str, Any]) -> bool:
    return bool(row["gold"]["expected"] == "failed")


def condition_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    """One condition's canonical-sample verdicts, scored against ACT gold.

    Deterministic against the gold label, never against the judge — the standing rule for every number
    in this benchmark. `false_positives` is flagging a case ACT passed; `false_negatives` is missing
    one ACT failed.
    """
    rows = canonical_rows(artifact)
    verdicts = {row["receipt"]["act_testcase_id"]: flagged(row) for row in rows}
    return {
        "condition": artifact["condition"]["condition"],
        "eval_set_id": artifact["eval_set_id"],
        "canonical_sample": artifact.get("canonical_sample", CANONICAL_SAMPLE),
        "cases": len(rows),
        "flagged": sum(1 for row in rows if flagged(row)),
        "correct": sum(1 for row in rows if flagged(row) == _should_flag(row)),
        "false_positives": sum(1 for row in rows if flagged(row) and not _should_flag(row)),
        "false_negatives": sum(1 for row in rows if not flagged(row) and _should_flag(row)),
        "conformance_collapse_rule": COLLAPSE_RULE,
        "verdicts": verdicts,
    }


def instability(artifact: dict[str, Any]) -> dict[str, Any]:
    """How often this condition's repeated samples disagree with each other, at finding level.

    The samples share a byte-identical ask (asserted by `image_pass.pass_failures`), so a disagreement
    between them is the stack rather than the question — which is what makes them the null replicates
    the endpoint's null rate is estimated from. Counted over **pairs** of samples, so the rate is
    comparable with a figure measured at a different sample count.

    A condition with one sample reports `measurable: False`. It is the distinction the run-scope module
    exists over: an empty answer and a measured zero read identically in a report, and only one is true.
    """
    samples = artifact["samples"]
    by_finding: dict[str, list[bool]] = {}
    cases: dict[str, str] = {}
    for sample in samples:
        for row in sample["rows"]:
            by_finding.setdefault(row["receipt"]["finding_id"], []).append(flagged(row))
            cases[row["receipt"]["finding_id"]] = row["receipt"]["act_testcase_id"]

    if len(samples) < 2:
        return {
            "condition": artifact["condition"]["condition"],
            "measurable": False,
            "samples": len(samples),
            "findings": len(by_finding),
            "pairs": 0,
            "note": (
                "one sample — within-condition stability is NOT measured here, which is not the same "
                "as measured and found perfect. This condition was pre-registered as descriptive."
            ),
        }

    disagreeing = sum(sum(1 for a, b in combinations(seen, 2) if a != b) for seen in by_finding.values())
    pairs = len(by_finding) * len(list(combinations(range(len(samples)), 2)))
    unstable = sorted(fid for fid, seen in by_finding.items() if len(set(seen)) > 1)
    return {
        "condition": artifact["condition"]["condition"],
        "measurable": True,
        "samples": len(samples),
        "findings": len(by_finding),
        "pairs": pairs,
        "disagreeing_pairs": disagreeing,
        "rate": disagreeing / pairs,
        "unstable_findings": unstable,
        "unstable_cases": [cases[fid] for fid in unstable],
    }


def _cue_row(case: dict[str, Any]) -> dict[str, Any]:
    elements = case["image_elements"]
    if len(elements) != 1:
        raise OutOfScope(
            f"{case['act_testcase_id']} renders {len(elements)} images — the cue measurement compares "
            "one `alt` against one `src`, and reading the first of several would report a cue for a "
            "picture the finding may not even be about"
        )
    element = elements[0]
    alt, src = element["alt"] or "", element["src"] or ""
    segment = src.rsplit("/", 1)[-1]
    stem = segment.rsplit(".", 1)[0] if "." in segment else segment
    return {
        "act_testcase_id": case["act_testcase_id"],
        "expected": case["expected"],
        "alt": alt,
        "src_last_segment": segment,
        "alt_equals_filename": alt.casefold() == segment.casefold(),
        "alt_equals_filename_stem": alt.casefold() == stem.casefold(),
    }


def filename_cue(artifact: Path = REACHABILITY) -> dict[str, Any]:
    """How many of the vendored pool's cases carry an `alt` that is their own filename — measured.

    Read from the frozen reachability artifact, which records each case's `alt` and `src` as scanned,
    so the number needs no browser and no model and moves only if the vendored pages move.

    The two readings disagree by one case, and both are reported. Neither is the "right" one: the
    point of the measurement is that a help text saying *a filename does not describe* meets a fixture
    whose `alt` is close to a string-equality match for its filename, and how close counts is exactly
    what a single number would hide.
    """
    frozen = json.loads(artifact.read_text())
    pool = set(frozen["pool"])
    cases = [case for case in frozen["cases"] if case["act_testcase_id"] in pool]
    rows = [_cue_row(case) for case in cases]
    helps = {minted["help"] for case in cases for minted in case["minted"]}
    return {
        "rule": CUE_RULE,
        "cases": rows,
        "alt_equals_filename": sum(1 for row in rows if row["alt_equals_filename"]),
        "alt_equals_filename_stem": sum(1 for row in rows if row["alt_equals_filename_stem"]),
        # Quoted from the frozen artifact rather than transcribed: the sentence below is only a caveat
        # if the prompt really does say this, and a hand-copied quote is a claim nobody re-checks.
        "help_text": sorted(helps),
        "note": (
            "In the vendored condition the drafter's help text says a filename does not describe an "
            "image, and these cases hand it an alt that is (or nearly is) the filename. So part of any "
            "leaky→opaque movement is a property of how a DEPRECATED rule's fixtures were authored, "
            "not of pages anyone ships. Reported beside the difference, never subtracted from it."
        ),
    }


def _caveat(cue: dict[str, Any]) -> str:
    """The one sentence that has to travel with the difference, written from the measured counts.

    Generated rather than transcribed so it cannot drift from the numbers beside it — and so the
    spec's own "4 of 7" is reproduced by a rule, not asserted.
    """
    total = len(cue["cases"])
    quoted = "; ".join(f'"{help_text}"' for help_text in cue["help_text"])
    return (
        f"This difference partly measures a fixture artifact. In the leaky condition "
        f"{cue['alt_equals_filename']} of {total} cases have an alt equal to their own filename "
        f"({cue['alt_equals_filename_stem']} of {total} once one extension is stripped; the rule is "
        f"{CUE_RULE}), and the drafter's help text says {quoted}. So on those cases the leaky cue is "
        "close to a string-equality trigger — a property of how a DEPRECATED rule's fixtures were "
        "authored, not of real pages."
    )


def ablation_gate_provenance() -> dict[str, Any]:
    """Where the real ablation gate lives, and the digest of the bytes it passed on.

    Deliberately a **pointer plus a checksum**, not a re-run. The gate is `image_opaque`'s offline
    token check over the minted prompts, asserted by the opaque set's own tests; re-implementing it
    here would give the milestone two gates that could disagree. What makes the pointer more than a
    claim is the second field: the ablated pages the gate passed on are checksummed, so a condition
    drafted over pages that have since moved shows up as a digest that no longer matches, rather than
    as a sentence nobody re-checked.
    """
    checksums = ACT_IMAGE_OPAQUE / "checksums.sha256"
    return {
        "gate": "clearway.eval.image_opaque.ablation_failures, over the minted `finding.html`",
        "asserted_by": "tests/test_image_opaque.py::test_the_ablation_gate_passes_on_every_minted_prompt",
        "note": (
            "THE ablation gate is that offline, model-free check — not the difference measured here. "
            "This report neither runs it nor stands in for it; it records which bytes the conditions "
            "were drafted over so a set that moved after the gate ran cannot pass unnoticed."
        ),
        "opaque_set_checksums_sha256": hashlib.sha256(checksums.read_bytes()).hexdigest(),
    }


def _text_only(artifact: dict[str, Any]) -> Condition:
    condition = condition_by_id(artifact["condition"]["condition"])
    if condition.carries_image:
        raise OutOfScope(
            f"{condition.condition_id!r} attaches a picture — this comparison is defined over the two "
            "text-only conditions, and running it over an image condition would report the endpoint's "
            "manipulation as a descriptive difference"
        )
    return condition


def text_only_difference(leaky: dict[str, Any], opaque: dict[str, Any]) -> dict[str, Any]:
    """The secondary descriptive finding: what removing the path cues did to the text-only verdicts.

    Paired by `act_testcase_id`, never by `finding_id`: the ablated pages sit at a different path and a
    finding id hashes its page's URL, so pairing on finding id would pair nothing and report a
    difference of zero over seven cases — an empty answer wearing a measurement's clothes.
    """
    conditions = (_text_only(leaky), _text_only(opaque))
    if {c.condition_id for c in conditions} != {LEAKY_NO_IMAGE.condition_id, OPAQUE_NO_IMAGE.condition_id}:
        raise OutOfScope(
            f"the difference is defined between the two text-only conditions "
            f"({LEAKY_NO_IMAGE.condition_id!r} and {OPAQUE_NO_IMAGE.condition_id!r}), not "
            f"{sorted(c.condition_id for c in conditions)}"
        )

    left, right = condition_summary(leaky), condition_summary(opaque)
    if set(left["verdicts"]) != set(right["verdicts"]):
        raise OutOfScope(
            "the two conditions do not cover the same cases — a difference over the intersection would "
            f"report whichever cases happened to overlap ({len(set(left['verdicts']) & set(right['verdicts']))} "
            f"of {len(set(left['verdicts']) | set(right['verdicts']))})"
        )

    cue = filename_cue()
    # Both readings are carried per case, because they disagree on one — and reporting the split under
    # the strict rule alone would file that case as movement away from the cue when it may be movement
    # on it. Which reading is right is exactly what this measurement cannot settle.
    carries_cue = {row["act_testcase_id"]: row["alt_equals_filename"] for row in cue["cases"]}
    carries_cue_stem = {row["act_testcase_id"]: row["alt_equals_filename_stem"] for row in cue["cases"]}
    gold = {row["receipt"]["act_testcase_id"]: row["gold"]["expected"] for row in canonical_rows(leaky)}
    by_case = [
        {
            "act_testcase_id": case_id,
            "expected": gold[case_id],
            "leaky_flagged": left["verdicts"][case_id],
            "opaque_flagged": right["verdicts"][case_id],
            "moved": left["verdicts"][case_id] != right["verdicts"][case_id],
            "direction": (
                None
                if left["verdicts"][case_id] == right["verdicts"][case_id]
                else ("toward_flag" if right["verdicts"][case_id] else "toward_clean")
            ),
            "carries_filename_cue": carries_cue.get(case_id, False),
            "carries_filename_cue_stem": carries_cue_stem.get(case_id, False),
        }
        for case_id in left["verdicts"]
    ]

    moved = [row for row in by_case if row["moved"]]
    differs = bool(moved)
    return {
        "cases": len(by_case),
        "moved": len(moved),
        "differs": differs,
        "toward_flag": sum(1 for row in moved if row["direction"] == "toward_flag"),
        "toward_clean": sum(1 for row in moved if row["direction"] == "toward_clean"),
        "moved_on_cue_cases": sum(1 for row in moved if row["carries_filename_cue"]),
        "moved_off_cue_cases": sum(1 for row in moved if not row["carries_filename_cue"]),
        "moved_on_cue_cases_stem": sum(1 for row in moved if row["carries_filename_cue_stem"]),
        "moved_off_cue_cases_stem": sum(1 for row in moved if not row["carries_filename_cue_stem"]),
        "reading": _reading(differs),
        "caveat": _caveat(cue),
        "by_case": by_case,
    }


def _reading(differs: bool) -> str:
    """What the difference licenses — fixed in advance, so the sentence is not chosen after the count."""
    if differs:
        return (
            "The two text-only conditions differ. This is descriptive and is NOT the ablation gate: "
            "the gate is the offline, model-free token check run when the opaque set was derived. A "
            "difference here is consistent with the path cues having carried information, and is also "
            "consistent with one case moving for an unrelated reason — see the per-case split and the "
            "filename-cue measurement before reading it as the first."
        )
    return (
        "The two text-only conditions do not differ: removing every path cue moved no verdict. Recorded "
        "as a measured property of the text-only pipeline, NOT as a failed ablation — a model-based "
        "reading fires on a perfect ablation whenever the drafter simply does not use filenames. It is "
        "not the ablation gate either way, and the pre-registered consequence is that the endpoint's "
        "conditions are not spent until the real gate (the offline token check) has been re-verified."
    )


def build_report() -> dict[str, Any]:
    """Re-derive the descriptive comparison from both frozen passes. Refuses an unsound pass."""
    passes = {condition: load_pass(condition) for condition in (LEAKY_NO_IMAGE, OPAQUE_NO_IMAGE)}
    for condition, artifact in passes.items():
        failures = pass_failures(artifact)
        if failures:
            raise OutOfScope(f"{condition.condition_id} is not a sound pass: {'; '.join(failures)}")

    leaky, opaque = passes[LEAKY_NO_IMAGE], passes[OPAQUE_NO_IMAGE]
    return {
        "artifact": "the leaky → opaque text-only difference, a secondary descriptive finding",
        "version": 1,
        "note": (
            "The two text-only conditions of the image experiment, compared. Scored deterministically "
            "against ACT gold, never by the judge. Descriptive: it is not an endpoint and it is NOT the "
            "ablation gate — that gate is the offline token check the opaque set was derived under. "
            "Both conditions were drafted against PINNED candidate criteria, so neither reflects what a "
            "live retriever would surface; the pinning is identical across them and cannot move the "
            "difference. The opaque condition's three samples share a byte-identical ask, so their "
            "disagreements are the stack and are recorded as the null replicates."
        ),
        "passes": {
            condition.condition_id: {
                "path": pass_path(condition).name,
                "created_at": artifact["created_at"],
                "drafter_model": artifact["drafter_model"],
                "drafter_model_digest": artifact["drafter_model_digest"],
                "corpus_version": artifact["corpus_version"],
                "samples": len(artifact["samples"]),
            }
            for condition, artifact in passes.items()
        },
        "conditions": {
            LEAKY_NO_IMAGE.condition_id: condition_summary(leaky),
            OPAQUE_NO_IMAGE.condition_id: condition_summary(opaque),
        },
        "instability": {
            LEAKY_NO_IMAGE.condition_id: instability(leaky),
            OPAQUE_NO_IMAGE.condition_id: instability(opaque),
        },
        "filename_cue": filename_cue(),
        "ablation_gate": ablation_gate_provenance(),
        "difference": text_only_difference(leaky, opaque),
    }


def main() -> None:
    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    difference = report["difference"]
    print(f"wrote {REPORT.relative_to(Path.cwd())}")
    for name, summary in report["conditions"].items():
        print(
            f"  {name:<16} correct {summary['correct']}/{summary['cases']}  "
            f"flagged {summary['flagged']}  FP {summary['false_positives']}  FN {summary['false_negatives']}"
        )
    print(
        f"  difference: {difference['moved']}/{difference['cases']} cases moved "
        f"({difference['toward_flag']} toward flag, {difference['toward_clean']} toward clean; "
        f"{difference['moved_on_cue_cases']} on filename-cue cases)"
    )
    stability = report["instability"][OPAQUE_NO_IMAGE.condition_id]
    print(f"  opaque stability: {stability['disagreeing_pairs']}/{stability['pairs']} pairs disagree")


if __name__ == "__main__":
    main()
