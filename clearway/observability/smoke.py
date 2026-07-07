"""Smoke emitter — push one sample trust metric to validate the pipeline end-to-end.

Lets us confirm OTLP → Collector → Prometheus → Grafana works *before* the real run
(T10) exists, and decouples pipeline debugging from integration. Usage:

    uv run python -m clearway.observability.smoke --rate 0.667
"""

from __future__ import annotations

import argparse

from clearway.observability import record_rate, setup_metrics, shutdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit a sample citation_hallucination_rate.")
    parser.add_argument("--rate", type=float, default=0.667, help="value in [0,1]")
    parser.add_argument("--eval-set-id", default="m0-core@1")
    parser.add_argument("--config-id", default="smoke")
    parser.add_argument("--oracle-regime", default="A-digital")
    args = parser.parse_args()

    setup_metrics()
    record_rate(
        args.rate,
        eval_set_id=args.eval_set_id,
        config_id=args.config_id,
        oracle_regime=args.oracle_regime,
    )
    shutdown()  # force-flush before exit
    print(f"emitted {args.rate} (eval_set_id={args.eval_set_id}, config_id={args.config_id})")


if __name__ == "__main__":
    main()
