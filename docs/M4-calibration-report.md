# M4 — calibration report

Closes the M4 exit criterion (`specs/M4-judge-calibration.md`): build an LLM-judge for the judgment
items that have no automated oracle, **prove it trustworthy** against a self-built gold set, then use
it to chart confidence-vs-correctness. It continues the honest-failure line of
[`docs/M2-failure-analysis.md`](M2-failure-analysis.md).

Two questions, answered from frozen artifacts that replay offline — the judge and oracle verdicts are
checked in, so every number here re-derives from [`calibration_set.json`](../clearway/fixtures/calibration_set.json)
and [`confidence_calibration.json`](../clearway/fixtures/confidence_calibration.json) via the pure math in
[`clearway/eval/kappa.py`](../clearway/eval/kappa.py) and [`clearway/eval/confidence.py`](../clearway/eval/confidence.py),
never by re-calling a non-deterministic model:

1. **Can we trust the judge?** — judge-vs-human agreement (Cohen's κ) against the gold set.
2. **Does the system know when it doesn't know?** — does low drafter confidence track low correctness?

The short version: **the judge is trustworthy; the drafter's confidence is not.** That two-part result
is the honest boundary this milestone draws and hands forward.

## Provenance (pinned)

| | |
|---|---|
| Drafter (rated) | `gemma4:31b`, temp 0 (local) |
| Judge (rater) | `gpt-5.6-luna`, temp 0, `rubric=e396f37f; effort=medium` (cloud reference) |
| Gold set | `quality-gold@1` — self-built digital judgment gold |
| Corpus | `wcag22-nomic-embed-text-768@1` |

The judge is a **different model family** from the drafter — a model grading its own family
self-preferences, so the rater must not be the rated. Cloud models are not bit-reproducible even at
temperature 0; a pinned dated snapshot + temp 0 + a fixed rubric is the best determinism available,
and it is recorded on every verdict rather than hidden.

## 1. The judge is trustworthy (κ = 0.79, above a pre-committed bar)

The trust gate is measured on a **deliberately balanced** draft set — 27 natural drafts plus 16
authentic negatives elicited toward the observed error taxonomy (false-`supports`: a present-but-poor
value read as adequate). The negatives are **real model outputs with authentic rationales, never
hand-flipped labels** — a strawman negative a judge catches trivially would inflate κ. Balancing is
required because a purely natural drafter pass is right ~90% of the time, so the human verdict stream
goes near-constant and κ collapses toward 0; a grader needs both polarities to be measured.

**Trust gate — balanced set (n = 43 drafts):**

| measure | value |
|---|---|
| Cohen's κ (3-way: correct / partial / incorrect) | **0.791** |
| Cohen's κ (collapsed to correct / not-correct) | 0.797 |
| raw agreement | 86.0 % |
| pre-committed threshold | 0.60 ("substantial", Landis & Koch) |
| **judge trusted?** | **yes** (0.791 ≥ 0.60) |

**Per-class counts (balanced set)** — reported because a small n makes an aggregate κ fragile, and
because the shape of the disagreement is itself a finding:

| verdict | human | judge | agree |
|---|---|---|---|
| correct | 13 | 17 | 13 |
| partial | 17 | 14 | 13 |
| incorrect | 13 | 12 | 11 |

The threshold was **committed in code before the number was seen** (`KAPPA_THRESHOLD = 0.6` in
`kappa.py`) — the whole point of the gate is that the bar cannot move to fit the result. This is the
first judge tried; it cleared the bar, so no model swap was needed.

### The honesty checks that ride alongside κ

- **Judge-vs-one-labeller, not judge-vs-consensus.** The gold was labelled by a single person (every
  label spot-checked against WCAG Understanding/Techniques, disagreements recorded in the gold set's
  `notes`). So this is agreement with *one* human, not ground truth by committee — κ must not be read
  as more than that.
- **Constructed-distribution caveat.** κ here measures whether the judge can tell a good draft from a
  bad one on a *balanced* set — the property routing will depend on — not the drafter's natural base
  rate. The cost: if the constructed negatives were systematically easier/harder than real errors, κ
  would mis-estimate real-workload reliability. Mitigated by drawing negatives only from the observed
  failure taxonomy with authentic rationales. As the honesty check, the **natural faithful pass** is
  reported too: κ 0.807, raw agreement 88.9 %, n = 27 — near-degenerate by construction (the human
  stream is nearly all-correct), which is exactly why the gate is measured on the balanced set instead.
- **Independence.** Findings from the same fixture share context, so the *effective* n is below 43 —
  one reason the gold is spread across ~12 fixtures rather than a few dense pages.

### Judge bias — a mild leniency

Absolute rubric scoring (not pairwise), so position bias is N/A. But the per-class counts surface a
real tendency: the judge assigns **"correct" more often than the human does (17 vs 13)**, and
"partial" less often (14 vs 17). It catches every draft the human calls fully correct, then over-credits
~4 borderline drafts the human rated "partial" up to "correct." **The judge is slightly lenient at the
partial/correct boundary** — worth watching if it is ever used to gate a quality claim, and a reason
its output stays an *estimate capped by κ*, never folded into the oracle-verified count.

## 2. The system does **not** know when it doesn't know

Binning every draft by the drafter's self-reported confidence and measuring correctness per bin —
oracle for verifiable items, the trusted judge for judgment items — gives the whole curve:

| confidence bin | drafts (n) | mean confidence | correctness | correct / n |
|---|---|---|---|---|
| 0.8 – 1.0 | 30 | 0.958 | 0.567 | 17 / 30 |

That is the entire curve. **Every draft's confidence lands in a single top bin** — there is no
low-confidence bin because confidence never drops. Within that bin the drafter is **95.8 % confident
while 56.7 % correct**:

- **Expected Calibration Error (ECE): 0.392** — the magnitude of miscalibration.
- **Over-confidence gap: +0.392** — signed, positive = systematically more confident than right.

With one populated bin the two collapse to the same number. **A flat, over-confident curve is the
finding, not a failure to produce one** — and it only reads honestly because the bin counts ship
beside it (n = 30, so the single point is not one lucky draft). This confirms the earlier reads:
the drafter's confidence is **decorative** — pinned near 1.0 regardless of correctness — which is why
the confidence-based review gate has been dormant since it was built.

Answer to the question: **no, the system does not know when it doesn't know.** Its confidence carries
no usable signal.

## Concrete failure modes named

- **Drafter over-confidence (the headline).** Confidence is uninformative: 95.8 % asserted, 56.7 %
  actual, zero spread. Any downstream logic that reads `confidence` as a trust signal is reading noise.
- **Judgment correctness is only ~56 %** (15 / 27 natural judgment drafts judged correct). On
  present-but-poor content — the product's actual value proposition — the local drafter is right only
  a little more than half the time. This is the number a better drafter or a routing choice must move.
- **Judge leniency at the partial/correct boundary** (§1) — the rater's own residual bias.

## The confidence requirement M4 hands forward

M4 **measures** the confidence failure; it does not fix it. The robust fix — a real trust signal —
structurally needs multi-model machinery M4 does not have, so it is **deferred, not dropped**: a
requirement for whatever milestone tackles confidence, not discharged here.

> The drafter's self-reported confidence carries **no usable signal** (ECE 0.392, zero spread). A
> later milestone must **synthesise a real confidence signal** — from self-consistency or cross-model
> disagreement — or key any routing decision to **finding-class, never the confidence field**, because
> that field is decorative.

Because the judge is now trusted (κ 0.79), that future work can score judgment items automatically,
with no human in the comparison loop — which is what sequencing calibration first bought.

## Reproducibility

Everything above replays offline: `uv run pytest tests/test_kappa.py tests/test_confidence_replay.py
tests/test_calibration_snapshot.py`. The live snapshot is pushed to the trust dashboard's
judge-calibration panels with `uv run python -m clearway.eval.calibration_snapshot` — a point-in-time
milestone gauge, refreshed only when the calibration is re-emitted, not a per-run series.
