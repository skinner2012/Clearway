"""Run the acceptance set N times and compute the noise floor — the live driver behind the pure math.

The benchmark's smallest meaningful gradation needs 3–5 repeats of the SAME held-out set. This driver
invokes the (checkpointed) acceptance runner N times, freezing each to `benchmark/runs/run_<i>.json`,
then replays them through the pure `build_noise_floor` → `benchmark/reports/noise_floor.json`. It is
RESUMABLE at the run granularity: an already-saved run is reused — so a prior single run (run_1) is
reused for free, and the sweep pays only for the ADDITIONAL runs. Combined with the per-case checkpoint
inside each run, a multi-hour sweep survives interruption.

Each run costs ~2h (gemma-bound) and is serial (one local model), so a 3-run floor is ~4h beyond the
existing run. Not in the test suite (needs Ollama + cloud + pgvector); the math it calls is tested.
Invoke: `uv run --env-file .env python -m clearway.eval.noise_floor_build [N]`  (N defaults to 3).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearway.eval.benchmark_build import _REPORTS_DIR, _RUNS_DIR, run_acceptance
from clearway.eval.noise_floor import build_noise_floor, run_headline_metrics

_NOISE_FLOOR = _REPORTS_DIR / "noise_floor.json"
_DEFAULT_RUNS = 3


def _run_path(i: int) -> Path:
    return _RUNS_DIR / f"run_{i}.json"


def collect_runs(n: int) -> list[dict[str, Any]]:
    """The N run artifacts — reusing any already frozen (run_1 is a prior single run, reused for free),
    running the rest live. Resumable: a rerun picks up where an interrupted sweep left off."""
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        path = _run_path(i)
        if path.exists():
            print(f"run {i}/{n}: reusing {path.name}", flush=True)
            runs.append(json.loads(path.read_text()))
            continue
        print(f"run {i}/{n}: live run (~2h, gemma-bound)…", flush=True)
        artifact = run_acceptance(datetime.now(timezone.utc).isoformat())
        path.write_text(json.dumps(artifact, ensure_ascii=False) + "\n")
        runs.append(artifact)
    return runs


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_RUNS
    if n < 2:
        raise SystemExit("the noise floor needs at least 2 runs")
    runs = collect_runs(n)

    print("\nper-run headline metrics:")
    for i, r in enumerate(runs, start=1):
        m = run_headline_metrics(r)
        print(f"  run {i}: recall {m['recall']:.3f}  FP {m['false_positive_rate']:.3f}  judge κ {m['judge_kappa']:.3f}")

    floor = build_noise_floor(runs)
    _NOISE_FLOOR.write_text(floor.model_dump_json(indent=2) + "\n")
    print(f"\nwrote {_NOISE_FLOOR.relative_to(Path.cwd())}")
    print(f"per-metric SD: {', '.join(f'{k} {v:.3f}' for k, v in floor.per_metric_sd.items())}")
    print(f"min detectable improvement: {floor.min_detectable_improvement:.3f} (floor: {floor.dominant_source})")
    print(floor.paired_mdi_note)


if __name__ == "__main__":
    main()
