"""Freeze the held-out acceptance benchmark into its regression baseline.

The baseline is the T5 deliverable: run_1's scored `OfflineEvalReport` with the 3-run noise floor bundled
in and every run's id listed, written to `benchmark/reports/scorecard.json`. It becomes the frozen
yardstick every later iteration is measured against.

Why run_1's numbers are the frozen numbers: the drafter is bit-stable at temperature 0 — the noise
floor measures SD 0 on both headline rates — so run_1 IS the drafter score, and `_assert_drafter_deterministic`
fails loud if a future sweep ever breaks that (a drifted drafter must not be silently frozen from run_1).
The judge is the noisy component; its run_1 numbers are frozen as-is and the embedded noise floor
discloses their run-to-run SD, rather than inventing an averaging the schema does not model.

Pure and offline: it replays the frozen run artifacts + the frozen noise floor into the report, never
re-invoking a model. Invoke: `uv run python -m clearway.eval.offline_freeze`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearway.eval.offline import build_report
from clearway.eval.offline_build import _REPORTS_DIR, _RUNS_DIR
from clearway.schemas.models import NoiseFloor, OfflineEvalReport

_NOISE_FLOOR = _REPORTS_DIR / "noise_floor.json"
_SCORECARD = _REPORTS_DIR / "scorecard.json"


def _assert_drafter_deterministic(runs: list[dict[str, Any]]) -> None:
    """The drafter's headline rates must be identical across the sweep — the determinism the noise
    floor claims (SD 0). If a run diverged, freezing run_1 as canonical would be a lie, so fail loud
    and make the human decide how to freeze rather than silently pick run_1."""
    base = build_report(runs[0]).scorecard.drafter
    base_key = (base.recall.value, base.false_positive_rate.value)
    for i, run in enumerate(runs[1:], start=2):
        d = build_report(run).scorecard.drafter
        if (d.recall.value, d.false_positive_rate.value) != base_key:
            raise ValueError(
                f"run_{i} drafter drifted from run_1 (recall/FP) — the noise floor claims SD 0, so run_1 "
                "cannot be taken as the canonical frozen score. Re-examine the sweep before freezing."
            )


def freeze_report(runs: list[dict[str, Any]], noise_floor: NoiseFloor) -> OfflineEvalReport:
    """Compose the frozen baseline: run_1's score, the noise floor embedded, and every run's id."""
    if not runs:
        raise ValueError("freeze_report needs at least one run artifact")
    _assert_drafter_deterministic(runs)
    run_ids = [rid for run in runs for rid in run["run_ids"]]
    return build_report(runs[0], noise_floor=noise_floor, run_ids=run_ids)


def _run_paths() -> list[Path]:
    """The sweep's raw runs, ordered numerically (run_1, run_2, …) — not lexically."""
    return sorted(_RUNS_DIR.glob("run_*.json"), key=lambda p: int(p.stem.split("_")[1]))


def main() -> None:
    paths = _run_paths()
    if not paths:
        raise SystemExit(f"no runs found under {_RUNS_DIR} — run the acceptance sweep first")
    runs = [json.loads(p.read_text()) for p in paths]
    noise_floor = NoiseFloor.model_validate(json.loads(_NOISE_FLOOR.read_text()))
    report = freeze_report(runs, noise_floor)
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _SCORECARD.write_text(report.model_dump_json(indent=2) + "\n")

    sc = report.scorecard
    d, j, nf = sc.drafter, sc.judge, sc.noise_floor
    recall, fp = d.recall, d.false_positive_rate
    print(f"froze {len(runs)} run(s) → {_SCORECARD.relative_to(Path.cwd())}")
    print(f"drafter: recall {recall.value:.3f} (n={recall.n}), FP {fp.value:.3f} (n={fp.n})")
    print(f"judge:   κ {j.kappa:.3f}, miss {j.miss_rate.value:.3f} (n={j.miss_rate.n})")
    if nf is not None:
        print(f"noise floor: MDI {nf.min_detectable_improvement:.3f} pp, dominant source {nf.dominant_source}")


if __name__ == "__main__":
    main()
