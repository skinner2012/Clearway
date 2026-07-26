"""The opaque set's pictures, captured through the production path and frozen beside it.

What this is for
----------------
The endpoint this milestone rests on shows each case its own picture in one condition and the wrong
picture in another, behind byte-identical prompts. Both conditions need bytes, and both need those
bytes to be *provably* the right ones — a frozen permutation over image names proves nothing about
what a model was actually shown. So the pictures are captured once, addressed by their own sha256,
and the permutation is resolved from names to digests here, before any verdict exists.

The capture comes through the production path, not a side channel: the pages are scanned by the same
`scan()` the pipeline runs, with the same interceptor and the same asset tree, and the reference
lands on `Finding.image_ref`. An eval-only capture would have proved the eval harness works.

Keyed by `finding.id`, never by `target`
----------------------------------------
`img` matches on nearly every case page, so a CSS target is not unique across the pool; `finding.id`
already hashes `(source_url, rule_id, target)` and is. Every downstream condition therefore looks up
its picture the same way it looks up everything else about a finding.

The two checks this file exists to run
--------------------------------------
1. **Three distinct images at multiplicity 4 / 2 / 1.** One assertion covering three separate ways
   the set could be quietly broken — the asset interceptor failing, the ablation's renaming
   colliding, or the pool no longer resolving to the three pictures the permutation was authored
   over. If one image stops decoding, this reads 2 distinct hashes and fails loudly instead of a
   blank picture being attached to a finding that still looks complete. The expected shape is
   asserted twice on purpose: against the literal the spec pins, and against the frozen
   permutation's own per-image case counts — which were derived from the ablated *markup*, while
   these digests come from what the browser *rendered*, so the two are independent paths to the
   same number.
2. **The permutation is a derangement on bytes.** T3 asserted it over image labels, which is a claim
   about the authoring; this asserts it over the digests actually captured, which is a claim about
   what will be sent. Four of the seven cases are the same photograph under different names, so
   label-level and byte-level derangement are genuinely different statements.

Regenerate with `uv run python -m clearway.eval.image_capture` (re-scans every pool case).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from clearway.eval.act_image_gold import _minting_findings
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE
from clearway.eval.image_opaque import PERMUTATION as OPAQUE_PERMUTATION
from clearway.eval.run_scope import IMAGE_OPAQUE, RunScope, cases_for
from clearway.scanner.capture import ImageStore
from clearway.scanner.scan import AXE_VERSION

STORE_DIR = "captured"
ARTIFACT = ACT_IMAGE_OPAQUE / "capture.json"

# The pool's measured shape, pinned as the acceptance the ticket states rather than derived, so a
# capture that agreed with a permutation that had itself drifted still fails. Four cases render the
# same photograph, two the same logo, one the bread.
EXPECTED_DISTINCT_IMAGES = 3
EXPECTED_MULTIPLICITY = (4, 2, 1)


def multiplicity(refs: Sequence[str]) -> list[int]:
    """How many findings each distinct picture carries, largest first — the pool's shape in one line.

    Over the references rather than over the files, because two names for one picture must count once.
    """
    return sorted((refs.count(ref) for ref in dict.fromkeys(refs)), reverse=True)


def multiplicity_failures(refs: Sequence[str]) -> list[str]:
    """ACCEPTANCE 1. The captured references must be three distinct pictures at 4 / 2 / 1.

    Pure, so the check reads identically in the builder and in a test.
    """
    counts = multiplicity(refs)
    failures: list[str] = []
    if len(counts) != EXPECTED_DISTINCT_IMAGES:
        failures.append(
            f"{len(counts)} distinct captured images, expected {EXPECTED_DISTINCT_IMAGES} — an image that "
            "stopped decoding, or an ablation whose renaming collided"
        )
    if tuple(counts) != EXPECTED_MULTIPLICITY:
        failures.append(f"multiplicity {tuple(counts)}, expected {EXPECTED_MULTIPLICITY}")
    return failures


def derangement_failures(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """ACCEPTANCE 2. Resolved to bytes, no case may receive a picture identical to its own.

    Byte-level, not label-level: four of the seven cases show the same photograph, so a mapping that
    is a derangement over names can still hand a case its own bytes back.
    """
    failures: list[str] = []
    for row in rows:
        if row["mismatched_image_ref"] == row["with_image_ref"]:
            failures.append(
                f"{row['act_testcase_id']} would be shown its own bytes "
                f"({row['with_image_ref'][:8]}…) — the resolved mapping is not a derangement"
            )
    return failures


def _permutation() -> dict[str, Any]:
    return dict(json.loads(OPAQUE_PERMUTATION.read_text()))


def capture_pool(scope: RunScope = IMAGE_OPAQUE, root: Path = ACT_IMAGE_OPAQUE) -> dict[str, Any]:
    """Scan every pool case with capture on, store the pictures, and resolve the permutation to bytes.

    The scope supplies the work list, the tree the cases resolve against and the run's identity. The
    findings are asked for with the store threaded — the scope's own minting callable is the
    production shape, which captures nothing, and only this ticket wants the pixels.
    """
    store = ImageStore(root / STORE_DIR)
    frozen = _permutation()
    ref_of_label = {label: image["sha256"] for label, image in frozen["images"].items()}
    label_of_ref = {ref: label for label, ref in ref_of_label.items()}
    rows_by_case = {row["act_testcase_id"]: row for row in frozen["mapping"]}

    captures: list[dict[str, Any]] = []
    for case in cases_for(scope):
        path = scope.root / case["path"]
        for finding in _minting_findings(path, store):
            if finding.image_ref is None:
                raise RuntimeError(
                    f"{case['act_testcase_id']} minted a finding with no captured picture — the image "
                    "channel produced nothing for a case whose gold presumes a rendered image"
                )
            captures.append(
                {
                    "act_testcase_id": case["act_testcase_id"],
                    "finding_id": finding.id,
                    "target": finding.target,
                    "image": label_of_ref.get(finding.image_ref, "UNKNOWN"),
                    "image_ref": finding.image_ref,
                    "media_type": store.media_type(finding.image_ref),
                    "bytes": len(store.read(finding.image_ref)),
                }
            )

    if len(captures) != len(rows_by_case):
        raise RuntimeError(f"captured {len(captures)} findings for {len(rows_by_case)} pool cases")
    unknown = [c["act_testcase_id"] for c in captures if c["image"] == "UNKNOWN"]
    if unknown:
        raise RuntimeError(
            f"{unknown} rendered a picture no frozen image label names — the pool no longer resolves to "
            "the three images the permutation was authored over"
        )

    failures = multiplicity_failures([c["image_ref"] for c in captures])
    if failures:
        raise RuntimeError(f"the capture set is not the measured pool: {'; '.join(failures)}")

    resolved: list[dict[str, Any]] = []
    for capture in captures:
        row = rows_by_case[capture["act_testcase_id"]]
        if capture["image"] != row["true_image"]:
            raise RuntimeError(
                f"{capture['act_testcase_id']} rendered {capture['image']!r}, but the frozen permutation "
                f"records its true image as {row['true_image']!r}"
            )
        resolved.append(
            {
                "act_testcase_id": capture["act_testcase_id"],
                "finding_id": capture["finding_id"],
                "true_image": row["true_image"],
                "with_image_ref": capture["image_ref"],
                "mismatched_image": row["mismatched_image"],
                "mismatched_image_ref": ref_of_label[row["mismatched_image"]],
                "live": row["live"],
            }
        )

    failures = derangement_failures(resolved)
    if failures:
        raise RuntimeError(f"the resolved permutation is not a derangement: {'; '.join(failures)}")
    held = set(store.refs())
    missing = sorted({r["mismatched_image_ref"] for r in resolved} - held)
    if missing:
        raise RuntimeError(f"the store holds no bytes for {missing} — the mismatched condition could not be run")

    return {
        "set_id": scope.eval_set_id,
        "version": 1,
        "config_id": scope.config_id,
        "axe_core_version": AXE_VERSION,
        "store": STORE_DIR,
        "derived_from": OPAQUE_PERMUTATION.name,
        "note": (
            "The picture every pool finding actually rendered, captured through the production scan "
            "and addressed by its own sha256. Keyed by finding.id, never by target: `img` matches on "
            "nearly every case page. The bytes are the asset's own — the response the browser "
            "fetched, not a canvas or screenshot re-encoding — so a capture digest is comparable "
            "with the vendored asset's digest, and the media type is sniffed from those bytes and "
            "never from the deliberately-uniform `.png` names. The store is content-addressed, so "
            "each file's name IS its checksum and a read that no longer matches is refused. "
            "`resolved_permutation` is the frozen mapping turned into bytes: `with_image_ref` is "
            "what the case rendered, `mismatched_image_ref` is what the manipulation attaches "
            "instead, and no case receives its own bytes."
        ),
        "distinct_images": len({c["image_ref"] for c in captures}),
        "multiplicity": multiplicity([c["image_ref"] for c in captures]),
        "captures": captures,
        "resolved_permutation": resolved,
    }


def load_capture(artifact: Path = ARTIFACT) -> dict[str, str]:
    """`finding_id → image_ref` for the with-image condition, verified against the store on the way out.

    Every reference is read rather than trusted: the store recomputes each digest, so an artifact
    that has drifted from the bytes beside it fails here instead of attaching the wrong picture.
    """
    frozen = json.loads(artifact.read_text())
    store = ImageStore(artifact.parent / frozen["store"])
    for capture in frozen["captures"]:
        store.read(capture["image_ref"])
    return {capture["finding_id"]: capture["image_ref"] for capture in frozen["captures"]}


def main() -> None:
    artifact = capture_pool()
    ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(Path.cwd())} — set_id {artifact['set_id']}")
    shape = f"{artifact['distinct_images']} distinct images {artifact['multiplicity']}"
    print(f"  {len(artifact['captures'])} findings, {shape}")
    for row in artifact["resolved_permutation"]:
        flag = "live" if row["live"] else "dead"
        print(
            f"    {row['act_testcase_id'][:10]} {row['true_image']:>9} {row['with_image_ref'][:8]}…"
            f" → {row['mismatched_image']:>9} {row['mismatched_image_ref'][:8]}… [{flag}]"
        )
    store = ImageStore(ACT_IMAGE_OPAQUE / STORE_DIR)
    for ref in store.refs():
        print(f"  {ref[:12]}… {store.media_type(ref):<11} {len(store.read(ref)):>6} B")


if __name__ == "__main__":
    main()
