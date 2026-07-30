"""The judge-comparison pre-flight record: the facts that can redirect the run, settled before a call.

Four things decide whether the comparison can be run as designed, and all four are cheap enough to
establish first — which is the whole point, because the expensive half is a cloud judge replayed three
times per configuration. **Nothing here calls a model.** A provider model *listing* is metadata: it
runs no inference, emits no tokens and bills nothing, and it is the only network access this module
makes. Every count is read off a frozen run artifact on disk.

The four facts:

1. **Is the pinned judge snapshot still addressable on the account?** A snapshot that has been retired
   would force a model change into the same run as the structural change, and the two would be
   inseparable afterwards. So this is a stop-loss, not a diagnostic.
2. **Do the earlier passes still carry their PER-FINDING judge output?** An aggregate confusion matrix
   cannot be re-scored, re-joined or re-partitioned; the per-draft booleans can. What survives decides
   whether an earlier baseline is replayable at all.
3. **What reasoning effort would the judge actually run at?** It is half of `judge_version`, so it has
   to be held fixed across configurations, and it resolves through an environment variable that a
   checkout does not necessarily set.
4. **The call budget**, computed from the frozen artifact rather than estimated — because the mutation
   calls outnumber the natural ones and an estimate that counts only the natural pass understates the
   run by a multiple.

**A failed lookup is not an answer.** `account_model_ids` raises when the listing cannot be fetched,
rather than degrading to "not available": an unreachable provider and a retired snapshot are the same
bytes to a caller that swallows the error, and only one of them should stop a milestone. The same
discipline the scope refusals follow — an empty answer and a negative answer must not be
indistinguishable in a record.

Invoke: `uv run --env-file .env python -m clearway.eval.judge_preflight`
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.eval.stats import COLLAPSE_RULE, is_flag
from clearway.schemas.models import Conformance

# The provider's model-listing endpoint — metadata only. Named here so the record can state exactly
# what established availability, and so a test can point it somewhere else.
MODELS_ENDPOINT = "https://api.openai.com/v1/models"

# The variables that move the judge's provider off the default host. The cloud client calls
# `litellm.responses(model="openai/…")`, and that route honours these — so a listing read from the
# hardcoded host above would answer for a provider the judge never reaches. Checked, not assumed: the
# stop-loss has to interrogate the same route it guards, or it can report a snapshot as addressable on
# a host that is not the one about to be billed.
BASE_URL_ENV: tuple[str, ...] = ("OPENAI_BASE_URL", "OPENAI_API_BASE")

# The per-finding judge output an anchored pass writes onto each draft record (`offline_build`). Their
# presence is what makes an earlier pass replayable; the aggregate confusion matrix is not.
JUDGE_ROW_FIELDS: tuple[str, ...] = (
    "judge_conformance_correct",
    "judge_citation_correct",
    "judge_verdict",
)

# Passes per configuration — the repeat count a non-bit-reproducible judge needs before any one
# configuration's verdict may be read as more than a single draw.
DEFAULT_PASSES = 3

# ACT's gold outcome for a case that genuinely fails the rule. The collapse in `stats` maps the four
# drafted verdicts onto this binary axis.
_GOLD_FAILED = "failed"


class SnapshotListingUnavailable(RuntimeError):
    """The model listing could not be read, so snapshot availability is UNKNOWN — not False.

    Raised rather than defaulted: a missing key, a proxy error and a retired snapshot all produce "the
    id is not in the list I have", and treating that as a retirement would stop a milestone over a
    network hiccup — or, worse, let a genuinely retired pin read as fine on a cached success.
    """


def provider_route() -> dict[str, str | None]:
    """Where the judge's provider actually points right now, and the listing endpoint that follows.

    Pure environment reading — no request. Recorded beside the availability answer because the two are
    only the same question while no override is set: point `OPENAI_BASE_URL` at a local proxy and the
    default host's listing describes a provider the judge will never call.
    """
    for name in BASE_URL_ENV:
        base = os.getenv(name)
        if base:
            return {
                "base_url_override": base.rstrip("/"),
                "base_url_override_source": name,
                "endpoint": f"{base.rstrip('/')}/models",
            }
    return {"base_url_override": None, "base_url_override_source": None, "endpoint": MODELS_ENDPOINT}


def account_model_ids(
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    timeout_s: float = 15.0,
) -> tuple[str, ...]:
    """Every model id the account can address, from the provider's LISTING — no inference, no tokens.

    The key comes from `OPENAI_API_KEY`, the same variable the cloud client's provider reads; it is
    never returned or recorded. The endpoint defaults to whatever `provider_route` resolves, so the
    listing is read from the host the judge would be billed on rather than from a constant. Raises
    `SnapshotListingUnavailable` on anything that stops the listing from being read, so an unanswered
    question never records itself as a negative answer.
    """
    endpoint = endpoint or str(provider_route()["endpoint"])
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise SnapshotListingUnavailable(
            "OPENAI_API_KEY is unset, so the account's model listing cannot be read. That leaves "
            "snapshot availability UNKNOWN, which is not the same as unavailable — run with "
            "`--env-file .env` rather than reading the absence as a retired pin."
        )
    request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 — every failure mode is the same unknown
        raise SnapshotListingUnavailable(
            f"could not read the model listing at {endpoint}: {type(exc).__name__}: {exc}. Snapshot "
            "availability is UNKNOWN, not False."
        ) from exc
    return tuple(sorted(str(m["id"]) for m in payload["data"]))


def snapshot_availability(
    model: str, listed_ids: tuple[str, ...], *, route: dict[str, str | None] | None = None
) -> dict[str, Any]:
    """Whether `model` appears in a listing that was successfully read — pure, so it is testable.

    `listed_model_count` rides along because "absent from a list of 125" and "absent from a list of 0"
    are different claims, and only the first is evidence. It is deliberately OUTSIDE the record's
    freeze check (`_VOLATILE_PATHS`) — it describes the provider's catalogue on the day, not this
    record. The route is recorded rather than described, so a later reader can see which host answered
    and whether an override was in force when it did.
    """
    resolved = route or provider_route()
    return {
        "model": model,
        "available": model in listed_ids,
        "listed_model_count": len(listed_ids),
        "source": f"GET {resolved['endpoint']} (model listing — metadata, no inference)",
        "base_url_override": resolved["base_url_override"],
        "base_url_override_source": resolved["base_url_override_source"],
    }


def judge_pins() -> dict[str, str]:
    """The judge provenance a run would carry right now: snapshot, effective reasoning effort, and the
    `judge_version` those two produce with the current prompt.

    Read by CONSTRUCTING the real client and the real judge — neither makes a call — rather than by
    restating the defaults here. A second copy of a pin is a copy that can be right while the code is
    wrong, and the effective effort is not a constant anyway: it resolves from `CLEARWAY_JUDGE_EFFORT`
    first and the client's code default only after, so a record that quoted the default would describe
    a machine other than the one the run happens on.
    """
    from clearway.judge import Judge
    from clearway.llm import CloudLLMClient, LocalLLMClient

    client = CloudLLMClient()
    judge = Judge(client, drafter_model=LocalLLMClient().model)
    return {
        "judge_model": client.model,
        "reasoning_effort": client.reasoning_effort,
        "judge_version": judge.judge_version,
        "reasoning_effort_source": ("CLEARWAY_JUDGE_EFFORT" if os.getenv("CLEARWAY_JUDGE_EFFORT") else "code default"),
    }


def judge_row_retention(artifact: dict[str, Any]) -> dict[str, Any]:
    """How much per-finding judge output one frozen pass retained.

    A pass whose drafts carry all of `JUDGE_ROW_FIELDS` can be re-scored, re-joined and re-partitioned
    offline; a pass that kept only a summary cannot be replayed at all, whatever its headline numbers
    say. `partial` is called out separately because a pass that carries the fields on *some* rows is
    neither replayable nor honestly summarisable, and it would otherwise hide inside "present".
    """
    rows = [d for c in artifact["cases"] for d in c["drafts"]]
    complete = [r for r in rows if all(f in r for f in JUDGE_ROW_FIELDS)]
    any_field = [r for r in rows if any(f in r for f in JUDGE_ROW_FIELDS)]
    return {
        "drafts": len(rows),
        "rows_with_all_judge_fields": len(complete),
        "partial_rows": len(any_field) - len(complete),
        "replayable": bool(rows) and len(complete) == len(rows),
        "fields": list(JUDGE_ROW_FIELDS),
    }


def conformance_correct(conformance: Conformance, expected: str, *, partial_flags: bool = True) -> bool:
    """Is this drafted verdict RIGHT against ACT gold, under the repo's four-value → binary collapse?

    ACT says only whether the case fails the rule, so the drafted verdict is collapsed with `is_flag`
    and compared to that. This is the same predicate the acceptance scorer applies as `act_correct`
    (`eval/offline.py`) and the same one the acceptance builder gates the conformance-flip mutation on
    (`eval/offline_build.py`) — stated once here for the pre-flight count, and pinned to that existing
    implementation by test rather than by assertion, so the budget cannot be computed under a rule the
    run will not be scored by.
    """
    return is_flag(conformance, partial_flags=partial_flags) == (expected == _GOLD_FAILED)


@dataclass(frozen=True)
class CallBudget:
    """The judge calls each configuration costs, derived from one frozen drafter pass.

    `natural_drafts` is the minted-finding count — the calls a pass would make if the natural draft
    were the only thing judged. It is not, on the anchored side: the injected-versus-real gap is
    measured there, every mutation is its own call, and the two mutations have DIFFERENT denominators.
    The SC swap applies to every draft; the conformance flip applies only to a draft that is already
    conformance-correct, because flipping a wrong verdict can land on the right one and the mutation
    would no longer be known-wrong.

    The blind side runs one call per finding and no mutations at all: a judge that never reads the
    draft makes a byte-identical call whether the draft was mutated or not, so a mutation pass there
    would spend money to re-derive arithmetic.

    ⚠️ Every total here is a FLOOR, never the amount that will be spent. A judge call retries on an
    unparseable response, and a retry leaves nothing on disk — the artifact records one row whether the
    verdict came back first try or second. So the counts below are what a run costs if no response is
    ever off-schema, and `max_attempts_per_call` is what turns each into its ceiling.
    """

    natural_drafts: int
    conformance_correct_drafts: int
    passes: int = DEFAULT_PASSES
    max_attempts_per_call: int = 2

    def __post_init__(self) -> None:
        if self.natural_drafts <= 0:
            raise ValueError("a call budget over zero drafts is not a budget — check the frozen artifact path")
        if not 0 <= self.conformance_correct_drafts <= self.natural_drafts:
            raise ValueError(
                f"{self.conformance_correct_drafts} conformance-correct drafts out of {self.natural_drafts}"
            )
        if self.passes < 1:
            raise ValueError("a configuration runs at least one pass")
        if self.max_attempts_per_call < 1:
            raise ValueError("a call is at least one attempt")

    @property
    def conformance_correct_share(self) -> float:
        """The share of drafts the conformance flip applies to — what makes the anchored side's cost
        depend on the drafter's accuracy rather than on the case count alone."""
        return self.conformance_correct_drafts / self.natural_drafts

    @property
    def anchored_per_pass(self) -> int:
        """natural + one SC swap per draft + one conformance flip per conformance-correct draft."""
        return 2 * self.natural_drafts + self.conformance_correct_drafts

    @property
    def blind_per_pass(self) -> int:
        return self.natural_drafts

    @property
    def anchored_total(self) -> int:
        return self.passes * self.anchored_per_pass

    @property
    def blind_total(self) -> int:
        return self.passes * self.blind_per_pass

    @property
    def grand_total(self) -> int:
        """The floor: every call succeeding on its first attempt. Never quote this as the total."""
        return self.anchored_total + self.blind_total

    @property
    def grand_total_ceiling(self) -> int:
        """The floor times the attempts a single call is allowed — the worst case, if every response
        came back off-schema once. The true figure sits between the two and is not observable on disk."""
        return self.grand_total * self.max_attempts_per_call

    def to_dict(self) -> dict[str, Any]:
        return {
            "natural_drafts": self.natural_drafts,
            "conformance_correct_drafts": self.conformance_correct_drafts,
            "conformance_correct_share": round(self.conformance_correct_share, 4),
            "passes_per_configuration": self.passes,
            "anchored_per_pass": self.anchored_per_pass,
            "anchored_total": self.anchored_total,
            "blind_per_pass": self.blind_per_pass,
            "blind_total": self.blind_total,
            "grand_total_is_a_floor": self.grand_total,
            "max_attempts_per_call": self.max_attempts_per_call,
            "grand_total_ceiling": self.grand_total_ceiling,
            "retry_visibility": (
                "a retried call leaves no trace in the run artifact — one row is written whether the "
                "verdict parsed on the first attempt or a later one, so the spend between floor and "
                "ceiling cannot be recovered afterwards and has to be read off the provider's usage"
            ),
            "conformance_collapse_rule": COLLAPSE_RULE,
            "arithmetic": (
                f"anchored = {self.passes} × ({self.natural_drafts} natural + {self.natural_drafts} SC-swap + "
                f"{self.conformance_correct_drafts} conformance-flip) = {self.anchored_total}; "
                f"blind = {self.passes} × {self.natural_drafts} = {self.blind_total}; "
                f"floor = {self.grand_total}; ceiling = {self.grand_total} × "
                f"{self.max_attempts_per_call} attempts = {self.grand_total_ceiling}"
            ),
        }


def judge_attempts_per_call() -> int:
    """How many times one judge call may reach the model, read from `Judge`'s declared default.

    Derived rather than restated: the judge retries an unparseable response, and neither harness that
    constructs it passes `retries`, so the constructor default IS the effective value. A copy of it here
    would be a number that can stay right while the judge changes underneath it.
    """
    import inspect

    from clearway.judge import Judge

    return int(inspect.signature(Judge.__init__).parameters["retries"].default) + 1


def call_budget(
    artifact: dict[str, Any], *, passes: int = DEFAULT_PASSES, max_attempts_per_call: int | None = None
) -> CallBudget:
    """The budget, counted off a frozen drafter pass — the natural drafts and how many of them are
    conformance-correct against the gold outcome their own case carries."""
    natural = 0
    correct = 0
    for case in artifact["cases"]:
        for draft in case["drafts"]:
            natural += 1
            correct += conformance_correct(Conformance(draft["conformance"]), case["expected"])
    return CallBudget(
        natural_drafts=natural,
        conformance_correct_drafts=correct,
        passes=passes,
        max_attempts_per_call=max_attempts_per_call if max_attempts_per_call is not None else judge_attempts_per_call(),
    )


# What a rebuild is allowed to move without that reading as an edit, named by PATH rather than by
# top-level key — one of the three sits two levels down.
#
#   * `created_at` — the wall clock.
#   * `reproducible_digest` — the digest computed over everything else.
#   * `judge_snapshot.listed_model_count` — ⚠️ the one that is not obvious, and the one this list exists
#     for. It is read LIVE from the provider's catalogue, so it moves whenever the provider adds or
#     retires any model, none of which is a fact about this record. Inside the digest it made a re-run
#     after a catalogue change indistinguishable from an edit — and it had already drifted once.
#
# The count stays IN the record, because "absent from a list of 126" and "absent from a list of 0" are
# different claims and only the first is evidence. What it is taken out of is the FREEZE CHECK: the
# answer rests on the id being *present*, which is `available`, and that stays inside the digest — so a
# snapshot that genuinely disappears still moves it.
_VOLATILE_PATHS: tuple[tuple[str, ...], ...] = (
    ("created_at",),
    ("reproducible_digest",),
    ("judge_snapshot", "listed_model_count"),
)


def _without_volatile(record: dict[str, Any]) -> dict[str, Any]:
    """The record with every declared volatile path removed — the part a rebuild must reproduce."""
    stable: dict[str, Any] = json.loads(json.dumps(record, ensure_ascii=False))
    for path in _VOLATILE_PATHS:
        node: Any = stable
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        else:
            node.pop(path[-1], None)
    return stable


def record_digest(record: dict[str, Any]) -> str:
    """sha256 over the record minus the volatile paths — the part a rebuild must reproduce.

    This is what a freeze test pins. Without it the only available check is the file's byte digest, which
    a fresh `created_at` breaks on every rebuild, so a genuine change and a re-run would look alike. The
    same argument is why the provider's live catalogue size is excluded: a digest that moves for a reason
    outside the record cannot answer "did this record change?" either.
    """
    stable = json.dumps(_without_volatile(record), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(stable.encode()).hexdigest()


def build_record(
    *,
    frozen_artifact: Path,
    prior_passes: dict[str, Path],
    listed_ids: tuple[str, ...],
    pins: dict[str, str],
    created_at: str,
    passes: int = DEFAULT_PASSES,
    route: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Assemble the pre-flight record. Pure given the listing and the pins, so the whole shape is
    testable without a network or an environment.

    The frozen artifact is recorded by content hash beside its path: the budget is a property of those
    bytes, and a path alone would let a re-frozen run silently inherit a budget computed for another.
    """
    artifact = json.loads(frozen_artifact.read_text())
    record: dict[str, Any] = {
        "created_at": created_at,
        "model_calls_spent": 0,
        "judge_snapshot": snapshot_availability(pins["judge_model"], listed_ids, route=route),
        "judge_pins": pins,
        "budget_source": {
            "path": frozen_artifact.name,
            "sha256": hashlib.sha256(frozen_artifact.read_bytes()).hexdigest(),
            "config_id": artifact["config_id"],
            "eval_set_id": artifact["eval_set_id"],
            "cases": len(artifact["cases"]),
        },
        "call_budget": call_budget(artifact, passes=passes).to_dict(),
        "prior_judge_rows": {
            name: judge_row_retention(json.loads(path.read_text())) for name, path in sorted(prior_passes.items())
        },
    }
    return {**record, "reproducible_digest": record_digest(record)}


def _report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_preflight.json"


def main() -> None:
    from clearway.eval.run_artifacts import CITATION_GROUNDING, acceptance_pass_paths, run_path

    # The pass the comparison replays, and the earlier passes whose judge output is being audited — both
    # named through `run_artifacts`, which owns every artifact filename in this tree.
    frozen = run_path(CITATION_GROUNDING, 1)
    prior = {p.name: p for p in acceptance_pass_paths()}
    pins = judge_pins()
    route = provider_route()
    record = build_record(
        frozen_artifact=frozen,
        prior_passes=prior,
        listed_ids=account_model_ids(endpoint=str(route["endpoint"])),
        pins=pins,
        created_at=datetime.now(timezone.utc).isoformat(),
        route=route,
    )

    snapshot = record["judge_snapshot"]
    budget = record["call_budget"]
    print(f"judge snapshot {snapshot['model']}: {'AVAILABLE' if snapshot['available'] else 'NOT AVAILABLE'}")
    print(f"  (listing carried {snapshot['listed_model_count']} ids from {snapshot['source'].split()[1]})")
    if snapshot["base_url_override"]:
        print(f"  ⚠ provider host overridden by {snapshot['base_url_override_source']}")
    print(f"judge pins: {pins['judge_version']} (effort from {pins['reasoning_effort_source']})")
    print(f"budget: {budget['arithmetic']}")
    print(f"  ⚠ {budget['grand_total_is_a_floor']} is a FLOOR — retries are invisible on disk")
    for name, retention in record["prior_judge_rows"].items():
        state = "replayable" if retention["replayable"] else "NOT replayable"
        print(f"  {name}: {retention['rows_with_all_judge_fields']}/{retention['drafts']} judged rows — {state}")

    path = _report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {path.relative_to(Path.cwd())} — 0 model calls")
    print(
        f"reproducible digest {record['reproducible_digest'][:12]}… (everything but the timestamp and "
        "the provider's live catalogue size)"
    )
    raise SystemExit(0 if snapshot["available"] else 1)


if __name__ == "__main__":
    main()
