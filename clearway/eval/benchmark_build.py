"""Run the held-out acceptance set through the full pipeline ONCE and freeze it to a `BenchmarkReport`.

Live: real drafter (gemma), real RAG retrieval, real judge (the cloud reference model) over every
vendored ACT case, then two checked-in JSON files — the raw run artifact (drafts + judge booleans +
provenance) and the scored report the pure `benchmark.build_report` derives from it. The artifact is
the reproducibility freeze: the non-deterministic models are called here once, and every number is
re-derivable network-free, exactly like the κ set. The runner reads the VENDORED gold, never the live
ACT endpoint.

This is scored ENTIRELY by deterministic comparison against ACT gold — the judge is graded here too,
as a subject, never as the ruler. Freeze is by content hash: the model DIGESTS (not the mutable Ollama
tag), the axe-core version, the corpus version, and the pinned ACT export hash all ride on the report.

Not run by the test suite (needs Ollama + the cloud key + pgvector). Invoke explicitly:
`uv run python -m clearway.eval.benchmark_build`. The pure assembly it calls is covered by tests.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter
from clearway.eval.act_gold import _ACT_GOLD, _EXPORT_SHA256, _MANIFEST, _minting_findings
from clearway.eval.benchmark import build_report
from clearway.eval.benchmark_inject import RATIONALE_NOTE, conformance_flip, sc_swap
from clearway.eval.benchmark_tier_b import NoisyFocalResult, tier_b_smoke
from clearway.eval.noisy_pages import _MANIFEST as _NOISY_MANIFEST
from clearway.eval.noisy_pages import _NOISY, _page_findings
from clearway.eval.stats import is_flag
from clearway.judge import Judge
from clearway.llm import CloudLLMClient, LocalLLMClient
from clearway.retriever import build_default_retriever
from clearway.scanner import AXE_VERSION
from clearway.schemas.models import Conformance

# The benchmark pins the SAME frozen single-model pipeline config the orchestrator runs (one model, no
# routing); only the eval set differs — it is held out, so it gets its own id, distinct from every dev
# fixture set. See specs: "distinct eval_set_id".
_CONFIG_ID = "m1-single@1"
_EVAL_SET_ID = "act-acceptance@1"

# Layout: raw runs are inputs (runs/), derived reports are outputs (reports/). A single run is run_1;
# the noise-floor sweep adds run_2… beside it. This builder owns only the raw run; the scored report
# under reports/ is a derived output — the noise-floor sweep and the freeze step (benchmark_freeze) own
# reports/, so a re-run of the single-run builder never clobbers the frozen baseline.
_OUT = Path(__file__).resolve().parents[2] / "benchmark"
_RUNS_DIR = _OUT / "runs"
_REPORTS_DIR = _OUT / "reports"
_RUN_ARTIFACT = _RUNS_DIR / "run_1.json"
# The per-case checkpoint: the expensive accumulated state (drafts + judge verdicts), flushed after
# every case so a mid-run crash or hang never loses the ~2h of drafting. Removed on clean completion;
# its presence on start-up means "resume". Transient — gitignored, never committed.
_PARTIAL = _OUT / "run.partial.json"

_OLLAMA_BASE_URL = os.getenv("CLEARWAY_OLLAMA_BASE_URL") or "http://localhost:11434"


def _read_partial(path: Path = _PARTIAL) -> dict[str, Any] | None:
    """The checkpoint to resume from, or None for a fresh run."""
    return dict(json.loads(path.read_text())) if path.exists() else None


def _write_partial(state: dict[str, Any], path: Path = _PARTIAL) -> None:
    """Flush the accumulated run state (compact, no indent — it is transient)."""
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n")


def _done_case_ids(partial: dict[str, Any] | None) -> set[str]:
    """The act_testcase_ids already completed in a checkpoint — the cases a resume must skip."""
    return {c["act_testcase_id"] for c in partial["cases"]} if partial else set()


def _ollama_digest(model: str, base_url: str = _OLLAMA_BASE_URL) -> str:
    """The Ollama model's immutable content digest (sha256 of its manifest) from `/api/tags` — the
    freeze key, NOT the mutable tag. Best-effort: a fetch failure records why rather than crashing a
    long live run, so the digest is degraded-but-honest, never silently wrong."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # pragma: no cover - live-only path
        return f"unavailable:{type(exc).__name__}"
    for m in data.get("models", []):
        if model in (m.get("name"), m.get("model")):
            return str(m.get("digest", "unknown"))
    return "unknown"


def _draft_record(finding: Any, draft: Any, judge_result: Any) -> dict[str, Any]:
    """One drafted finding + the judge's raw conformance/citation booleans. The pure scorer derives the
    deterministic act-correctness itself; the judge booleans are the only judge output stored."""
    return {
        "finding_id": finding.id,
        "target": finding.target,
        "conformance": draft.conformance.value,
        "cited_sc_ids": [c.sc_id for c in draft.citations],
        "confidence": draft.confidence,
        "judge_conformance_correct": judge_result.conformance_correct,
        "judge_citation_correct": judge_result.citation_correct,
        "judge_verdict": judge_result.verdict.value,
    }


def _run_tier_b(drafter: Drafter, retriever: Any, clean_flags: dict[str, bool]) -> dict[str, Any]:
    """Draft each noisy page; for its focal snippet compare the noisy verdict to the clean counterpart
    (from the Tier-A run), and count noise-region false positives (a flagged noise finding citing one of
    its tested properties). Drafter-only — Tier B is a smoke test of survival under noise, not judged."""
    manifest = json.loads(_NOISY_MANIFEST.read_text())
    results: list[NoisyFocalResult] = []
    for page in manifest["pages"]:
        by_key = {(f.rule_id, f.target): f for f in _page_findings(_NOISY / page["path"])}
        focal = page["focal"]
        ff = by_key[(focal["axe_rule"], focal["target"])]
        flagged_noisy = is_flag(drafter.draft(ff, retriever.retrieve(ff)).conformance)
        noise_fp = 0
        for n in page["noise"]:
            nf = by_key[(n["axe_rule"], n["target"])]
            nd = drafter.draft(nf, retriever.retrieve(nf))
            if is_flag(nd.conformance) and {c.sc_id for c in nd.citations} & set(n["tested_sc"]):
                noise_fp += 1
        results.append(
            NoisyFocalResult(
                page_id=page["page_id"],
                focal_rule=focal["axe_rule"],
                focal_expected=focal["expected"],
                flagged_clean=clean_flags.get(focal["act_testcase_id"], flagged_noisy),
                flagged_noisy=flagged_noisy,
                noise_fp=noise_fp,
            )
        )
    return tier_b_smoke(results)


def run_acceptance(created_at: str) -> dict[str, Any]:
    """Draft + judge every minting ACT case, carry the honest-misses as drafts-less cases, and stamp
    the reproducibility provenance → the raw run artifact. Prints per-case progress (the run is long,
    gemma-bound) so it is never opaque.

    CHECKPOINTED: the accumulated case/injection state is flushed after every case, so a crash or hang
    resumes from the last completed case instead of losing the whole run. A checkpoint present on entry
    means "resume" — its `created_at` (hence run identity) is kept, and completed cases are skipped.
    The checkpoint is removed on clean completion.
    """
    manifest = json.loads(_MANIFEST.read_text())
    total = len(manifest["cases"])

    partial = _read_partial()
    if partial:
        created_at = partial["created_at"]  # keep the original run identity across the resume
        cases, conf_flip, sc_swaps, tier_b = (
            partial["cases"],
            partial["conf_flip"],
            partial["sc_swaps"],
            partial.get("tier_b"),
        )
        done = _done_case_ids(partial)
        print(f"resuming run {created_at}: {len(done)}/{total} cases already done", flush=True)
    else:
        cases, conf_flip, sc_swaps, tier_b, done = [], [], [], None, set()

    drafter_client = LocalLLMClient()
    judge_client = CloudLLMClient()
    retriever = build_default_retriever()
    drafter = Drafter(drafter_client)
    judge = Judge(judge_client, drafter_model=drafter_client.model)
    run_id = f"acceptance-{created_at}"

    for i, case in enumerate(manifest["cases"], start=1):
        if case["act_testcase_id"] in done:
            continue  # already checkpointed — do not re-draft
        rule, gold = case["rule_name"], case["gold_success_criteria"]
        findings = _minting_findings(_ACT_GOLD / case["path"], case["axe_rule"])
        drafts: list[dict[str, Any]] = []
        for finding in findings:
            citations = retriever.retrieve(finding)
            draft = drafter.draft(finding, citations)
            drafts.append(_draft_record(finding, draft, judge.judge(finding, draft, run_id)))

            # SC-swap: a wrong citation on every draft → caught = judge flags the CITATION as wrong.
            swapped = judge.judge(finding, sc_swap(draft, gold), run_id)
            sc_swaps.append({"rule_name": rule, "caught": not swapped.citation_correct})
            # Conformance-flip: ONLY on conformance-correct drafts (else the flip could land on right).
            if is_flag(draft.conformance) == (case["expected"] == "failed"):
                flipped = judge.judge(finding, conformance_flip(draft), run_id)
                conf_flip.append({"rule_name": rule, "caught": not flipped.conformance_correct})

        cases.append(
            {
                "act_testcase_id": case["act_testcase_id"],
                "rule_name": rule,
                "axe_rule": case["axe_rule"],
                "expected": case["expected"],
                "gold_success_criteria": gold,
                "drafts": drafts,
            }
        )
        _write_partial({"created_at": created_at, "cases": cases, "conf_flip": conf_flip, "sc_swaps": sc_swaps})
        print(f"[{i:2d}/{total}] {rule[:30]:30s} {case['expected']:7s} n={len(drafts)}", flush=True)

    honest_misses = [
        {
            "act_testcase_id": m["act_testcase_id"],
            "rule_name": m["rule_name"],
            "expected": m["expected"],
            "gold_success_criteria": m["gold_success_criteria"],
        }
        for m in manifest["honest_misses"]
    ]
    # The realistic-page smoke test needs each focal's clean-counterpart verdict from the Tier-A run.
    clean_flags = {
        c["act_testcase_id"]: any(is_flag(Conformance(d["conformance"])) for d in c["drafts"]) for c in cases
    }
    if tier_b is None:  # Tier B is the last phase; checkpoint it so a late crash need not repeat it.
        tier_b = _run_tier_b(drafter, retriever, clean_flags)
        _write_partial(
            {"created_at": created_at, "cases": cases, "conf_flip": conf_flip, "sc_swaps": sc_swaps, "tier_b": tier_b}
        )

    artifact = {
        "run_ids": [run_id],
        "config_id": _CONFIG_ID,
        "eval_set_id": _EVAL_SET_ID,
        "corpus_version": retriever.corpus_version,
        "drafter_model": drafter_client.model,
        "drafter_model_digest": _ollama_digest(drafter_client.model),
        # Cloud models carry no Ollama-style digest; the pinned snapshot id is the best freeze key, and
        # cloud is not bit-reproducible even so (a pinned snapshot + fixed effort + fixed rubric is the
        # honest best available — the judge module says the same).
        "judge_model": judge_client.model,
        "judge_model_digest": f"cloud-snapshot:{judge_client.model}",
        "judge_version": judge.judge_version,
        "axe_core_version": AXE_VERSION,
        "act_export_hash": _EXPORT_SHA256,
        "created_at": created_at,
        "cases": cases,
        "honest_misses": honest_misses,
        "injected": {"conformance_flip": conf_flip, "sc_swap": sc_swaps, "rationale_note": RATIONALE_NOTE},
        "tier_b": tier_b,
    }
    _PARTIAL.unlink(missing_ok=True)  # fully assembled in memory → the checkpoint has done its job
    return artifact


def main() -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    artifact = run_acceptance(created_at=datetime.now(timezone.utc).isoformat())
    _RUN_ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    report = build_report(artifact)

    d = report.scorecard.drafter
    j = report.scorecard.judge
    fp, mr, far = d.false_positive_rate, j.miss_rate, j.false_alarm_rate
    print(f"\nwrote {_RUN_ARTIFACT.relative_to(Path.cwd())} (freeze the baseline with benchmark_freeze)")
    print(f"drafter: recall {d.recall.value:.3f} (n={d.recall.n}), FP {fp.value:.3f} (n={fp.n})")
    print(f"judge:   miss {mr.value:.3f} (n={mr.n}), false-alarm {far.value:.3f}, κ {j.kappa:.3f}")


if __name__ == "__main__":
    main()
