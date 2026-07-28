"""One image condition, run against the real model and frozen — the only record that it happened.

A condition is `condition.samples` repeats of one sample, and a sample is every finding in the pool
drafted once (`image_conditions.drafted_findings`). This module spends the model calls, records what
came back beside what was sent, and freezes the two together under a name no other condition can take.

Why one artifact per condition, and not one per sample
------------------------------------------------------
The sample count is part of what a condition *is* — it was pre-registered, and a condition that ran
two of its three samples is not a shorter version of that condition, it is an incomplete one. With one
file per sample, "how many samples did this condition take" is a property of a directory listing, and
a missing file reads as a file nobody wrote yet. With one file per condition, the count is a field
`pass_failures` checks against the pre-registration, and the artifact is complete or absent.

Why its own naming scheme rather than `run_artifacts`' labels
-------------------------------------------------------------
`RUN_LABELS` namespaces a *paired* run: a dry gate, a verdict vector, a technique-match score and a
prior run to attribute against. An image condition has none of those — it is scored outside
`referent_injection_score` and runs with no pre-flight gate (both recorded in `run_scope`) — so
adopting those labels would make four paths resolvable that name artifacts nothing here will ever
write. `refuse_to_overwrite` is reused, because that guard is about a frozen measurement and applies
to any of them.

Checkpointing is per **sample**, not per case
---------------------------------------------
A sample is seven model calls; a condition is up to twenty-one. Resuming at sample granularity costs
at most one sample on a crash and leaves `drafted_findings` — the one definition of a sample — with no
resumption argument threaded through it. A resume keeps the original `created_at`, so one measurement
never freezes under two identities.

Not run by the test suite (it needs Ollama). Invoke a condition explicitly:
`uv run python -m clearway.eval.image_pass "opaque/no-image"`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter, DraftResult, is_fallback_draft
from clearway.eval.drafter_payload import citations_for
from clearway.eval.image_capture import ARTIFACT as CAPTURE_ARTIFACT
from clearway.eval.image_conditions import (
    ALL_CONDITIONS,
    Condition,
    condition_by_id,
    drafted_findings,
    receipt_row,
    sent_request,
)
from clearway.eval.offline_build import _OUT, _RUNS_DIR, _ollama_digest
from clearway.eval.run_artifacts import refuse_to_overwrite
from clearway.eval.run_scope import cases_for
from clearway.llm import LocalLLMClient
from clearway.schemas.models import Finding

# Which sample defines a condition's verdict, fixed in advance and used by every reader. Pass 1 is
# canonical throughout this project; the others exist to say how stable it is, not to be averaged in.
CANONICAL_SAMPLE = 1


def condition_slug(condition: Condition) -> str:
    """A filename-safe name for a condition. `leaky/no-image` → `leaky_no_image`."""
    return condition.condition_id.replace("/", "_").replace("-", "_")


def pass_path(condition: Condition) -> Path:
    """Where this condition's frozen pass lives — one file, all its samples."""
    return _RUNS_DIR / f"image_{condition_slug(condition)}.json"


def partial_path(condition: Condition) -> Path:
    """The completed-samples checkpoint: gitignored working state, deliberately OUTSIDE `runs/` so a
    half-written condition cannot be picked up as a frozen one by anything that globs."""
    return _OUT / f"image_{condition_slug(condition)}.partial.json"


def pinned_corpus_version() -> str:
    """The identity of the candidate criteria these runs were drafted against.

    The image conditions do not retrieve — the candidate block is pinned, so the byte-identical-prompt
    premise the endpoint rests on does not depend on a live service ordering two queries the same way
    hours apart. That makes `corpus_version` a claim about a fixed list rather than about a database,
    so it is derived FROM the list: change a pinned citation and this string moves, which is exactly
    what a corpus version is for.
    """
    citations = citations_for("image-alt")
    canonical = json.dumps([c.model_dump(mode="json") for c in citations], sort_keys=True, ensure_ascii=False)
    return f"pinned:image-alt@{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"


def _draft_row(condition: Condition, case: dict[str, Any], finding: Finding, result: DraftResult) -> dict[str, Any]:
    """One drafted finding: what was sent, what the gold says, and what came back.

    The three are separated rather than flattened because they have three different owners and three
    different lifetimes — the receipt is evidence about the request, the gold is ACT's label, and the
    draft is the model's answer. A flat row invites a reader to compare a field against itself.

    **A contradicted row is recorded; an unparseable one still aborts.** Both degrade to the identical
    fallback, so the two are told apart by the claim the drafter carries out of the guard. An
    unparseable draft is a broken measurement — it would freeze `does_not_support`@0.0 as a verdict no
    model gave. A contradicted one is a *result*: the model claimed to have seen a picture nothing
    sent, which is one of the answers this ticket exists to count, and aborting on it would abort on
    the measurement. It is recorded with the claim preserved, so a scorer can put it where it belongs
    — out of the numerator of "reported the absence", still in its denominator.
    """
    contradicted = result.contradicted_claim
    if is_fallback_draft(result.row) and contradicted is None:
        raise RuntimeError(
            f"drafter fell back on finding {finding.id!r} under {condition.condition_id!r} (no parseable "
            "model output) — aborting the condition. A fallback ships as does_not_support@0.0 and would "
            "be frozen as a verdict the model never gave. Fix the model, delete nothing, re-run."
        )
    return {
        "receipt": receipt_row(condition, case["act_testcase_id"], finding, sent_request(condition, finding, result)),
        "gold": {
            "rule_name": case["rule_name"],
            "expected": case["expected"],
            "gold_success_criteria": list(case["gold_success_criteria"]),
        },
        "draft": {
            "conformance": result.row.conformance.value,
            "cited_sc_ids": [c.sc_id for c in result.row.citations],
            "confidence": result.row.confidence,
            "remediation": result.row.remediation,
            # The model's claim and the system's fact, kept apart on the row exactly as they are kept
            # apart on `DraftRow` — and a third column for the claim that was refused, which is on
            # neither, because the row carrying it was thrown away.
            "visual_evidence": result.row.visual_evidence.value if result.row.visual_evidence else None,
            "visually_verified": result.row.visually_verified,
            "contradicted_claim": contradicted.value if contradicted else None,
        },
    }


def build_pass(
    condition: Condition,
    drafter: Drafter,
    *,
    created_at: str,
    drafter_model: str,
    drafter_model_digest: str,
    artifact: Path = CAPTURE_ARTIFACT,
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    """Draft this condition's pre-registered samples and return the pass artifact.

    Checkpointed per completed sample. A checkpoint present on entry means resume: its `created_at`
    is kept, so a resumed condition carries the identity it started with rather than a second one.
    """
    checkpoint = partial_path(condition) if checkpoint is None else checkpoint
    samples: list[dict[str, Any]] = []
    if checkpoint.exists():
        resumed = json.loads(checkpoint.read_text())
        created_at, samples = resumed["created_at"], resumed["samples"]
        print(
            f"resuming {condition.condition_id} ({created_at}): {len(samples)}/{condition.samples} samples", flush=True
        )

    for sample_n in range(len(samples) + 1, condition.samples + 1):
        rows: list[dict[str, Any]] = []
        for case, finding, result in drafted_findings(condition, drafter, artifact):
            rows.append(_draft_row(condition, case, finding, result))
            # Per finding, not per sample: a sample is seven calls of roughly a minute each, and a
            # thinking model mid-generation is indistinguishable from a wedged server if the only
            # output is a line printed when the whole sample is already done.
            print(
                f"  [{sample_n}/{condition.samples}] {case['act_testcase_id'][:10]} "
                f"{case['expected']:7s} → {result.row.conformance.value}",
                flush=True,
            )
        samples.append({"sample": sample_n, "rows": rows})
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({"created_at": created_at, "samples": samples}, ensure_ascii=False) + "\n")
        print(f"[{sample_n}/{condition.samples}] {condition.condition_id} n={len(rows)}", flush=True)

    built = {
        "artifact": "one image condition drafted against the real model, all its samples",
        "version": 1,
        "condition": {
            "condition": condition.condition_id,
            "scope": condition.scope.scope_id,
            "attaches": condition.attaches,
            "samples": condition.samples,
            "announces": condition.announces,
        },
        "canonical_sample": CANONICAL_SAMPLE,
        "citations": {
            "source": "pinned",
            "sc_ids": [c.sc_id for c in citations_for("image-alt")],
            "note": (
                "The candidate criteria were PINNED (eval/drafter_payload.PINNED_CITATIONS), not retrieved. "
                "The endpoint is defined over prompts that are byte-identical across conditions differing "
                "only in pixels, and a live retriever is a service whose ordering is one more thing that "
                "could move between two calls run hours apart. The cost is real and is not hidden: the "
                "block holds the one criterion this class is about, where production retrieval surfaces "
                "several candidates including distractors, so these conditions are drafted against an "
                "easier candidate set than a live scan would produce. It is the same set for all four "
                "conditions, so it cannot move a difference between them."
            ),
        },
        **condition.scope.provenance(
            run_ids=[
                f"image-{condition_slug(condition)}-sample{n}-{created_at}" for n in range(1, condition.samples + 1)
            ],
            corpus_version=pinned_corpus_version(),
            drafter_model=drafter_model,
            drafter_model_digest=drafter_model_digest,
            created_at=created_at,
            # The condition's, not the scope's: the announced pair drafts the byte-identical opaque
            # pages under a prompt and a response schema that are both different, which is a moved
            # pipeline configuration and an unmoved case set.
            config_id=condition.config_id,
        ),
        "samples": samples,
    }
    checkpoint.unlink(missing_ok=True)  # fully assembled in memory — the checkpoint has done its job
    return built


def receipt_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Every sample's receipt rows, and nothing else — the shape the cross-condition check reads."""
    return [row["receipt"] for sample in artifact["samples"] for row in sample["rows"]]


def canonical_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of the sample that defines this condition's verdicts."""
    canonical = artifact.get("canonical_sample", CANONICAL_SAMPLE)
    return [row for sample in artifact["samples"] if sample["sample"] == canonical for row in sample["rows"]]


def load_pass(condition: Condition) -> dict[str, Any]:
    """This condition's frozen pass, or a refusal naming the command that would produce it."""
    path = pass_path(condition)
    if not path.exists():
        raise FileNotFoundError(
            f"{condition.condition_id!r} has not been run: {path.name} does not exist. Build it with "
            f'`uv run python -m clearway.eval.image_pass "{condition.condition_id}"` — it spends '
            f"{condition.samples * 7} model calls."
        )
    return dict(json.loads(path.read_text()))


def _answered_the_evidence_question(draft: dict[str, Any]) -> bool:
    """Did this row come back from a model that was asked what its judgment could see?

    Either answer counts: a claim the row carries, or a claim the guard refused and the drafter handed
    out. Read with `.get`, and that is deliberate rather than lax — the keys are absent on every row
    frozen before the field existed, and this predicate is only ever applied to announced conditions,
    which cannot be among them.
    """
    return draft.get("visual_evidence") is not None or draft.get("contradicted_claim") is not None


def pass_failures(artifact: dict[str, Any]) -> list[str]:
    """Every way one condition's pass can fail to be the run it says it is. Pure over the artifact.

    Deliberately *within* one condition: the cross-condition assertion — that the mismatched pictures
    are the ones the frozen permutation names — needs all four passes and belongs to the endpoint.
    What is checkable here is completeness and internal consistency, and those are the failures that
    leave a complete-looking artifact behind:

    1. the pre-registered number of samples is present;
    2. each sample covers every pool finding, exactly once — a duplicate row and a missing one have
       the same total, so both are checked;
    3. every row belongs to this condition and its scope;
    4. a text-only condition attached nothing on every row;
    5. the samples are repeats of the **identical ask** — same prompt hash and same payload hash per
       finding. This is what makes them null replicates: if the ask moved between samples, a
       disagreement between them measures the prompt rather than the stack;
    6. an **announced** condition actually asked: every row carries either the model's claim or the
       claim the guard refused. A condition that ran with the announcement silently off would be seven
       complete-looking findings whose every answer to "could you see it" is empty — which reads in a
       report as a drafter that declined to say, and is instead a drafter that was never asked. The
       check is applied to announced conditions only, so the conditions frozen before the field existed
       are read by a rule that does not look for it.
    """
    condition = condition_by_id(artifact["condition"]["condition"])
    expected_rows = sum(case["expected_finding_count"] for case in cases_for(condition.scope))
    failures: list[str] = []

    samples = artifact["samples"]
    if len(samples) != condition.samples:
        failures.append(
            f"{condition.condition_id}: {len(samples)} samples for a condition pre-registered at "
            f"{condition.samples} — an incomplete condition, not a shorter one"
        )
    if artifact["condition"]["samples"] != condition.samples:
        failures.append(
            f"{condition.condition_id} declares {artifact['condition']['samples']} samples but was "
            f"pre-registered at {condition.samples} — the count a report prints must be the count the "
            "run was defined by, so it is taken from the pre-registration and never from the artifact"
        )

    asks: dict[str, set[tuple[str, str]]] = {}
    for sample in samples:
        rows = sample["rows"]
        finding_ids = [row["receipt"]["finding_id"] for row in rows]
        if len(rows) != expected_rows:
            failures.append(
                f"{condition.condition_id} sample {sample['sample']} drafted {len(rows)} of {expected_rows} findings"
            )
        if len(set(finding_ids)) != len(finding_ids):
            failures.append(
                f"{condition.condition_id} sample {sample['sample']} drafted the same finding twice — "
                "the row count can be right while a finding is missing"
            )
        for row in rows:
            receipt = row["receipt"]
            if receipt["condition"] != condition.condition_id or receipt["scope"] != condition.scope.scope_id:
                failures.append(
                    f"{condition.condition_id} carries rows of {receipt['condition']!r} / "
                    f"{receipt['scope']!r} — two conditions have been mixed into one artifact"
                )
            if not condition.carries_image and receipt["image_sha256"] is not None:
                failures.append(f"{condition.condition_id} {receipt['finding_id']} attached a picture and must not")
            if condition.announces and not _answered_the_evidence_question(row["draft"]):
                failures.append(
                    f"{condition.condition_id} {receipt['finding_id']} carries no visual-evidence "
                    "answer and no refused claim — an announced condition whose announcement never "
                    "reached the model, which reads as a drafter that declined to say"
                )
            asks.setdefault(receipt["finding_id"], set()).add((receipt["prompt_sha256"], receipt["payload_sha256"]))

    failures += [
        f"{finding_id} was asked {len(seen)} different things across the samples of "
        f"{condition.condition_id} — samples are repeats of one ask, and a moved ask makes a "
        "disagreement between them a measurement of the prompt rather than of the stack"
        for finding_id, seen in asks.items()
        if len(seen) != 1
    ]
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="run one image condition against the real model and freeze it")
    parser.add_argument(
        "condition",
        choices=[c.condition_id for c in ALL_CONDITIONS],
        help="which condition to run — required, never defaulted: the condition decides the case set, "
        "the picture attached to every finding, and whether the drafter is told about it",
    )
    args = parser.parse_args()
    condition = condition_by_id(args.condition)

    # Checked BEFORE the model is called: a refusal to write is worth far more now than after the calls.
    out = pass_path(condition)
    refuse_to_overwrite(out)

    client = LocalLLMClient()
    artifact = build_pass(
        condition,
        Drafter(client),
        created_at=datetime.now(timezone.utc).isoformat(),
        drafter_model=client.model,
        drafter_model_digest=_ollama_digest(client.model),
    )
    failures = pass_failures(artifact)
    if failures:
        raise RuntimeError(f"the pass is not the run it says it is: {'; '.join(failures)}")

    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    refuse_to_overwrite(out)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"\nwrote {out.relative_to(Path.cwd())} — {condition.samples} samples × {len(artifact['samples'][0]['rows'])}"
    )


if __name__ == "__main__":
    main()
