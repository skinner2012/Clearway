# Clearway — M5: Acceptance benchmark

## Table of Contents

- [Preamble](#preamble)
- [What is measured, and by what](#what-is-measured-and-by-what)
- [Composition of the acceptance set](#composition-of-the-acceptance-set)
- [Goal & exit criterion](#goal--exit-criterion)
- [Feasibility: which ACT rules can actually reach the pipeline](#feasibility-which-act-rules-can-actually-reach-the-pipeline)
- [Noise floor](#noise-floor)
- [Scorecard](#scorecard)
- [What is explicitly not measured](#what-is-explicitly-not-measured)
- [Tickets](#tickets)

---

## Preamble

M0–M4 built the **infrastructure to measure**: instrumentation, per-run metrics, a dashboard, a calibrated judge. But every number so far was produced on **fixtures we planted ourselves and looked at throughout development**.

> **Those are training-set scores, not generalization scores.**

A score reported on data that was tuned against is not a valid claim about the system's ability — this is a basic principle of evaluation. No number from the dev fixture set can support a claim about what the system does on content it has not seen.

M5 exists to answer a question M0–M4 cannot:

> **Does this thing work? How accurate is it? And on the next change, can I tell improvement from noise?**

**How M5 answers each part:**

| Question | Mechanism |
|---|---|
| **Does it work?** | Run on a **held-out** acceptance set and measure *two* things: does it find real problems (ACT failed examples), and **does it cry wolf** (ACT passed examples → false-positive rate). A system that flags good content is not merely "less accurate" — it *costs* the specialist time, inverting the product's value. |
| **How accurate?** | A number with **n and a confidence interval**, scored against an **external, deterministic ground truth** (W3C's expert answers) — not our own judgment, and not an LLM's. |
| **Improvement or noise?** | A **noise floor** (variance over 3–5 repeat runs) defines the **minimum detectable improvement**. Changes smaller than it cannot be claimed as progress. This becomes the regression baseline for every later iteration. |

**The enabling resource:** W3C's **ACT (Accessibility Conformance Testing)** publishes **expert-authored test cases** — maintained by the ACT Rules Community Group, each carrying its WCAG SC and expected outcome (passed / failed / inapplicable), under the **W3C Software and Document License** (redistribution and derivative use permitted *with* the W3C attribution/NOTICE — see T1). Each case has a content-hash `testcaseId`; the aggregate export carries **no version field of its own**, which is why T1 must **vendor and pin** it rather than fetch it live (below). **We do not need to become WCAG experts to label ground truth — W3C already did.**

Crucially, these are rules that require **human judgment** — the descriptiveness calls **axe cannot make**. That is precisely where Clearway claims its differentiation. No LLM scores the result, and axe makes **none of the judgments being measured** — so the *scoring* is not circular. Axe does still **gate coverage**: a `Finding` exists only when axe emits a whitelisted pass, so every rate here is *conditional on axe surfacing the element*. T1 confirms each case actually mints a `Finding`; a failed case that mints none is counted an honest miss, not silently dropped.

---

## What is measured, and by what

**This section is the foundation of the spec. Get it wrong and every number is void.**

> ## ⚠️ Nothing in this benchmark is scored by an LLM.
> **Everything is a deterministic comparison against ACT gold.**

| Role | Identity |
|---|---|
| **ACT gold** | **The only ground truth** (deterministic comparison: conformance + SC) |
| **Drafter** | Subject under test #1 — its `DraftRow` *is* the system's output |
| **Judge** | **Subject under test #2** ← **not the ruler; the thing being measured** |

**Why the judge cannot be the ruler:** M4's rule was "judgment items have no oracle → use the judge." **But M5's entire premise is that ACT supplies an oracle for judgment items.** That rule no longer holds here. Scoring with the judge when gold exists means discarding W3C's expert answers in favour of an LLM grading an LLM — **exactly what this project exists to refuse.**

### How the judge is measured

In production the judge does binary classification: "is this draft correct?" — and here **we know the answer**. So it gets a confusion matrix against ACT gold:

| | ACT says draft is correct | ACT says draft is wrong |
|---|---|---|
| **judge says "pass"** | ✅ correct release | ⚠️ **missed error** |
| **judge says "fail"** | ⚠️ false alarm | ✅ correct catch |

**The two errors are not symmetric and must be reported separately — never collapsed into a single κ:**

- **A missed error is dangerous** — a wrong draft is rubber-stamped and reaches the specialist wearing "high confidence, verified."
- **A false alarm is merely annoying** — the specialist will notice it was fine.

A κ that merges them hides the half that actually matters.

**⚠️ Statistical trap:** if the drafter is 80% accurate, the judge only ever sees 20% wrong drafts — **too few samples to measure the miss rate reliably.**
**Fix: inject known-bad drafts** (swap the SC, flip the conformance) to give the judge a *controlled* set of errors to catch. Its detection ability then no longer depends on how many mistakes the drafter happened to make. (Conceptually: mutation testing.)

**⚠️ Caveat — inherit M4's own lesson, and separate the two mutations.** A **conformance flip** (`does_not_support→supports`) with the *original rationale left in place* is self-contradictory and trivially catchable — the strawman effect M4 showed inflates a score; to be fair its rationale must be regenerated to argue the flipped verdict (which reintroduces LLM authorship, a bias to note). An **SC swap** tests only citation-catching — a *secondary* axis, not the conformance judgment. So report the two detection rates **separately, each with its n**, state how rationale coherence was preserved, and treat both as an **upper bound** on the judge's real miss-catching, never a point estimate.

**Why this is worth more than M4's κ:** M4's κ was computed on a **self-built** gold set; this one is computed on **W3C expert gold** — harder and independent.
**And it is the real product insight:** in production (scanning a client's site) **there is no gold** — the pipeline can only self-assess via the judge. So "how far the judge diverges from expert gold" tells you directly **how much the system's self-assessment can be trusted in production.**

---

## Composition of the acceptance set

### Tier A — ACT judgment rules

Counts below were regenerated from the official W3C machine-readable export
(`act-rules.github.io/testcases.json` — 91 rules, 1134 test cases; each rule ships ~12 example
pages: passed / failed / inapplicable). `passed` → a true negative (clean content the system
must *not* flag); `failed` → a true positive (a real problem the system must find). Inapplicable
examples mint no `Finding` and are not counted.

| Rule | WCAG SC | passed (true negatives) | failed (true positives) | axe rule that mints the `Finding` |
|---|---|---|---|---|
| Link in context is descriptive | 2.4.4 · 2.4.9 | 9 | 6 | `link-name` |
| Link is descriptive | 2.4.9 | 4 | 5 | `link-name` |
| Form field label is descriptive | 2.4.6 | 6 | 5 | `label` |
| Heading is descriptive | 2.4.6 | 8 | 5 | `empty-heading` *(add to whitelist)* |
| HTML page title is descriptive | 2.4.2 | 3 | 2 | `document-title` *(add to whitelist)* |
| **Total (n ≤ 53, pending T1)** | | **30** | **23** | |

Two families are **excluded, not estimated** (both recorded in feasibility, with reasons):

- *"Error message describes invalid form field value"* (3.3.1) — no axe rule confirms the error
  message *exists*, so it never mints a `Finding`.
- *"Links with identical accessible names …"* (2 rules, 35 cases) — their ACT outcome is defined
  over a **set** of links ("do these same-named links go to equivalent destinations?"). Clearway
  mints one independent per-element `Finding` and judges each link in isolation, so it structurally
  cannot represent the cross-element judgment; it would score every failed case as a systematic
  miss. Dropped, not counted.

**n ≈ 53 is not a shortfall against a bigger number — it is the true size of the intersection**
"DOM-decidable **and** single-element **and** a judgment call axe can't make" between ACT and
Clearway's architecture. The image rules can't be seen, the identical-names rules can't be
represented; what remains is exactly these five. There is no larger honest denominator to recover.

These are pure text-vs-text semantic judgments, fully DOM-decidable. Example:

```html
<h1>Weather</h1>
<p>We are open Monday through Friday from 10 to 16</p>   <!-- FAIL: heading doesn't describe the content -->
```

### ⚠️ Explicitly excluded: the two image rules

- **Image accessible name is descriptive** (3P / 3F)
- **Image not in the accessibility tree is decorative** (5P / 5F)

**Reason: their ground truth concerns the *content of the image*, and a DOM-only pipeline cannot see the image.** In the test cases the filename (`w3c-logo.png`) happens to leak the answer, so the system can only score by matching alt against filename — a shortcut that does not exist on real pages (`IMG_20240315.jpg`). **What we would measure is filename-matching ability, not image-text-correspondence judgment. It does not transfer.**

**Future iteration:** judging alt-text quality honestly requires the drafter to **see the image** — i.e. multimodal. The local Gemma 4 / Qwen 3.5 are already multimodal, so this is the natural next step (logged as a future small milestone).

### Tier B — realistic pages (2 instances)

Embed an ACT snippet **as an intact block** into a realistic page with noise (nav, sidebar, footer, other content). **The label travels with the snippet — no new expert judgment is required, which is the only reason Tier B is viable.** Consequently **Tier B is scored exactly like Tier A**: a deterministic comparison against ACT gold.

The question it answers: **when a judgment item is buried in the noise of a real page, does the system still find it and get it right?** The delta between the clean and noisy version of the same snippet *is* the cost of real-world messiness.

**At n = 2 this delta is illustrative, not statistical** — a demonstration that the pipeline survives real-page noise, not a measured rate (no confidence interval attaches to two points). Report it as a smoke test; it does **not** enter the headline scorecard as a number.

**⚠️ Validity discipline (violate this and the gold becomes invalid):**

- Some rules are **context-dependent** ("Link in context is descriptive" depends on the text surrounding the link). **The snippet must be embedded intact, preserving its local context; noise goes outside that block.**
- **Noise must not interact with the rule** (e.g. the nav must not introduce links with the same accessible name — that could mint new rule instances or flip the outcome).
- **Spot-check every embedded case to confirm its label still holds.**
- Start with context-independent rules (page title, form field label) — they are safest.

**💡 How to construct the noise (key design):**

Problem: if the drafter emits findings in the **noise region** (nav, footer), those have **no gold** — you can call them neither right nor wrong.

**Fix: build the noise region out of ACT *passed* examples plus neutral prose.**

The noise region is then, by construction, **not-failed by the rules its snippets test** — so a finding raised there that cites one of those tested properties is a false positive. (ACT `passed` means "not failed *by this rule*," not "conformant under every SC"; a noise finding citing an *unrelated* SC may be legitimate and is **excluded** from the FP count, not auto-scored.) No extra labelling, and no circularity (we never use our own pipeline to certify the noise).

**Methodology status: preliminary, not settled.** This will be researched further and this document updated when implementation reaches it. The report must state the method used and its limitations.

---

## Goal & exit criterion

Produce a credible, reproducible, frozen scorecard on an acceptance set **never seen during development**, to serve as the regression baseline for every later iteration.

**What this benchmark is — and isn't.** At n ≤ 53 clustered in ~5 rules (so the *effective* sample is closer to the rule count than to 53), it delivers a **coarse but trustworthy** verdict — *"does it work, or does it cry wolf so badly it inverts the product's value?"* — plus a regression baseline for future change. It is **not** a precise accuracy figure and cannot finely rank two decent versions; that is what the paired regression test and the T6 failure analysis are for. Its authority rests on **honest, robust method** (frozen gold, external expert answers, never LLM-scored, wide intervals reported as-is), **not** on a narrow number.

**Exit criterion:**

1. **Tier A acceptance set** built from the DOM-decidable ACT judgment rules, with both failed (true positives) and passed (**true negatives**) examples.
2. **Tier B**: 2 realistic-page instances (ACT snippets embedded in noisy pages), measuring the cost of real-world messiness.
3. **The drafter's score comes entirely from a deterministic comparison against ACT gold** (never via the judge).
4. **The judge is measured independently**: a confusion matrix against ACT gold (**missed errors vs false alarms reported separately**) plus its detection rate on injected bad drafts.
5. **Noise floor** established: 3–5 repeat runs on the same set → variance → **minimum detectable improvement**.
6. **A frozen scorecard**: every number carries **n and a confidence interval** (bar the two figures the Scorecard exempts), and the **not-measured list is stated explicitly**.
7. **An honest analysis** diagnosing failure modes and naming the next step.

---

## Feasibility: which ACT rules can actually reach the pipeline

**This is M5's first step and its most likely failure point. Do not assume.**

A Clearway `Finding` exists **only when axe emits something**. Judgment items are minted from axe's `passes[]` bucket for a whitelist of *existence-only* rules — axe confirms a name/attribute/title **exists** but not that it is **meaningful**.

**⚠️ Ground this in the code, not the decision log.** CONTRACTS §6 (v0.11) records the *intended* whitelist as six rules, but the implementation ([`clearway/normalizer/quality_review.py`](../clearway/normalizer/quality_review.py)) scoped down to the four empirically confirmed to pass on present-but-poor content, and **deliberately deferred `document-title` and `button-name`** (a title/button with any text usually reads as adequate, so a clean "present-but-inadequate" case is hard to plant, and enabling them perturbs the frozen regression fixtures). The doc and the code drifted; the code is authoritative.

**Actually-active whitelist (from `quality_review.py`):** `image-alt`, `link-name`, `label`, `frame-title`.

Mapping the surviving ACT judgment rules onto it:

| ACT rule | Needs axe rule | Reachable today? |
|---|---|---|
| Link in context is descriptive | `link-name` | ✅ whitelisted |
| Link is descriptive | `link-name` | ✅ whitelisted |
| Form field label is descriptive | `label` | ✅ whitelisted |
| **Heading is descriptive** | `empty-heading` | ⬜ **add to whitelist (decided)** |
| **HTML page title is descriptive** | `document-title` | ⬜ **add to whitelist (decided)** — *not currently active; the earlier "✅" was wrong* |
| ~~Links w/ identical names — equivalent purpose~~ | `link-name` | ❌ **drop — multi-element, cannot map to a per-element `Finding`** |
| ~~Links w/ identical names + context~~ | `link-name` | ❌ **drop — same reason** |
| **Error message describes invalid form field value** | — | ❌ **no axe rule — drop** |

**Three decisions, and their cost:**

1. **Add `empty-heading` to the whitelist — a genuinely new rule** (it is in *neither* the active four nor the documented-but-deferred two, so record it in CONTRACTS §6 as a **new** entry, not a deferral reversal). It *fits* the existence-only definition (heading non-empty, but descriptive?), but `quality_review.py`'s bar is **empirical, not definitional** — T1 must confirm it actually passes on present-but-poor headings before its +13 cases (SC 2.4.6) count.
2. **Add `document-title` to the whitelist.** Same shape (title present, but is it descriptive?). Recovers "HTML page title is descriptive" (+5 cases, SC 2.4.2). This **reverses** the earlier deferral — acceptable for the benchmark, but see the cost below.
3. **Drop the error-message rule and both multi-element link rules.** No axe rule confirms an error message exists; the identical-names rules cannot be represented per-element (see composition).

> **⚠️ Cost of the two whitelist additions — do not skip.** The whitelist is global: it changes what findings are minted on *every* page, including the frozen M1/M2 regression fixtures (every fixture has a `<title>`; most have non-empty headings). Adding either rule mints new judgment findings there and moves versioned anchors, so each addition needs a **fixture version bump** — exactly the mechanism `quality_review.py` already prescribes. Record both additions in `quality_review.py` (the KEYS + task-honest help text) *and* in the CONTRACTS §6 decision log.

**Reachable n ≤ 53 (30 TN + 23 TP)** once both rules are added and the three drops are taken — an *upper bound* until T1 confirms `empty-heading` and `document-title` actually mint findings (the largest single contributor, +13, rides on the still-unvetted `empty-heading`).

**Still verify empirically (T1):** that each of the five rules actually mints a `Finding` on its passed *and* failed cases. The multi-element rules are dropped by analysis (not deferred to the test), but T1 should still confirm they behave as predicted — systematic misses — and record it.

---

## Noise floor

An LLM is not fully deterministic even at temperature 0. **Run the same acceptance set 3–5 times and report the variance.**

> If run-to-run variance is ±4 percentage points, then "I improved it by 2 points" **is noise, not progress.**

**You cannot detect an improvement smaller than the noise floor.** This benchmark is meant to be the yardstick for later iterations — the noise floor is that yardstick's **smallest gradation**. Without it, you will chase noise and believe you are improving.

**Three refinements that keep the floor honest:**

- **An SD from 3–5 runs is itself a rough estimate** — treat the floor as an order-of-magnitude guardrail, not a precise threshold; widen the run count if a close call depends on it.
- **At temperature 0 on a local model the run-to-run jitter may be near zero.** If so, the floor is set by binomial sampling, not LLM variance — report which of the two dominates rather than assuming it is the model.
- **Separate "how good is it" from "did this change help."** The *absolute* precision is the (clustered) stratified CI — see Scorecard. But the benchmark's primary job is a *paired* comparison on the **same** held-out cases: count how many cases flip verdict between run A and run B (McNemar). Run it **per stratum** — TN→FP flips and TP→miss flips counted **separately, never pooled** (pooling lets a fix in one cancel a regression in the other, violating the rule that the two harms stay separate). And a change is real only if its discordance **exceeds the same-config jitter discordance** (the noise floor), not zero. At ~5 clusters this is still coarse: a *consistent* rule-level shift is detectable; a one- or two-case flicker is not.

---

## Scorecard

A frozen, versioned artifact. `EvalReport` already carries `config_id` / `eval_set_id` / `oracle_version` — but a reproducible benchmark needs more, so T0's `BenchmarkReport` must **also** capture: `corpus_version` (it lives on `CorpusChunk`, not `EvalReport`); the judge provenance (`judge_model` / `judge_version`, on `JudgeResult`); the **drafter and judge model digests** (the immutable hash, *not* the mutable Ollama tag) plus the axe-core version; and the **pinned ACT export hash** (see Feasibility/T1). **Freeze is by content hash, not by a name.**

**Subject #1 — Drafter (the system's output)**

| Metric | Source | Meaning |
|---|---|---|
| Recall on real problems (true positives) | **conformance vs ACT failed examples** | does it **find the problem** — the primary correctness axis |
| **False-positive rate (true negatives)** | **conformance vs ACT passed examples** | **does it cry wolf ← the most important number** |
| SC-citation match | cited `sc_id` ∩ ACT `gold_success_criteria` | does it cite the right SC — **reported separately, secondary** (see Scoring definitions) |
| Confidence calibration (ECE, overconfidence gap) | self-reported confidence vs ACT gold | does the system know when it doesn't know |
| Remediation technique-match rate | ACT metadata (`G94` / `G95` / `F30` …) | is the fix pointing in the right **direction** (**a proxy only**) |

**Subject #2 — Judge** (measurement method above, "How the judge is measured")

| Metric | Meaning |
|---|---|
| **Miss rate** | judge passed a wrong draft — **the dangerous half** |
| False-alarm rate | judge blocked a correct draft — the annoying half |
| Detection rate on injected bad drafts | independent of how often the drafter actually errs |
| κ (on W3C gold) | harder and more independent than M4's self-built-gold κ |

**Overall**

| Metric | Source | Meaning |
|---|---|---|
| Noise floor | variance across repeat runs | minimum detectable improvement |
| Clean vs noisy (Tier A vs B) | the two tiers compared | the cost of real-page noise |

**Every number carries `n` and a confidence interval — quote the *stratified* interval (not the pooled one) as observed, asymmetric Wilson bounds (not a symmetric ±).** The headline metrics run on a subset: the false-positive rate on the 30 true negatives, recall on the 23 true positives. Their worst-case (p = 0.5) widths are ~±18 pp and ~±20 pp — but real Wilson bounds are asymmetric and usually tighter near 0; the pooled n = 53 (~±13 pp) is not where any headline metric runs, so quoting it would flatter.

**⚠️ And even the stratified Wilson understates the truth: the cases cluster in ~5 rules** ({9,8,6,4,3} TN · {6,5,5,5,2} TP), and the drafter shares one prompt/framing per rule, so within-rule outcomes correlate — the **effective n is closer to the rule count than to 30/23**. Report the CIs with an explicit note that they assume an independence the data lacks (state effective-n ≈ #rules). With ~5 clusters no interval is *precise* — which is exactly why M5's verdict is "works / broken," not a fine number.

Two figures are **exempt from the n+CI rule and must say so**: **ECE** (at n ≤ 53 with M4's single-bin overconfidence there is nothing to bin — report the raw gap, no CI) and the **judge's real-draft miss rate** (too few naturally-wrong drafts; the reported figure is the *injected* detection rate, an upper bound — see "How the judge is measured"). **Honest, not flattering.**

### Scoring definitions (deterministic — pin these before T3)

Every comparison below is mechanical; no LLM scores anything.

**Conformance (primary axis).** Collapse Clearway's four-value verdict to ACT's binary:
`FLAGS = {does_not_support, partially_supports}` · `CLEAN = {supports, not_applicable}`.

- On an ACT **failed** case → **correct** if the drafter FLAGS, **miss** if CLEAN.
- On an ACT **passed** case → **correct** if CLEAN, **false positive (cry wolf)** if FLAGS.

`partially_supports ∈ FLAGS` by design: on clean content it *is* crying wolf; on a real problem it did catch that something is off. State the rule in the report so the collapse is auditable.

**SC-citation match (secondary, reported separately).** Match the drafter's `citations[].sc_id` set against ACT `gold_success_criteria` (intersection non-empty), computed **only over correctly-flagged failed cases** — it is meaningless on a case the drafter never flagged. Kept out of the primary correctness number on purpose: the quality-review help text steers the drafter to SCs that **disagree with ACT gold** (`label` → 1.3.1 / 3.3.2 vs ACT **2.4.6**; `link-name` → 2.4.4 vs "Link is descriptive" ACT **2.4.9**), so SC-match will read low for reasons of *framing*, not capability.

> **⚠️ Do not "fix" the SC mismatch by editing the help text to match ACT gold.** That help text drives production drafts; tuning it to the held-out benchmark is contamination — the exact sin this milestone exists to avoid. SC-match stays an honest, possibly-low secondary number.

**Case → finding matching.** Each ACT test case targets one rule; score only the `Finding`(s) minted for that rule's axe rule. A failed case that mints **no** finding is a genuine **miss** (the drafter never got the chance), not an exclusion — record it, since T1's feasibility pass should already have confirmed the rule mints a finding on its examples.

### Why the false-positive rate is the most important number

M4's `passes[]` allowlist makes Clearway **actively accuse things axe passed**. If it flags a pile of perfectly good headings / links / labels, it is not merely "less good" — **it increases the specialist's workload, inverting the product's value proposition (expert-minutes-per-finding).**

Left unmeasured, this failure mode is **completely invisible**. ACT's passed examples are exactly the true negatives needed — **free**.

---

## What is explicitly not measured

**State these. Do not hide them.**

1. **Anything requiring a real human expert.**
   - (a) Is the drafted remediation **actually useful** to an implementer? We only check whether it aligns with the canonical technique — that is **direction**, not **efficacy**.
   - (b) **Has expert-minutes-per-finding actually fallen?** That needs a real specialist and a real stopwatch. **This is the one link in the value proposition that remains unproven.**
   - **Why not a separate milestone:** measuring it properly requires a real accessibility specialist's time — **exactly the resource we do not have.**

2. **Recall (missed findings)** — we can measure whether what the system says is correct, but not **how much it missed**. Findings only exist when axe emits something; what axe cannot see (reading order, motion), we cannot see either.

3. **Image alt-text quality** — the system **does** raise alt-quality judgments via `passes[]`, but **this benchmark cannot validate them** (see the exclusion above). Needs a multimodal drafter.

4. **The judge's own ceiling** — judgment-item scores in production are the judge's; **the judge's accuracy is their upper bound.** No judgment-item number can be trusted beyond `judge_kappa`.

---

## Tickets

### T0 — CONTRACTS additions *(foundation)*
- **Produces:** `BenchmarkReport` / `AcceptanceScorecard` schemas; `GoldLabel` gains `source` (`self` / `w3c-act`, default `self`) and `act_testcase_id` (Optional); update `CONTRACTS.md` §3 **and its §5 + §6 in the same change** (the schema-edit rule).
- **Detail:**
  - The scorecard must hold, per metric: value + `n` + confidence interval (**Wilson**; bar the two figures the Scorecard exempts — ECE and the judge's real-draft miss rate); the noise floor (variance) and the paired minimum-detectable-improvement; Tier A/B stratification; the judge's confusion matrix (miss rate / false-alarm rate / injected-bad-draft detection); and a structured not-measured list.
  - **Reproducibility provenance on `BenchmarkReport`:** `config_id`, `eval_set_id`, `corpus_version`, drafter + judge **model digests** (not Ollama tags), `judge_model` / `judge_version`, axe-core version, and the **pinned ACT export hash** — freeze by content hash, not name.
  - **Both new `GoldLabel` fields must be Optional-with-default** (`source="self"`, `act_testcase_id=None`). The existing `calibration_set.json` gold carries neither and `GoldLabel` is `extra="forbid"`, so a required field without a default would fail to load the M4 gold.
- **Acceptance:** models import; JSON-schema smoke test passes; **the existing `calibration_set.json` still loads unchanged**; existing reports without a judge remain valid.
- **Depends on:** —

### T1 — ⚠️ Feasibility test + ACT converter *(most critical — do this first)*
- **Produces:** the **vendored, pinned ACT gold** (frozen `testcases.json` + the referenced HTML), a feasibility report (which ACT rules actually reach the pipeline), and a `testcases.json` → `GoldLabel[]` converter.
- **Detail:**
  1. **Vendor and freeze the gold first — the export is a live, unversioned endpoint.** Fetch `testcases.json` **and every referenced HTML file** for the surviving rules into the repo; the aggregate has **no version field**, so pin by the per-case content-hash `testcaseId` (SHA-1) and record the fetch date + source commit. The runner reads the **vendored copy, never the live URL**. Add the W3C attribution/NOTICE the licence requires (**W3C Software and Document License** — redistribution + derivative embedding permitted *with* notice).
  2. **Test empirically:** feed each of the five candidate rules' passed *and* failed cases through the pipeline and confirm a `Finding` is actually minted (depends on axe passing the rule *and* the rule being in the `passes[]` whitelist). **Do not assume** — `empty-heading` is unvetted.
  3. **Add `empty-heading` AND `document-title` to the whitelist.** Record each in `clearway/normalizer/quality_review.py` (KEY + task-honest help text) *and* the CONTRACTS §6 log — `empty-heading` as a **new** entry, `document-title` as a deferral reversal. Give each help text the SC that is **production-correct for that quality check** (heading → 2.4.6, title → 2.4.2), chosen on its own merits — **not** to match ACT, and **do not** retune the existing rules' SCs to fit ACT (that would be tuning to the held-out set). **Each addition perturbs the frozen fixtures — bump the affected fixture versions.**
  4. **Drop both multi-element link rules and the error-message rule** (per Composition/Feasibility); confirm the predicted systematic-miss behavior once and record it.
  5. Convert the survivors into `GoldLabel`s:
     - `gold_conformance` ← map `expected`: `failed → does_not_support`, `passed → supports`; skip `inapplicable` (mints no finding).
     - `gold_success_criteria` ← `ruleAccessibilityRequirements`, **filtered to WCAG SC keys only** (`^wcag2\d:`, i.e. `wcag20:`/`wcag21:`/`wcag22:`; drop `wcag-technique:` / `aria11:` / …), prefix stripped to dotted ids, kept as a **list** (several rules carry two SCs, e.g. 2.4.4 + 2.4.9).
     - `act_testcase_id` ← `testcaseId`; `gold_version` ← a set-level freeze id recording the vendored export's hash + fetch date; `source` = `w3c-act`; `labeller` = `"ACT Rules Community Group"`.
  6. **Exclude the two image rules explicitly, recording the reason in code and docs.**
- **Acceptance:** the vendored gold (JSON + HTML) is committed, pinned by hash, with the W3C NOTICE; the feasibility report states pass/fail per rule; the final `n` is a definite number (**≤ 53, set by what T1 confirms**); the converter is reproducible against the vendored copy; the image-rule and multi-element exclusions recorded; each whitelist addition carries a fixture version bump.
- **Depends on:** T0

### T2 — Tier B: realistic pages (2 instances)
- **Produces:** 2 acceptance cases embedding ACT snippets into realistic noisy pages.
- **Detail:** follow the validity discipline (intact embedding, local context preserved, noise must not interact with the rule, spot-check each label after embedding). Build the noise region from ACT *passed* examples + neutral prose; a finding there **citing a tested property** is a false positive, while one citing an *unrelated* SC is **excluded, not auto-scored** (see Composition/Tier B). Start with context-independent rules.
- **Acceptance:** both instances' labels still hold after embedding (spot-check recorded); the clean and noisy versions are directly comparable.
- **Note:** methodology is preliminary; it will be iterated and this document updated during implementation. The report must state the method and its limits.
- **Depends on:** T1

### T3 — Benchmark runner *(scored against ACT gold, never the judge)*
- **Produces:** a runner that puts the acceptance set through the full pipeline, emitting a `BenchmarkReport`.
- **Detail:**
  - The acceptance set is **fully isolated from the dev fixtures** (a distinct `eval_set_id`). Pinned config + pinned judge version.
  - **⚠️ Scoring: compare the drafter's `DraftRow` against ACT gold using the pinned Scoring definitions — conformance as the primary axis, SC-citation match reported separately. Do not score with the judge.** The true negatives (ACT passed examples) yield the false-positive rate.
  - **⚠️ Settle at implementation, not on paper:** how `not_applicable` counts in the FP denominator (report as a separate "abstained" cell, not silently "clean"); a sensitivity check showing FP/recall with `partially_supports` scored the other way; and, as a construct-validity read, conformance-correctness restricted to cases whose cited SC intersects the ACT SC. Flag now; resolve against real T1 output.
  - **The judge is a subject, not the ruler:** in a separate pass, have the judge assess each draft, then compare the judge's verdicts against ACT gold to produce its confusion matrix (**miss rate and false-alarm rate reported separately**).
  - **Inject known-bad drafts** — an SC swap *and* a conformance flip (the latter with its rationale **regenerated to match**, per the caveat under "How the judge is measured") — and measure the judge's detection as **two separate rates, each with its n**, each an **upper bound** on real miss-catching, independent of the drafter's actual error count.
- **Acceptance:** one run emits a complete `BenchmarkReport`; the drafter's score derives **entirely from ACT gold**; the judge has an independent confusion matrix; reproducible given the same config/corpus (LLM jitter aside).
- **Depends on:** T1

### T4 — Noise floor
- **Produces:** variance over 3–5 repeat runs on the same acceptance set, and the **minimum detectable improvement**.
- **Detail:** compute the standard deviation of each headline metric; state explicitly: "a change smaller than X percentage points may not be claimed as an improvement."
- **Acceptance:** variance is quantified; the minimum detectable improvement is recorded in the scorecard.
- **Depends on:** T3

### T5 — Frozen scorecard
- **Produces:** a versioned, frozen scorecard artifact (committed to the repo) + the corresponding Grafana panels.
- **Detail:** every metric with n + CI; Tier A and Tier B reported separately; the noise floor; the structured not-measured list. **This scorecard becomes the regression baseline for all later iterations.**
- **Acceptance:** the scorecard is frozen and comparable against the next run; every number has n and a CI; the not-measured list is complete.
- **Depends on:** T3, T4

### T6 — Honest analysis *(deliverable)*
- **Produces:** a written analysis: where the system failed, why, and what to do next.
- **Detail:** ground every claim in a real trace. Diagnosis → action:
  - low judgment-item correctness → retrieval or drafter-prompt problem
  - **high false-positive rate** → the `passes[]` allowlist is too aggressive → tighten it or raise the surfacing threshold
  - poor calibration (overconfident) → self-reported confidence is useless → derive confidence from another signal (retrieval score, judge score)
  - Tier A good but Tier B poor → real-page noise is the bottleneck
- **Acceptance:** ≥3 concrete, trace-grounded failure modes, each with a next step; **no flattering conclusions**.
- **Rule: report ugly numbers as they are — do not soften or hide them.** An honest analysis is worth more than a flattering number. The unacceptable failure is not a low score but an **untrustworthy** one — a contaminated acceptance set, or a difference drowned in noise. The held-out set and the noise floor exist to prevent exactly those two.
- **Depends on:** T5
