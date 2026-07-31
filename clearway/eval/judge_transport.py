"""The paid seam both judge configurations run through: the ledger, the recording client, the cost.

Everything here sits **below** the judge and is shared by every configuration that spends calls,
because none of it is about what a judge is asked — it is about what the transport did.

**Why below the judge, and not inside it.** `Judge.judge_prepared` and `BlindJudge.answer` return a
`JudgeResult` / a `BlindAnswer`, neither of which carries tokens, cost or latency: the `Completion.usage`
the client produced is dropped at that seam. Widening a production shape for an eval-only need was
rejected, so the usage is captured one layer down, by a client wrapper. **⚠️ The consequence is that
usage is per TRANSPORT CALL and cannot be attributed to a particular ask** — a retry is a second call on
the same prompt and neither judge reports which attempt succeeded. What that buys instead is better than
a join: the recorded call count is the count of asks *plus* every retry, so a retry budget is visible in
the aggregate rather than being the invisible gap between a floor and a ceiling.

**One copy, deliberately.** A second configuration reaching for its own ledger and its own recording
client is two implementations of the one thing whose correctness the spend depends on, and they would
drift at the first fix. The pieces that genuinely differ between configurations — the asks, the
responses, the scoring — live with each configuration; nothing here knows what a judge was asked.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from clearway.llm import Completion, ImagePart, LLMClient, LLMRequest, LLMUsage


class LedgerMismatch(RuntimeError):
    """A recorded response offered for a prompt it was not the answer to.

    Raised rather than ignored: a ledger is only a saving if replaying it is indistinguishable from
    having made the call. A row whose prompt digest does not match the ask about to be sent means the
    asks moved under the ledger — a re-scan, an edited frozen block, a changed rubric — and replaying
    it would silently fabricate a measurement out of answers to different questions.
    """


# ---------------------------------------------------------------------------------------------
# The ledger and the recording client
# ---------------------------------------------------------------------------------------------


@dataclass
class CallLedger:
    """Every transport call the measurement has made, appended the moment each one returns.

    Deliberately append-only JSONL rather than a rewritten JSON document: the file has to survive the
    process being killed between two paid calls, and a partial line is recoverable while a truncated
    re-serialization of the whole record is not.
    """

    path: Path
    rows: list[dict[str, Any]]

    @classmethod
    def open(cls, path: Path) -> CallLedger:
        rows: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return cls(path=path, rows=rows)

    def recorded(self, pass_index: int) -> list[dict[str, Any]]:
        """This pass's calls, in the order they were made."""
        return [row for row in self.rows if row["pass"] == pass_index]

    def append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows.append(row)


class RecordingJudgeClient:
    """An `LLMClient` that wraps another one, records what each call cost, and replays a ledger.

    It sits below the judge rather than inside it because the alternative is widening `JudgeResult`,
    a production shape under the contracts, with three fields only a measurement wants. The price of
    that choice is stated in the module docstring and in the artifact: usage is per transport call,
    so it cannot be attributed to a particular ask.
    """

    def __init__(self, inner: LLMClient, ledger: CallLedger, pass_index: int) -> None:
        self._inner = inner
        self._ledger = ledger
        self._pass = pass_index
        self._replay = ledger.recorded(pass_index)
        self._ordinal = 0
        self.spent = 0
        self.replayed = 0

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def reasoning_effort(self) -> str:
        effort = getattr(self._inner, "reasoning_effort", "")
        return str(effort)

    def complete_json(
        self, system: str, user: str, schema: type[BaseModel], image: ImagePart | None = None
    ) -> Completion:
        digest = LLMRequest.of(system, user, schema, image).prompt_sha256
        ordinal, self._ordinal = self._ordinal, self._ordinal + 1
        if ordinal < len(self._replay):
            row = self._replay[ordinal]
            if row["prompt_sha256"] != digest:
                raise LedgerMismatch(
                    f"ledger row {ordinal} of pass {self._pass} answers prompt {row['prompt_sha256'][:12]}… "
                    f"and the ask about to be sent is {digest[:12]}…. The asks have moved under the "
                    "ledger, so replaying it would answer a question that was never put. Delete the "
                    "ledger and re-run, or find what moved the prompt."
                )
            self.replayed += 1
            return Completion(row["content"], _usage_of(row))
        completion = self._inner.complete_json(system, user, schema, image)
        self.spent += 1
        self._ledger.append(
            {
                "pass": self._pass,
                "ordinal": ordinal,
                "prompt_sha256": digest,
                "content": completion.content,
                **_usage_row(completion.usage),
            }
        )
        return completion


def _usage_row(usage: LLMUsage) -> dict[str, Any]:
    return {
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
        "cost_usd": usage.cost_usd,
        "latency_ms": usage.latency_ms,
    }


def _usage_of(row: dict[str, Any]) -> LLMUsage:
    return LLMUsage(
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        cost_usd=row["cost_usd"],
        latency_ms=row["latency_ms"],
    )


def cost_block(transport: Sequence[dict[str, Any]], *, asks_made: int) -> dict[str, Any]:
    """What the calls cost and how long they took — per TRANSPORT CALL, which is not per ask.

    ⚠️ The count here is a floor for the whole spend, one layer tighter than the run artifact's: it
    counts every call this process put through the client seam, retries included, and cannot see a
    retry made inside the provider client below it. The provider's own usage page is the only place
    the true total lives.
    """
    latencies = [float(row["latency_ms"]) for row in transport if row["latency_ms"] is not None]
    costs = [float(row["cost_usd"]) for row in transport if row["cost_usd"] is not None]
    tokens_in = [int(row["tokens_in"]) for row in transport if row["tokens_in"] is not None]
    tokens_out = [int(row["tokens_out"]) for row in transport if row["tokens_out"] is not None]

    def _stat(values: list[float], name: str) -> dict[str, Any]:
        if not values:
            return {"n": 0, "note": f"no {name} was reported on any call"}
        return {
            "n": len(values),
            "total": round(sum(values), 6),
            "mean": round(statistics.fmean(values), 6),
            "median": round(statistics.median(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }

    return {
        "transport_calls": len(transport),
        "asks": asks_made,
        "calls_beyond_one_per_ask": len(transport) - asks_made,
        "calls_are_a_floor": (
            "Counted at the client seam, so every retry the judge made is included — which is one "
            "layer tighter than a count taken off the artifact, where a retried ask writes one row "
            "either way. It is still a floor: a retry inside the provider client is invisible here, "
            "and the real spend is read off the provider."
        ),
        "latency_ms": _stat(latencies, "latency"),
        "cost_usd": _stat(costs, "cost"),
        "cost_priced_on": f"{len(costs)} of {len(transport)} calls",
        "tokens_in": _stat([float(v) for v in tokens_in], "input token count"),
        "tokens_out": _stat([float(v) for v in tokens_out], "output token count"),
        "unit": (
            "per transport call, never per ask: usage is captured below the judge, and the judge does "
            "not report which of its attempts produced the verdict it returned"
        ),
        "pricing_source": (
            "⚠️ `cost_usd` is a LOCAL PRICE TABLE applied to the provider's reported token counts, not "
            "an amount anyone was billed: the client asks LiteLLM to price each response, and a table "
            "that is stale for a snapshot prices it wrongly while one that has never heard of it "
            "prices it not at all — which is what `cost_priced_on` counts. The token counts themselves "
            "are the provider's own, and the output count includes whatever reasoning tokens the "
            "effort setting bought. Latency is measured locally around the call, so it carries this "
            "machine's network path as well as the model's. Read the billed total off the provider."
        ),
    }


PAID_CALLS = "calls_that_bought_these_responses"
REPLAYED_CALLS = "calls_replayed_from_an_earlier_attempt"


def ledger_block(*, path: Path, paid: int, replayed: int) -> dict[str, Any]:
    """How the responses in this record were obtained — assembled here, never carried through verbatim.

    ⚠️ **Both counts describe the invocation that BOUGHT the responses, not the process that last wrote
    the file.** A re-derivation recomputes every field from those same responses and makes no call, so a
    block copied across unchanged would eventually describe a run nobody made. It is rebuilt from the
    two integers instead, which is also what keeps this note true when the note itself is edited.
    """
    return {
        "path": path.name,
        PAID_CALLS: paid,
        REPLAYED_CALLS: replayed,
        "note": (
            "⚠️ Both counts describe the invocation that BOUGHT the responses in this record, and "
            "neither ever describes the process that last wrote the file: a re-derivation "
            "(`--rederive`) recomputes every field from those same responses, makes no call at all, "
            "and reproduces these two unchanged. A run resumed from the ledger spends only what the "
            "ledger had not reached, so the two split the measurement between paid and replayed and "
            "their sum is `cost.transport_calls` — itself a floor."
        ),
    }
