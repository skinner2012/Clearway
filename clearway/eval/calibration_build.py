"""Build the balanced calibration draft set + judge verdicts, and freeze it to a versioned artifact.

Live: runs the real drafter (gemma), real RAG retrieval, and the real judge (the cloud reference
model) ONCE, then writes a checked-in JSON that the pure κ math in `kappa.py` replays network-free.
This is the only place the non-deterministic models are called for calibration — κ itself never
re-derives them, so the trust number stays reproducible from the frozen artifact.

Per gold finding:
- a **natural** draft — the faithful drafter pass, the drafter's real-workload output (always kept);
- an **elicited-negative** draft — but ONLY where gemma authentically produces one. Empirically
  (probed on gemma4:31b) the drafter RESISTS manufactured errors: it will not over-flag genuinely
  good content (a false-`does_not_support` lever fails), and it cites the correct SC even when offered
  only misleading candidates (a wrong-SC lever fails). The one lever that yields an authentic negative
  is **false-`supports`**: strip the quality-review reframe so a *borderline* poor value is read as
  already-conformant, and gemma drafts `supports`. So negatives are harvested by applying false-supports
  to the `does_not_support` findings and KEEPING only the ones that actually flip; `supports` and
  obvious-garbage findings yield no authentic negative and contribute their natural draft alone.

The realized set is therefore ~70/30 (correct/negative), not 50/50 — the honest ceiling given the
drafter's genuine skill, and still non-degenerate for κ. Only the framing is constructed; the label
is always the human verdict derived mechanically from gold. The shipped drafter is untouched.

Not run by the test suite (it needs Ollama + the cloud key + pgvector). Invoke explicitly:
`uv run python -m clearway.eval.calibration_build`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter
from clearway.drafter.llm import _assemble, _LLMDraft, _system_prompt
from clearway.eval.kappa import KAPPA_THRESHOLD, analyze, human_verdict
from clearway.judge import Judge
from clearway.llm import CloudLLMClient, LLMClient, LocalLLMClient
from clearway.normalizer import normalize
from clearway.retriever import build_default_retriever
from clearway.scanner import scan
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    Conformance,
    DraftRow,
    Finding,
    GoldLabel,
    JudgeVerdict,
    Severity,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_GOLD_MANIFEST = _FIXTURES / "expected_quality.json"
_ARTIFACT = _FIXTURES / "calibration_set.json"

_CALIBRATION_VERSION = "calibration@1"


def load_gold_pairs() -> list[tuple[Finding, GoldLabel]]:
    """Load the gold set the way the guard test does: scan+normalize each fixture, match each
    labelled target to its `AxeBucket.PASSES` finding, and pair the `Finding` with a `GoldLabel`
    (finding_id derived from the live scan — it hashes an absolute file:// URL, so it isn't stored)."""
    manifest = json.loads(_GOLD_MANIFEST.read_text())
    pairs: list[tuple[Finding, GoldLabel]] = []
    for page in manifest["pages"]:
        findings = normalize(scan(str(_FIXTURES / page["path"])))
        passes = {f.target: f for f in findings if f.source_bucket is AxeBucket.PASSES}
        for item in page["items"]:
            finding = passes[item["target"]]
            gold = GoldLabel(
                finding_id=finding.id,
                gold_success_criteria=[page["sc"]],
                gold_conformance=Conformance(item["conformance"]),
                gold_severity=Severity(item["severity"]) if item["severity"] else None,
                labeller=manifest["labeller"],
                gold_version=manifest["gold_version"],
                notes=item["notes"],
            )
            pairs.append((finding, gold))
    return pairs


def _candidate_lines(citations: list[Citation]) -> str:
    return "\n".join(f"- {c.sc_id} ({c.url})" for c in citations) or "- (none retrieved)"


def _false_supports_prompt(finding: Finding, citations: list[Citation]) -> str:
    """Strip the quality-review reframe: present the passed check as "the attribute is present",
    inducing the pre-quality-review read that present == conformant → an authentic `supports` on a
    borderline value. (Obvious-garbage values don't flip — gemma knows they're bad — which is exactly
    why only the borderline items yield negatives, and why those are the interesting judge calls.)"""
    return (
        f"Finding: axe rule '{finding.rule_id}' PASSED its automated check — the required "
        "name/text/attribute is PRESENT on the element.\n"
        f"Target element: {finding.target}\n"
        f"HTML: {finding.html or '(not captured)'}\n"
        f"Candidate WCAG success criteria you may cite:\n{_candidate_lines(citations)}\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )


def _elicit(client: LLMClient, finding: Finding, citations: list[Citation], user: str, retries: int = 1) -> DraftRow:
    """Run gemma with a perturbed USER framing (system prompt + output schema unchanged), then
    assemble the `DraftRow` with the drafter's own code — so a negative is a real, corpus-grounded
    drafter output, identical in shape to a natural one, differing only in the framing that produced
    it. Raises loudly if the model never parses — a build-time failure should be seen, not swallowed."""
    for _ in range(retries + 1):
        completion = client.complete_json(_system_prompt(), user, _LLMDraft)
        try:
            out = _LLMDraft.model_validate_json(completion.content)
        except ValueError:
            continue
        return _assemble(finding, citations, out)
    raise RuntimeError(f"elicitation produced no parseable draft for finding {finding.id!r}")


def _record(
    finding: Finding, gold: GoldLabel, draft: DraftRow, lever: str, judge: Judge, run_id: str
) -> dict[str, Any]:
    """One artifact row: the raw draft + its gold (so the human verdict is re-derivable at replay) +
    the judge's raw booleans/verdict. The 3-way verdicts are stored for readability; the replay test
    recomputes them from the raw fields, so the frozen data is self-checking, never merely trusted."""
    result = judge.judge(finding, draft, run_id)
    return {
        "finding_id": finding.id,
        "target": finding.target,
        "rule_id": finding.rule_id,
        "lever": lever,
        "draft": {
            "conformance": draft.conformance.value,
            "cited_sc_ids": [c.sc_id for c in draft.citations],
            "confidence": draft.confidence,
            "remediation": draft.remediation,
        },
        "gold": {
            "gold_success_criteria": gold.gold_success_criteria,
            "gold_conformance": gold.gold_conformance.value,
        },
        "human_verdict": human_verdict(draft, gold).value,
        "judge": {
            "citation_correct": result.citation_correct,
            "conformance_correct": result.conformance_correct,
            "verdict": result.verdict.value,
            "rationale": result.rationale,
        },
    }


def build_calibration_set(created_at: str) -> dict[str, Any]:
    """Run the full live build: a natural draft for every gold finding, plus an authentic
    false-supports negative for each `does_not_support` finding that actually flips. Prints per-finding
    progress (the run is ~40 min, gemma-bound) so it is never opaque."""
    pairs = load_gold_pairs()
    drafter_client = LocalLLMClient()
    judge_client = CloudLLMClient()
    retriever = build_default_retriever()
    drafter = Drafter(drafter_client)
    judge = Judge(judge_client, drafter_model=drafter_client.model)

    rows: list[dict[str, Any]] = []
    negatives_kept = 0
    for i, (finding, gold) in enumerate(pairs, start=1):
        citations = retriever.retrieve(finding)
        natural_row = _record(finding, gold, drafter.draft(finding, citations), "natural", judge, _CALIBRATION_VERSION)
        rows.append(natural_row)
        note = f"natural={natural_row['human_verdict']}"
        # Authentic negatives: only false-supports on does_not_support findings, kept only when the
        # draft actually flips (borderline values). Everything else yields no authentic negative.
        if gold.gold_conformance is Conformance.DOES_NOT_SUPPORT:
            negative = _elicit(drafter_client, finding, citations, _false_supports_prompt(finding, citations))
            if human_verdict(negative, gold) is not JudgeVerdict.CORRECT:
                rows.append(_record(finding, gold, negative, "false_supports", judge, _CALIBRATION_VERSION))
                negatives_kept += 1
                note += " | negative=KEPT"
            else:
                note += " | negative=no-flip (discarded)"
        print(f"[{i:2d}/{len(pairs)}] {finding.rule_id:11s} {finding.target:12s} {note}", flush=True)

    print(f"kept {negatives_kept} authentic negatives", flush=True)
    return {
        "set_id": "calibration",
        "version": 1,
        "calibration_version": _CALIBRATION_VERSION,
        "gold_version": pairs[0][1].gold_version,
        "drafter_model": drafter_client.model,
        "judge_model": judge_client.model,
        "judge_version": judge.judge_version,
        "corpus_version": retriever.corpus_version,
        "kappa_threshold": KAPPA_THRESHOLD,
        "created_at": created_at,
        "drafts": rows,
    }


def _print_summary(artifact: dict[str, Any]) -> None:
    """Show the realized balance + both κ's, so the operator sees immediately whether the balanced-set
    κ clears the bar (else Phase 3: tighten the rubric, then swap the judge model)."""
    rows = artifact["drafts"]

    def _streams(subset: list[dict[str, Any]]) -> tuple[list[JudgeVerdict], list[JudgeVerdict]]:
        return (
            [JudgeVerdict(r["human_verdict"]) for r in subset],
            [JudgeVerdict(r["judge"]["verdict"]) for r in subset],
        )

    balanced = analyze(*_streams(rows))
    natural = analyze(*_streams([r for r in rows if r["lever"] == "natural"]))
    correct = sum(1 for r in rows if r["human_verdict"] == "correct")
    threshold = artifact["kappa_threshold"]
    trusted = "TRUSTED" if balanced.kappa >= threshold else "NOT TRUSTED"
    print(f"balance:  {correct} correct / {len(rows) - correct} not-correct  (of {len(rows)} drafts)")
    print(f"balanced: n={balanced.n} κ={balanced.kappa:.3f} agree={balanced.agreement:.3f}")
    print(f"          binary-collapse κ={balanced.kappa_binary:.3f}")
    print(f"natural:  n={natural.n} κ={natural.kappa:.3f} agree={natural.agreement:.3f}")
    print(f"gate:     κ≥{threshold} → {trusted}")


def main() -> None:
    artifact = build_calibration_set(created_at=datetime.now(timezone.utc).isoformat())
    _ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {_ARTIFACT.relative_to(Path.cwd())} — {len(artifact['drafts'])} drafts")
    _print_summary(artifact)


if __name__ == "__main__":
    main()
