"""What the frozen image conditions say — scored deterministically against ACT gold, never by a judge.

Three measurements live here, and they are not of the same rank. **"Endpoint" is the trial-design
sense throughout — a pre-registered outcome measure, never an HTTP route; see the package docstring.**

**The primary endpoint is D**: the number of pool cases whose verdict moves when the *wrong* picture
is attached behind a byte-identical prompt. It is the milestone's whole question — does the drafter
attend to the pixels — and it is read against a null rate, a retained-cell rule and four verdicts all
fixed before any condition ran. Its section starts at `endpoint_d`.

**The second endpoint is A**: of the six pool cases whose judgment needs pixels, how many withhold a
conformance judgment when the drafter is told no picture is attached and given a field to say so. It
is a different question from D — D asks whether the pixels are read, A asks whether their *absence*
is reported — and it is read against two controls and four verdicts fixed before either of its
conditions ran. It never touches D: its conditions announce the channel, so their prompts differ from
D's by construction, which is checked here rather than asserted. Its section starts at `endpoint_a`.

**The secondary descriptive finding** is the difference between the two
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
a finding id: the pairing is on `act_testcase_id`, and every id that appears is read back out of a
frozen artifact. The endpoint's receipt check does compare two of those path-bound artifacts against
each other — but both are frozen, so the comparison is between two recordings and not against this
directory. Both reports therefore reproduce byte-identically wherever the repo sits, and their
byte-identity tests are determinism checks rather than checks on a path.

Regenerate both with `uv run python -m clearway.eval.image_score`, once all four conditions are
frozen. Pure: no model, no network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from clearway.eval.blind_judgment import baseline
from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_conditions import (
    ANNOUNCED_CONDITIONS,
    CONDITIONS,
    LEAKY_NO_IMAGE,
    OPAQUE_MISMATCHED_IMAGE,
    OPAQUE_NO_IMAGE,
    OPAQUE_TOLD_NO_IMAGE,
    OPAQUE_TOLD_WITH_IMAGE,
    OPAQUE_WITH_IMAGE,
    RECEIPT,
    Condition,
    condition_by_id,
    receipt_failures,
)
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE, PERMUTATION, specificity_control_row
from clearway.eval.image_pass import CANONICAL_SAMPLE, canonical_rows, load_pass, pass_failures, pass_path
from clearway.eval.image_reachability import ARTIFACT as REACHABILITY
from clearway.eval.offline_build import _REPORTS_DIR
from clearway.eval.run_scope import OutOfScope
from clearway.eval.stats import COLLAPSE_RULE, binomial_tail_ge, is_flag
from clearway.schemas.models import Conformance, VisualEvidence

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


# --- the primary endpoint: D -------------------------------------------------

# The null rate M7 measured on this stack: 1 drifting finding in 54, across three passes of one
# condition at temperature 0 — numerical nondeterminism from KV-cache reuse, not sampling. It is the
# FLOOR under M8's own estimate, never a replacement for it: 63 pairs here expect ~1.2 disagreements,
# which is too coarse to certify a clean run as a clean stack. Recorded in docs/referent-injection-result.md.
M7_DRIFT_RATE = 1 / 54

# The four verdicts, pre-committed in the spec before any condition ran. Strings rather than an enum
# because they are quoted verbatim into the milestone's report and must not be paraphrased there.
VERDICT_CONFIRMED = "delivery confirmed"
VERDICT_INCONCLUSIVE = "inconclusive — indistinguishable from drift"
VERDICT_REFUTED = "delivery refuted"
VERDICT_UNINTERPRETABLE = "uninterpretable — fewer than two retained cells"

# What every disagreement was pre-registered to look like if the pixels are being read: the wrong
# picture should push the drafter toward does_not_support. Secondary, and never gated on — gating on
# direction would condition the denominator on the result.
PREDICTED_DIRECTION = "toward_flag"

SPECIFICITY_CONTROL_READING = (
    "This cell is dead by design: its alt is a hex digest, which describes no picture, so the correct "
    "verdict is the same whatever is attached. It stays inside D as a within-experiment control — a "
    "disagreement here is evidence the manipulation moved something other than perception, so it is "
    "reported, never dropped."
)

UNDER_DETECTION_NOTE = (
    "D systematically under-detects attendance. A mismatched picture may make the drafter genuinely "
    "uncertain rather than cleanly flip it, and the stability filter codes that uncertainty as noise "
    "and excludes the cell. The bias is conservative — it can only cost D, never inflate it."
)

ENDPOINT_REPORT = _REPORTS_DIR / "image_endpoint.json"


def _cells(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One cell per pool case: its canonical verdict, every sample's verdict, and whether it held.

    Keyed by `act_testcase_id`, because that is the unit D is defined over and the only key that
    survives a clone at a different path. A case that minted more than one finding is **refused**:
    collapsing several findings into one cell needs a rule (flag-if-any, in M7's case), and this
    endpoint was pre-registered over a pool of one finding per case.
    """
    canonical = artifact.get("canonical_sample", CANONICAL_SAMPLE)
    condition = artifact["condition"]["condition"]
    cells: dict[str, dict[str, Any]] = {}
    for sample in artifact["samples"]:
        seen: set[str] = set()
        for row in sample["rows"]:
            case_id = row["receipt"]["act_testcase_id"]
            if case_id in seen:
                raise OutOfScope(
                    f"{case_id} carries more than one finding in sample {sample['sample']} of "
                    f"{condition} — D is defined over cases, and folding several findings into one "
                    "cell needs a collapse rule this endpoint was never registered under"
                )
            seen.add(case_id)
            cell = cells.setdefault(case_id, {"flags": [], "conformance": []})
            cell["flags"].append(flagged(row))
            cell["conformance"].append(row["draft"]["conformance"])
            if sample["sample"] == canonical:
                cell["canonical_flag"] = flagged(row)
                cell["canonical_conformance"] = row["draft"]["conformance"]
    for case_id, cell in cells.items():
        if "canonical_flag" not in cell:
            raise OutOfScope(
                f"{condition} carries no sample {canonical}, so {case_id} has no canonical verdict. "
                "Reading a later sample instead would define the endpoint from a replicate that "
                "exists only to say how stable the canonical pass is."
            )
        cell["stable"] = len(set(cell["flags"])) == 1
    return cells


def specificity_control(artifact: Path = PERMUTATION) -> dict[str, Any]:
    """The cell that should not move, read out of the frozen permutation rather than transcribed.

    Its `alt` is a hex digest: it describes neither the picture the case shows nor the one the
    manipulation attaches, so its correct verdict is invariant under the swap. The identification
    itself lives beside the note that authors it (`image_opaque.specificity_control_row`) — this cell
    is also the instance the pixel-decided marking over-fires on, and a case named by two measurements
    is named once. What this adds is D's reading of it.
    """
    row = specificity_control_row(artifact)
    return {
        "act_testcase_id": row["act_testcase_id"],
        "alt": row["alt"],
        "live": row["live"],
        "frozen_note": row["note"],
        "reading": SPECIFICITY_CONTROL_READING,
    }


def _endpoint_pair(with_image: dict[str, Any], mismatched: dict[str, Any]) -> None:
    """Refuse anything but the endpoint's two conditions, in that order.

    Order matters and is not a style point: the direction check reads the mismatched condition against
    the with-image one, so a swapped pair would report every movement backwards.
    """
    got = (with_image["condition"]["condition"], mismatched["condition"]["condition"])
    expected = (OPAQUE_WITH_IMAGE.condition_id, OPAQUE_MISMATCHED_IMAGE.condition_id)
    if got != expected:
        raise OutOfScope(
            f"D is defined between {expected[0]!r} (with-image) and {expected[1]!r}, in that order — "
            f"got {list(got)}. The direction check reads one against the other, so a swapped pair "
            "would report every movement backwards."
        )


def endpoint_d(with_image: dict[str, Any], mismatched: dict[str, Any]) -> dict[str, Any]:
    """**D**: the pool cases whose verdict moved when the picture did, behind an identical prompt.

    Defined over cells fixed in advance, never over verdicts. All seven are in — the four *live* cells
    describe the power, and a dead cell that moves is evidence the manipulation touched something
    other than perception, which is exactly why it is not filtered out.

    A cell whose three samples disagree in **either** condition is excluded and named: under an
    identical ask it moved on its own, so it cannot tell a picture from drift. Since D's threshold is
    an absolute count, excluding a cell costs power and cannot bias toward confirmation.
    """
    _endpoint_pair(with_image, mismatched)
    left, right = _cells(with_image), _cells(mismatched)
    if set(left) != set(right):
        raise OutOfScope(
            "the two conditions do not cover the same cases — D over the intersection would count "
            f"whichever cells happened to overlap ({len(set(left) & set(right))} of {len(set(left) | set(right))})"
        )

    frozen = json.loads(CAPTURE_ARTIFACT.read_text())["resolved_permutation"]
    if {row["act_testcase_id"] for row in frozen} != set(left):
        raise OutOfScope(
            "the conditions cover cases the frozen permutation does not name (or miss ones it does) — "
            "every cell of D has to be one the mapping was frozen over before any verdict existed"
        )

    control_id = specificity_control()["act_testcase_id"]
    by_case = []
    for row in frozen:
        case_id = row["act_testcase_id"]
        this, other = left[case_id], right[case_id]
        retained = bool(this["stable"] and other["stable"])
        differs = this["canonical_flag"] != other["canonical_flag"]
        by_case.append(
            {
                "act_testcase_id": case_id,
                "live": row["live"],
                "true_image": row["true_image"],
                "mismatched_image": row["mismatched_image"],
                "with_image": {
                    "conformance": this["canonical_conformance"],
                    "flagged": this["canonical_flag"],
                    "samples": this["conformance"],
                    "stable": this["stable"],
                },
                "mismatched": {
                    "conformance": other["canonical_conformance"],
                    "flagged": other["canonical_flag"],
                    "samples": other["conformance"],
                    "stable": other["stable"],
                },
                "retained": retained,
                "differs": differs,
                "counted_in_d": retained and differs,
                # The finer movement, recorded beside the collapsed one it cannot replace: D is defined
                # on the binary collapse, the same axis the null replicates are counted on.
                "conformance_differs": this["canonical_conformance"] != other["canonical_conformance"],
                "direction": (
                    None if not differs else (PREDICTED_DIRECTION if other["canonical_flag"] else "toward_clean")
                ),
            }
        )

    counted = [row for row in by_case if row["counted_in_d"]]
    control = next(row for row in by_case if row["act_testcase_id"] == control_id)
    return {
        "statistic": (
            "D = the number of pool cases whose opaque/with-image verdict differs from its "
            "opaque/mismatched-image verdict, over cells fixed in advance"
        ),
        "collapse_rule": COLLAPSE_RULE,
        "cells": len(by_case),
        "live_cells": sum(1 for row in by_case if row["live"]),
        "retained": sum(1 for row in by_case if row["retained"]),
        "live_cells_retained": sum(1 for row in by_case if row["live"] and row["retained"]),
        "excluded": [row["act_testcase_id"] for row in by_case if not row["retained"]],
        "d": len(counted),
        # Reported so an excluded cell that moved is visible rather than absorbed: it is not evidence,
        # but a reader must be able to see that D and the raw movement are not the same number.
        "differing_cells_including_excluded": sum(1 for row in by_case if row["differs"]),
        "direction": {
            "predicted": PREDICTED_DIRECTION,
            "toward_flag": sum(1 for row in counted if row["direction"] == "toward_flag"),
            "toward_clean": sum(1 for row in counted if row["direction"] == "toward_clean"),
            "note": (
                "A pre-registered SECONDARY strengthening: if the pixels are being read, the wrong "
                "picture should push the drafter toward does_not_support. Reported, never gated on — "
                "gating on direction would re-import a denominator conditioned on the result."
            ),
        },
        "specificity_control": {**specificity_control(), **{k: control[k] for k in ("differs", "retained")}},
        "by_case": by_case,
    }


def null_rate(artifacts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The rate at which this stack answers an identical ask differently — the endpoint's null.

    Pooled over **every** condition that took repeats, **including the cells D excludes**. Estimating
    it from the retained cells only would be circular: those cells are retained *because* they held,
    and the excluded ones are the evidence that drift exists, so dropping them from the denominator
    while acting on them in the numerator biases toward confirmation.

    The rate used is `max(measured here, M7's 1/54)`. M8's own estimate is low-resolution — 63 pairs,
    expecting about 1.2 disagreements — so it corroborates M7's figure rather than replacing it, and a
    lucky clean run cannot buy a null rate of zero, under which any single disagreement would look
    decisive.
    """
    per_condition = [instability(artifact) for artifact in artifacts]
    measurable = [measured for measured in per_condition if measured["measurable"]]
    if not measurable:
        raise OutOfScope(
            "no replicates: every condition given took a single sample, so this stack's disagreement "
            "rate is not measured here. An unmeasured rate is not a rate of zero."
        )

    pairs = sum(measured["pairs"] for measured in measurable)
    disagreeing = sum(measured["disagreeing_pairs"] for measured in measurable)
    measured_rate = disagreeing / pairs
    return {
        "pairs": pairs,
        "disagreeing_pairs": disagreeing,
        "measured_rate": measured_rate,
        "m7_rate": M7_DRIFT_RATE,
        "rate": max(measured_rate, M7_DRIFT_RATE),
        "source": "M8" if measured_rate > M7_DRIFT_RATE else "M7",
        "conditions": per_condition,
        "not_measurable": [measured["condition"] for measured in per_condition if not measured["measurable"]],
        "note": (
            "Pooled over every condition that took repeats, including the cells D excludes — a rate "
            "estimated from the retained cells alone would be conditioned on the very stability the "
            "endpoint acts on. The rate used is the max of this and M7's 1 finding in 54, because 63 "
            "pairs cannot certify a clean stack and a null rate of zero would make one disagreement "
            "look decisive."
        ),
    }


def endpoint_verdict(d: int, retained: int) -> str:
    """One of the four pre-committed verdicts, from D and the retained-cell count alone.

    The uninterpretable branch is checked **first**: below two retained cells, D ≥ 2 is unreachable by
    construction, so reading D = 0 as *refuted* would publish a false negative as the headline of a
    measurement that never had the power to say anything.
    """
    if retained < 2:
        return VERDICT_UNINTERPRETABLE
    if d >= 2:
        return VERDICT_CONFIRMED
    if d == 1:
        return VERDICT_INCONCLUSIVE
    return VERDICT_REFUTED


def endpoint_reading(endpoint: dict[str, Any], null: dict[str, Any]) -> dict[str, Any]:
    """What D licenses: the verdict, the null rate it was read against, and the tail it implies.

    The tail is computed over the **retained** cells rather than over all seven, so a run that lost
    cells to drift quotes the power it actually had. The verdict is a function of D and the retained
    count only — the p-value is reported beside it, never substituted for it, because the thresholds
    were pre-registered as counts.
    """
    d, retained, rate = endpoint["d"], endpoint["retained"], null["rate"]
    return {
        "d": d,
        "cells": endpoint["cells"],
        "retained": retained,
        "excluded": endpoint["excluded"],
        "null_rate": rate,
        "null_rate_source": null["source"],
        "measured_null_rate": null["measured_rate"],
        "p_value": binomial_tail_ge(d, retained, rate),
        "p_value_note": (
            f"P(D ≥ {d}) over the {retained} retained cells at a null rate of {rate:.5f}. The "
            "pre-registered thresholds are counts, so this is reported beside the verdict and never "
            "in place of it; it says what the retained cells were worth, which a seven-cell tail "
            "would overstate."
        ),
        "pre_registered_thresholds": [
            {"d": "≥ 2", "p_at_7_cells": binomial_tail_ge(2, 7, M7_DRIFT_RATE), "verdict": VERDICT_CONFIRMED},
            {"d": "1", "p_at_7_cells": binomial_tail_ge(1, 7, M7_DRIFT_RATE), "verdict": VERDICT_INCONCLUSIVE},
            {"d": "0", "p_at_7_cells": None, "verdict": VERDICT_REFUTED},
            {"d": "any, with fewer than 2 retained cells", "p_at_7_cells": None, "verdict": VERDICT_UNINTERPRETABLE},
        ],
        "verdict": endpoint_verdict(d, retained),
        "direction": endpoint["direction"],
        "note": UNDER_DETECTION_NOTE,
    }


def _sample_rows(artifact: dict[str, Any], sample_n: int) -> list[dict[str, Any]]:
    """This condition's receipt rows for sample `n`, falling back to its canonical sample.

    The fallback is for the one-sample descriptive condition: it has no second or third pass, and its
    rows are in every check because the receipt check requires all four conditions to be complete.
    """
    for sample in artifact["samples"]:
        if sample["sample"] == sample_n:
            return [row["receipt"] for row in sample["rows"]]
    return [row["receipt"] for row in canonical_rows(artifact)]


def receipt_assertion(passes: Mapping[Condition, dict[str, Any]]) -> dict[str, Any]:
    """The live proof that the manipulation was actually run mismatched — every sample, not just one.

    Two independent claims, kept apart because they falsify different things:

    1. `failures` — the frozen permutation was honoured and the prompts were byte-identical across the
       opaque conditions, checked by `image_conditions.receipt_failures` over one sample of each of the
       four conditions at a time. Run per sample rather than on the canonical one alone: a condition
       whose later samples sent the case's own bytes would still be three samples of *something*, and
       the endpoint would read them as stability.
    2. `dry_receipt_failures` — the digests actually sent are the ones the model-free rehearsal froze
       before a single call was spent. A live pass that attached something else is a different
       experiment wearing this one's name.
    """
    if set(passes) != set(CONDITIONS):
        raise OutOfScope(
            "the receipt assertion needs all four conditions — the permutation check is defined "
            f"across them, and a missing one silently drops its rows from every claim (got "
            f"{sorted(c.condition_id for c in passes)})"
        )

    failures: list[str] = []
    rows_checked = 0
    samples = max(len(artifact["samples"]) for artifact in passes.values())
    for sample_n in range(1, samples + 1):
        rows = [row for artifact in passes.values() for row in _sample_rows(artifact, sample_n)]
        rows_checked += len(rows)
        failures += [f"sample {sample_n}: {failure}" for failure in receipt_failures(rows)]

    frozen = {
        (row["condition"], row["finding_id"]): row["image_sha256"] for row in json.loads(RECEIPT.read_text())["rows"]
    }
    dry_failures = []
    for artifact in passes.values():
        for sample in artifact["samples"]:
            for row in sample["rows"]:
                receipt = row["receipt"]
                key = (receipt["condition"], receipt["finding_id"])
                if key not in frozen:
                    dry_failures.append(f"{key} appears in no rehearsed condition — nothing pre-registered it")
                elif frozen[key] != receipt["image_sha256"]:
                    dry_failures.append(
                        f"{key} sent {str(receipt['image_sha256'])[:8]}…, the rehearsal froze "
                        f"{str(frozen[key])[:8]}… — a different picture from the pre-registered one"
                    )

    with_image = {row["finding_id"]: row["image_sha256"] for row in _sample_rows(passes[OPAQUE_WITH_IMAGE], 1)}
    mismatched = {row["finding_id"]: row["image_sha256"] for row in _sample_rows(passes[OPAQUE_MISMATCHED_IMAGE], 1)}
    return {
        "failures": failures,
        "dry_receipt_failures": dry_failures,
        "matches_dry_receipt": not dry_failures,
        "samples_checked": samples,
        "rows_checked": rows_checked,
        "digests_differ": sum(1 for fid, ref in with_image.items() if mismatched.get(fid) != ref),
        "findings": len(with_image),
        "note": (
            "A digest per finding per condition, and not a byte count: four of the seven findings "
            "render the same photograph, so a count check would pass whether or not the frozen "
            "permutation was honoured. The digests are the ones the drafter reported having sent."
        ),
    }


def build_endpoint_report() -> dict[str, Any]:
    """Re-derive the endpoint from the four frozen passes. Refuses an unsound pass or a bad receipt."""
    passes = {condition: load_pass(condition) for condition in CONDITIONS}
    for condition, artifact in passes.items():
        failures = pass_failures(artifact)
        if failures:
            raise OutOfScope(f"{condition.condition_id} is not a sound pass: {'; '.join(failures)}")

    receipts = receipt_assertion(passes)
    if receipts["failures"] or receipts["dry_receipt_failures"]:
        raise OutOfScope(
            "the conditions did not send what the frozen mapping says, so D would be a statistic over "
            f"an unknown manipulation: {'; '.join(receipts['failures'] + receipts['dry_receipt_failures'])}"
        )

    endpoint = endpoint_d(passes[OPAQUE_WITH_IMAGE], passes[OPAQUE_MISMATCHED_IMAGE])
    null = null_rate(list(passes.values()))
    return {
        "artifact": "the primary endpoint: does the drafter attend to the pixels?",
        "version": 1,
        "note": (
            "D counts the pool cases whose verdict moved when the WRONG picture was attached behind a "
            "byte-identical prompt. Scored deterministically against the drafted verdicts, never by "
            "the judge. All four conditions were drafted against PINNED candidate criteria, not live "
            "retrieval, so none of them reflects what a live retriever would surface; the pinning is "
            "identical across them and cannot move D. The prompts never say a picture is attached — "
            "keeping the text identical is what the endpoint rests on, and it also means the model was "
            "never told to look."
        ),
        "passes": {
            condition.condition_id: {
                "path": pass_path(condition).name,
                "created_at": artifact["created_at"],
                "drafter_model": artifact["drafter_model"],
                "drafter_model_digest": artifact["drafter_model_digest"],
                "corpus_version": artifact["corpus_version"],
                "attaches": artifact["condition"]["attaches"],
                "samples": len(artifact["samples"]),
            }
            for condition, artifact in passes.items()
        },
        "conditions": {
            condition.condition_id: condition_summary(artifact)
            for condition, artifact in passes.items()
            if condition.carries_image
        },
        "instability": {condition.condition_id: instability(artifact) for condition, artifact in passes.items()},
        "null_rate": null,
        "receipts": receipts,
        "endpoint": endpoint,
        "reading": endpoint_reading(endpoint, null),
    }


# --- the second endpoint: A, does the drafter report the absence? ------------

ABSENCE_REPORT = _REPORTS_DIR / "image_absence_endpoint.json"

# The one pool case the frozen permutation records as decided by TEXT alone: its `alt` is a hex digest,
# which describes nothing whatever is attached. Written down rather than recomputed, and checked below
# against the artifact that names it, so neither can drift alone. A predicate re-deriving
# "image-decided" would be a second definition of a set the permutation already fixed — and this case
# is both the one A's denominator excludes and the control that says A is reasoning rather than
# obedience, so it must be exactly one case and exactly that one.
TEXT_DECIDED_CASE = "a2333ec76e676624212dcd616ed11ae576ab775e"

# What withholding looks like on the row: the model reporting that deciding this element needed a
# picture and none was available to it. Read off the enum, never spelled as a literal, so the value
# the model is asked for and the value counted here cannot come apart.
WITHHOLDING = VisualEvidence.ABSENT.value
TEXT_DECIDED_ANSWER = VisualEvidence.NOT_NEEDED.value

# The four verdicts, pre-committed in the spec before either announced condition ran.
VERDICT_A_UNINTERPRETABLE = "uninterpretable — a control failed"
VERDICT_A_CLOSED = "closed — the drafter reports the absence wherever its judgment needed pixels"
VERDICT_A_PARTIAL = "partial — the drafter reports the absence on some of the cases and not others"
VERDICT_A_NOT_USED = "not used — an explicit statement of absence does not change what the drafter does"

A_CONFORMANCE_NOTE = (
    "`Conformance` has nowhere to put an abstention — its four values are supports, "
    "partially_supports, does_not_support and not_applicable, and the fourth speaks about the RULE "
    "rather than about the evidence — so a row that withholds still carries a conformance verdict. "
    "That is a property of the instrument, not a hedge, and the verdict is printed beside every "
    "withheld row so a reader sees what the model answered while saying it could not see. Adding an "
    "abstention value would move stats.FLAGS/CLEAN and every acceptance number in the repo."
)

A_UNSTABLE_NOTE = (
    "A is read from sample 1 over all six cases, and an unstable case is NAMED rather than dropped. D "
    "excludes a cell whose samples disagree because D is a count read against a null rate, where a "
    "lost cell costs power and cannot inflate the result; A is an absolute count out of a fixed six, "
    "where dropping a case shrinks the denominator and makes a partial result look closer to closed."
)


def _absence_cells(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One cell per pool case: what it said it could see, in the canonical sample and in every sample.

    Keyed by `act_testcase_id`, like D's cells and for the same reason — it is the unit the endpoint is
    defined over, and the only key that survives a clone at a different path. A case appearing twice in
    one sample is refused rather than folded: this endpoint was registered over a pool of one finding
    per case, and a collapse rule invented here would be a rule nobody pre-registered.
    """
    canonical = artifact.get("canonical_sample", CANONICAL_SAMPLE)
    condition = artifact["condition"]["condition"]
    cells: dict[str, dict[str, Any]] = {}
    for sample in artifact["samples"]:
        seen: set[str] = set()
        for row in sample["rows"]:
            case_id = row["receipt"]["act_testcase_id"]
            if case_id in seen:
                raise OutOfScope(
                    f"{case_id} carries more than one finding in sample {sample['sample']} of "
                    f"{condition} — A is defined over cases, one row each"
                )
            seen.add(case_id)
            draft = row["draft"]
            cell = cells.setdefault(case_id, {"samples": []})
            cell["samples"].append(draft["visual_evidence"])
            if sample["sample"] == canonical:
                cell["visual_evidence"] = draft["visual_evidence"]
                cell["contradicted_claim"] = draft["contradicted_claim"]
                cell["visually_verified"] = draft["visually_verified"]
                cell["conformance"] = draft["conformance"]
                cell["confidence"] = draft["confidence"]
    for case_id, cell in cells.items():
        if "visual_evidence" not in cell:
            raise OutOfScope(
                f"{condition} carries no sample {canonical}, so {case_id} has no canonical answer. "
                "Reading a later sample instead would define the endpoint from a replicate that exists "
                "only to say how stable the canonical pass is."
            )
        cell["agrees_across_samples"] = len(set(cell["samples"])) == 1
    return cells


def a_denominator(artifact: Path = PERMUTATION) -> list[str]:
    """The six cases A is counted over: the frozen pool, minus the one decided by text alone.

    The pool is seven rows in a frozen mapping and the excluded case is named by id at the top of this
    section, so nothing here recomputes which cases pixels decide. The transcription is checked against
    the mapping's own note in the same breath: a set that moved would otherwise leave a hard-coded id
    pointing at a case that is no longer the control, and the denominator would silently become the
    wrong six.
    """
    control = specificity_control(artifact)["act_testcase_id"]
    if control != TEXT_DECIDED_CASE:
        raise OutOfScope(
            f"the frozen permutation names {control} as the case decided by text alone, and this module "
            f"was written against {TEXT_DECIDED_CASE} — A's denominator and its first control are two "
            "readings of one row, so a disagreement between them makes both unreadable"
        )
    pool = [row["act_testcase_id"] for row in json.loads(artifact.read_text())["mapping"]]
    six = [case_id for case_id in pool if case_id != TEXT_DECIDED_CASE]
    if len(six) != 6:
        raise OutOfScope(
            f"A is defined as a count out of six and the frozen pool leaves {len(six)} once the "
            "text-decided case is removed — an absolute count over a moved denominator is not A"
        )
    return six


def endpoint_a(told_no_image: dict[str, Any]) -> dict[str, Any]:
    """**A**: how many of the six image-decided cases withhold judgment when told no picture is there.

    Read from sample 1, over all six, with the unstable ones named rather than excluded. A contradicted
    row — the model claimed to have seen a picture the system records not sending — is out of the
    numerator and in the denominator, counted and named: it is not withholding, and it is not a missing
    measurement either.
    """
    if told_no_image["condition"]["condition"] != OPAQUE_TOLD_NO_IMAGE.condition_id:
        raise OutOfScope(
            f"A is defined over {OPAQUE_TOLD_NO_IMAGE.condition_id!r} — the blind announced condition — "
            f"and was handed {told_no_image['condition']['condition']!r}. Read off a condition that was "
            "shown its picture it would count a drafter answering a question it did not have."
        )
    cells = _absence_cells(told_no_image)
    six = a_denominator()
    missing = [case_id for case_id in six if case_id not in cells]
    if missing:
        raise OutOfScope(f"{OPAQUE_TOLD_NO_IMAGE.condition_id} drafted none of {missing} — A's six are not all present")

    by_case = [
        {
            "act_testcase_id": case_id,
            "visual_evidence": cells[case_id]["visual_evidence"],
            "contradicted_claim": cells[case_id]["contradicted_claim"],
            "withholds": cells[case_id]["visual_evidence"] == WITHHOLDING,
            # Printed beside every row, withheld or not: the instrument has nowhere to put an
            # abstention, so a withheld row still carries a verdict and a reader must see which.
            "conformance": cells[case_id]["conformance"],
            "confidence": cells[case_id]["confidence"],
            "visually_verified": cells[case_id]["visually_verified"],
            "samples": cells[case_id]["samples"],
            "agrees_across_samples": cells[case_id]["agrees_across_samples"],
        }
        for case_id in six
    ]
    withheld = [row for row in by_case if row["withholds"]]
    return {
        "statistic": (
            "A = the number of the 6 image-decided pool cases whose blind verdict withholds a "
            "conformance judgment — reports the visual evidence its judgment needed as `absent` — out "
            "of 6, read from sample 1"
        ),
        "condition": OPAQUE_TOLD_NO_IMAGE.condition_id,
        "canonical_sample": told_no_image.get("canonical_sample", CANONICAL_SAMPLE),
        "denominator": len(by_case),
        "excluded_case": TEXT_DECIDED_CASE,
        "a": len(withheld),
        "withholding": [row["act_testcase_id"] for row in withheld],
        # The cases that did not withhold, named: "partial" is only readable with them.
        "leaked": [
            {
                "act_testcase_id": row["act_testcase_id"],
                "said": row["visual_evidence"],
                "conformance": row["conformance"],
            }
            for row in by_case
            if not row["withholds"]
        ],
        "contradicted": [row["act_testcase_id"] for row in by_case if row["contradicted_claim"] is not None],
        "unstable": [row["act_testcase_id"] for row in by_case if not row["agrees_across_samples"]],
        # Beside A rather than folded into it: the samples say how firmly the canonical answer was
        # held, and A is the canonical answer. Per case in `by_case`, summed here.
        "cases_agreeing_across_samples": sum(1 for row in by_case if row["agrees_across_samples"]),
        "conformance_note": A_CONFORMANCE_NOTE,
        "unstable_note": A_UNSTABLE_NOTE,
        "by_case": by_case,
    }


def absence_controls(told_no_image: dict[str, Any], told_with_image: dict[str, Any]) -> dict[str, Any]:
    """The two controls A is read against. They fail in opposite directions, which is why one is not enough.

    **Control 1** — the case decided by text alone, drafted blind, must report `not_needed`. A drafter
    that answers `absent` there is obeying *"no picture is attached"* as a blanket instruction rather
    than reasoning about what its judgment needed, and under blanket obedience A measures the sentence.
    It fails equally on `seen`, which the guard turns into a contradicted row.

    **Control 2** — the picture is attached and the model is told so, and no row may report `absent`.
    If the field's mere existence suppresses judgment, A measures the field rather than the reasoning.
    Stated as the absence of withholding rather than as `seen` on all seven, because `not_needed`
    stays legitimate for the text-decided case even with its picture attached, and a predicate
    forbidding it would fail a correct implementation.

    Neither reads `confidence`; it is reported for both and gated on for neither.
    """
    blind, sighted = _absence_cells(told_no_image), _absence_cells(told_with_image)
    if TEXT_DECIDED_CASE not in blind:
        raise OutOfScope(f"{OPAQUE_TOLD_NO_IMAGE.condition_id} drafted no {TEXT_DECIDED_CASE} — Control 1 has no row")
    control = blind[TEXT_DECIDED_CASE]
    withholding = sorted(case_id for case_id, cell in sighted.items() if cell["visual_evidence"] == WITHHOLDING)
    return {
        "text_decided_case_reports_not_needed": {
            "act_testcase_id": TEXT_DECIDED_CASE,
            "condition": OPAQUE_TOLD_NO_IMAGE.condition_id,
            "expected": TEXT_DECIDED_ANSWER,
            "visual_evidence": control["visual_evidence"],
            "contradicted_claim": control["contradicted_claim"],
            "conformance": control["conformance"],
            "confidence": control["confidence"],
            "holds": control["visual_evidence"] == TEXT_DECIDED_ANSWER,
            "reading_if_it_fails": (
                "the drafter is obeying 'no image' as a blanket instruction rather than reasoning "
                "about what the question needs, and A measures the sentence it was handed"
            ),
        },
        "sighted_rows_never_withhold": {
            "condition": OPAQUE_TOLD_WITH_IMAGE.condition_id,
            "cases": len(sighted),
            "withholding": withholding,
            "confidence": {case_id: cell["confidence"] for case_id, cell in sorted(sighted.items())},
            "holds": not withholding,
            "reading_if_it_fails": (
                "the new mechanism suppresses judgment by its mere existence, and A measures the field "
                "rather than the reasoning"
            ),
        },
    }


def absence_verdict(a: int, controls_hold: bool, denominator: int = 6) -> str:
    """One of the four pre-committed verdicts, checked in the order the spec fixed them in.

    The controls are checked **first**: with either one failing, blanket obedience and reasoning are
    indistinguishable, and every value of A means both things at once.
    """
    if denominator != 6:
        raise OutOfScope(
            f"the verdicts are thresholds on a count out of six and this run has {denominator} cases — "
            "a threshold read against a moved denominator is not the pre-registered one"
        )
    if not controls_hold:
        return VERDICT_A_UNINTERPRETABLE
    if a == 6:
        return VERDICT_A_CLOSED
    if a >= 3:
        return VERDICT_A_PARTIAL
    return VERDICT_A_NOT_USED


def absence_reading(endpoint: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    """What A licenses: the verdict, the controls it was read against, and what it does not decide."""
    holds = all(control["holds"] for control in controls.values())
    return {
        "a": endpoint["a"],
        "denominator": endpoint["denominator"],
        "controls_hold": holds,
        "controls_failed": sorted(name for name, control in controls.items() if not control["holds"]),
        "unstable_cases": endpoint["unstable"],
        "contradicted_cases": endpoint["contradicted"],
        "pre_registered_thresholds": [
            {"a": "either control fails", "verdict": VERDICT_A_UNINTERPRETABLE},
            {"a": "6", "verdict": VERDICT_A_CLOSED},
            {"a": "3 to 5", "verdict": VERDICT_A_PARTIAL},
            {"a": "0 to 2", "verdict": VERDICT_A_NOT_USED},
        ],
        "verdict": absence_verdict(endpoint["a"], holds, endpoint["denominator"]),
        "does_not_decide": (
            "A does not decide whether the marking ships — that shipped on its own evidence, with no "
            "model call. What it decides is whether `announce_image` becomes production's default, and "
            "that flip is a separately declared prompt change with its own re-frozen baseline."
        ),
    }


def announced_prompts_differ_from_d(announced: Mapping[Condition, dict[str, Any]]) -> dict[str, Any]:
    """That the announced conditions never enter D, checked rather than asserted.

    Their prompts differ from D's by construction — the announcement is a sentence in the user prompt
    and the ask is a differently-named schema, both inside `prompt_sha256` — so the check is that no
    prompt hash is shared with any of the four conditions D is defined over. If one ever were, the two
    experiments would be one, and D's byte-identical-prompt premise would have quietly acquired two
    more conditions.
    """
    d_prompts = {
        row["receipt"]["prompt_sha256"]
        for condition in CONDITIONS
        for sample in load_pass(condition)["samples"]
        for row in sample["rows"]
    }
    shared = sorted(
        {
            row["receipt"]["prompt_sha256"]
            for artifact in announced.values()
            for sample in artifact["samples"]
            for row in sample["rows"]
        }
        & d_prompts
    )
    return {
        "d_conditions": [c.condition_id for c in CONDITIONS],
        "shared_prompt_hashes": len(shared),
        "differ": not shared,
        "note": (
            "The announced conditions ask a different question — a sentence saying whether a picture "
            "is attached, and a response schema that carries the answer — so their prompt hashes are "
            "expected NOT to match D's. That is why they are a separate registry and why D is neither "
            "recomputed nor re-run by this endpoint."
        ),
    }


def build_absence_report() -> dict[str, Any]:
    """Re-derive A from the two announced passes. Refuses an unsound pass or a bad receipt."""
    passes = {condition: load_pass(condition) for condition in ANNOUNCED_CONDITIONS}
    for condition, artifact in passes.items():
        failures = pass_failures(artifact)
        if failures:
            raise OutOfScope(f"{condition.condition_id} is not a sound pass: {'; '.join(failures)}")

    receipts: list[str] = []
    rows_checked = 0
    samples = max(len(artifact["samples"]) for artifact in passes.values())
    for sample_n in range(1, samples + 1):
        rows = [row for artifact in passes.values() for row in _sample_rows(artifact, sample_n)]
        rows_checked += len(rows)
        receipts += [f"sample {sample_n}: {failure}" for failure in receipt_failures(rows, ANNOUNCED_CONDITIONS)]
    if receipts:
        raise OutOfScope(f"the announced conditions did not send what the frozen mapping says: {'; '.join(receipts)}")

    told_no_image, told_with_image = passes[OPAQUE_TOLD_NO_IMAGE], passes[OPAQUE_TOLD_WITH_IMAGE]
    endpoint = endpoint_a(told_no_image)
    controls = absence_controls(told_no_image, told_with_image)
    return {
        "artifact": "the second endpoint: told it has no picture, does the drafter say so?",
        "version": 1,
        "note": (
            "A counts the six image-decided pool cases whose blind verdict reports that the evidence "
            "its judgment needed was absent. Both conditions announce whether a picture is attached "
            "and ask the model to report what it could see, so their prompts differ from the four "
            "conditions D is defined over by construction — D is neither recomputed nor re-run here. "
            "Like every condition in this milestone they are drafted against PINNED candidate "
            "criteria, not live retrieval. The baseline below is the same detector rule run over the "
            "already-frozen rows: the number A moves from."
        ),
        "passes": {
            condition.condition_id: {
                "path": pass_path(condition).name,
                "created_at": artifact["created_at"],
                "config_id": artifact["config_id"],
                "eval_set_id": artifact["eval_set_id"],
                "drafter_model": artifact["drafter_model"],
                "drafter_model_digest": artifact["drafter_model_digest"],
                "corpus_version": artifact["corpus_version"],
                "attaches": artifact["condition"]["attaches"],
                "announces": artifact["condition"]["announces"],
                "samples": len(artifact["samples"]),
            }
            for condition, artifact in passes.items()
        },
        "baseline": baseline(),
        # Recorded rather than merely enforced. The check above raises on any failure, so reaching
        # here is already the proof — but a passing check that leaves no trace is indistinguishable in
        # an artifact from a check nobody ran, which is the thing this repo refuses everywhere else.
        "receipts": {
            "failures": receipts,
            "samples_checked": samples,
            "rows_checked": rows_checked,
            "note": (
                "Every sample of both conditions read through the same rule the endpoint's four are "
                "held to: each condition covers every pool finding, the blind one attached nothing, "
                "the sighted one attached each case's OWN captured bytes, and the two announcement "
                "states ask two different prompts — which is the manipulation, since a single prompt "
                "across both would mean the drafter was told the same thing about two different "
                "messages."
            ),
        },
        "instability": {condition.condition_id: instability(artifact) for condition, artifact in passes.items()},
        "prompts_vs_d": announced_prompts_differ_from_d(passes),
        "endpoint": endpoint,
        "controls": controls,
        "reading": absence_reading(endpoint, controls),
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

    endpoint_report = build_endpoint_report()
    ENDPOINT_REPORT.write_text(json.dumps(endpoint_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reading, receipts = endpoint_report["reading"], endpoint_report["receipts"]
    print(f"\nwrote {ENDPOINT_REPORT.relative_to(Path.cwd())}")
    print(f"  receipts: {receipts['rows_checked']} rows over {receipts['samples_checked']} samples, 0 failures")
    print(
        f"  D = {reading['d']} over {reading['retained']}/{endpoint_report['endpoint']['cells']} retained cells "
        f"(null {reading['null_rate']:.5f} from {reading['null_rate_source']}, p = {reading['p_value']:.4f})"
    )
    print(f"  verdict: {reading['verdict']}")

    absence = build_absence_report()
    ABSENCE_REPORT.write_text(json.dumps(absence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    a_reading, a_endpoint, controls = absence["reading"], absence["endpoint"], absence["controls"]
    print(f"\nwrote {ABSENCE_REPORT.relative_to(Path.cwd())}")
    print(
        f"  baseline: {absence['baseline']['blind_rows_signalling']} of "
        f"{absence['baseline']['blind_rows']} already-frozen blind rows report the absence"
    )
    for name, control in controls.items():
        print(f"  control:  {name} {'holds' if control['holds'] else 'FAILS'}")
    print(
        f"  A = {a_endpoint['a']} of {a_endpoint['denominator']} "
        f"(unstable {len(a_endpoint['unstable'])}, contradicted {len(a_endpoint['contradicted'])})"
    )
    print(f"  verdict: {a_reading['verdict']}")


if __name__ == "__main__":
    main()
