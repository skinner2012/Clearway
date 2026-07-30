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

⚠️ **A rebuild is guarded, because this script reads a prompt it does not own.** The natural drafts
come from the shipped `Drafter` and the elicited negatives reuse `_system_prompt()`, so κ frozen here
describes the drafter prompt *as it was on the day of the build*. Nothing in the artifact used to say
which day that was, so a prompt change elsewhere in the repo could — months later, silently — have a
re-run overwrite the frozen number with one that is not comparable to it. The artifact now records
the sha256 of the system prompt it was built under, and `assert_rebuild_is_comparable` refuses to
overwrite a frozen artifact the current prompt no longer matches. See that function for what happens
to an artifact that predates the pin, which is not treated as a match.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.drafter import Drafter
from clearway.drafter.llm import _assemble, _LLMDraft, _system_prompt, _visually_verified
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

# The artifact key holding the sha256 of the drafter system prompt the build ran under. Named on the
# artifact rather than kept here alone, so a reader can tell which prompt produced a κ from the file
# in front of them instead of from git history.
SYSTEM_PROMPT_SHA256_KEY = "drafter_system_prompt_sha256"


class IncomparableRebuild(RuntimeError):
    """A rebuild that would overwrite the frozen calibration artifact with one not comparable to it."""


def system_prompt_sha256() -> str:
    """The sha256 of the drafter system prompt a build would run under, right now.

    Hashed from the live `_system_prompt()` rather than a second frozen copy of its text: two copies
    of a prompt drift, and the copy that drifts is always the one nobody reads.
    """
    return hashlib.sha256(_system_prompt().encode()).hexdigest()


def provenance_pin() -> dict[str, str]:
    """What a build stamps on its artifact to say which prompt it ran under.

    One function, so the value the build writes and the value the guard reads cannot drift apart —
    and so the loop (build stamps → next build is checked against the stamp) is testable without a
    forty-minute model run.
    """
    return {SYSTEM_PROMPT_SHA256_KEY: system_prompt_sha256()}


def assert_rebuild_is_comparable(artifact_path: Path = _ARTIFACT) -> None:
    """Refuse to overwrite a frozen calibration artifact that this rebuild would not be comparable to.

    κ is a measurement of the judge against drafts, and those drafts were produced under a particular
    drafter prompt. Change the prompt and a rebuild answers a different question — but the file it
    writes has the same name, the same shape and the same authority, so the substitution is invisible.
    That is the "stale trusted surface" failure with a delay on it: the trap arms today and fires on
    whoever re-runs this months from now.

    Four states, and the third is the one that needs saying out loud:

    * **No frozen artifact.** Nothing to be incomparable with — a first build proceeds.
    * **Recorded hash matches.** The prompt is the one the frozen κ was measured under; proceed.
    * **No recorded hash.** The artifact predates the pin, so it cannot state which prompt produced
      it. That is not a match — it is an unanswerable question, and answering it "yes" by default is
      exactly the silent inheritance this guard exists to stop. It refuses.
    * **Recorded hash differs.** The prompt moved; refuse, naming both hashes.

    The escape hatch is deliberate rather than a flag: to supersede a frozen artifact, delete it and
    rebuild. That is a visible, reviewable, version-controlled act, where a `--force` is a reflex.

    Scope, stated so it is not over-read: this pins the system prompt, which is a constant. The
    per-finding user prompt is not a constant and is not pinned here — a change to *its* assembly is
    caught by the drafter's own byte-pinned prompt tests, not by this guard.
    """
    if not artifact_path.is_file():
        return
    recorded = json.loads(artifact_path.read_text()).get(SYSTEM_PROMPT_SHA256_KEY)
    current = system_prompt_sha256()
    if recorded == current:
        return
    if recorded is None:
        raise IncomparableRebuild(
            f"{artifact_path.name} predates the system-prompt pin: it records no "
            f"{SYSTEM_PROMPT_SHA256_KEY}, so it cannot state which drafter prompt produced its κ. "
            f"That is an unanswerable question, not a match, and a rebuild would replace a frozen "
            f"measurement with one nobody can compare against it. The current prompt hashes to "
            f"{current}. To supersede the frozen artifact, delete it deliberately and rebuild — the "
            f"new one records its pin, and every rebuild after that is checked against it."
        )
    raise IncomparableRebuild(
        f"the drafter system prompt has changed since {artifact_path.name} was frozen: the artifact "
        f"records {recorded}, the current prompt hashes to {current}. A κ measured on drafts written "
        f"under the old prompt does not describe drafts written under the new one, so rebuilding here "
        f"would overwrite a measurement with an incomparable one under the same name. To supersede "
        f"the frozen artifact, delete it deliberately and rebuild."
    )


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
        # The same system fact a natural draft of this finding would carry: nothing is attached here,
        # so a pixel-decided class is marked unverified exactly as the production path marks it. This
        # elicitation exists to produce rows identical in shape to natural ones, and the marking is
        # part of that shape.
        return _assemble(finding, citations, out, _visually_verified(finding, None))
    raise RuntimeError(f"elicitation produced no parseable draft for finding {finding.id!r}")


def _record(
    finding: Finding,
    gold: GoldLabel,
    draft: DraftRow,
    lever: str,
    judge: Judge,
    run_id: str,
    citations: list[Citation],
) -> dict[str, Any]:
    """One artifact row: the raw draft + its gold (so the human verdict is re-derivable at replay) +
    the judge's raw booleans/verdict. The 3-way verdicts are stored for readability; the replay test
    recomputes them from the raw fields, so the frozen data is self-checking, never merely trusted.

    The judge is handed the finding's own retrieved candidates — the same list the draft was made
    against — because its finding-side prompt renders them. ⚠️ A rebuild of this set therefore runs a
    judge whose input is not the one the frozen calibration was measured under; the frozen rows stay
    valid, a re-freeze would be a new measurement."""
    result = judge.judge(finding, draft, run_id, citations=citations)
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
        natural_row = _record(
            finding, gold, drafter.draft(finding, citations), "natural", judge, _CALIBRATION_VERSION, citations
        )
        rows.append(natural_row)
        note = f"natural={natural_row['human_verdict']}"
        # Authentic negatives: only false-supports on does_not_support findings, kept only when the
        # draft actually flips (borderline values). Everything else yields no authentic negative.
        if gold.gold_conformance is Conformance.DOES_NOT_SUPPORT:
            negative = _elicit(drafter_client, finding, citations, _false_supports_prompt(finding, citations))
            if human_verdict(negative, gold) is not JudgeVerdict.CORRECT:
                rows.append(_record(finding, gold, negative, "false_supports", judge, _CALIBRATION_VERSION, citations))
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
        **provenance_pin(),
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
    # Before the ~40-minute, cloud-billed run, not after: a guard that fires at write time has
    # already spent the money and the operator's afternoon on an artifact it then refuses to keep.
    assert_rebuild_is_comparable()
    artifact = build_calibration_set(created_at=datetime.now(timezone.utc).isoformat())
    _ARTIFACT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {_ARTIFACT.relative_to(Path.cwd())} — {len(artifact['drafts'])} drafts")
    _print_summary(artifact)


if __name__ == "__main__":
    main()
