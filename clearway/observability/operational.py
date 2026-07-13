"""Observability — operational LLM + pipeline metrics (ARCHITECTURE §4.5, T2).

Two families, recorded from `orchestrator/machine.py` *during* the run (unlike the trust gauges in
`metrics.py`, which are set from the finished `EvalReport`):

- **GenAI semantic-convention LLM metrics** — `gen_ai.client.operation.duration` (seconds) and
  `gen_ai.client.token.usage` (tokens, split by `gen_ai.token.type` input/output), tagged by
  `gen_ai.request.model` so the future cloud-vs-local comparison (M4) is data-ready (cost is ~0 for
  local Ollama but the tokens/latency are real). The semconv is still Development-stage
  (ARCHITECTURE §4.5): the exact metric/attribute names were verified against the installed SDK,
  and `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` is set.
- **Custom pipeline metrics** — `pipeline_step_retries` / `pipeline_failures` (counters; the
  Prometheus exporter suffixes monotonic counters `_total`) and `pipeline_step_duration`
  (histogram, seconds), each tagged by pipeline `step`.
- **MCP client-call metric** — `mcp.client.operation.duration` (seconds) for the opt-in over-MCP
  retrieval path, tagged `mcp.method.name` + `gen_ai.tool.name` and, on failure, `error.type` (so
  the dashboard derives an error rate from the same series). The matching span-attribute vocabulary
  (`mcp_span_attributes`) lives here too, so every MCP/GenAI semconv name is defined in one module;
  names were verified against the installed SDK, same as the GenAI ones.

Like the trust gauges, every instrument is a module singleton created in
`setup_operational_metrics()`; a recording call before setup is a cheap no-op, so offline tests
need no MeterProvider. Production leaves `provider=None` so instruments export through the global
provider `metrics.setup_metrics()` installs; tests pass their own provider to read the data back.
"""

from __future__ import annotations

import os

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, MeterProvider
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_TOKEN_TYPE,
    GEN_AI_TOOL_NAME,
    GenAiOperationNameValues,
    GenAiTokenTypeValues,
)
from opentelemetry.semconv._incubating.attributes.mcp_attributes import (
    MCP_METHOD_NAME,
    MCP_SESSION_ID,
)
from opentelemetry.semconv._incubating.attributes.network_attributes import (
    NETWORK_PROTOCOL_NAME,
    NETWORK_TRANSPORT,
    NetworkTransportValues,
)
from opentelemetry.semconv._incubating.metrics.gen_ai_metrics import (
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_TOKEN_USAGE,
)
from opentelemetry.semconv._incubating.metrics.mcp_metrics import MCP_CLIENT_OPERATION_DURATION
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from clearway.llm import LLMUsage

_llm_duration: Histogram | None = None
_llm_tokens: Histogram | None = None
_step_retries: Counter | None = None
_step_failures: Counter | None = None
_step_duration: Histogram | None = None
_mcp_duration: Histogram | None = None


def setup_operational_metrics(provider: MeterProvider | None = None) -> None:
    """Create the operational instruments (idempotent). `provider=None` uses the global MeterProvider
    (production, installed by `setup_metrics()`); tests pass their own to read the data back."""
    global _llm_duration, _llm_tokens, _step_retries, _step_failures, _step_duration, _mcp_duration
    if _llm_duration is not None:
        return
    # Development-stage semconv: opt in so any auto-instrumentation agrees with our hand-rolled names.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
    meter = (provider or metrics.get_meter_provider()).get_meter("clearway.pipeline")
    _llm_duration = meter.create_histogram(
        GEN_AI_CLIENT_OPERATION_DURATION, unit="s", description="Duration of one LLM call."
    )
    _llm_tokens = meter.create_histogram(
        GEN_AI_CLIENT_TOKEN_USAGE, unit="{token}", description="Tokens consumed per LLM call, split by input/output."
    )
    # No `_total` in the instrument name: the Prometheus exporter appends it for monotonic counters.
    _step_retries = meter.create_counter(
        "pipeline_step_retries", description="Retry attempts beyond the first, per pipeline step."
    )
    _step_failures = meter.create_counter(
        "pipeline_failures", description="Steps that exhausted their retries and failed, per step."
    )
    # No unit on purpose (repo convention: a unit would suffix the Prometheus series name).
    _step_duration = meter.create_histogram(
        "pipeline_step_duration", description="Wall-clock seconds for one pipeline step (including retries)."
    )
    _mcp_duration = meter.create_histogram(
        MCP_CLIENT_OPERATION_DURATION, unit="s", description="Duration of one MCP tool call, client side."
    )


def record_llm_call(*, model: str, usage: LLMUsage) -> None:
    """Emit GenAI-semconv LLM metrics for one call. No-op if setup hasn't run; each field is skipped
    when absent (a fake/offline client reports all-`None`)."""
    if _llm_duration is None or _llm_tokens is None:
        return
    attrs = {GEN_AI_OPERATION_NAME: GenAiOperationNameValues.CHAT.value, GEN_AI_REQUEST_MODEL: model}
    if usage.latency_ms is not None:
        _llm_duration.record(usage.latency_ms / 1000.0, attrs)
    if usage.tokens_in is not None:
        _llm_tokens.record(usage.tokens_in, {**attrs, GEN_AI_TOKEN_TYPE: GenAiTokenTypeValues.INPUT.value})
    if usage.tokens_out is not None:
        _llm_tokens.record(usage.tokens_out, {**attrs, GEN_AI_TOKEN_TYPE: GenAiTokenTypeValues.COMPLETION.value})


def record_step(*, step: str, attempts: int, failed: bool, duration_s: float) -> None:
    """Emit the custom pipeline metrics for one executed (non-replayed) step. No-op before setup."""
    if _step_duration is None or _step_retries is None or _step_failures is None:
        return
    labels = {"step": step}
    _step_duration.record(duration_s, labels)
    retries = max(0, attempts - 1)
    if retries:
        _step_retries.add(retries, labels)
    if failed:
        _step_failures.add(1, labels)


# The one MCP method we invoke: a streamable-HTTP tool call. Constant, so it lives beside the metric.
_MCP_TOOLS_CALL = "tools/call"


def mcp_span_attributes(*, tool: str, session_id: str | None = None) -> dict[str, str]:
    """The MCP-semconv attribute set for a `tools/call` span, set on both the client span and the
    server child span so the cross-boundary call is self-describing. Names verified against the
    installed semconv (`mcp.*`, `gen_ai.tool.name`, `network.*`); `mcp.session.id` is included only
    when known (the client learns it after `initialize`)."""
    attrs = {
        MCP_METHOD_NAME: _MCP_TOOLS_CALL,
        GEN_AI_TOOL_NAME: tool,
        NETWORK_TRANSPORT: NetworkTransportValues.TCP.value,
        NETWORK_PROTOCOL_NAME: "http",
    }
    if session_id is not None:
        attrs[MCP_SESSION_ID] = session_id
    return attrs


def record_mcp_call(*, tool: str, duration_s: float, error_type: str | None = None) -> None:
    """Emit the MCP client-call duration metric (`mcp.client.operation.duration`). No-op before setup.
    `error_type` (the exception class name) is stamped on failure so the dashboard derives an error
    rate from the same series (semconv `error.type`)."""
    if _mcp_duration is None:
        return
    attrs = {MCP_METHOD_NAME: _MCP_TOOLS_CALL, GEN_AI_TOOL_NAME: tool}
    if error_type is not None:
        attrs[ERROR_TYPE] = error_type
    _mcp_duration.record(duration_s, attrs)


def shutdown_operational_metrics() -> None:
    """Drop the instrument singletons so a later setup rebuilds them (mirrors `metrics.shutdown()`;
    the underlying MeterProvider is flushed/torn down by `metrics.shutdown()`, which owns it)."""
    global _llm_duration, _llm_tokens, _step_retries, _step_failures, _step_duration, _mcp_duration
    _llm_duration = _llm_tokens = _step_retries = _step_failures = _step_duration = _mcp_duration = None
