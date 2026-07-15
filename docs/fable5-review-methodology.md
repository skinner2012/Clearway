# External review — can this system prove its own trustworthiness?

- **Reviewer:** Claude (Fable 5), independent whole-repo read, 2026-07-15.
- **Charge:** with no human accessibility expert available, what is still missing or mis-designed in
  Clearway's ability to prove how trustworthy it is?
- **Method:** every design doc, spec, analysis, contract, and the eval/orchestrator/judge/drafter
  code paths were read; every claim below cites a file, number, or line. Nothing here is scored on
  vibes. Where the repo is already right, this review says so and moves on.

**The one-paragraph verdict.** The measurement *instrument* built here is genuinely strong — frozen
content-hash provenance, deterministic scoring, pre-committed thresholds, Wilson intervals with an
honest effective-n, honest-misses counted against recall, a negative-κ contract bound, and a failure
analysis (`docs/acceptance-analysis.md`) that reports its own product as broken. That discipline is
rarer than the capability it measured. What is *missing* is propagation and closure: the benchmark's
verdicts have not been pushed back into the artifacts that still claim the opposite (a green
"TRUSTED" badge, an unamended calibration report, a required-but-decorative `confidence` field, two
never-validated finding classes still minting in production, a documented injection posture that
mostly does not exist in code), the acceptance gold is spent with no stated source for the next
acceptance claim, and one third of the deliverable — remediation — has never been measured by any
instrument at all. The system's honest self-assessment exists; it just isn't yet the version of the
story the system tells.

---

## What already holds — do not change it

Honesty cuts both ways; these need no work and should be defended against "improvement":

- **Deterministic, never-LLM scoring against external gold** (`clearway/eval/benchmark.py`,
  `clearway/eval/drafter_score.py`) and the refusal it encodes (`specs/M5-benchmark.md`, "What is
  measured, and by what"). This is the load-bearing discipline; the analysis is right that it is
  "the real deliverable."
- **Freeze-by-content-hash provenance** (`BenchmarkReport` in `CONTRACTS.md` §3; model digests, axe
  4.12.1, ACT export `a805d865…` in `benchmark/reports/scorecard.json`).
- **Statistical honesty in the schema itself**: `MetricCI.effective_n`, `ExemptMetric.exempt_reason`,
  κ bounded `[-1, 1]` so a worse-than-chance judge cannot be clamped away (`CONTRACTS.md` §3), the
  per-stratum McNemar rule, and the two-denominator gold count (47 cases / 63 findings,
  `docs/act-feasibility.md`).
- **Judge kept out of the runtime path.** No runtime state or badge derives from `JudgeResult`; the
  only `VERIFIED` in the system is the deterministic citation verdict (`clearway/validator/check.py:37`).
  The HITL gate force-routes every judgment finding to a human regardless of confidence
  (`clearway/orchestrator/machine.py:259-262` — `AXE_INCOMPLETE` / `UNVERIFIABLE_JUDGMENT` fire on
  bucket and verdict, not on the dead confidence signal).
- **The benchmark row's own hygiene**: κ SD charted as its own panel with an honest description, the
  drafter-deterministic / judge-unstable note on the dashboard, and tests that pin the emitted
  gauges to the frozen scorecard (`tests/test_acceptance_snapshot.py`, `tests/test_dashboard_benchmark.py`).

---

## 1. Design and methodology problems, by severity

### 1.1 The trust surfaces still display the verdict the benchmark falsified

The product definition is "a system that honestly states how trustworthy its own outputs are"
(`README.md:11`). Right now its primary statement surface contradicts its own strongest measurement:

- The trust dashboard (`stack/grafana/dashboards/citation_hallucination.json`) renders, in the
  judge-calibration row, a **"judge trusted?" stat mapped to a green "TRUSTED"** (panel id 23) and a
  κ gauge that goes green at 0.6 (panel id 15) — one row above the benchmark row whose κ-vs-W3C-gold
  gauge reads **0.137** (id 38) with SD 0.158 (id 44). No panel, description, or text on the
  dashboard says the first row was superseded, or even scoped, by the second. A viewer meeting this
  dashboard cold sees the system simultaneously claiming a trusted and a chance-level judge.
- `clearway/eval/calibration_snapshot.py` still re-derives and re-emits `judge_trusted = True`
  (κ 0.7909) from the frozen internal gold, and its tests pin that
  (`tests/test_calibration_snapshot.py:43-44`). The snapshot is point-in-time by design, but nothing
  marks its verdict as scoped to the self-built distribution.
- `docs/M4-calibration-report.md` stands unamended: "**The judge is trustworthy** (κ = 0.79…)"
  (line 34) and "Because the judge is now trusted (κ 0.79), that future work can score judgment
  items automatically, with no human in the comparison loop" (line 136) — the exact inference the
  held-out benchmark disproved. The report is linked from the README as a current document.
- The "judgment correctness (judge-scored)" gauge (panel id 19, `judgment_correctness_rate`, 15/27)
  is described on the dashboard as "an ESTIMATE capped by κ." Its cap is now ≈ 0 — the panel's own
  framing implies the number carries nothing — yet it still displays 56% with no such note.

The failure analysis already made the call ("take the judge out of the trust path — a decision that
can ship immediately," `docs/acceptance-analysis.md:253`). It has not shipped. For this particular
product, a stale trust claim is not documentation debt — it is the defect class the system exists to
prevent. This is the most severe finding because it is fully known, fully measured, cheap to fix,
and still live.

### 1.2 The judge trust gate measured a construct that could not predict production — and both proposed re-validation paths repeat the mistake

The analysis calls the 0.791 → ≈ 0 collapse "a textbook generalization gap"
(`docs/acceptance-analysis.md:118`). That framing under-diagnoses it. Three things shifted at once
between the gate and the benchmark, and the repo cannot currently say which one killed the judge:

1. **Labeller: the system's own designer → W3C.** The internal gold was labelled by the same person
   who wrote the drafter's help-text framing (`clearway/normalizer/quality_review.py`), the judge
   rubric (`clearway/judge/judge.py:51-53`), and the labels (`docs/M4-calibration-report.md:69-71`,
   "single person"). κ 0.791 therefore measured *agreement with the system's author*, and the
   author's framing — SC steering, the `passes[] → suspected defect` prior — is precisely what ACT
   gold contradicted (SC-citation failure mode 5; the shared-prior root cause). The calibration
   report's "judge-vs-one-labeller" caveat names the arithmetic problem (n = 1 rater) but not the
   structural one: the one rater was not independent of the system under test. Self-built gold can
   never validate this judge, because labeller and judge share the priors being tested.
2. **Error population: elicited → natural.** The gate's negatives were "elicited toward the observed
   error taxonomy" (`docs/M4-calibration-report.md:37-40`). The benchmark then measured, directly,
   that manufactured errors are ~2.5× more catchable than natural ones — injected-flip detection
   **0.821** vs natural-error catch **0.333** (`docs/acceptance-analysis.md:223-227`). That pair of
   numbers is the mechanism of the gate's inflation, sitting in the repo, and no document connects
   it back to the 0.791. The connection matters because it generalizes: *any* gate built on
   constructed negatives reports an upper bound, however authentic the rationales.
3. **Metric: 3-way citation∧conformance agreement → binary conformance-only detection**
   (`clearway/eval/kappa.py:106-119` vs `clearway/eval/judge_score.py:116`). The smaller shift of
   the three (the gate's binary collapse was 0.797), but it means "0.79 → 0.137" is not a
   same-instrument delta and should not be quoted as one.

Two further gate-design defects, independent of the collapse:

- **No variance protocol.** The gate measured κ once. The benchmark later measured the same judge's
  run-to-run κ SD at **0.158** with one negative run (`benchmark/reports/scorecard.json`,
  noise-floor block). A single draw from a distribution that wide could have cleared — or missed —
  the 0.6 bar by luck. A pre-committed threshold without a repeat-run requirement is half a gate.
- **The re-validation protocols on offer re-create the problem.** The calibration spec's rule was
  "iterate the model until one clears it" (`specs/M4-judge-calibration.md`, exit criterion and its
  judge-calibration ticket) — selection on the gate set, α inflating with each retry. And the
  analysis's remedy — any rescued judge "must re-clear κ on this held-out set"
  (`docs/acceptance-analysis.md:257`) — points at a set that is *already spent* (§1.3): iterating
  candidate judges against it until one clears is the same forking-paths procedure that minted the
  first false "TRUSTED," now aimed at the last unspent gold. What is missing is a written rule: a
  trust gate is valid only for the distribution it was measured on, must state that domain on the
  artifact (`CalibrationReport` has no field for it), must include a repeat-run variance bound, and
  can only be re-cleared on gold not used to develop the thing being gated.

### 1.3 The acceptance gold is spent, and there is no stated source for the next acceptance claim

All 53 applicable ACT cases for the five reachable rules were consumed — 47 minting cases plus 6
honest misses; no split, no reserve (`clearway/eval/act_gold.py:108-137`; confirmed against the
vendored `testcases.json`: the five rules have 67 cases, 14 inapplicable, zero held back). The
five-rule intersection is honestly described as exhausted — "there is no larger honest denominator
to recover" (`docs/act-feasibility.md:88-90`).

The recommended next work is to tune the whitelist and the drafter's input *using this set's
findings* and to measure the fix "on this same held-out set"
(`docs/acceptance-analysis.md:93-99, 244-251`). That is the right regression procedure — paired
per-stratum McNemar against a bit-deterministic baseline is exactly what the harness is for — but
the moment it happens, the set is a development set. Two consequences are nowhere written down:

- **Post-fix numbers are regression evidence, not acceptance evidence.** "FP fell from 0.433 to X on
  the frozen set the fix was tuned against" is a true and useful sentence; "the system's held-out
  false-positive rate is X" would be false. The distinction should be recorded *before* the fix
  lands, in the same pre-commitment spirit as the κ threshold, because after the fact the flattering
  reading will be available and tempting.
- **There is currently no source of unspent external gold.** The other ACT rule families are
  structurally unreachable (image content invisible, set-level rules unrepresentable, error-message
  rule unmintable — `clearway/eval/act_gold.py:53-71`), so a renewed acceptance claim requires gold
  that does not exist yet: a future ACT export revision with new cases, a new external expert
  artifact, or a multimodal pipeline that makes the 16 image examples valid (§2, rank 4). Saying
  this plainly in the repo would cost three sentences and prevent the most likely future
  overstatement.

Related scope honesty: the measured FP 0.433 is a rate *on ACT's minimal synthetic pages*. The only
real-page evidence is Tier B at n = 2 (`scorecard.json`, `tier_b`), which the repo correctly refuses
to read as a rate. So "flags ~43% of genuinely-clean content" (`README.md:19`) is
distribution-bound; the real-page false-positive rate is unmeasured, and the honest phrasing is
"~43% of clean ACT-style content."

### 1.4 Remediation — a third of the deliverable — has never been measured by any instrument

The product promise is "decision-ready, cited, confidence-scored evidence," where decision-ready
includes "writing remediation an implementer can act on" (`DESIGN_NOTE.md` §2; `README.md:5`). The
measurement record for remediation text, across the entire history of the project:

- The benchmark spec planned one proxy — remediation technique-match against ACT metadata
  (`specs/M5-benchmark.md`, Scorecard table). The frozen scorecard shipped it as
  `remediation_technique_match: null` (`benchmark/reports/scorecard.json`) with **no exemption
  note** — the contract's `ExemptMetric` pattern exists for exactly this and was not used. The
  not-measured list covers remediation *efficacy* ("genuinely useful to an implementer"), but the
  promised *direction* proxy just silently didn't happen.
- The judge never sees remediation: its prompt contains the finding, the drafted conformance, and
  the cited SCs only (`clearway/judge/judge.py:137-149`). Even when the judge was believed
  trustworthy, it was never grading the remediation text.
- `expert_edit_distance` measures remediation edits and is fully wired
  (`clearway/eval/edit_distance.py` → `EvalMetrics` → a Prometheus gauge at
  `clearway/observability/metrics.py:128`), and has had **zero data ever** — no `NeedsReview` has
  ever been resolved as `EDITED` in any fixture or recorded run, so the gauge reads 0.0 (which
  renders as "perfect"). `docs/M2-failure-analysis.md` §5 flagged this as "vacuous until the
  needs-review queue is worked"; it never was.

Net: the conformance verdict is measured (badly, but honestly), citations are measured on the
verifiable subset, confidence is measured (decorative) — and the remediation column has never
produced a number from any instrument. For an evidence product this is not a small hole; it is one
of the three claimed output qualities, and unlike expert-minutes it *had* a planned no-expert proxy
that was dropped without a trace.

### 1.5 Production still mints finding classes the benchmark condemned or could never validate

The active whitelist is six rules (`clearway/normalizer/quality_review.py:55-76`):

- **`document-title`** was added *for the benchmark* (a deferral reversal — the earlier study had
  deferred it because "a clean present-but-inadequate case is hard to plant,"
  `specs/M4-judge-calibration.md`), and the benchmark then measured it as a constant classifier:
  all five cases drafted `does_not_support` @ 0.95, 3/3 false positives on passed cases
  (`docs/acceptance-analysis.md:61-73`). It is still active, minting a noise finding on essentially
  every page (every page has a `<title>`). The benchmark changed production to measure more, the
  measurement condemned the change, and production kept it.
- **`image-alt` and `frame-title`** have never been validated by anything. The image class is
  structurally unvalidatable text-only (the ACT exclusion: filename-matching, not image-text
  judgment, `docs/act-feasibility.md:63`); `frame-title` simply has no gold anywhere. Both mint
  judgment findings in production whose per-class error rate is unknown — and the five classes that
  *were* measured came back at 43% false positives, which is not a prior in these classes' favor.
- The one validated trust signal the system now has is **per-class**: the per-rule table
  (`empty-heading` recall 4/5 · FP 1/8 vs `document-title` 100% FP,
  `docs/acceptance-analysis.md:53-59`). Nothing in the output or the dashboard carries class-level
  trust status — a specialist receives an `empty-heading` finding (measured, decent), a `label`
  finding (measured, ~50% cry-wolf), and an `image-alt` finding (never measured) as
  indistinguishable peers.

The honest interim posture costs nothing new: drop or threshold the condemned rule, and either stop
minting the unvalidated classes or mark them as unmeasured — the whitelist and fixture-version-bump
machinery for exactly this already exists (`clearway/normalizer/quality_review.py:39-42`).

### 1.6 `confidence` is still a required, unqualified contract field — after three negative measurements

`DraftRow.confidence` is mandatory, with the description "model's self-reported confidence" and no
health warning (`CONTRACTS.md:292`) — in a contract that annotates nearly every other trust-adjacent
field with its failure modes. The measurement record: decorative in the first forward-path read
(`docs/M1-weak-spots.md` §3), decorative and gate-inert in the control-loop read
(`docs/M2-failure-analysis.md` §4), ECE 0.392 with zero spread in the calibration study, and gap
+0.329 held-out with `abstained_n = 0` (`docs/acceptance-analysis.md:161-177`). The gate trigger
keyed to it is documented as dormant "until M4 calibration" (`clearway/orchestrator/README.md:64`) —
a promise now stale twice over, since the calibration concluded the signal cannot be calibrated,
only replaced.

Yet the field still flows, at 0.85–1.0, onto every draft a specialist will read, and the one-liner
still leads with "confidence-scored evidence" (`README.md:5`, `ARCHITECTURE.md` §1). Until a derived
signal exists (the analysis's rec 3), the honest moves are contract-level: a warning in the field
description, removal of "confidence-scored" from the claim sentence, and either suppression or an
explicit "decorative — do not gate on this" annotation wherever the value is displayed. Measured
three times, still advertised: this is the clearest case in the repo of a known-false signal being
shipped because removing it feels like losing a feature.

### 1.7 The documented injection posture mostly does not exist in code

`ARCHITECTURE.md` §4.10 declares the risk "live from M1 on" and records four DECIDED mitigations.
Code reality:

- **"Structural separation: page-derived content goes into the LLM prompt inside a labelled, fenced
  region marked as untrusted data"** — absent. Raw page HTML is interpolated verbatim into both
  prompts: `f"HTML: {finding.html …}"` in the drafter (`clearway/drafter/llm.py:116`) and the judge
  (`clearway/judge/judge.py:144`). No fencing, labelling, or escaping exists anywhere between the
  scanner's `node.get("html")` (`clearway/scanner/scan.py:59`) and the prompt.
- **"Provenance + detection: page-derived fields are tagged untrusted; instruction-like content is
  flagged as a trace attribute"** — absent. No such tagging or detection code exists.
- **"Side-effect-free by design"** — genuinely holds (the drafter has no tools; MCP retrieval is
  read-only), and it is the strongest of the four.
- **"Verification as backstop"** — holds only where the oracle reaches (L1 on the verifiable
  subset) plus the forced human routing of judgment items.

So the posture is real on blast-radius and absent on isolation and observability, and there are zero
adversarial tests. One measured result makes this more than theoretical: the benchmark's central
mechanism is that *prompt framing overrode page content* — the help-text prior made both models
flag clean content regardless of what the DOM said. A model that demonstrably privileges its framing
over the evidence is exactly the model whose behavior under adversarial in-DOM framing you cannot
assume. (Also in this family: §4.2 records robots.txt handling as DECIDED; only the explicit
User-Agent exists in code.)

### 1.8 Smaller measurement-integrity items

- **The gate ignores the one deterministic negative signal.** `_review_reason`
  (`clearway/orchestrator/machine.py:252-263`) routes on low confidence (dead), incomplete bucket,
  and `UNVERIFIABLE` citations — but not on `HALLUCINATED`. The control-loop analysis recorded the
  consequence: the run's one hallucinated-citation draft "is not gated at all and ships"
  (`docs/M2-failure-analysis.md` §4). The system's hard oracle catches a false citation and the HITL
  gate does not act on the catch.
- **`min_detectable_improvement` froze at 0.0** (`benchmark/reports/noise_floor.json`) because the
  drafter is bit-deterministic, and it is exported as a gauge. Read naively, "0.0" says every
  nonzero change is claimable progress; the true limiter is binomial sampling at effective-n ≈ 5
  (the artifact does record `dominant_source: "binomial-sampling"`, and the analysis reads it
  correctly — but the gauge alone invites the wrong reading).
- **Judge-derived numbers upstream of the collapse are retroactively soft.** The calibration
  study's judgment-correctness 15/27 and its confidence-curve correctness were judge-graded; with
  the judge at chance on natural errors, those specific numbers inherit its unreliability (the
  held-out benchmark happens to confirm their direction deterministically, which is the only reason
  they can still be cited).
- **An orphaned metric-honesty commitment.** The control-loop analysis found that the HITL gate
  makes `unverifiable_share` read 0.000 while the routed work sits in the queue, and assigned "M5
  must define the honest composite metric (automated report ⊕ queue)"
  (`docs/M2-failure-analysis.md` §1). The milestone that inherited that name became the benchmark;
  the composite metric was never defined, and the gauge still understates human burden to zero on a
  gated run.

### 1.9 The crack, stated plainly

The project's own framing is correct that this cannot be routed around, so here is the boundary as
measured:

**What is proven without an expert:** on five DOM-decidable finding classes, verdict-level
performance against expert-authored gold — and the result is negative (FP 0.433 [0.27, 0.61], recall
0.739 [0.54, 0.88] with effective-n ≈ 5, judge mean κ ≈ 0.005). Citation validity is proven on the
axe-verifiable subset only (L0/L1). The measuring instrument itself — determinism, freeze, honest
misses — is proven by construction and test.

**What is not provable with the resources in this repo, and never was:** whether the evidence prose
and remediation would satisfy an implementer or specialist (no instrument has ever scored them —
§1.4); whether the specialist's minutes actually fall (the value proposition's last link,
`specs/M5-benchmark.md`, not-measured item 1); real-page false-positive behavior (Tier B, n = 2);
the image/frame judgment classes (§1.5); whole-page recall beyond axe's reach. "Expert-quality" is,
today, an aspiration the system can neither support nor refute — and the benchmark's honest negative
on the *decidable* subset makes optimistic extrapolation to the undecidable subset indefensible.

The only honest closures available without an expert are: (a) **shrink the claims to the measured
set** — the README's first sentence currently promises "decision-ready, cited, confidence-scored"
where only "cited" has surviving measurement behind it, and each of the three adjectives should
either carry its number or be dropped; (b) **preserve the ability to make future claims** — the
unspent-gold discipline of §1.3; and (c) **convert asserted properties into tested ones** where that
is possible without new gold (§1.7). What is *not* available is any amount of additional
self-measurement that substitutes for the missing rater. The repo's design note already contains the
correctly-scoped expert ask (`DESIGN_NOTE.md` §11) — the ~30-minute judgment-boundary conversation
remains the single cheapest thing that would move this boundary, and nothing in this review's power
can move it instead. One warning attaches: the design note's Regime-B fallback ("a self-built set
spot-checked by any CASp") should be re-read in light of the benchmark — self-built gold *without*
that spot-check just demonstrated a false-trust factor of 0.79 → ≈ 0.

---

## 2. The next step, ranked

Ranking rule, per the charge: which work most improves the weakest, most trust-critical link, where
the weakness is *already measured*. Two entries come from this review's findings; the six planned
candidates follow. The test applied to each: does it make the trustworthiness claim harder to hold,
or is it one more feature?

**1. Ship the honesty decisions the analysis already made, and propagate the verdicts (gap-derived —
§1.1, §1.6, parts of §1.8).** Measured weakness addressed: judge mean κ ≈ 0.005 (SD 0.158) still
wearing a green TRUSTED badge; ECE 0.392/0.329 still shipping as a required field under a
"confidence-scored" claim; judgment-correctness gauge void but live. Concretely: annotate or retire
the calibration row's trusted badge and gauges; amend `docs/M4-calibration-report.md` with a
superseded-verdict note; add the domain-of-validity statement to the gate artifact; health-warn
`DraftRow.confidence` and de-claim "confidence-scored"; route `HALLUCINATED` citations to review;
record the regression-vs-acceptance rule of §1.3. Roughly a day of work, no model calls, and until
it lands every other improvement is built on a surface that misstates the system's state. This ranks
above the drafter fix not because it is bigger but because it is strictly prerequisite: the product
is the honest statement, and the statement is currently wrong.

**2. Fix the drafter's surfacing and input, and shrink the whitelist to validated classes
(= the analysis's rec 1, plus §1.5).** Measured weakness: FP 0.433 pooled / 0.481 non-trivial — the
value-inverting number — with grounded mechanism (constant-classifier `document-title`;
mechanism-tracking label verdicts; the resolved-accessible-name input gap,
`docs/acceptance-analysis.md:44-99`); plus 15/16 judge misses being co-signed drafter FPs, so this
fix mechanically improves the judge's numbers too. Include the class hygiene: drop/threshold
`document-title`, raise the `label`/`link-in-context` bar, gate or tag `image-alt`/`frame-title` as
unmeasured. Measure by paired per-stratum McNemar against the SD-0 baseline — and record the result
as regression evidence, never as a fresh acceptance claim (§1.3).

**3. Prompt-injection hardening — but implementation-first, not red-team-first (planned candidate,
re-scoped — §1.7).** Measured weakness, honestly stated: none directly — which is itself the
finding, since the architecture declares the risk live and two of its four DECIDED mitigations do
not exist. Step one is to *build the documented posture* (fenced untrusted regions in both prompts;
provenance tag + instruction-like-content trace attribute); step two is a small fixture-based
injection suite measuring verdict/confidence flips and detection rate, turning §4.10 from an
asserted property into a measured one. Grounded suspicion: the benchmark proved both models follow
prompt framing over page content — the exact channel injection uses. Ranked below the drafter work
because hardening the pipe matters less while what flows through it is 43% cry-wolf; ranked above
everything else because it is the only remaining candidate that converts a standing *claim* into a
*measurement* at bounded cost.

**4. Multimodal drafter (planned candidate) — defer until 1–2 land; then it is the only listed
candidate that mints new gold.** It addresses a real, honestly-documented exclusion (image rules
excluded because filename-matching does not transfer, `docs/act-feasibility.md:63`) rather than a
measured failure. Its genuine trust value is usually understated: with pixels visible, the 16
excluded ACT image examples become *valid external gold* — the only new acceptance data reachable
without waiting on W3C or an expert (§1.3). But adding a second unvalidated judgment capability
while the first one fails its benchmark would be growth, not finishing; the analysis's own rec 4
(scope expansion "only after 1–3") is correct. Interim honesty for the image class belongs to
rank 2 (gate or tag it).

**5. LLM routing (planned candidate) — defer; its decision data is void and its trust kernel is
already inside rank 2.** The architecture requires routing policy to be "justified by eval data —
incl. the … judge's judgment-item scores" (`ARCHITECTURE.md` §4.4); those scores now grade at
chance, so a routing choice justified by them would be built on the failed instrument. The
trust-relevant kernel — dispatch/suppress by finding-class using the measured per-rule table — is
exactly the whitelist policy of rank 2 and needs no multi-model machinery. Cost and latency are
measured and unalarming (local $0; drafting ≈ 50 s/call as an honest baseline,
`docs/M2-failure-analysis.md`, operational read). Multi-model dispatch becomes justifiable only
after a trusted scorer exists to compare models on judgment items.

**6. Reflection loop (planned candidate) — reject on this benchmark's evidence; revisit only after a
judge re-earns trust on unspent gold.** Three measured facts each independently break its premise.
(a) The critic co-signs the failure mode: 15/16 judge misses are rubber-stamped drafter FPs; a loop
that iterates until the judge passes optimizes drafts toward the shared prior, not toward ACT truth.
(b) The drafter's errors are deterministic (recall/FP SD 0.000 across runs) — framing and
missing-input defects, not one-shot sampling noise; re-rolling with comments from a chance-level
critic adds no information the model lacks, whereas rank 2 adds exactly the missing input. (c) The
Goodhart cost is concrete here: drafter–judge *disagreement* is the one derived signal the analysis
wants to keep as a human-routing trigger (rec 2) and a confidence proxy (rec 3); putting the judge
inside generation consumes that signal permanently. The candidate list's own ⚠️ was right, and the
benchmark upgraded it from risk to measured fact.

**7. CLI PDF report (planned candidate) — reject for now.** It addresses no measured weakness
("does this make the trustworthiness claim harder?" — no; it is the definitional "one more
feature"), and it has a concrete downside today: a client-facing artifact typeset from current
outputs would render decorative confidence values and judge-derived verdicts into the most
authoritative-looking format the project has ever produced, before rank 1 has scrubbed those
signals. Delivery format is a legitimate finishing task *after* the outputs stop overstating
themselves.

**8. Hand-rolled orchestration vs framework comparison (planned candidate) — reject.** The
orchestration layer is the one component whose measured record is clean: 0 retries, 0 failures,
durable resume and gate tested (`docs/M2-failure-analysis.md`, operational read;
`clearway/orchestrator/README.md`). A Temporal comparison would produce an engineering essay about
the healthiest part of the system while the trust core — the actual product — is measured broken.
It sharpens no trust claim and belongs, at most, in a retrospective write-up.

---

## 3. Spec ↔ code gaps

Found while verifying the above; ordered by consequence.

1. **`ARCHITECTURE.md` §4.10 rows 1 and 4 are unimplemented** (fenced untrusted prompt regions;
   provenance tagging + instruction-like-content detection) — detailed in §1.7. Either implement
   them (rank 3) or re-status the rows from DECIDED-as-built to open; a decision log that reads as a
   description of the system should not describe code that does not exist. Same family: §4.2's
   robots.txt handling (also a `CLAUDE.md` rule) has no implementation; only the explicit User-Agent
   exists (`clearway/scanner/scan.py:38`).
2. **The benchmark spec's injected-flip design was silently narrowed.** The spec requires the
   conformance-flip's rationale be "regenerated to argue the flipped verdict" to avoid strawman
   inflation (`specs/M5-benchmark.md`, judge-measurement caveat and runner ticket); the
   implementation skips regeneration (`clearway/eval/benchmark_inject.py:36-41`). The skip is
   *sound* — but only because the judge never reads rationales at all
   (`clearway/judge/judge.py:137-149`), which contradicts the spec's implicit model of a judge that
   reviews the drafter's reasoning. Record which is intended: a verdict-only judge (then fix the
   spec's caveat) or a reasoning-reading judge (then the current judge is thinner than specified,
   and the injected-detection upper bound is looser than reported).
3. **`remediation_technique_match` was specified as a scorecard metric and shipped `null` with no
   exemption note** (`specs/M5-benchmark.md` Scorecard table vs `benchmark/reports/scorecard.json`),
   despite the contract having an `ExemptMetric` pattern whose whole purpose is that no omission is
   silent. See §1.4.
4. **The control-loop analysis's composite-metric hand-forward was orphaned by the milestone pivot**
   (`docs/M2-failure-analysis.md` §1 assigned it to a milestone that became the benchmark). The
   `unverifiable_share` gauge still reads 0.000 on a gated run while the queue holds the routed
   work. Smaller instances of the same drift: the retrieval reranker and citation-cap items in
   `docs/M1-weak-spots.md` / `docs/M2-failure-analysis.md` point at old milestone numbers whose
   meanings were reassigned; the orchestrator README's "inert until M4 calibration" promise
   (`clearway/orchestrator/README.md:64`) was overtaken by the calibration's actual result.
5. **`DESIGN_NOTE.md` still claims the abandoned half of the thesis.** Its subtitle says "proven
   across two oracle regimes," and §5–§7 present Regime B as the plan, while the architecture's
   change log records "Removed M6 (Regime B) — not being built" (`ARCHITECTURE.md` §8, v0.5). The
   design note is the WHY document; it should carry the surrender honestly rather than by silent
   contradiction with the authoritative plan.
6. **Verified-clean items, for the record:** the benchmark exit criteria are genuinely met and
   test-pinned (gold vendored + hash-pinned with the W3C NOTICE; drafter scored only against ACT
   gold; judge confusion separated; noise floor with dominant source; frozen scorecard with n + CI
   and a four-item not-measured list; the honest analysis exceeds its ≥3-failure-mode floor). The
   whitelist additions were recorded in the contracts change log with fixture bumps as required
   (`docs/act-feasibility.md`, "Whitelist cost"). No divergence found in the scoring definitions:
   the FLAGS/CLEAN collapse, honest-miss handling, and abstention cell match the spec
   (`clearway/eval/stats.py:37`, `clearway/eval/drafter_score.py:142,204`).

---

*Every number above reconciles to `benchmark/reports/scorecard.json`, `benchmark/runs/run_{1,2,3}.json`,
`clearway/fixtures/calibration_set.json`, or the cited line. Where this review disagrees with a repo
document, the disagreement is stated against the file, not around it.*
