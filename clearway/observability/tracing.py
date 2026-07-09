"""Observability — run/finding/step tracing via OTel spans (ARCHITECTURE §4.5, T2).

`setup_tracing()` wires a `TracerProvider` + OTLP/HTTP span exporter, pushing spans to the OTel
Collector's `traces` pipeline (which today just echoes them to the collector log via the `debug`
exporter — a real trace backend like Grafana Tempo is deferred, ARCHITECTURE §4.5). The
orchestrator (`machine.py`) emits spans through the OTel *API* (`trace.get_tracer`), which is a
no-op until this setup installs a provider — so the whole pipeline stays testable offline with no
stack running, exactly as the metric path does.

Same short-lived-CLI caveat as `metrics.py`: force-flush before the process exits or buffered
spans never leave — see `shutdown_tracing()`, which the CLI calls in a `finally`. The `Resource`
carries the same fixed `service.instance.id` so traces attribute to the one `clearway-cli` service.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_DEFAULT_ENDPOINT = "http://localhost:4318"

_provider: TracerProvider | None = None


def setup_tracing(endpoint: str | None = None) -> None:
    """Install a global OTLP/HTTP `TracerProvider` (idempotent). Must run *before* the run
    executes, since spans are produced during `execute()`, not recorded after the fact."""
    global _provider
    if _provider is not None:
        return
    base = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or _DEFAULT_ENDPOINT
    exporter = OTLPSpanExporter(endpoint=f"{base.rstrip('/')}/v1/traces")
    provider = TracerProvider(
        resource=Resource.create({"service.name": "clearway", "service.instance.id": "clearway-cli"}),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider


def shutdown_tracing() -> None:
    """Flush pending spans and tear down. MUST run before a short-lived process exits."""
    global _provider
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
        _provider = None
