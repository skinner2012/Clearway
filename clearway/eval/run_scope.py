"""What a run covers — the case set, the classes and the provenance — as a value a call site names.

Every module under `eval/` grew around one case set: the four descriptiveness classes the acceptance
gold scores, over the 44 cases the offline gate asserts. That scope was never written down. It lived in
a module-level manifest path, in a default argument, in `.get()` fallbacks and in a `continue`, and the
result was uniform: handed a *different* case set, nothing raised. Each path returned a well-formed,
plausible, empty answer — a schema-valid verdict vector over zero cases, a pooled endpoint reading
`b = 0 / c = 0`, an attribution reporting the prior run intact against a baseline it shares no case with,
a mechanism row rendering a class blank, and one set's pre-registered predictions scored into another
set's result. An empty answer and a negative answer are indistinguishable in a report, and only one of
them is true.

This module makes the scope explicit. A `RunScope` carries the four things a run cannot infer:

* **which cases** — the gold manifest and the root its `path` entries resolve against;
* **which classes** — the axe rules whose findings the run scores;
* **how a case mints findings** — the image sets must serve their vendored assets, and a scan without
  them mints the IDENTICAL finding over a picture that never arrived, which is the one failure in this
  repo that leaves no trace on a `Finding`;
* **what provenance it stamps** — the config and eval-set ids, so a run cannot freeze another run's
  identity into its own artifact.

`OutOfScope` is the refusal every one of those paths now raises. It lives here because the scope is what
was violated; the guards themselves stay in the modules that own the arithmetic.

**The image config id departs from the `m1-single@1` precedent deliberately.** That literal carries a
milestone label into every artifact it stamps, which this repo's own rule forbids; the frozen ones cannot
be rewritten, but the precedent stops here. `single-multimodal@1` names what it actually identifies — one
model, no routing, with the image channel — and carries no ticket bookkeeping.

Two decisions recorded here rather than left to be re-derived, because a later report has to state both:

1. **The image runs are scored outside `referent_injection_score.score_run`.** It refuses fewer than two
   passes and its endpoint is a paired κ against a frozen baseline; the image endpoint is neither.
2. **The image runs have no pre-flight gate.** `dry_gate` is pinned to the acceptance case set and to the
   referent blocks, and is not generalised — so no gate ran, and that is stated rather than implied.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clearway.eval.act_gold import _ACT_GOLD, _EXPORT_SHA256, _MANIFEST, RULE_TO_AXE
from clearway.eval.act_gold import _minting_findings as _acceptance_minting_findings
from clearway.eval.act_image_gold import MANIFEST as _IMAGE_LEAKY_MANIFEST
from clearway.eval.act_image_gold import _minting_findings as _image_minting_findings
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE
from clearway.eval.image_opaque import MANIFEST as _IMAGE_OPAQUE_MANIFEST
from clearway.eval.image_opaque import SET_ID as OPAQUE_EVAL_SET_ID
from clearway.eval.image_reachability import ACT_IMAGE, IMAGE_AXE_RULE
from clearway.eval.image_reachability import SET_ID as _IMAGE_LEAKY_SET_ID
from clearway.scanner import AXE_VERSION
from clearway.schemas.models import Finding

# The acceptance pipeline's frozen identity: the SAME single-model config the orchestrator runs (one
# model, no routing), over a held-out set that gets its own id, distinct from every dev fixture set.
# Every already-frozen run carries these two strings and the dry gate's environment check compares a
# live run against them, so moving either turns the gate red on runs that cannot be re-run.
ACCEPTANCE_CONFIG_ID = "m1-single@1"
ACCEPTANCE_EVAL_SET_ID = "act-acceptance@1"

# The image pipeline: the same single model at the same temperature, with the image channel wired in.
IMAGE_CONFIG_ID = "single-multimodal@1"

# The derived set's id is now the builder's own (`OPAQUE_EVAL_SET_ID`, imported above) rather than a
# literal reserved here — the same treatment the vendored set gets. It is read, never restated: an id
# spelled in two places can be corrected in one of them.

# The classes the referent fix treats — the pool the primary endpoint runs over. `document-title` is
# measured (secondary, on mechanism) but is not in the pool: its ceiling cannot clear alpha, so pooling
# it in would only drag the primary endpoint it can never help. ONE definition, imported by both modules
# that test it: it was declared twice, and a pool declared twice can be corrected in one place and stay
# wrong in the other with nothing to show for it but a p-value.
POOLED_AXE_RULES = ("label", "link-name")


class OutOfScope(ValueError):
    """Work asked of a scope that does not cover it — refused, because the alternative is an empty answer.

    Every path this is raised from used to return something: zero grouped cases, zero discordant pairs,
    an empty id list, a blank mechanism cell. None of those is distinguishable in a report from a real
    measurement that came out zero, which is why the refusal is loud rather than defaulted.
    """


def _image_minting(case_path: Path, axe_rule: str) -> list[Finding]:
    """The image scopes' minting adapter: the asset tree is threaded by construction, never passed in.

    The axe rule is checked rather than used, because there is exactly one rule that mints a judgment
    finding on an image and a caller asking for another has the wrong scope, not the wrong argument.
    """
    if axe_rule != IMAGE_AXE_RULE:
        raise OutOfScope(
            f"the image scope mints {IMAGE_AXE_RULE!r} findings only, not {axe_rule!r} — a text class "
            "asked of an image scope means the case set and the class set have come apart"
        )
    return _image_minting_findings(case_path)


@dataclass(frozen=True)
class RunScope:
    """One run's case set, class set, minting rule and provenance — everything a run cannot infer.

    `manifest` is the gold manifest the cases come from and `root` is what each case's `path` resolves
    against; `axe_rules` are the classes whose findings the run scores. `carries_honest_misses` is
    declared rather than probed: a manifest with no honest-miss list and one whose list is empty read
    identically through a `.get(..., [])`, and only the first is a set that never had any.
    """

    scope_id: str
    manifest: Path
    root: Path
    axe_rules: tuple[str, ...]
    config_id: str
    eval_set_id: str
    carries_honest_misses: bool
    minting_findings: Callable[[Path, str], list[Finding]]

    def provenance(
        self,
        *,
        run_ids: Sequence[str],
        corpus_version: str,
        drafter_model: str,
        drafter_model_digest: str,
        created_at: str,
    ) -> dict[str, Any]:
        """The reproducibility header a pass artifact carries, with this scope's identity on it.

        The config and eval-set ids come from the scope rather than from the builder's module, which is
        what let an image pass stamp the acceptance run's identity into its own artifact. The axe-core
        version and the ACT export hash are global to the vendored gold and are read from it."""
        return {
            "run_ids": list(run_ids),
            "config_id": self.config_id,
            "eval_set_id": self.eval_set_id,
            "corpus_version": corpus_version,
            "drafter_model": drafter_model,
            "drafter_model_digest": drafter_model_digest,
            "axe_core_version": AXE_VERSION,
            "act_export_hash": _EXPORT_SHA256,
            "created_at": created_at,
        }


ACCEPTANCE = RunScope(
    scope_id="acceptance",
    manifest=_MANIFEST,
    root=_ACT_GOLD,
    axe_rules=tuple(sorted(set(RULE_TO_AXE.values()))),
    config_id=ACCEPTANCE_CONFIG_ID,
    eval_set_id=ACCEPTANCE_EVAL_SET_ID,
    carries_honest_misses=True,
    minting_findings=_acceptance_minting_findings,
)

IMAGE_LEAKY = RunScope(
    scope_id="image-leaky",
    manifest=_IMAGE_LEAKY_MANIFEST,
    root=ACT_IMAGE,
    axe_rules=(IMAGE_AXE_RULE,),
    config_id=IMAGE_CONFIG_ID,
    eval_set_id=_IMAGE_LEAKY_SET_ID,
    carries_honest_misses=False,
    minting_findings=_image_minting,
)

# The same seven cases with every path cue ablated. A separate scope rather than a flag on the one
# above: the two sets are different bytes under different ids, and a run that mixed them would read as
# one condition while being two.
IMAGE_OPAQUE = RunScope(
    scope_id="image-opaque",
    manifest=_IMAGE_OPAQUE_MANIFEST,
    root=ACT_IMAGE_OPAQUE,
    axe_rules=(IMAGE_AXE_RULE,),
    config_id=IMAGE_CONFIG_ID,
    eval_set_id=OPAQUE_EVAL_SET_ID,
    carries_honest_misses=False,
    minting_findings=_image_minting,
)


# Every scope this repo defines — the corpus a new guard's blast radius is measured over.
#
# It exists so "the whole scoped corpus" is a named value rather than a list re-derived by each
# measurement, and so a scope added later joins the count by being declared here rather than by being
# remembered. A guard counted only over the cases it was designed to fire on is not measured.
ALL_SCOPES: tuple[RunScope, ...] = (ACCEPTANCE, IMAGE_LEAKY, IMAGE_OPAQUE)


def _manifest_of(scope: RunScope) -> dict[str, Any]:
    return dict(json.loads(scope.manifest.read_text()))


def cases_for(scope: RunScope) -> list[dict[str, Any]]:
    """The manifest cases this scope covers — the drafting work list, selected by the named scope.

    A scope that selects nothing is refused: an empty work list produces a pass artifact with no cases,
    which every downstream scorer reads as a run that happened."""
    cases = [c for c in _manifest_of(scope)["cases"] if c["axe_rule"] in scope.axe_rules]
    if not cases:
        raise OutOfScope(
            f"scope {scope.scope_id!r} selects no case from {scope.manifest.name} — its classes are "
            f"{list(scope.axe_rules)}. An empty work list drafts nothing and freezes an artifact that "
            "reads as a completed run over zero cases."
        )
    return cases


def honest_misses_for(scope: RunScope) -> list[dict[str, Any]]:
    """The scope's honest misses — cases the gold labels but the scanner never minted a finding for.

    Empty for a scope that declares it carries none, which is not the same as a manifest whose list
    happens to be empty; a scope that declares it carries them and has none is a drift, not a fact."""
    if not scope.carries_honest_misses:
        return []
    return [m for m in _manifest_of(scope)["honest_misses"] if m["axe_rule"] in scope.axe_rules]


def assert_pooled_classes_present(present: set[str], pooled: tuple[str, ...] = POOLED_AXE_RULES) -> None:
    """Refuse a pooled endpoint over classes the run does not contain.

    Summing discordant pairs over absent classes yields `b = 0, c = 0` and a p of 1.0 — the arithmetic
    of a run that moved nothing, reported for a run that was never in the pool at all."""
    if not present & set(pooled):
        raise OutOfScope(
            f"no pooled class present: the pooled endpoint is defined over {list(pooled)} and this run "
            f"carries {sorted(present)}. Pooling here would report b = 0, c = 0 — indistinguishable "
            "from a run that moved nothing."
        )
