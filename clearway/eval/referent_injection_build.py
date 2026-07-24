"""Run A — the referent-injection acceptance pass, DRAFTER-ONLY, frozen to `benchmark/runs/`.

This is the referent-injection experiment. It re-scans every ACT case live (Playwright + axe + the
scanner's referent extraction), retrieves citations, and calls the drafter — whose prompt now carries the
injected referent. The judge is deliberately ABSENT: no acceptance number in this experiment reads a judge
field (the pooled thesis, the per-class verdicts, κ and the control all score the drafter against ACT gold),
so calling the paid judge here would buy nothing the experiment uses. The judge returns in Run B, where the
citation-grounding and remediation-scoring work need it.

**It never touches `run_1.json`.** That file is the frozen PRE-injection baseline the paired test compares
against; Run A writes its own `referent_injection_run_{n}.json`, one per determinism pass. The output
artifact carries only the drafter-side fields the verdict-vector and κ builders read — pure functions of it.

CHECKPOINTED per case (`referent_injection_run_{n}.partial.json`, gitignored) so a mid-pass crash resumes
rather than losing ~30-50 min of drafting. A single fallback draft aborts the pass (`_draft_checked`) — a
`does_not_support`@0.0 row would score as a phantom flag, and the injected (longer) prompt is exactly what
raises off-schema drift; fix the prompt and restart, never relax the guard.

Not run by the test suite (needs Ollama + pgvector). Invoke a pass explicitly:
`uv run python -m clearway.eval.referent_injection_build 1`   (then 2, then 3 for the determinism sweep).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter
from clearway.eval.act_gold import _ACT_GOLD, _EXPORT_SHA256, _MANIFEST, RULE_TO_AXE, _minting_findings
from clearway.eval.offline_build import _CONFIG_ID, _EVAL_SET_ID, _RUNS_DIR, _draft_checked, _ollama_digest
from clearway.llm import LocalLLMClient
from clearway.retriever import build_default_retriever
from clearway.scanner import AXE_VERSION


def _partial_path(pass_n: int) -> Path:
    return _RUNS_DIR.parent / f"referent_injection_run_{pass_n}.partial.json"


def _run_path(pass_n: int) -> Path:
    return _RUNS_DIR / f"referent_injection_run_{pass_n}.json"


def _read_partial(path: Path) -> dict[str, Any] | None:
    return dict(json.loads(path.read_text())) if path.exists() else None


def _write_partial(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n")


def _draft_record(finding: Any, draft: Any) -> dict[str, Any]:
    """One drafted finding — drafter-side only, no judge booleans. The verdict-vector and κ builders read
    exactly these fields (`conformance` for the FLAG/CLEAN collapse; the rest for provenance/scoring)."""
    return {
        "finding_id": finding.id,
        "target": finding.target,
        "conformance": draft.conformance.value,
        "cited_sc_ids": [c.sc_id for c in draft.citations],
        "confidence": draft.confidence,
    }


def run_acceptance_drafter_only(created_at: str, pass_n: int) -> dict[str, Any]:
    """Draft every scoped ACT minting case with referent injection, carry the honest-misses as drafts-less
    cases, stamp the reproducibility provenance → the raw Run A artifact. Drafter-only, checkpointed."""
    manifest = json.loads(_MANIFEST.read_text())
    scoped_cases = [c for c in manifest["cases"] if c["rule_name"] in RULE_TO_AXE]
    total = len(scoped_cases)
    partial_path = _partial_path(pass_n)

    partial = _read_partial(partial_path)
    if partial:
        created_at = partial["created_at"]
        cases = partial["cases"]
        done = {c["act_testcase_id"] for c in cases}
        print(f"resuming Run A pass {pass_n} ({created_at}): {len(done)}/{total} cases done", flush=True)
    else:
        cases, done = [], set()

    retriever = build_default_retriever()
    drafter_client = LocalLLMClient()
    drafter = Drafter(drafter_client)

    for i, case in enumerate(scoped_cases, start=1):
        if case["act_testcase_id"] in done:
            continue
        drafts: list[dict[str, Any]] = []
        for finding in _minting_findings(_ACT_GOLD / case["path"], case["axe_rule"]):
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
        _write_partial(partial_path, {"created_at": created_at, "cases": cases})
        print(f"[{i:2d}/{total}] {case['rule_name'][:30]:30s} {case['expected']:7s} n={len(drafts)}", flush=True)

    honest_misses = [
        {
            "act_testcase_id": m["act_testcase_id"],
            "rule_name": m["rule_name"],
            "expected": m["expected"],
            "gold_success_criteria": m["gold_success_criteria"],
        }
        for m in manifest["honest_misses"]
        if m["rule_name"] in RULE_TO_AXE
    ]

    model = drafter_client.model
    artifact = {
        "run_ids": [f"referent-injection-pass{pass_n}-{created_at}"],
        "config_id": _CONFIG_ID,
        "eval_set_id": _EVAL_SET_ID,
        "corpus_version": retriever.corpus_version,
        "drafter_model": model,
        "drafter_model_digest": _ollama_digest(model),
        "axe_core_version": AXE_VERSION,
        "act_export_hash": _EXPORT_SHA256,
        "created_at": created_at,
        "cases": cases,
        "honest_misses": honest_misses,
    }
    partial_path.unlink(missing_ok=True)
    return artifact


def main() -> None:
    pass_n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    artifact = run_acceptance_drafter_only(created_at=datetime.now(timezone.utc).isoformat(), pass_n=pass_n)
    out = _run_path(pass_n)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out.relative_to(Path.cwd())}  ({len(artifact['cases'])} cases, drafter-only)")


if __name__ == "__main__":
    main()
