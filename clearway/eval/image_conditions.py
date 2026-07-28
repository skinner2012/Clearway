"""The conditions the image pool is drafted under, and the receipt of what each one sent.

A condition is a value, not a flag
----------------------------------
Each condition names four things a pass cannot infer: **which case set** it drafts (the vendored
pages or the ablated ones), **which picture** it attaches to each finding (none, the case's own, or
the wrong one), **how many samples** it takes, and **whether it announces the picture** — telling the
model whether one is attached and asking it to report what its judgment could see. Those were the
things most likely to be supplied by a default argument and then reported as something else — the
same failure `run_scope` exists to stop one level up, at the case set.

Two registries, because they are two experiments
------------------------------------------------
`CONDITIONS` is the primary endpoint's four, and it is not a list of runs: the frozen dry receipt is
asserted to rebuild from it and every receipt check demands a full set of rows for each of its
members, so it is the *definition* that endpoint's evidence is checked against. `ANNOUNCED_CONDITIONS`
is the pair that tells the drafter what it is looking at. They never pool — their prompts differ by
construction, which is exactly why the announced pair cannot enter the primary endpoint.

Why a receipt, and why it records a digest
------------------------------------------
The whole experiment rests on one unobservable claim: that the picture the frozen permutation names
is the picture the model was actually shown. Nothing in a drafted row can show that. A byte *count*
cannot show it either — four of the seven findings render the same photograph, so a count check
passes whether or not the mapping was honoured.

So every draft records the sha256 of what it attached, per `finding.id`, per condition, taken from
the request the drafter reports having sent (`DraftResult.request`) rather than from what a caller
believes it passed. `receipt_failures` then reads that against the frozen capture and permutation:
the with-image rows must be each case's own captured bytes, and the mismatched rows must be the other
picture the mapping named — and never the case's own.

The dry receipt: the same proof, before any call is spent
--------------------------------------------------------
`dry_receipt()` drives the **real** `Drafter` over all four conditions with a canned client, so the
attachment, the refusal paths and the payload hashes are all exercised with no model running. It is
frozen because it is the expectation a live pass is checked against: the image digests in it are what
must appear in the live receipt, finding by finding, condition by condition.

**Its payload hashes are computed with the pinned citations** (`drafter_payload.citations_for`), not
retrieved ones, so a live pass — which retrieves its own — will not reproduce them. That is by design
and stated on the artifact: the frozen claim here is about *pictures*, and a live pass compares its
payload hashes **across its own conditions**, which is where the byte-identical-prompt premise has to
hold. What the no-image payload hashes here do line up with, exactly, is the pre-wiring control in
`drafter_payload.BASELINE` — the same pinned inputs, computed through a different path.

Regenerate with `uv run python -m clearway.eval.image_conditions` (re-scans the pool; no model calls).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter, DraftResult
from clearway.eval.drafter_payload import citations_for
from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_capture import load_capture
from clearway.eval.run_scope import (
    ANNOUNCED_IMAGE_CONFIG_ID,
    IMAGE_LEAKY,
    IMAGE_OPAQUE,
    OutOfScope,
    RunScope,
    cases_for,
)
from clearway.llm import FakeLLMClient, ImagePart, LLMRequest
from clearway.scanner.capture import ImageStore
from clearway.schemas.models import Finding

RECEIPT = Path(__file__).resolve().parents[2] / "benchmark" / "reports" / "image_condition_dry_receipt.json"

# What a condition attaches. Named rather than boolean because there are three answers, and the third
# one — the wrong picture, from a mapping frozen before any verdict existed — is the manipulation.
ATTACHES_NOTHING = "none"
ATTACHES_TRUE_IMAGE = "true"
ATTACHES_MISMATCHED_IMAGE = "mismatched"

# A canned response, so the dry rehearsal exercises the real assembly path without a model. Its content
# is irrelevant to what the receipt records: the receipt is about the request, not the answer.
_CANNED_JUDGMENT = '{"conformance":"does_not_support","cited_sc_ids":["1.1.1"],"remediation":"x","confidence":0.5}'


@dataclass(frozen=True)
class Condition:
    """One condition: a case set, a picture rule, a pre-registered sample count, and an announcement.

    `samples` is here because it is part of what the condition *is*, and because it was pre-registered
    before any of this ran: one descriptive pass over the vendored set, three over each ablated one.
    A pass that took a different number would be answering a different question about stability, and
    the number a report prints must be the number a run was defined by.

    `announces` is the fourth on the same grounds. Whether the prompt says a picture is attached, and
    whether the model is asked to report what its judgment could see, is not something a pass can infer
    from the pictures it sends — a blind condition that announces and one that does not are the same
    seven findings with no picture, and they are two different experiments.
    """

    condition_id: str
    scope: RunScope
    attaches: str
    samples: int
    announces: bool

    @property
    def carries_image(self) -> bool:
        return self.attaches != ATTACHES_NOTHING

    @property
    def config_id(self) -> str:
        """The pipeline configuration this condition drafts under.

        It is the condition's rather than the scope's because the announcement changes the pipeline
        and not the case set: the announced conditions run the byte-identical opaque pages, so their
        `eval_set_id` is the scope's and unmoved, while their prompt and their response schema are
        both different — which is exactly what a config id names.
        """
        return ANNOUNCED_IMAGE_CONFIG_ID if self.announces else self.scope.config_id


LEAKY_NO_IMAGE = Condition("leaky/no-image", IMAGE_LEAKY, ATTACHES_NOTHING, samples=1, announces=False)
OPAQUE_NO_IMAGE = Condition("opaque/no-image", IMAGE_OPAQUE, ATTACHES_NOTHING, samples=3, announces=False)
OPAQUE_WITH_IMAGE = Condition("opaque/with-image", IMAGE_OPAQUE, ATTACHES_TRUE_IMAGE, samples=3, announces=False)
OPAQUE_MISMATCHED_IMAGE = Condition(
    "opaque/mismatched-image", IMAGE_OPAQUE, ATTACHES_MISMATCHED_IMAGE, samples=3, announces=False
)

CONDITIONS = (LEAKY_NO_IMAGE, OPAQUE_NO_IMAGE, OPAQUE_WITH_IMAGE, OPAQUE_MISMATCHED_IMAGE)

# The two conditions that TELL the drafter whether a picture is attached, and give it a field to
# answer in. They are a separate tuple rather than two more members of `CONDITIONS`, and the reason is
# that `CONDITIONS` is not a list of runs — it is the definition the primary endpoint's evidence is
# checked against. `receipt_failures` demands a full set of rows for every member and the frozen dry
# receipt is asserted to rebuild from it, so appending here would re-freeze an artifact whose whole
# purpose is to have been frozen before that endpoint was read.
OPAQUE_TOLD_NO_IMAGE = Condition("opaque/told-no-image", IMAGE_OPAQUE, ATTACHES_NOTHING, samples=3, announces=True)
OPAQUE_TOLD_WITH_IMAGE = Condition(
    "opaque/told-with-image", IMAGE_OPAQUE, ATTACHES_TRUE_IMAGE, samples=3, announces=True
)

ANNOUNCED_CONDITIONS = (OPAQUE_TOLD_NO_IMAGE, OPAQUE_TOLD_WITH_IMAGE)

# Every condition this experiment defines — the namespace a condition id resolves in, and nothing
# more. No measurement is defined over this tuple: the two registries answer different questions and
# a reader that pooled them would be reading one endpoint's evidence into the other's.
ALL_CONDITIONS = CONDITIONS + ANNOUNCED_CONDITIONS


def condition_by_id(condition_id: str) -> Condition:
    """A condition named by its id — so a CLI or a report cannot invent one."""
    for condition in ALL_CONDITIONS:
        if condition.condition_id == condition_id:
            return condition
    raise OutOfScope(
        f"{condition_id!r} is not one of the registered conditions {[c.condition_id for c in ALL_CONDITIONS]}"
    )


def refs_for(condition: Condition, artifact: Path = CAPTURE_ARTIFACT) -> dict[str, str]:
    """`finding_id → image ref` for a condition, read from the frozen capture and permutation.

    Empty for a text-only condition. The with-image mapping comes through `load_capture`, which reads
    every reference back out of the content-addressed store, so an artifact that has drifted from the
    bytes beside it fails here rather than attaching a picture nobody froze.
    """
    if not condition.carries_image:
        return {}
    if condition.attaches == ATTACHES_TRUE_IMAGE:
        return load_capture(artifact)
    frozen = json.loads(artifact.read_text())
    return {row["finding_id"]: row["mismatched_image_ref"] for row in frozen["resolved_permutation"]}


class ImageChannel:
    """The pictures one condition attaches, resolved to bytes and keyed by `finding.id`.

    A finding the condition should have a picture for and does not is **refused**, never skipped: a
    text-only draft in an image condition is the exact failure that would read as "the pixels did not
    matter" in the result. The bytes are read through the store, which recomputes each digest, and the
    media type is sniffed from them — never from the deliberately-uniform `.png` names.
    """

    def __init__(self, condition: Condition, artifact: Path = CAPTURE_ARTIFACT) -> None:
        self.condition = condition
        self._refs = refs_for(condition, artifact)
        store_root = artifact.parent / json.loads(artifact.read_text())["store"]
        self._store = ImageStore(store_root)

    def for_finding(self, finding_id: str) -> ImagePart | None:
        if not self.condition.carries_image:
            return None
        ref = self._refs.get(finding_id)
        if ref is None:
            raise OutOfScope(
                f"condition {self.condition.condition_id!r} attaches a picture, but no frozen reference "
                f"names finding {finding_id!r}. Drafting it text-only would produce a row that reads as "
                "the pixels having made no difference."
            )
        return ImagePart(self._store.read(ref), self._store.media_type(ref))


def receipt_row(condition: Condition, act_testcase_id: str, finding: Finding, request: LLMRequest) -> dict[str, Any]:
    """One row of the receipt: what this condition sent for this finding, digest and all.

    `request` is the drafter's own report of what it sent, so the row cannot claim an attachment the
    call did not make. `image_sha256` is `None` for a text-only condition — recorded as an absence
    rather than omitted, because a missing key and an attached-nothing are different facts.

    **Both hashes are recorded, and neither is redundant.** `prompt_sha256` covers the text alone and
    must be identical across the conditions that differ only in pixels; `payload_sha256` covers the
    text *and* the picture, so it must differ between them. Recording only one would make the pair
    of claims unfalsifiable in one direction: with the full hash alone, a moved prompt and a changed
    picture are the same observation.
    """
    return {
        "condition": condition.condition_id,
        "scope": condition.scope.scope_id,
        "act_testcase_id": act_testcase_id,
        "finding_id": finding.id,
        "target": finding.target,
        "image_sha256": request.image_ref,
        "media_type": request.image_media_type,
        "prompt_sha256": request.prompt_sha256,
        "payload_sha256": request.sha256,
    }


def drafted_findings(
    condition: Condition, drafter: Drafter, artifact: Path = CAPTURE_ARTIFACT
) -> Iterator[tuple[dict[str, Any], Finding, DraftResult]]:
    """One sample: every finding this condition covers, drafted once, with the picture it attaches.

    **This is the only definition of what a sample is**, and both the model-free rehearsal and a live
    pass consume it. Two copies of this loop would be two definitions, and they would come apart in
    the direction that costs most — a pass that drafts six of the seven findings, or one that quietly
    sends no picture, freezes an artifact that reads as a completed condition either way.

    Citations are the pinned ones (`drafter_payload.citations_for`), never retrieved. The premise the
    endpoint is defined over is that the three opaque conditions send byte-identical prompts, and a
    live retriever is a service whose ordering is one more thing that could move between two calls
    hours apart. Pinning takes it out of the premise: the candidate block is fixed, named and offline,
    so the only thing that differs between those conditions is the pixels. What it costs is stated
    rather than hidden — the block holds the one criterion this class is about, where production
    retrieval would surface several candidates including distractors, so these conditions are drafted
    against an easier candidate set than a live scan would produce. That is a property of all four
    conditions equally, so it cannot move a difference *between* them.

    The announcement is passed from the condition for the same reason the picture is: it is part of
    what the condition sends, so a pass cannot take a default and freeze the result under a name that
    says otherwise. It is `False` for all four of the primary endpoint's conditions, which is what
    keeps their asks byte-identical to the ones already frozen.
    """
    channel = ImageChannel(condition, artifact)
    for case in cases_for(condition.scope):
        path = condition.scope.root / case["path"]
        for finding in condition.scope.minting_findings(path, case["axe_rule"]):
            image = channel.for_finding(finding.id)
            yield (
                case,
                finding,
                drafter.draft_with_usage(finding, citations_for(case["axe_rule"]), image, condition.announces),
            )


def sent_request(condition: Condition, finding: Finding, result: DraftResult) -> LLMRequest:
    """The request the drafter reports having sent, or a refusal.

    A `DraftResult` may carry none — only a hand-built one does — and a receipt row built over that
    absence would have to invent the digest it is supposed to be evidence of.
    """
    if result.request is None:
        raise RuntimeError(
            f"the drafter reported no request for finding {finding.id} under "
            f"{condition.condition_id!r} — a receipt cannot record what was sent"
        )
    return result.request


def draft_condition(condition: Condition, drafter: Drafter, artifact: Path = CAPTURE_ARTIFACT) -> list[dict[str, Any]]:
    """Draft every finding this condition covers, once, and return the receipt rows."""
    return [
        receipt_row(condition, case["act_testcase_id"], finding, sent_request(condition, finding, result))
        for case, finding, result in drafted_findings(condition, drafter, artifact)
    ]


def announcement_state(condition: Condition) -> tuple[bool, bool]:
    """What a condition's prompt says about pictures — the thing its prompt hash is a function of.

    Two conditions in the same state must ask byte-identical prompts; two in different states must
    not. A silent condition is in one state whatever it attaches, which is the endpoint's premise: the
    prompt never mentions the picture, so only the pixels move. An announced one is in a state per
    attachment, because the sentence it renders states which — and two announced conditions asking the
    identical prompt would mean the drafter was told the same thing about two different messages.
    """
    return (condition.announces, condition.announces and condition.carries_image)


def receipt_failures(
    rows: list[dict[str, Any]],
    conditions: tuple[Condition, ...] = CONDITIONS,
    artifact: Path = CAPTURE_ARTIFACT,
) -> list[str]:
    """Every way a receipt can fail to be the run the frozen mapping describes.

    `conditions` is the set being checked, taken as an argument rather than read off the module: two
    registries are defined here and each is the complete expectation for its own run. Checking one
    group's rows against the other's membership would demand rows nothing drafted and report a
    complete run as a short one.

    Pure over `rows`, so it reads the same over a dry rehearsal and over a live pass:

    1. every condition covers every pool finding — a condition short of a row drafted less than it says;
    2. a text-only condition attached nothing;
    3. with-image attached each finding's **own** captured bytes;
    4. mismatched attached exactly the picture the frozen permutation names, and never the case's own —
       this is the assertion that the manipulation was actually run mismatched;
    5. the opaque conditions ask one **prompt** hash per finding per announcement state — the
       byte-identical-prompt premise the endpoint is defined over, checked rather than assumed, and its
       counterpart for the announced pair, whose prompts must differ because they say opposite things;
    6. and their **payload** hashes all differ, because a picture that changed must change the ask. The
       two together are what "only the pixels change" means; either alone is satisfiable by a bug.
    """
    frozen = json.loads(artifact.read_text())
    captured = {c["finding_id"]: c["image_ref"] for c in frozen["captures"]}
    mismatched = {r["finding_id"]: r["mismatched_image_ref"] for r in frozen["resolved_permutation"]}
    by_condition: dict[str, list[dict[str, Any]]] = {c.condition_id: [] for c in conditions}
    failures: list[str] = []

    for row in rows:
        if row["condition"] not in by_condition:
            failures.append(
                f"{row['condition']!r} is not one of the conditions this receipt is checked against "
                f"{[c.condition_id for c in conditions]}"
            )
            continue
        by_condition[row["condition"]].append(row)

    for condition in conditions:
        present = by_condition[condition.condition_id]
        expected = sum(case["expected_finding_count"] for case in cases_for(condition.scope))
        if len(present) != expected:
            failures.append(
                f"{condition.condition_id}: {len(present)} rows for {expected} findings — a condition "
                "that drafted fewer findings than it covers"
            )
        for row in present:
            if not condition.carries_image:
                if row["image_sha256"] is not None:
                    failures.append(f"{condition.condition_id} {row['finding_id']} attached a picture and must not")
                continue
            expected_ref = (captured if condition.attaches == ATTACHES_TRUE_IMAGE else mismatched).get(
                row["finding_id"]
            )
            if expected_ref is None:
                failures.append(f"{condition.condition_id} {row['finding_id']} is named by no frozen mapping")
            elif row["image_sha256"] != expected_ref:
                failures.append(
                    f"{condition.condition_id} {row['finding_id']} sent "
                    f"{str(row['image_sha256'])[:8]}…, frozen mapping says {expected_ref[:8]}…"
                )
            if condition.attaches == ATTACHES_MISMATCHED_IMAGE and row["image_sha256"] == captured.get(
                row["finding_id"]
            ):
                failures.append(
                    f"{condition.condition_id} {row['finding_id']} was shown its OWN bytes — the "
                    "manipulation did not run mismatched"
                )

    opaque = [c for c in conditions if c.scope is IMAGE_OPAQUE]
    opaque_ids = {c.condition_id for c in opaque}
    asks = len({announcement_state(c) for c in opaque})
    prompts: dict[str, set[str]] = {}
    payloads: dict[str, set[str]] = {}
    for row in rows:
        if row["condition"] in opaque_ids:
            prompts.setdefault(row["finding_id"], set()).add(row["prompt_sha256"])
            payloads.setdefault(row["finding_id"], set()).add(row["payload_sha256"])
    failures += [
        f"{finding_id} was drafted under {len(hashes)} different prompts across the opaque conditions, "
        f"which cover {asks} announcement state(s) and so admit exactly {asks} — the endpoint is "
        "defined over byte-identical prompts differing only in pixels, and an announced condition's "
        "prompt differs from a silent one's, and from its own twin's, by construction"
        for finding_id, hashes in prompts.items()
        if len(hashes) != asks
    ]
    failures += [
        f"{finding_id} sent the same payload under {len(opaque)} conditions that differ in the picture "
        "they attach, in what they announce, or in both — an identical payload means neither moved"
        for finding_id, hashes in payloads.items()
        if len(hashes) != len(opaque)
    ]
    return failures


def dry_receipt(artifact: Path = CAPTURE_ARTIFACT, conditions: tuple[Condition, ...] = CONDITIONS) -> dict[str, Any]:
    """Rehearse a set of conditions through the real drafter with a canned client — no model calls.

    Defaulted to the primary endpoint's four, because the artifact this function freezes is theirs.
    The announced pair rehearses through the same code and is checked the same way, but is not frozen
    beside them: the frozen receipt's value is that it predates the endpoint it is evidence for.
    """
    drafter = Drafter(FakeLLMClient(_CANNED_JUDGMENT))
    rows = [row for condition in conditions for row in draft_condition(condition, drafter, artifact)]
    failures = receipt_failures(rows, conditions, artifact)
    if failures:
        raise RuntimeError(f"the conditions do not send what the frozen mapping says: {'; '.join(failures)}")
    return {
        "artifact": "what each condition attaches, per finding — rehearsed with no model call",
        "version": 1,
        "derived_from": artifact.name,
        "note": (
            "The picture every condition sends, recorded as the sha256 the drafter reports having "
            "attached, per finding.id, per condition. A digest and not a byte count: four of the seven "
            "findings render the same photograph, so a count check passes whether or not the frozen "
            "permutation was honoured. Produced by driving the real Drafter with a canned client, so "
            "the attachment path is the production one and no model call is spent. The payload hashes "
            "are computed with the citations pinned in eval/drafter_payload.py — a live pass retrieves "
            "its own and will not reproduce them; what a live pass must reproduce is the image_sha256 "
            "column, and it checks its own prompts for byte-identity ACROSS its conditions. The "
            "no-image payload hashes here do equal the pre-wiring control in drafter_payload.BASELINE, "
            "which is the same inputs reached by a different path."
        ),
        "conditions": [
            {
                "condition": c.condition_id,
                "scope": c.scope.scope_id,
                "eval_set_id": c.scope.eval_set_id,
                "config_id": c.config_id,
                "attaches": c.attaches,
                "samples": c.samples,
            }
            for c in conditions
        ],
        "rows": rows,
    }


def main() -> None:
    receipt = dry_receipt()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {RECEIPT.relative_to(Path.cwd())} — {len(receipt['rows'])} rows")
    for row in receipt["rows"]:
        sent = f"{row['image_sha256'][:12]}… {row['media_type']}" if row["image_sha256"] else "no image"
        print(f"  {row['condition']:<24} {row['act_testcase_id'][:10]} {sent}")


if __name__ == "__main__":
    main()
