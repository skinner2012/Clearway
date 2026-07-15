"""The pure Tier-B smoke math: clean-vs-noisy focal delta + noise-region FP count → the `TierBSmoke`
payload. Illustrative (n=2), never a headline rate — asserted here so the note is exact.
"""

from __future__ import annotations

from clearway.eval.benchmark_tier_b import NoisyFocalResult, tier_b_smoke


def _clean_survives() -> list[NoisyFocalResult]:
    return [
        NoisyFocalResult(
            "page-a-title", "document-title", "failed", flagged_clean=True, flagged_noisy=True, noise_fp=0
        ),
        NoisyFocalResult("page-b-label", "label", "passed", flagged_clean=False, flagged_noisy=False, noise_fp=0),
    ]


def test_no_change_under_noise_reports_zero_delta() -> None:
    smoke = tier_b_smoke(_clean_survives())
    assert smoke["n"] == 2
    assert smoke["instance_ids"] == ["page-a-title", "page-b-label"]
    assert "changed under noise: 0/2" in smoke["clean_vs_noisy_note"]
    assert "noise-region false positives: 0" in smoke["clean_vs_noisy_note"]
    assert "illustrative" in smoke["method_and_limits"]


def test_a_focal_flip_under_noise_is_counted() -> None:
    """The failed focal was flagged clean but missed under noise → 1 focal verdict changed (a miss the
    noise induced)."""
    results = [
        NoisyFocalResult(
            "page-a-title", "document-title", "failed", flagged_clean=True, flagged_noisy=False, noise_fp=0
        ),
        NoisyFocalResult("page-b-label", "label", "passed", flagged_clean=False, flagged_noisy=False, noise_fp=2),
    ]
    note = tier_b_smoke(results)["clean_vs_noisy_note"]
    assert "changed under noise: 1/2" in note
    assert "noise-region false positives: 2" in note
    assert "noisy=wrong" in note  # the induced miss is visible per-page


def test_method_and_limits_is_always_present() -> None:
    assert tier_b_smoke(_clean_survives())["method_and_limits"].strip()
