# Held-out acceptance benchmark — honest failure analysis

This is the first time Clearway's two models have been scored against **external, expert-authored
ground truth** — W3C ACT test cases — under one discipline: **nothing here is graded by an LLM.** The
drafter (`gemma4:31b`) and the judge (`gpt-5.6-luna`) are both *subjects*; ACT gold is the only ruler,
and every comparison is deterministic code. Provenance is frozen by content hash in
`benchmark/reports/scorecard.json` (corpus `wcag22-nomic-embed-text-768@1`, axe-core 4.12.1, ACT export
`a805d865…`, config `m1-single@1`, eval set `act-acceptance@1`).

Every number below was re-derived by hand from `benchmark/runs/run_{1,2,3}.json` and the case HTML, and
reconciles to the frozen scorecard exactly (recall 17/23, FP 13/30, judge confusion 31/16/8/8, injected
32/39 and 63/63, per-run κ {0.137, −0.171, 0.049}).

## The one-line verdict

**On external ground truth, the drafter pattern-matches surface form instead of judging meaning, and the
judge — seeing the same DOM with the same prior — cannot tell.** The two capabilities Clearway claims to
add on top of axe-core (a local model that judges whether a *present* name/label/title is *meaningful*,
and a cloud model that *verifies* that judgment) do not hold up as measured. The instrument itself, and
the deterministic drafter as a regression yardstick, are trustworthy enough to drive the fix.

---

## The central finding: the two headline failures are one event

The headline numbers look like two separate problems — the drafter cries wolf on **43%** of clean
content, and the judge rubber-stamps **67%** of wrong drafts. They are largely the same event counted
twice.

Of the judge's **16 "missed errors" in run 1, 15 are cases where the drafter flagged clean content and
the judge co-signed it.** Only one is a genuine defect waved through. The drafter's false positives and
the judge's misses are the same rows.

The reason is structural. Both models receive only the DOM (axe rule, help text, target, HTML), and both
are given the same prior: the whitelist help text (`clearway/normalizer/quality_review.py`) reframes every
surfaced pass as a suspected defect, and the judge rubric (`clearway/judge/judge.py`) says *"a
present-but-inadequate value is `does_not_support` or `partially_supports`, never `supports`."* The judge
is not an independent reference — it is a **second copy of the drafter's framing**, so their errors
correlate instead of cancelling. The "verify" stage mostly ratifies the "draft" stage's mistakes. That
framing should drive how the failure modes below are read.

---

## Failure mode 1 — The drafter judges surface form, not meaning (FP 0.433, the value-inverting number)

**The ugly number.** False-positive rate **0.433** (13/30 true negatives; Wilson ~[0.27, 0.61]); on the
27 non-trivial true negatives, **0.481** (13/27). The drafter flags roughly **half** of genuinely-clean,
W3C-certified content. Left here, this inverts the product: a specialist told to "go look" on half of the
clean content stops looking.

**Per rule** (honest-misses folded into the denominators, so it reconciles to 17/23 and 13/30):

| Rule | Recall (caught / failed) | False-positive rate (cried wolf / passed) |
|---|---|---|
| HTML page title is descriptive | 2/2 | **3/3** |
| Form field label is descriptive | 4/5 | **4/6** |
| Link in context is descriptive | 4/6 | **4/9** |
| Link is descriptive | 3/5 | 1/4 |
| Heading is descriptive | 4/5 | **1/8** |

**Grounded trace — a whole rule is a constant classifier.** All **five** `document-title` cases — 3
passed, 2 failed — were drafted `does_not_support` at confidence 0.95. The two the drafter cannot tell
apart:

| act_testcase_id | ACT gold | actual `<title>` / body | drafted |
|---|---|---|---|
| `30012df5…` | **passed** | "Clementine harvesting season" over clementine content | `does_not_support` @0.95 |
| `64ad3868…` | **failed** | "Apple harvesting season" over the **same** clementine content | `does_not_support` @0.95 |

The ACT failure in `64ad3868` is exactly that the title says *Apple* while the page is about
*clementines*. The drafter gives the matching and the mismatched title the identical verdict. Its "2/2
recall" on titles is an artifact of a constant stamp that happens to be right when the title is bad and a
false positive when it is good.

**Grounded trace — the label verdict tracks markup, not the label.** Same text, opposite verdict:

| act_testcase_id | ACT gold | label content / mechanism | drafted |
|---|---|---|---|
| `0ed8074a…` | passed | "First name:" via wrapping `<label>` | `does_not_support` (FP) |
| `2a311355…` | passed | "First name:" via `aria-labelledby` | `supports` (correct) |
| `80c83d04…` | **failed** | **"Menu"** labelling a name field, via `aria-labelledby` | `supports` (**miss**) |

The good label "First name:" is flagged when it is a wrapping `<label>` and cleared when it is
`aria-labelledby`; the genuinely-bad label "Menu" on a name field (the ACT failure) is cleared. The
verdict tracks the *labelling mechanism*, not the descriptiveness the help text asks about.

**Root cause.** `quality_review.py` mints a judgment finding for *every* whitelisted `passes[]` element
and hands the drafter raw HTML plus a target selector. For rules that fire on essentially every page
(`document-title` fires whenever a `<title>` exists), this surfaces a call the drafter cannot make from
the DOM, so it defaults to the primed "there is probably a problem." Where it *can* decide, it keys on
structural form (wrapping vs `aria-labelledby`) rather than the resolved accessible name.

**Next step.** Two levers, both measurable on this same held-out set (the drafter is deterministic — see
"What is trustworthy"): (1) **tighten the whitelist / raise the surfacing bar** — `document-title` adds
only noise (a constant classifier) and should be dropped or thresholded, and the ~50%-FP rules (`label`,
`link in context`) need a higher bar; (2) **fix the drafter's input** — hand it the *resolved accessible
name string*, identical whether the label is a wrapping `<label>` or `aria-labelledby`, plus explicit
context, and ask the descriptiveness question on that string. **Do not** retune the SC help text against
these cases — that is contamination (see Failure mode 5).

---

## Failure mode 2 — The judge is not a working check (κ ≈ 0, unstable, biased toward rubber-stamping)

**The ugly numbers.** Cohen's κ against ACT gold is **0.137** in the frozen run — but that is the
*luckiest* of three identical-drafter runs:

| Run | judge κ | miss rate | confusion (release / miss / false-alarm / catch) |
|---|---|---|---|
| run_1 (headline) | **0.137** | 16/24 = 0.667 | 31 / 16 / 8 / 8 |
| run_2 | **−0.171** | 21/24 = 0.875 | 28 / 21 / 11 / 3 |
| run_3 | 0.049 | 18/24 = 0.750 | 31 / 18 / 8 / 6 |
| **mean** | **≈ 0.005** | ≈ 0.76 | |

Because the drafter is bit-identical across all three runs (recall/FP SD = 0.000), **100% of this swing is
the judge's own nondeterminism.** Mean κ ≈ 0.005 is indistinguishable from no agreement beyond chance, and
in run_2 the judge did **worse than a coin**. Against the earlier self-built gold the same judge scored
κ 0.791; moving to external gold collapsed it to zero — a textbook generalization gap. The reported 0.137
must never be quoted without the SD 0.158 beside it.

**Grounded trace — the dangerous direction.** `3bb19863…` is a paragraph about a W3C workshop followed by
`<a href="…/workshop-report.html">Workshop</a>` — ACT `failed` (2.4.4 + 2.4.9), because "Workshop" points
to the *report*. The drafter drafted `supports` at 0.95 (a miss), and the judge returned
`conformance_correct = true`. **A real defect was cleared by the drafter and ratified by the judge**,
reaching the specialist wearing "verified." That is the single case where both subjects failed together,
and it is the worst-case path in the product.

**Root cause.** The judge inherits the drafter's prior (the rubric line above) and sees only the same
DOM — never the drafter's reasoning. It re-litigates the same call with the same blind spots, so it
co-signs the drafter's flags and cannot catch its errors.

**Next step.** **Take the judge out of the trust path** — a decision that can ship immediately. At κ ≈ 0
(negative in one run) a "verified" badge is false assurance; treat every judgment-item draft as
*unverified*. Use drafter/judge **disagreement** as a trigger to route a finding to a human, not as a
release gate. Re-earning judge trust requires real expert gold (the resource the not-measured list flags
as unavailable), after which trust should be re-derived **per finding-class**, never pooled.

---

## Failure mode 3 — Recall is a keyword blocklist, not judgment

**The ugly number.** Recall **0.739** (17/23) reads acceptable, but 3 of the 23 true positives are
honest-misses that mint no finding; on the cases the drafter actually saw it is 17/20, and it decomposes
into "catches the blatant, misses the subtle."

| act_testcase_id | ACT gold | link text | drafted |
|---|---|---|---|
| `7155e250…` | failed | **"More"** | `does_not_support` (correct) |
| `1c577f9a…` | failed | **"this product"** (→ a multi-page product) | `supports` @0.95 (**miss**) |

"More" is on every accessibility cheat-sheet; "this product", "Workshop" (`3bb19863`), and "Menu"
(`80c83d04`) require judging purpose-in-context — the oracle-poor calls Clearway exists to make — and the
drafter cleared all three at high confidence. It behaves like a blocklist of known-bad phrases, not a model
reasoning about whether a name conveys purpose. axe already catches the blatant cases for free.

**Next step.** The same input reconstruction as Failure mode 1; then track recall specifically on the
*subtle* (non-blocklist) subset, which the pooled 0.739 flatters.

---

## Failure mode 4 — Self-reported confidence is decorative, and there is no abstention channel

**The ugly number.** Over-confidence gap **+0.329**: mean confidence **0.948** against conformance
accuracy **0.619** (39/63). Confidence takes only the values {0.85, 0.9, 0.95, 1.0}; `abstained_n = 0` and
`not_applicable` is never used. There is one populated confidence bin above 0.85 — which is itself the
finding, and why ECE (0.329) is reported without a CI.

**Grounded trace.** Confidence does not separate hits from errors: `does_not_support` on the good "First
name:" label (`0ed8074a`) at **0.95**; `supports` on the bad "Menu" label (`80c83d04`) at **0.90**;
`supports` on the failed "Workshop" link (`3bb19863`) at **0.95**. Mean confidence on drafts that are
*wrong* on conformance (0.933) is statistically indistinguishable from drafts that are *right* (0.958).

**Next step.** A signal that is ~0.95 whether the model is right or wrong carries no routing information —
do not gate or triage on it, and do not "calibrate" it against this held-out set. Derive a confidence proxy
from an independent signal (drafter/judge agreement, self-consistency across resampled drafts, or per-rule
reliability priors — `empty-heading` is trustworthy, `document-title` is not), and give the drafter a real
abstention path.

---

## Failure mode 5 — SC-citation is a framing artifact and a contamination trap

**The number.** SC-citation match **0.647** (11/17). Every one of the 6 non-matches is explained by the
help text, not by capability: `quality_review.py` steers `label` to "1.3.1 / 3.3.2" (ACT gold: **2.4.6**)
and plain `link-name` to "2.4.4" (ACT gold: **2.4.9**). Where help and gold agree — headings (2.4.6) and
titles (2.4.2) — the drafter matches 6/6. Restricted to failed cases whose cited SC intersects ACT gold,
conformance-correctness is **11/12**: the drafter gets the right answer for the right reason *when it
cites the aligned SC*.

**Why it matters.** This is a genuine construct-validity limit — the metric measures our prompt wording,
not the drafter — **and** a trap: re-pointing the help text at 2.4.6 / 2.4.9 to raise the number would be
fitting the prompt to the held-out answers. Leave the help text alone; exclude SC-match from any
capability claim, or measure it on a separate, frame-neutral set.

---

## What *is* trustworthy

Honesty cuts both ways.

- **The drafter is a bit-deterministic regression yardstick.** Recall and FP SD are exactly **0.000**
  across three runs, and the paired McNemar discordance floor is **0** in both strata (TP→miss and TN→FP).
  Any single case that flips under a future change is real signal, not jitter. As an A/B detector on this
  fixed set it is excellent — which is what makes Failure mode 1 actionable.
- **But the absolute numbers are soft.** Effective n ≈ 5: the 63 findings cluster into 5 rules that each
  share one drafter framing, so the iid Wilson intervals understate the true width. Reproducible ≠
  precise — trust the *direction* and paired per-stratum deltas, not the third decimal, and do not certify
  a modest aggregate-rate improvement.
- **The pipeline is not hopeless.** `empty-heading` is the best rule (recall 4/5, FP 1/8) — evidence the
  drafter *can* do descriptiveness judgment when the DOM carries the answer (its one FP is `<h1>A</h1>`, a
  valid alphabetical glossary heading — a genuinely hard call).
- **The harness itself is honest.** Non-LLM scoring, Wilson intervals, honest-misses carried in as
  automatic misses (so recall can't be gamed by minting nothing), CI exemptions where n is too small, and
  the `partially_supports` sensitivity read are all sound. The instrument is trustworthy even where the
  subjects are not.

---

## What the method itself cannot tell you

- **Effective n ≈ 5** caps the resolution of every drafter rate; treat the CIs as lower bounds on
  uncertainty. This benchmark answers "works / broken," not "which of two decent versions is better."
- **Injected detection is a loose upper bound.** The judge caught 32/39 = **0.821** of injected
  conformance-flips but only 8/24 = **0.333** of natural errors — manufactured errors are ~2.5× more
  catchable than the plausible ones the drafter actually makes. SC-swap detection 63/63 = 1.000 is a
  *trivial* discrimination (a contrast SC on a link finding) that does not transfer to the hard
  2.4.4-vs-2.4.9 calls. Do not read 0.82 as production miss-catching.
- **The judge's instability caps every judgment number.** With mean κ ≈ 0 and one negative run, no
  downstream judgment-item metric can be trusted beyond it.
- **Tier B is n = 2, illustrative only.** It is consistent with Tier A — the `page-b-label` focal (the
  "First name:" label) was a false positive *both* clean and noisy, plus one noise-region FP, while the
  `page-a-title` focal held — but 0/2 focal flips under noise cannot establish that real-page noise is or
  is not a bottleneck. On this evidence, noise is not the bottleneck; the drafter's judgment is.
- **Total missed-finding volume and image-alt quality are structurally unmeasurable here** (axe-gated,
  DOM-only; ACT filenames leak the image answer).

---

## Recommendation — the next body of work

Both headline failures trace to one root: the `passes[]` framing tells *both* models "this is probably a
problem," and neither can assess descriptiveness from the DOM on the hard cases. Ranked:

1. **Fix the drafter's judgment on the hard cases — the highest-leverage, measurable work.** It is the
   value-inverting defect (FP 0.481 on non-trivial clean content), it is deterministic (so improvement is
   measurable to a single case), and — because 15 of 16 judge misses are rubber-stamped drafter FPs —
   cutting drafter FPs *mechanically improves the judge's numbers too*. Concretely: drop or threshold the
   constant-classifier `document-title` rule and raise the surfacing bar for `label` / `link in context`;
   and reconstruct the drafter's input so it sees the *resolved accessible name*, mechanism-invariant, plus
   context, and answers the descriptiveness question on that string. Keep `empty-heading`. Change surfacing
   and input — never the SC help text against this held-out set.

2. **Take the judge out of the trust path — a decision to ship now.** At κ ≈ 0 (negative in one run) it
   provides no verification; shipping "verified" is false assurance. Treat judgment-item outputs as
   unverified, and use drafter/judge *disagreement* as a human-routing trigger rather than a same-family
   co-signer that inherits the drafter's prior. Any attempt to rescue the judge (a different model, a
   retrieval-grounded rubric) is a separate research bet that must re-clear κ on this held-out set before
   it earns trust.

3. **Replace self-reported confidence with a derived signal, and add an abstention path.** Gap +0.329,
   flat, zero abstentions. Derive triage confidence from agreement, self-consistency, or per-rule
   reliability priors — do not tune the self-report.

4. **Grow gold beyond effective-n ≈ 5 and DOM-only rules — but only after 1–3.** More rules, more contexts
   per rule, a larger real-page set, and a multimodal drafter for the excluded image rules would tighten
   the intervals. But more data on a judge that grades at chance buys little; scope expansion is a
   follow-on, not the next step.

The through-line: two subjects, both failing, and failing *together*. Keep the deterministic drafter as a
paired regression harness, treat its absolute rates as directional, and keep the discipline that surfaced
all of this — refusing to let one model grade another once real gold exists. A self-graded benchmark would
have reported the judge as trustworthy (κ 0.791); external gold showed it grading at chance. That refusal
is the real deliverable.
