"""One drafter-only acceptance pass, frozen under `benchmark/runs/` in its run's own namespace.

It re-scans every ACT case live (Playwright + axe + the scanner's referent extraction), retrieves
citations, and calls the drafter under whatever prompt is currently built. **DRAFTER-ONLY: the judge is
deliberately absent, and stays absent.** No acceptance number here reads a judge field — the pooled
thesis, the per-class verdicts, κ and the control all score the drafter against ACT gold — and the
standing rule is to score against ACT gold, never the judge, which sits at chance. A citation change is
measured the same way, deterministically against gold, so no run this module builds calls the judge.

**Which run it builds is an explicit argument, never a default.** The label namespaces every artifact
(see `run_artifacts`): the referent-injection run and the citation-grounding run write different files,
so the second cannot overwrite the first — which matters because the first is the comparison the second
is measured against. `refuse_to_overwrite` backs that up at the write itself, so a mislabelled invocation
fails loudly instead of replacing a frozen measurement.

**It never touches `run_1.json`** — the frozen pre-injection baseline every paired test compares against.
The output artifact carries only the drafter-side fields the verdict-vector and κ builders read.

CHECKPOINTED per case (`{label}_run_{n}.partial.json`, gitignored, kept out of the runs directory) so a
mid-pass crash resumes rather than losing ~30-50 min of drafting. A single fallback draft aborts the pass
(`_draft_checked`) — a `does_not_support`@0.0 row would score as a phantom flag, and a longer prompt is
exactly what raises off-schema drift; fix the prompt and restart, never relax the guard.

Not run by the test suite (needs Ollama + pgvector). Invoke a pass explicitly:
`uv run python -m clearway.eval.referent_injection_build --run citation_grounding 1`  (then 2, then 3).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter
from clearway.eval.offline_build import _RUNS_DIR, _draft_checked, _ollama_digest
from clearway.eval.run_artifacts import RUN_LABELS, partial_path, refuse_to_overwrite, run_path
from clearway.eval.run_scope import ACCEPTANCE, RunScope, cases_for, honest_misses_for
from clearway.llm import LocalLLMClient
from clearway.retriever import build_default_retriever


def _read_partial(path: Path) -> dict[str, Any] | None:
    return dict(json.loads(path.read_text())) if path.exists() else None


def _write_partial(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n")


def _draft_record(finding: Any, draft: Any) -> dict[str, Any]:
    """One drafted finding — drafter-side only, no judge booleans.

    `conformance` drives the FLAG/CLEAN collapse the verdict-vector and κ builders score; the rest is
    provenance. `remediation` is the drafted fix sentence, recorded because it is the whole input to the
    fix-direction metric (`technique_match`) and dropping it made that metric uncomputable from a run —
    the sentence cannot be recovered afterwards without re-drafting, which would be a fresh model pass.
    Artifacts written before it was added simply lack the key; every reader here takes the fields it
    needs by name, so old and new artifacts both load and nothing is re-frozen to add it.
    """
    return {
        "finding_id": finding.id,
        "target": finding.target,
        "conformance": draft.conformance.value,
        "cited_sc_ids": [c.sc_id for c in draft.citations],
        "confidence": draft.confidence,
        "remediation": draft.remediation,
    }


def run_acceptance_drafter_only(scope: RunScope, created_at: str, pass_n: int, label: str) -> dict[str, Any]:
    """Draft every case this scope covers under the current prompt, carry the honest-misses as drafts-less
    cases, stamp the scope's reproducibility provenance → the raw pass artifact. Drafter-only, checkpointed.

    `scope` is required and is the whole work list: which manifest the cases come from, which classes are
    in it, how a case mints its findings, and which config and eval-set ids the artifact carries. It used
    to be four module-level constants, so any reuse of this builder silently drafted the acceptance 44 and
    stamped the acceptance identity on the result.

    `label` names which run this pass belongs to and namespaces its checkpoint and its run ids, so two
    runs never resume from each other's half-written state."""
    scoped_cases = cases_for(scope)
    total = len(scoped_cases)
    checkpoint = partial_path(label, pass_n)

    partial = _read_partial(checkpoint)
    if partial:
        created_at = partial["created_at"]
        cases = partial["cases"]
        done = {c["act_testcase_id"] for c in cases}
        print(f"resuming {label} pass {pass_n} ({created_at}): {len(done)}/{total} cases done", flush=True)
    else:
        cases, done = [], set()

    retriever = build_default_retriever()
    drafter_client = LocalLLMClient()
    drafter = Drafter(drafter_client)

    for i, case in enumerate(scoped_cases, start=1):
        if case["act_testcase_id"] in done:
            continue
        drafts: list[dict[str, Any]] = []
        for finding in scope.minting_findings(scope.root / case["path"], case["axe_rule"]):
            draft = _draft_checked(drafter, finding, retriever.retrieve(finding))
            drafts.append(_draft_record(finding, draft))
        cases.append(
            {
                "act_testcase_id": case["act_testcase_id"],
                "rule_name": case["rule_name"],
                "axe_rule": case["axe_rule"],
                "expected": case["expected"],
                "gold_success_criteria": case["gold_success_criteria"],
                "drafts": drafts,
            }
        )
        _write_partial(checkpoint, {"created_at": created_at, "cases": cases})
        print(f"[{i:2d}/{total}] {case['rule_name'][:30]:30s} {case['expected']:7s} n={len(drafts)}", flush=True)

    honest_misses = [
        {
            "act_testcase_id": m["act_testcase_id"],
            "rule_name": m["rule_name"],
            "expected": m["expected"],
            "gold_success_criteria": m["gold_success_criteria"],
        }
        for m in honest_misses_for(scope)
    ]

    model = drafter_client.model
    artifact = {
        **scope.provenance(
            run_ids=[f"{label.replace('_', '-')}-pass{pass_n}-{created_at}"],
            corpus_version=retriever.corpus_version,
            drafter_model=model,
            drafter_model_digest=_ollama_digest(model),
            created_at=created_at,
        ),
        "cases": cases,
        "honest_misses": honest_misses,
    }
    checkpoint.unlink(missing_ok=True)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="build one drafter-only acceptance pass")
    parser.add_argument(
        "--run",
        required=True,
        choices=RUN_LABELS,
        help="which run this pass belongs to — required, never defaulted, because the label decides "
        "which frozen artifacts get written",
    )
    parser.add_argument("pass_n", type=int, help="determinism pass number (pass 1 is the canonical one)")
    args = parser.parse_args()

    # Checked BEFORE the model is called: an hours-long pass that ends in a refusal to write is worse
    # than the same refusal now, and worse still is the write going through over a frozen measurement.
    out = run_path(args.run, args.pass_n)
    refuse_to_overwrite(out)

    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    artifact = run_acceptance_drafter_only(
        ACCEPTANCE, created_at=datetime.now(timezone.utc).isoformat(), pass_n=args.pass_n, label=args.run
    )
    refuse_to_overwrite(out)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out.relative_to(Path.cwd())}  ({len(artifact['cases'])} cases, drafter-only)")


if __name__ == "__main__":
    main()
