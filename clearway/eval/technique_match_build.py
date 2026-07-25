"""Run the technique-classification pass over a frozen run's remediation text and freeze the result.

Reads a frozen drafter run artifact, pulls the drafted remediation sentence for every case in a class
that carries ACT technique gold, classifies each one ONCE with the technique classifier, scores the
stream chance-corrected against that gold (`technique_match`), and writes the artifact under
`benchmark/reports/`. It never writes to `benchmark/runs/` and never re-drafts anything.

**No drafter call is made here.** The remediation text is read from an artifact that already exists, so
this pass adds nothing to the held-out drafter run count — the only model calls are the classifier's,
one per scoreable case, at scoring time and not per finding.

**A run artifact that does not persist `remediation` cannot be scored**, and this raises rather than
scoring an empty stream: the drafted sentence is the whole input, so a missing one is a missing
measurement, never a zero.

`--smoke` stamps the output as a PIPELINE SMOKE — a proof that the chain runs end to end, explicitly not
a measurement of anything — and the stamp lands in the artifact's own fields (`status`,
`is_reported_metric`, `smoke_reason`), not only in prose, so a later reader cannot mistake it for the
real number. Every classification is echoed into the artifact with the sentence it was made from, so the
κ recomputes from the file alone.

Not run by the test suite (it calls a cloud model). Invoke it explicitly:
`uv run python -m clearway.eval.technique_match_build --run citation_grounding`
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from clearway.eval.technique_match import (
    RemediationDraft,
    classification_rows,
    classify_all,
    prompt_sha256,
    score_technique_match,
    scoreable,
    technique_gold_by_class,
    technique_vocabulary,
)
from clearway.llm.cloud import technique_classifier_client

_SMOKE_STATUS = "PIPELINE_SMOKE — NOT THE REPORTED METRIC"
_MEASUREMENT_STATUS = "measurement"


def remediation_drafts(artifact: dict[str, Any]) -> list[RemediationDraft]:
    """The scoreable remediation sentences in a frozen run artifact: one per drafted finding in a class
    that carries technique gold. Raises when the artifact persists no remediation text at all, naming
    the fix — the run has to record the sentence for it to ever be scored."""
    drafts = [
        RemediationDraft(
            act_testcase_id=case["act_testcase_id"],
            axe_rule=case["axe_rule"],
            remediation=draft["remediation"],
        )
        for case in artifact["cases"]
        for draft in case["drafts"]
        if draft.get("remediation")
    ]
    covered = scoreable(drafts)
    if not covered:
        raise RuntimeError(
            "no scoreable remediation text in this run artifact — either it persists no `remediation` "
            "field on its drafts (the run builder must record it), or none of its cases fall in a class "
            f"carrying ACT technique gold ({', '.join(technique_gold_by_class())})"
        )
    return covered


def build_technique_match(
    artifact: dict[str, Any], *, source: str, smoke_reason: str | None, created_at: str
) -> dict[str, Any]:
    """Classify the artifact's remediation text and assemble the frozen technique-match payload."""
    drafts = remediation_drafts(artifact)
    vocabulary = technique_vocabulary()
    client = technique_classifier_client()
    classifications = classify_all(client, drafts, vocabulary=vocabulary)
    scoring = score_technique_match(classifications, classifier_model=client.model)
    return {
        "status": _SMOKE_STATUS if smoke_reason else _MEASUREMENT_STATUS,
        "is_reported_metric": smoke_reason is None,
        "smoke_reason": smoke_reason,
        "metric": scoring.metric.model_dump(),
        "notes": scoring.notes,
        "classifications": classification_rows(classifications),
        "source_artifact": source,
        "source_run_ids": artifact.get("run_ids", []),
        "drafter_model": artifact.get("drafter_model"),
        "classifier_model": client.model,
        "classifier_reasoning_effort": client.reasoning_effort,
        "classifier_prompt_sha256": prompt_sha256(vocabulary),
        "classifier_vocabulary_size": len(vocabulary),
        "classifier_calls": len(classifications),
        "drafter_calls": 0,
        "provenance_note": (
            "The remediation text was read from the input artifact, not drafted here: NO drafter call was "
            "made, so this pass adds nothing to the held-out drafter run count. The only model calls are the "
            "classifier's — one per scoreable case, at scoring time. The classifier's answer is scored "
            "against ACT gold, never trusted: it is a classification, not a judge, and it is a different "
            "model from both the drafter and the judge role, which takes no part in this number. Every "
            "classified sentence is echoed in `classifications`, so the κ recomputes from this file alone."
        ),
        "created_at": created_at,
    }


def _print_read(result: dict[str, Any]) -> None:
    metric = result["metric"]
    print(f"status: {result['status']}")
    if result["smoke_reason"]:
        print(f"  smoke reason: {result['smoke_reason']}")
    print(
        f"κ={metric['kappa']:+.3f}  CI [{metric['ci_low']:+.3f}, {metric['ci_high']:+.3f}]  n={metric['n']}  "
        f"raw agreement {metric['raw_agreement']:.3f} (context, not the metric)  "
        f"constant_classifier={metric['constant_classifier']}"
    )
    print(f"coverage: {', '.join(metric['covered_classes'])} scored | {', '.join(metric['uncovered_classes'])} absent")
    for row in result["classifications"]:
        mark = "ok " if row["agrees"] else "MIS"
        print(f"  {mark} {row['axe_rule']:<15} inferred={row['inferred_technique']:<6} gold={row['gold_key']}")


def main() -> None:
    from clearway.eval.run_artifacts import RUN_LABELS, run_path, technique_match_path

    parser = argparse.ArgumentParser(description="score drafted remediation direction against ACT technique gold")
    parser.add_argument(
        "--run",
        required=True,
        choices=RUN_LABELS,
        help="which run's drafted remediation to score — it names both the input artifact and the output, "
        "so a score can never be read as another run's",
    )
    parser.add_argument("--pass-n", type=int, default=1, help="which determinism pass to read (default: 1, canonical)")
    parser.add_argument(
        "--smoke",
        default=None,
        metavar="REASON",
        help="stamp the output as a pipeline smoke that is NOT the reported metric, with the reason why",
    )
    args = parser.parse_args()

    source = run_path(args.run, args.pass_n)
    if not source.exists():
        raise SystemExit(f"no frozen pass at {source} — build it first")
    result = build_technique_match(
        json.loads(source.read_text()),
        source=str(source),
        smoke_reason=args.smoke,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    out = technique_match_path(args.run)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    _print_read(result)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
