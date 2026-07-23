"""The trust metrics actually land in Prometheus (stack-gated).

Integration tests against the real observability stack. They skip cleanly when the stack
isn't up (`docker compose up -d`), so the normal offline suite stays green. This is the
machine-checkable form of "the metric is visible on the panel": emit → Prometheus scrapes
the collector → query the Prometheus API → assert the value.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

import pytest

from clearway.observability import record_eval_report, record_rate, shutdown
from clearway.schemas.models import OnlineEvalMetrics, OnlineEvalReport, OracleRegime

_PROM = "http://localhost:9090"


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _query(expr: str) -> list[dict]:
    url = _PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=3) as resp:
        return json.load(resp)["data"]["result"]


stack_up = pytest.mark.skipif(
    not _http_ok(_PROM + "/-/ready"),
    reason="observability stack not running (docker compose up -d)",
)


@stack_up
def test_emitted_rate_reaches_prometheus() -> None:
    value = 0.123456
    record_rate(value, eval_set_id="pytest", config_id="pytest", oracle_regime="A-digital")
    shutdown()  # force-flush

    expr = 'citation_hallucination_rate{config_id="pytest",eval_set_id="pytest"}'
    result: list[dict] = []
    for _ in range(20):  # Prometheus scrapes every 5s; allow ~20s
        result = _query(expr)
        if result and abs(float(result[0]["value"][1]) - value) < 1e-9:
            break
        time.sleep(1)

    assert result, "metric never appeared in Prometheus"
    assert float(result[0]["value"][1]) == pytest.approx(value)


def _poll(expr: str, want: float) -> list[dict]:
    result: list[dict] = []
    for _ in range(20):  # Prometheus scrapes every 5s; allow ~20s
        result = _query(expr)
        if result and abs(float(result[0]["value"][1]) - want) < 1e-9:
            break
        time.sleep(1)
    return result


@stack_up
def test_eval_report_emits_all_stratified_metrics() -> None:
    # A report where the verifiable rate and unverifiable share differ from the overall rate,
    # so a mixed-up gauge assignment would be caught.
    report = OnlineEvalReport(
        run_id="pytest-strat",
        config_id="pytest-strat",
        eval_set_id="pytest-strat",
        oracle_regime=OracleRegime.A_DIGITAL,
        oracle_version="wcag2.2-sc@1",
        created_at=datetime(2026, 7, 8, 12, 0, 0),
        metrics=OnlineEvalMetrics(
            citation_hallucination_rate=0.25,
            findings_total=4,
            citations_total=4,
            hallucinations_total=1,
            citation_hallucination_rate_verifiable=0.5,
            unverifiable_share=0.5,
            citations_verifiable_total=2,
            citations_unverifiable_total=2,
            expert_edit_distance=0.42,
        ),
    )
    record_eval_report(report)
    shutdown()  # force-flush

    labels = '{config_id="pytest-strat",eval_set_id="pytest-strat"}'
    overall = _poll("citation_hallucination_rate" + labels, 0.25)
    verifiable = _poll("citation_hallucination_rate_verifiable" + labels, 0.5)
    share = _poll("unverifiable_share" + labels, 0.5)
    edit_distance = _poll("expert_edit_distance" + labels, 0.42)

    assert overall and float(overall[0]["value"][1]) == pytest.approx(0.25)
    assert verifiable and float(verifiable[0]["value"][1]) == pytest.approx(0.5)
    assert share and float(share[0]["value"][1]) == pytest.approx(0.5)
    assert edit_distance and float(edit_distance[0]["value"][1]) == pytest.approx(0.42)
