"""The Run A dry gate: assert offline, before the model is called once, that the run is worth starting.

Four checks, each seconds of computation against a run that costs a long local sweep — a run started with
the gate red is a wasted run:

1. **Referent present, verbatim.** For every fixed class (`label`, `document-title`, `link-name`) the
   named referent string the injection block emits appears **verbatim** in the assembled prompt. This is
   the criterion that gates the experiment: if the referent is not verifiably in the prompt, the thesis was
   never tested and the run proves nothing about it.
2. **Control byte-identical.** Every `empty-heading` prompt carries no referent block at all — the three
   class-gated block helpers each return `''` on it, so its prompt is byte-identical to the pre-injection
   one. The control is the anchor proving the instrument works; a leak into it destroys the attribution.
3. **Case set identical — 44.** The scoped case set (act_testcase_ids) matches the frozen baseline verdict
   vector exactly. Prompt changes cannot mint or drop findings, so a differing set means something other
   than the prompt moved.
4. **Environment held fixed.** The five provenance fields — drafter model digest, axe-core version, ACT
   export hash, corpus version, config id — match the baseline artifact exactly.

**The gate is gold-free by construction.** It never reads a gold label to decide whether to run: no
"opposite-gold cases share a prompt" condition, no distinct-prompt threshold. Distinct-prompt counts ARE
computed here and returned, but as a post-hoc diagnostic reported after the run, never as a go/no-go input.

The check functions are pure and unit-tested; `run_dry_gate` is the live driver (Playwright re-scan +
corpus retrieval, no model) and is invoked explicitly, like the acceptance builder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The distinctive opening phrases of each referent block (see `drafter/llm.py`). Their ABSENCE from an
# `empty-heading` prompt is the leak check; a phrase here that drifts from the block text would weaken the
# control silently, so the two are kept verbatim-equal and that equality is asserted by test.
_BLOCK_MARKERS = (
    "Resolved accessible name:",
    "Nearest section heading:",
    "Resolved page title:",
    "Page topic",
    "Surrounding context",
)

# The referent each fixed class must carry verbatim, as the injection block emits it. `document-title`'s
# deciding fact is the resolved title (the topic is only what it is compared against), so the title is the
# gated string; `label` and `link-name` turn on the accessible name where one is computed.
_PRIMARY_REFERENT = {
    "label": "accessible_name",
    "document-title": "document_title",
    "link-name": "accessible_name",
}
# A second acceptable referent for a class whose primary may be legitimately absent (a link with no
# accessible name is carried by its surrounding context instead).
_FALLBACK_REFERENT = {"link-name": "surrounding_context"}

_FIXED_CLASSES = ("label", "document-title", "link-name")
_CONTROL_CLASS = "empty-heading"
_ENV_FIELDS = ("drafter_model_digest", "axe_core_version", "act_export_hash", "corpus_version", "config_id")


def referent_text(referent: Any, attr: str) -> str | None:
    """The `.text` of one referent excerpt (`accessible_name`, `document_title`, …), or None when the whole
    referent or that excerpt is absent. `text == ""` (present but empty) is returned as-is, never collapsed
    to None — an empty referent is a real signal, distinct from a missing one."""
    if referent is None:
        return None
    excerpt = getattr(referent, attr, None)
    return None if excerpt is None else excerpt.text


def referent_verbatim_failures(records: list["PromptRecord"]) -> list[str]:
    """The fixed-class prompts whose named referent is NOT present verbatim — the gate-1 failures.

    For each fixed-class record the primary referent string must appear verbatim in the prompt; where the
    primary is absent and the class allows a fallback (link-name → surrounding context), the fallback must.
    A record whose class carries neither is a failure, named to its case."""
    failures: list[str] = []
    for r in records:
        if r.axe_rule not in _FIXED_CLASSES:
            continue
        primary = referent_text(r.referent, _PRIMARY_REFERENT[r.axe_rule])
        candidates = [t for t in (primary,) if t]
        fb_attr = _FALLBACK_REFERENT.get(r.axe_rule)
        if fb_attr is not None:
            fb = referent_text(r.referent, fb_attr)
            if fb:
                candidates.append(fb)
        if not candidates:
            failures.append(f"{r.axe_rule}/{r.act_testcase_id}: no referent string present to inject")
        elif not any(text in r.prompt for text in candidates):
            failures.append(f"{r.axe_rule}/{r.act_testcase_id}: referent not found verbatim in prompt")
    return failures


def control_leak_failures(records: list["PromptRecord"]) -> list[str]:
    """The control (`empty-heading`) prompts that carry a referent block marker — the gate-2 failures. The
    control must be byte-identical to the pre-injection prompt, so no block phrase may appear in it."""
    failures: list[str] = []
    for r in records:
        if r.axe_rule != _CONTROL_CLASS:
            continue
        leaked = [m for m in _BLOCK_MARKERS if m in r.prompt]
        if leaked:
            failures.append(f"{_CONTROL_CLASS}/{r.act_testcase_id}: control prompt leaked {leaked}")
    return failures


def case_set_failures(scoped_ids: set[str], baseline_ids: set[str]) -> list[str]:
    """Gate 3: the scoped case set must equal the baseline's exactly (hence be 44)."""
    failures: list[str] = []
    if len(baseline_ids) != 44:
        failures.append(f"baseline verdict vector has {len(baseline_ids)} cases, expected 44")
    if scoped_ids != baseline_ids:
        missing = sorted(baseline_ids - scoped_ids)
        extra = sorted(scoped_ids - baseline_ids)
        failures.append(f"scoped case set != baseline. missing: {missing}; extra: {extra}")
    return failures


def env_failures(live: dict[str, str], baseline: dict[str, str]) -> list[str]:
    """Gate 4: the five provenance fields must match the baseline artifact exactly."""
    return [
        f"env {k}: live {live.get(k)!r} != baseline {baseline.get(k)!r}"
        for k in _ENV_FIELDS
        if live.get(k) != baseline.get(k)
    ]


@dataclass(frozen=True)
class PromptRecord:
    """One assembled prompt for the dry gate: its class, case id, referent, and the full prompt text."""

    axe_rule: str
    act_testcase_id: str
    referent: Any
    prompt: str


@dataclass(frozen=True)
class DryGateResult:
    """The gate verdict: green iff every check passed, with each check's failures named."""

    green: bool
    referent_failures: list[str]
    control_failures: list[str]
    case_set_failures: list[str]
    env_failures: list[str]
    distinct_prompts_by_class: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "green": self.green,
            "referent_failures": self.referent_failures,
            "control_failures": self.control_failures,
            "case_set_failures": self.case_set_failures,
            "env_failures": self.env_failures,
            "distinct_prompts_by_class": self.distinct_prompts_by_class,
        }


def evaluate(
    records: list[PromptRecord],
    *,
    scoped_ids: set[str],
    baseline_ids: set[str],
    live_env: dict[str, str],
    baseline_env: dict[str, str],
) -> DryGateResult:
    """Run all four checks over the assembled records → the gate verdict. Pure: no scan, no model."""
    ref = referent_verbatim_failures(records)
    ctrl = control_leak_failures(records)
    cases = case_set_failures(scoped_ids, baseline_ids)
    env = env_failures(live_env, baseline_env)
    distinct: dict[str, set[str]] = {}
    for r in records:
        distinct.setdefault(r.axe_rule, set()).add(r.prompt)
    distinct_counts = {k: len(v) for k, v in distinct.items()}
    return DryGateResult(
        green=not (ref or ctrl or cases or env),
        referent_failures=ref,
        control_failures=ctrl,
        case_set_failures=cases,
        env_failures=env,
        distinct_prompts_by_class=distinct_counts,
    )


def _baseline_env(baseline_artifact: dict[str, Any]) -> dict[str, str]:
    return {k: baseline_artifact[k] for k in _ENV_FIELDS}


def _assemble_records() -> tuple[list[PromptRecord], set[str]]:
    """LIVE: re-scan every scoped minting case (Playwright + axe + referent extraction), retrieve its
    citations, assemble the drafter prompt. No model call. Returns the records and the scoped case-id set
    (minting cases + honest misses), the set the verdict vector is keyed on."""
    from clearway.drafter.llm import _user_prompt
    from clearway.eval.act_gold import _ACT_GOLD, _MANIFEST, RULE_TO_AXE, _minting_findings
    from clearway.retriever import build_default_retriever

    manifest = json.loads(_MANIFEST.read_text())
    scoped = [c for c in manifest["cases"] if c["rule_name"] in RULE_TO_AXE]
    retriever = build_default_retriever()
    records: list[PromptRecord] = []
    for case in scoped:
        for finding in _minting_findings(_ACT_GOLD / case["path"], case["axe_rule"]):
            prompt = _user_prompt(finding, retriever.retrieve(finding))
            records.append(
                PromptRecord(
                    axe_rule=case["axe_rule"],
                    act_testcase_id=case["act_testcase_id"],
                    referent=finding.referent,
                    prompt=prompt,
                )
            )
    scoped_ids = {c["act_testcase_id"] for c in scoped}
    scoped_ids |= {m["act_testcase_id"] for m in manifest["honest_misses"] if m["rule_name"] in RULE_TO_AXE}
    return records, scoped_ids


def run_dry_gate() -> DryGateResult:
    """The live gate: assemble every scoped prompt (no model), read the frozen baseline, run the four
    checks, print the verdict. Invoke: `uv run python -m clearway.eval.dry_gate`."""
    from clearway.eval.act_gold import _EXPORT_SHA256
    from clearway.eval.offline_build import _CONFIG_ID, _REPORTS_DIR, _ollama_digest
    from clearway.llm import LocalLLMClient
    from clearway.retriever import build_default_retriever
    from clearway.scanner import AXE_VERSION

    baseline = json.loads((_REPORTS_DIR / "drafter_kappa_baseline.json").read_text())
    baseline_vec = json.loads((_REPORTS_DIR / "verdict_vector.json").read_text())
    baseline_ids = {c["act_testcase_id"] for c in baseline_vec["cases"]}

    records, scoped_ids = _assemble_records()

    drafter_model = LocalLLMClient().model
    live_env = {
        "drafter_model_digest": _ollama_digest(drafter_model),
        "axe_core_version": AXE_VERSION,
        "act_export_hash": _EXPORT_SHA256,
        "corpus_version": build_default_retriever().corpus_version,
        "config_id": _CONFIG_ID,
    }

    result = evaluate(
        records,
        scoped_ids=scoped_ids,
        baseline_ids=baseline_ids,
        live_env=live_env,
        baseline_env=_baseline_env(baseline),
    )

    print(f"\nDRY GATE: {'GREEN — safe to run' if result.green else 'RED — do NOT run'}")
    for name, fails in (
        ("referent verbatim", result.referent_failures),
        ("control byte-identical", result.control_failures),
        ("case set == 44", result.case_set_failures),
        ("env five fields", result.env_failures),
    ):
        print(f"  [{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"        - {f}")
    print(f"  distinct prompts by class (diagnostic): {result.distinct_prompts_by_class}")
    (_REPORTS_DIR / "referent_injection_dry_gate.json").write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"
    )
    return result


def main() -> None:
    raise SystemExit(0 if run_dry_gate().green else 1)


if __name__ == "__main__":
    main()
