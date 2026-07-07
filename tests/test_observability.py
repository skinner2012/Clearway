"""T9 acceptance: the trust metric actually lands in Prometheus (stack-gated).

This is an integration test against the real observability stack. It skips cleanly
when the stack isn't up (`docker compose up -d`), so the normal offline suite stays
green. It's the machine-checkable form of "the metric is visible on the panel":
emit → Prometheus scrapes the collector → query the Prometheus API → assert the value.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import pytest

from clearway.observability import record_rate, shutdown

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
