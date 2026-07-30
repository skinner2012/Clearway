# Clearway — M9: Judge decorrelation

> **Scope note.** M9 touches the judge only. It re-runs the judge against M7's frozen artifacts — the
> drafter is never called — so the only thing that varies is the judge's own prompt. **It measures; it
> does not wire anything up.** The comparison lives in `clearway/eval/`; the orchestrator's routing
> behaviour and the HITL queue are untouched. Making the disagreement signal act in production is later
> work, and this milestone does not name when.
>
> **⚠️ "Offline" here means *outside the production path*, never *without live services*.** The drafter
> is genuinely never called, but **the judge's input is not on the frozen run**: a draft record carries
> `finding_id`, `target`, `conformance`, `cited_sc_ids`, `confidence` and `remediation`, and no
> `Finding` at all. Rebuilding what the judge must read needs the live scanner (Playwright → headless
> Chromium → `axe.run()`, because `referent` is captured inside the page session and the DOM is gone
> afterwards) and the live retriever (pgvector + the embedder). **Only the drafter is absent — plan the
> run for the full local stack.**
>
> **It is not an attempt to make the benchmark more accurate.** The benchmark always scores against
> ACT gold, and the judge is a subject of measurement, never an instrument of it. What M9 repairs is
> the judge's **product role**: the disagreement detector.

## Table of Contents

- [Preamble](#preamble)
- [What is measured, and by what](#what-is-measured-and-by-what)
- [What is explicitly not measured](#what-is-explicitly-not-measured)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)
- [Runs and cost](#runs-and-cost)
- [Evidence ledger](#evidence-ledger)
- [Appendix — the commit-first configuration](#appendix--the-commit-first-configuration)

---

## Preamble

M5 measured the judge and got κ = 0.137 — barely distinguishable from a coin. It also **co-signed 15
of the drafter's 16 false positives**.

M6 through M8 spent their effort on the drafter, and it worked: false positives fell from 0.433 to
0.231, and `document-title` went from a constant stamp (κ 0.000) to perfect discrimination
(κ +1.000). **The judge is the last unrepaired component, and it is broken.**

### What the judge is for, and why that function is currently broken

The judge's role was settled after M5: **not a verifier, a disagreement detector.** When it disagrees
with the drafter, that finding goes to a human.

So the question is not *is the judge accurate* but **when it raises its hand, is it worth sending
someone to look?** From M5's confusion matrix:

```
63 findings, 24 genuinely wrong        → pick at random and you are right 38% of the time
judge flagged 16, of which 8 were wrong → follow the judge and you are right 50% of the time
```

**Thirty percent better than guessing.** That is what routing human attention at random looks like as
a number, and it is what M9 exists to fix.

**⚠️ Those figures are M5's, on M5's drafts, and they are the motivation — not the starting point.**
M6–M8 changed the drafter, so the frozen run this milestone replays has a different number of wrong
drafts. Nothing above may be reused as M9's baseline; T3 measures the baseline that applies.

### The diagnosis: M5 guessed shared input; the literature names anchoring

M5 attributed the failure to *shared DOM input plus a shared biased rubric*. The direction is right,
but **the external literature identifies a more specific operative cause: the judge anchors on the
candidate answer it is shown.**

Measured effect sizes (arXiv 2607.05904 — see the evidence ledger):

| Setting | False-positive rate on wrong answers |
|---|---|
| Ordinary verify prompt (judge scores the answer in front of it) | **0.719** |
| Judge required to write its own answer first, candidate still visible | **0.012** |
| Judge never shown the candidate; code compares its independent answer | **0.012** (discrimination 0.96) |

The paper concludes that candidate anchoring — rather than model family, model scale, or even whether
the candidate is visible at all — is the operative cause. And critically, **an ensemble of three
different model families still accepted 55% of the wrong answers**: switching families and adding
voters does not address anchoring.

Clearway already did the family half of that advice — `judge.py` raises at construction if the judge
model equals the drafter model. **What remains is the anchoring.**

### What this milestone builds is not a reflection loop

The mechanism M9 enables has an established name, and it is not *reflection*. There is no
self-examination and no iteration:

> **Independent dual read.** Two readers answer the same question without seeing each other's answer;
> **code** compares the two; discordant cases go to a human. This is how double reading works in
> screening — two radiologists read the same image independently, and discordant cases go to
> arbitration.

The distinction matters because it is what keeps Goodhart's Law out. A loop that runs until the judge
approves optimises against the judge; **a single independent read has no optimisation pressure at
all**, because there is no second attempt. There is nothing to game.

It also puts the judge where it is strong. A loop needs the judge to **approve correctly** — the thing
M5 measured it failing at, 15 times in 16. Dual read needs the judge only to **answer
independently**; whichever reader is right, the disagreement itself carries information.

### A deeper problem: the current κ is not methodologically valid

**Cohen's κ measures agreement between two independent raters.**

But the current judge **can see rater one's answer**. It is not an independent rater; it is a marker
grading a paper with the answer written on it. The number `kappa.py` computes is therefore not
measuring what κ is defined to measure.

**Blinding the judge makes κ mean what it claims to mean.** That is an architectural correction, not
a debiasing trick.

### ⚠️ A new fact created by M7: the judge now sees less than the drafter

Since M7, `Finding.referent` exists and the drafter uses it — the resolved accessible name, the
page-topic signal, the surrounding context.

**But `_judge_user_prompt` passes only `finding.html`. The judge cannot see the referent.**

So the judge is grading a verdict formed from information it does not have. On `label`, the drafter
sees the resolved accessible name; the judge sees only the raw markup.

**Two consequences:**

1. **M5's judge baseline cannot be reused.** It was measured when drafter and judge saw the same
   thing. That relationship has changed, so the baseline must be rebuilt.
2. **Blinding only works if the judge receives what the drafter received, referent included.**
   Otherwise the experiment measures an information asymmetry rather than a difference in judgment.
   **Getting this wrong voids the milestone.**

---

## What is measured, and by what

> ## ⚠️ No M9 acceptance number is scored by an LLM.
> **ACT gold is the only oracle.** The judge is the subject.

### Two configurations

There are two because M9 is a before-and-after. **anchored is not a design choice — it is the code as
it stands today**, and it exists here only as the thing to measure against. **blind is the
intervention.**

Blind rather than some other fix, for two reasons that happen to point the same way:

- **It removes the diagnosed cause most completely.** The anchor is the draft itself, so withholding
  the draft is the strongest available removal. Softer variants — a neutral rubric, a stronger judge,
  an ensemble — all leave the anchor in place, which is why they do not work.
- **It is the shape the product role already needs.** A disagreement detector requires a second
  *answer*, not a *grade*: two verdicts that code can compare. A judge that grades cannot produce
  that, however well it grades.

So blinding is not a debiasing trick applied to an otherwise-fine design. It is what the judge should
have been doing all along, and removing the anchor is a side effect of getting the architecture right.

Both configurations run **the same judge model** — `gpt-5.6-luna`, which is and must remain a
different model from the drafter's `gemma4:31b`. Both receive **the same finding-side input**: the
finding, its referent, and the retrieved SC candidate list.

**What differs is whether the draft is an input at all.** For anchored it is — the draft is the thing
being graded. For blind it is not: the judge never sees it, and the frozen draft is used only
afterwards, by code, as the thing to compare against.

| Configuration | Sees the draft | Produces | Who decides agreement |
|---|---|---|---|
| **anchored** (current baseline) | yes | a grade of the draft | the model |
| **blind** | **no** | its own conformance + cited SC | **code** |

A third configuration, **commit-first**, is retained as a mechanism probe and specified in the
appendix. It informs *why* any effect occurs; no product decision depends on it.

### ⚠️ Two comparisons live in this milestone, and they answer different questions

They share one run and share several metrics, and blurring them is the easiest mistake this document
invites. **Every number in the written read names which comparison it belongs to.**

| | **Comparison 1 — judge vs judge** | **Comparison 2 — judge vs drafter** |
|---|---|---|
| What it asks | did removing the anchor make the **routing decision** better? | what does the second reader actually look like, and is it worth having? |
| The two sides | anchored ↔ blind | **the blind judge ↔ the frozen drafter** |
| Oracle | ACT gold, M5's four cells | ACT gold for *who is right*; **no gold at all** for the rate itself |
| Statistically tested? | yes — the one-sided sign test | **no. Descriptive by construction** — per-class n did not grow |
| Exists under anchored? | it *is* the anchored side | **no.** An anchored judge emits a grade of a draft, not a conformance verdict, so there is no second answer to compare against the drafter's |

**⚠️ The testable comparison is the less useful one.** Comparison 1 can at best establish that blind
routes better than a mechanism this project already judged broken. **Comparison 2 is what decides
whether the signal is worth wiring into anything**, and it carries no p-value whatsoever. Read the
report in that order, and never let a p-value stand in front of the number that matters.

**The number that matters is the disagreement rate, with its absolute count.** Everything else here
either explains it — composition, direction, per-class spread — or says whether following it pays
(each rater's κ against gold). **Producing that number honestly, priced in people-visits, is this
milestone's primary deliverable.** The sign test is a secondary check on how it was arrived at.

### What the judge receives

Spelling out that shared input for the blind configuration:

| Given to the blind judge | Withheld |
|---|---|
| the finding (rule, target, HTML, **referent**) | **which SC the drafter chose** |
| the **same retrieved SC candidate list** the drafter got | **the drafter's conformance verdict** |

**The retrieved candidate list is shared deliberately.** Letting the judge run its own retrieval would
produce a different candidate set, so a disagreement could come from *different retrieval* rather than
*different judgment* — the attribution would break. Sharing the retrieval keeps the variable clean:
**the question is shared, the answer is independent.**

**⚠️ The cost is one correlated input left in place** — a bad retrieval ordering misleads both
readers, and they agree for the wrong reason. Blinding removes anchoring, not this. Carried forward as
a known limitation.

### What code compares

Two fields, and only two. Prose is never compared.

| Field | Compared? | Rule |
|---|---|---|
| `conformance` | **yes** | **raw four-value equality** — `partially_supports` ≠ `does_not_support` counts as a disagreement |
| `citations[].sc_id` | **yes** | **exact set match** — any difference is a disagreement |
| `remediation` | no | free prose |
| `confidence` | no | the schema already declares it decorative |

**Why raw four-value rather than the FLAG/CLEAN collapse.** The collapse exists because ACT gold is
binary — four drafted verdicts have to map onto passed/failed to be scored against it. That constraint
applies to **scoring against gold**, not to **comparing two drafts**. Both readers emit the same
four-value enum, so they can be compared directly, and a difference in degree is a real difference of
opinion worth a human's attention. *(Volume note: `partially_supports` appears 5 times in 54 frozen
drafts, so this decision is real but small.)*

**⚠️ The collapse still governs every gold-scored number.** κ, false-positive rate and recall against
ACT gold continue to use `stats.is_flag` and `COLLAPSE_RULE` unchanged. Routing comparison and gold
scoring are two different comparisons with two different rules; conflating them is a spec violation.

**Why exact set match on SC ids.** *When the drafter cites at all* it emits exactly one SC per rule
with zero variance, so a non-empty set is a singleton and exact matching is not over-sensitive. A
looser rule (overlap, Jaccard threshold) would add a tunable parameter, and tuning it after seeing
results is exactly the kind of knob this project does not permit itself.

**⚠️ But the drafter carries an unwritten convention, and the SC axis is worthless without it.** In the
frozen run a `supports` draft usually cites **nothing at all** — an empty `cited_sc_ids` — and mostly
only a flagging draft names a criterion. **Nobody has ever told the judge this.** A blind judge that
answers `supports` while still naming the criterion it reasoned from produces a set mismatch on nearly
every clean finding, and the disagreement rate then reports a formatting habit as a difference of
opinion.

**⚠️ And the convention is not absolute — the pre-flight counted the exceptions, and they are
class-structured.** Over the 54 frozen drafts, 21 of the 28 `supports` rows are empty and **7 cite
anyway**, and every one of the 7 sits in a class the convention does not reach:

| class | `supports` rows | of which empty | of which citing |
|---|---|---|---|
| `label` | 7 | 7 | 0 |
| `link-name` | 12 | 12 | 0 |
| `empty-heading` | 6 | 2 | **4** |
| `document-title` | 3 | 0 | **3** |

So the habit is real on `label` and `link-name`, **inverted on `document-title`, and internally
inconsistent on `empty-heading`** — where the same class both cites and does not. Every citing row
names exactly one SC, and exactly one distinct SC per rule (`label` 3.3.2, `empty-heading` 2.4.6,
`document-title` 2.4.2, `link-name` 2.4.4), so *exact set match* remains the right rule; what is wrong
is the premise that the drafter's clean rows are uniformly empty.

**Two consequences, both for the rubric rather than for the design.** A rubric instructed to cite
nothing when clean will mismatch those 7 rows *by construction*, and a rubric instructed to always
cite will mismatch the other 21. **No single instruction agrees on all 54** — `empty-heading` splits 2
empty against 4 citing, so no deterministic rule reproduces it.

**⚠️ But the honest reason to stop there is impermissibility, not impossibility.** A *per-rule*
instruction — cite on `document-title` and `empty-heading`, stay silent on `label` and `link-name` —
would agree on **52 of 54**, so the wording problem is very nearly solvable. It is rejected because
solving it that way means **telling a supposedly blind judge what the drafter's per-class habits are**,
which leaks the very thing blinding withholds, and moves one rater toward the other — the Goodhart
failure this spec forbids elsewhere. The axis is therefore left uncleaned **by choice**, and that is a
stronger statement than "nothing could be done".

So the honest handling is to state the rule the rubric was frozen under, report **how many of the
SC-axis disagreements fall on the 7 rows the drafter is inconsistent on**, and read the axis knowing
that share is a formatting artefact rather than a difference of opinion. **The convention still goes
into the rubric before any run** — instructed as *name the criterion you decided against, and name
nothing when you find no failure*, matching the majority shape — and **this cannot be repaired
afterwards:** repairing it means editing the rubric, and Control 5 freezes the rubric before the frozen
set is touched.

**⚠️ And the artefact is not spread evenly — it lands hardest on the smallest class, which distorts one
Group A metric.** Measured against each class's whole finding count, not just its `supports` rows:

| class | inconsistent rows / findings in class | share of the class |
|---|---|---|
| `document-title` | 3 / 5 | **60%** |
| `empty-heading` | 4 / 11 | **36%** |
| `label` | 0 / 17 | 0% |
| `link-name` | 0 / 21 | 0% |

**So *disagreement rate per finding-class* is not comparable across classes on the SC axis.** Up to
60% of `document-title`'s SC-axis disagreement can be formatting alone — and `document-title` is
exactly the class where the drafter scores κ = 1.000, so an unannotated figure there reads as mechanism
evidence when it is a citation habit. **That row carries this caveat wherever it is reported**, and the
per-class SC figures are quoted beside the class's inconsistent-row count, never on their own.

*(For scale on how new the habit is: in the immediately preceding frozen run every one of its 27
`supports` rows cited, several with two or three SCs. The convention is an artefact of the
citation-grounding prompt, one run old, and it is not a drafter invariant.)*

**⚠️ Expect the SC axis to be quiet, and say so in the read.** The retrieval query is built from the
rule and its help text, so every finding of a rule receives the same candidate criteria in the same
order — a judge that cites at all will usually cite what the drafter cited. **The SC axis therefore
contributes little disagreement of its own and sits close to all-or-nothing on the convention above;
the conformance axis is where the signal lives.** Report the three composition shares knowing this,
rather than presenting them as three independent channels.

### How the two configurations are compared

The configurations produce **different output shapes** — anchored grades a draft, blind emits its own
answer — so they cannot be paired field-for-field. **They are comparable at the level of the routing
decision, which is the product behaviour and what M5 already measured.**

| | anchored raises its hand when | blind raises its hand when |
|---|---|---|
| **flag** | it grades the draft incorrect | its own answer differs from the draft |
| **release** | it grades the draft correct | its own answer matches the draft |

That binary decision is then scored against ACT gold into M5's four cells — `correct_release`,
`missed_error`, `false_alarm`, `correct_catch` — and the **paired test compares the correctness of the
routing decision**, not the correctness of any verdict.

Reusing the mechanism M6 pre-registered and M7 exercised: **one-sided exact sign test, α = 0.05,
scored on discordant pairs.**

**⚠️ The test's threshold is registered after T3, not here.** The sign test asks whether blind won on
more **cases** than it lost on, and that question has no answer until it is known how many flip **when
nothing changes at all**. A cloud judge run twice under one configuration produces discordant pairs of
its own; a threshold chosen before that count is known can be cleared by jitter alone. **T3 measures the
floor, and the discordant count required for a result is fixed from it, in writing, before T4's first
call.** What is fixed *here* is the test family — one-sided exact sign test, α = 0.05 — and the unit,
which **T1 settled at the case (40 units)**. What is not fixed here is how many discordant pairs
constitute a result.

**⚠️ Each configuration's routing decision comes from its N passes, never from one.** A single pass of
a non-reproducible judge is one draw. The **per-finding** decision is that configuration's **majority
verdict across its passes**, and the pass-to-pass disagreement is reported beside the result. That
per-finding decision is then aggregated to the unit the test is scored on — see immediately below —
so **two collapses apply, in this order and not the other:** majority across passes first, per
finding; then flag-if-any across the findings within a case. Reversing them answers a different
question and can land on a different case decision.

### ⚠️ The observation unit: settled at **per case**, before any run

M6 set the drafter's unit to per-case precisely to avoid pseudo-replication, and M8 abandoned a
statistic entirely for the same reason. Clustering looks lighter here, but **the judge's observations
must not be treated as independent units without stating the ground**, so the ground was measured
first — zero model calls, over the frozen replay pass and the earlier judged passes — and frozen at
`benchmark/reports/judge_observation_unit.json` (rebuild:
`uv run python -m clearway.eval.judge_observation_unit`).

**The structure.** 54 observations — one **natural judgment** per minted finding — in **40 clusters**,
one per minting ACT case. **⚠️ An observation is not a call:** the anchored side spends 147 calls per
pass on these same 54 findings, because each mutation is its own call, and those extra calls feed the
injected-gap diagnostic rather than the routing comparison. Counting calls would inflate the structure
by 2.7× for reasons that have nothing to do with clustering. **The manifest carries 44 rows**: the other
4 mint no finding, are never judged, and
are therefore not clusters at all. Dividing by them gives 54/44 = 1.23 findings per row against the
true 54/40 = **1.35 per cluster**, which is why the observations are counted and the manifest rows are
not. 33 clusters are singletons; **7 hold more than one finding (sizes 2, 2, 3, 3, 3, 4, 4) and carry
21 of the 54 observations — 38.9%.** The size-weighted (Kish) mean cluster size `Σm²/Σm` is **1.852**.
**All of the clustering lives in two of the four classes:** `document-title` (5 cases / 5 findings) and
`empty-heading` (11 / 11) are entirely singletons, so the unit cannot move a number on them;
`label` is 11 cases / 17 findings and `link-name` 13 / 21.

**The correlation, on the axis a test consumes.** The judge's own routing decision
(`judge_conformance_correct`, negated: it raises its hand when it grades the draft incorrect) is read
off the three earlier judged passes, restricted to the four scored rules — where the case set **and the
per-case finding ids are identical to the replay pass**, asserted rather than assumed. Within-case pair
agreement against the marginal chance rate gives an intracluster correlation of **+0.168 / +0.464 /
+0.524** across the three passes of that one configuration, and **+0.424 on the majority verdict** —
the quantity the paired test actually consumes (19 of 23 within-case pairs agree against a chance rate
of 0.698; 5 of the 7 multi-finding cases answered one value throughout).

**The decision is arithmetic, not preference.** Design effect `1 + (1.852 − 1)·ρ`, effective n
`54 / design effect`:

| within-case ρ | source | per-finding effective n | beats the 40 clusters? |
|---|---|---|---|
| 0.000 | independence, for reference | 54.0 | yes |
| **+0.424** | **judge routing, majority across passes** (pairwise estimator) | **39.7** | **no** |
| **+0.384** | **the same quantity under the one-way ANOVA estimator** | **40.7** | **marginally yes** |
| +0.168 / +0.464 / +0.524 | judge routing, the three individual passes | 47.3 / 38.7 / 37.3 | 1 of 3 |
| +1.000 | the bound (total within-case agreement) | 29.2 | no |

**⚠️ Both estimators are quoted because the decision sits on the boundary and a strict inequality here
would flip with the estimator.** The pairwise form lands 0.3 observations below the cluster count, the
textbook one-way random-effects form 0.7 above it. **The honest statement is that the two units differ
by less than one observation** — so a per-finding unit buys nothing measurable, while costing an
independence assumption the data does not support on a set where 2 clusters hold 15% of the
observations. Two further grounds point the same way and neither is marginal: the drafter's per-class κ
exists **only** as a per-case number keyed by `act_testcase_id`, so the case is **the only unit at which
Group B's side-by-side comparison is expressible at all** — necessary, and *not* sufficient, for the
reason set out under *what ground (2) can bear* below; and ACT gold is a case-level label, so every
finding inside a case is scored against the same answer key. **What would have decided the other way:** a
within-case correlation at or below zero, which would have left the per-finding effective n near 54
against 40 and made the extra observations real by a wide margin rather than a rounding error. The
*drafter's* verdicts do sit there (ρ = **−0.142** on raw four-value conformance; only 1 of 7
multi-finding cases homogeneous), and that is exactly why the judge's own number is the one the pin
rests on: **the two raters cluster differently, and only one of them is the subject.**

#### ⚠️ What ground (2) can bear — it is weaker than "like-for-like"

An earlier draft of this section claimed the case makes the Group B comparison "only like-for-like at
the case". **That is stronger than the artifacts support, and the correction matters because ground (2)
is one of the three the pin rests on.** What survives:

- **What it bears.** There is no per-finding drafter κ anywhere in the repo — the quantity does not
  exist. So at a per-finding unit the side-by-side comparison could not be *stated* without inventing a
  drafter number, whereas at the case it can. **The case is a necessary condition for the comparison to
  exist.**
- **What it does not bear.** Being at the same unit does not make the two sides comparable. Their
  per-class denominators still differ — 44 against 40, entirely inside `empty-heading` and `link-name` —
  so *sufficiency* needs two further things, and both are T5's to declare:
  1. **Which denominator the judge's side is quoted on**, with the 4-row gap stated per class. The
     recommended handling is the judge over its own 40, the drafter over its 44, both n printed on every
     row, and no arithmetic that subtracts one from the other. Restricting the drafter to the 40 minting
     cases is the alternative — it buys one denominator at the price of dropping 2 real errors from the
     drafter's count, which flatters it, and it means **republishing** a frozen number.
  2. **⚠️ That the drafter's side is recomputed from the replay pass, not read off
     `DrafterKappaBaseline`.** The frozen baseline was built from the acceptance sweep — its `run_ids`
     are `acceptance-2026-07-15…` — so it is the **pre-referent** drafter. Its per-class κ is
     0.000 / 0.675 / 0.127 / 0.211, while the same computation over the replay pass this milestone
     actually replays gives **1.000 / 0.675 / 0.820 / 0.211**: two of four classes are materially
     different, and they are exactly the two the referent work fixed. Its `denominators.findings` is 54,
     the same as the replay pass, which makes the substitution look sound on inspection. **Reading the
     drafter's side off that file would place the blind judge beside a drafter two prompt revisions
     stale, and the "which of them is more often right" verdict would be wrong on `document-title` and
     `label`.**

**Two declared costs, both carried rather than argued away.**

1. **The case collapse is flag-if-any, and it hides what it aggregates.** Measured on the judge's
   majority stream: **2 of the 7 multi-finding cases are internally split** (6 findings), and
   flag-if-any lands on a different answer from a within-case majority on **2 of 40** cases. This
   project has already been burnt by a case-level figure that was false one level below it, so **the
   per-finding table is reported beside the test, never instead of it.**
2. **⚠️ The disagreement rate keeps the FINDING as its denominator** — it is a queue-volume number and
   disagreement is per-finding by construction (code compares the judge's answer against *that
   finding's* draft), so collapsing it would report fewer people-visits than the queue holds. **Two
   units live in this milestone and every figure names which one it is on**, with the count of distinct
   cases the disagreements touch quoted beside the per-finding count.

**⚠️ Three numbers the pin does NOT reach, so they stay per-finding and say so.**

1. **The two injected-detection rates.** A mutation is applied to a *draft*, and M5's comparator
   (`injected_sc_swap` n = 63, `injected_conformance_flip` n = 39) is per-draft. Collapsing them to the
   case would break the only like-for-like available and would need an aggregation rule for a quantity
   that is not a routing decision. **Denominators: 54 and 39, per mutated draft.**
2. **The call budget.** `judge_preflight.json`'s 54 / 39 / ≥603 are call counts off per-finding
   denominators and are unaffected by the pin. Nothing in the budget is an observation count.
3. **⚠️ The confusion matrix changes unit, and its shape cannot say so.** M5's 31/16/8/8 summed to 63
   *findings*; the rebuilt cells sum to **40 cases**. `JudgeConfusion` carries no unit field, so two
   matrices at two units are indistinguishable on disk — and `judge_score.score_judge` builds its cells
   from one `JudgedDraft` per finding, so **it cannot be reused unchanged at the pinned unit**: the rows
   have to be collapsed to the case before they reach it, or the run will freeze a per-finding matrix
   that reads as a per-case one. Whichever path is taken, the unit goes in the run artifact beside the
   cells.

   **⚠️ And the change does not stop at the scorer — it reaches published series.** Every site that
   reads those cells or a rate derived from them, swept rather than assumed:

   | site | what it does with the cells |
   |---|---|
   | `eval/offline.py` `_judged_drafts` | builds one `JudgedDraft` **per finding** — the input that fixes the unit |
   | `eval/offline_build.py` | writes the per-finding judge fields onto each draft row |
   | `eval/judge_score.py` `confusion` / `score_judge` | tallies the four cells and κ, per finding |
   | `eval/offline_freeze.py` | prints κ, miss rate and its n into the freeze summary |
   | `eval/noise_floor.py` | lifts `judge_kappa` and `judge_miss_rate` into `per_metric_sd`; **its own `case_outcomes` is already per-case over 44** — the drafter's denominator, not the judge's 40 |
   | `eval/noise_floor_build.py` | prints `judge κ` per run |
   | `eval/acceptance_snapshot.py` | **pushes the frozen scorecard to the OTLP collector** |
   | `observability/metrics.py` | owns the six benchmark judge gauges — `benchmark_judge_kappa`, `benchmark_judge_miss_rate`, `benchmark_judge_false_alarm_rate`, **`benchmark_judge_injected_flip_detection`**, **`benchmark_judge_injected_swap_detection`**, `benchmark_noise_floor_judge_kappa_sd` — **all names carrying no unit**, so a unit change silently redefines a live series |
   | **`stack/grafana/dashboards/citation_hallucination.json`** | **a checked-in, provisioned dashboard that queries all six by name**, one `stat` panel each: *judge κ (vs W3C gold)*, *miss rate — DANGEROUS*, *false-alarm — annoying*, *injected flip detection ↑bound*, *injected swap detection ↑bound*, *judge κ SD (run-to-run)*. No panel title carries a unit |
   | **`stack/grafana/README.md`** | documents the family as one thing — "the judge's confusion against **external** expert gold (κ, the dangerous miss-rate, false-alarm, injected-detection upper bounds), and the noise floor" — a sentence that goes stale the moment the family splits across two units |
   | `schemas/models.py` | `JudgeConfusion` (no unit field) and `OnlineEvalMetrics.judge_kappa` |

   **⚠️ The consequence is concrete, and it lands on one screen.** Three of those panels — κ, miss rate,
   false-alarm — re-scale to **40 cases** the moment the cells are frozen per case. The two
   injected-detection panels **stay per finding** (54 mutated drafts and 39), because a mutation is
   applied to a draft; and the κ SD panel is a spread over whichever κ it was computed from. So the
   dashboard would display **per-case confusion figures beside per-finding detection rates, adjacent, with
   nothing on the screen saying so** — and the panels would simply re-scale in place, with no version
   marker and no gap in the series to notice.

   **A gauge whose meaning changes while its name does not is the failure this note exists to prevent.**
   Either the case-level figures publish under **new** names, or the existing series are re-based
   deliberately, the dashboard panels and the README sentence are updated in the same change, and the
   re-basing is recorded. **This is a scope handoff, not a redesign: nothing about the dashboard is fixed
   here.** *(Not in scope either: `calibration_snapshot.py` and `metrics.py`'s bare `judge_kappa`, plus
   the four panels reading it, `judge_trusted`, `judge_agreement_rate` and `judgment_correctness_rate` —
   those are the judge-vs-human κ on the self-built gold, already marked *superseded* on the dashboard,
   a different measurement that must not be "fixed" to match.)*

#### ⚠️ What the collapse erases from the test's currency — and it is not a design effect

**Effective n describes the precision of a proportion; the sign test's currency is discordant pairs, and
flag-if-any can delete one outright.** If two configurations raise their hand on the same case for
*different* findings, the collapsed decision is identical and the pair disappears. No design effect can
see that, so it is counted directly — between every pair of the three judged passes, where the
difference is **null by construction**:

| pass pair | findings differing | cases differing | cases holding a differing finding that collapse the same | findings erased | share erased |
|---|---|---|---|---|---|
| 1 vs 2 | 10 | 9 | 0 | 0 | 0.000 |
| 1 vs 3 | 10 | 7 | 2 | 2 | 0.200 |
| 2 vs 3 | 10 | 8 | 2 | 2 | 0.200 |
| **total / mean** | **30 (10.0)** | **24 (8.0)** | **4** | **4** | **0.133** |

Across all three passes together, **15 of 54 findings** and **12 of 40 cases** moved. So the collapse
retains 80% of the finding-level discordant count and **erases 13.3%** of it outright.

#### ⚠️ The repairable ceiling, and the power statement it forces

Deterministic from the replay pass and ACT gold, under the acceptance scorer's own correctness
predicate — **this was measurable here and the power table wrongly deferred all of it to T3:**

| unit | act-wrong | total | note |
|---|---|---|---|
| findings | **15** | 54 | what the judge is shown |
| **judge-visible cases** | **7** | **40** | **the pinned unit — the whole repairable ceiling** |
| drafter cases | 9 | 44 | includes 2 failed honest misses the mechanism cannot reach |

Per class (findings / judge-visible cases / drafter cases): `document-title` 0/0/0, `empty-heading`
1/1/2, `label` **6/1**/1, `link-name` 8/5/6. **The collapse absorbs 8 of the 15 wrong findings** —
`label` folds six wrong findings into one wrong case — so the ceiling is a property of the unit, not
only of the drafter.

**Now set the two numbers beside each other, because the comparison is uncomfortable and it is the
honest power statement this milestone owes T3:**

- **Repairable ceiling: 7 of 40 cases.**
- **Null movement, same configuration, nothing changed: mean 8.0 of 40 cases per pass-pair** (7, 8 and 9),
  12 of 40 over the union of three passes.
- **The sign test's bar is 5 improvements at zero regressions** (`sign_test_p(5, 0) = 0.031`), and the
  null already produces **b = 5** on its own — pass 2 vs 3 improves 5 cases and fails to clear α only
  because it also regresses 3. The three null pairs run b/c = 3/6, 3/4, 5/3 at p = 0.91, 0.77, 0.36.

**Read plainly: the judge's own jitter moves about as many case-level routing decisions as there are
wrong drafts to repair in total.** For Comparison 1 to certify, blind would have to convert nearly the
entire ceiling one-way while jitter scatters ~8 flips at random. That does not invalidate the design —
it is exactly why the threshold is derived from the floor rather than assumed, and why **the
disagreement rate, not the p-value, is the deliverable.** T3 fixes the threshold against these figures;
nothing here pre-registers it.

**⚠️ What is still genuinely unmeasurable at this stage** — and must not be confused with the erasure
above, which *was* measurable and is now measured. The correlation is estimated on *levels*, each
configuration's own routing decision. The within-case correlation of a **real between-configuration
difference** needs two configurations' judge output, and no artifact carries that; the null differences
above are the closest available substitute and they are null by construction. **T3 is the first place a
real difference exists.** The judge-side numbers here are also a **prior, not the thing itself**: they
come from the anchored rubric on referent-free input over a different draft set. The clusters are the
same; the instrument is not.

**Power is this milestone's chief hope, and it is not yet a fact.**

The judge is measured across the whole frozen set at once rather than inside a single finding-class, so
it starts with more observations than any per-class test M7 could run. **But the two figures that decide
whether that helps are unknown at spec time:**

| | status at spec time |
|---|---|
| **Observations** | **settled at T1: 40 cases** — the frozen M7 run's 54 findings collapsed to the pinned unit. **Not M5's 63**, which was a different and larger draft set, and not 54, which is the disagreement rate's denominator rather than the test's |
| **The repairable ceiling** — how many routing decisions are currently wrong | **Settled at T1 for the drafter side: 7 of the 40 case-level units are act-wrong** (15 of 54 findings; 9 of the drafter's 44, 2 of them unreachable). M5's figures do not transfer — they were counted on M5's drafts. What still needs T3 is how many of those 7 the *judge* currently routes wrongly, which needs judge output |
| **Discordant pairs needed for α = 0.05** | **derived from T3's noise floor.** Five suffices only if exactly five pairs are discordant and all five point one way — and **T1 measured the null producing b = 5 on its own**, so five is demonstrably not a safe bar |
| **⚠️ Effect against noise** | **measured at T1 and it is tight: a ceiling of 7 against a mean null movement of 8.0 cases per pass-pair.** Stated here rather than discovered at T5 |

**⚠️ Do not carry M5's figures into this table.** They were measured on a draft set this milestone does
not use, and quoting them as the margin would pre-register a bar against numbers that no longer apply.

### Metrics to report

**Group A — computed from the drafter's frozen row and the judge's answer alone, no gold required.**
These describe the mechanism and are the numbers that would carry over to production. **All of them
belong to Comparison 2**, and the last column says which configuration can actually produce each — an
anchored judge has no verdict of its own, so several of these do not exist on that side.

| Metric | Why | Configuration |
|---|---|---|
| **Disagreement rate**, as a rate **and an absolute count** — *the milestone's primary deliverable*. **Unit: the finding (denominator 54), with the count of distinct cases touched beside it** | the queue volume — and a rate alone hides the workload, so it is never reported without the number of people-visits it implies | **both**, but they are different events: anchored = *it graded the draft incorrect*; blind = *its own answer differs*. Never averaged together |
| **Disagreement rate per finding-class** | concentrated in referent-weak classes, or uniform? mechanism evidence | both, same caveat |
| **Composition of disagreements** | conformance only / SC only / both — three shares | both |
| **⚠️ Direction of disagreement** | when conformance differs, is the drafter or the judge systematically stricter? A one-sided skew means these are **not peer raters** — likely a stronger cloud model correcting a weaker local one, which is useful but a different claim | **blind only** — it needs the judge's own conformance value |
| **drafter–judge κ** | agreement between two raters | **blind only** — an anchored judge produces no second verdict to agree or disagree with, which is the same reason its κ was never methodologically valid |

> **⚠️ `drafter–judge κ` is descriptive and must never become a target.** Raising it means moving the
> drafter toward the judge, which is optimising against the judge — Goodhart. It is reported because it
> characterises the pair, not because it should go up.
>
> **Its unit is the finding**, because that is where the two raters' answers pair one-to-one with no
> aggregation at all — and it is therefore **not** on the same unit as Group B's per-class κ against
> gold, which is per-case. Both are labelled where they appear. **No interval on it is read as tight:**
> the measured within-case correlation puts its effective n near 40, not 54.

**⚠️ Group A is reported per finding and Comparison 1 is tested per case.** That is not an
inconsistency — a queue-volume number counts visits and a paired test counts independent units — but an
unlabelled figure is ambiguous between them, so every number here carries its unit as well as its
comparison.

**Group B — requires ACT gold. Offline measurement only; never computed in production.** The first
three belong to **Comparison 1**; the last is **Comparison 2**'s only gold-scored metric and the one
that says whether following the signal pays.

| Metric | Answers | Comparison |
|---|---|---|
| **Confusion matrix** (release / missed / false alarm / catch) | is the routing decision correct — M5's shape, unchanged | 1 |
| **Share of the disagreement set that is genuinely wrong** | is a human visit worth making | 1 |
| **Share of all real errors that fall inside the disagreement set** | the routing signal's **recall** | 1 |
| **Injected-versus-real detection gap** *(anchored only — see below)* | is anchoring the dominant cause | 1 |
| **⚠️ Each rater's own κ against ACT gold, per finding-class, side by side** | **when the two disagree, which of them is more often right, and on which classes.** Neither Group A metric can answer this, and without it the disagreement rate is a number with no consequence attached: you know how many people to send, not what they will find. **Blind is what unlocks it** — an anchored judge emits a grade of a draft, not a conformance verdict, so it cannot be scored against gold as a rater at all. **⚠️ The drafter's side must be recomputed from the replay pass, NOT read off `DrafterKappaBaseline`** — that file is the pre-referent drafter (see *what ground (2) can bear*) | **2**, blind only |

**The middle two are a pair and are reported together.** Looking only at "how many flagged items are
wrong" hides "how many wrong items were never flagged" — M5's miss rate of 0.67 is the second number,
and it is the uglier one.

### Comparing the two raters against gold — the four conditions, declared before the run

Putting the blind judge's per-class κ beside the drafter's frozen baseline is the point of that last
row, and the two *are* comparable: one eval set, one gold export, one axe-core version, one corpus
version, one collapse rule, and an exact join. **⚠️ The join key is `act_testcase_id`, not
`finding_id`** — corrected at T1: `DrafterKappaBaseline` is a **per-case** measurement ("the unit is one
ACT case, not one finding", `drafter_kappa.py`), so there is no per-finding row on the drafter's side to
join to, and the judge's κ has to be computed at the case to sit beside it at all. That is the same unit
the paired test is pinned to, so one collapse serves both.
**Four things would break the comparison, and all four are declared here rather than argued
afterwards.**

1. **⚠️ The two raters do not carry the same variance, and the table must show it.** The drafter's
   frozen passes are bit-identical, so its κ is a point estimate. A cloud judge is not bit-reproducible
   even at a fixed effort, so its κ is a draw from a distribution. **The judge's side is reported as the
   majority verdict over its passes, or as mean ± SD — never as one pass placed beside a deterministic
   number.**
2. **⚠️ Model and role are confounded, so no capability claim is available.** The judge is a cloud
   reasoning model and the drafter a local one. A κ difference is *different model **and** different
   role*, and may not be attributed to blinding. That is enough for the product question — is a second
   reader worth having — and is not enough for any statement about what either model can do.
3. **⚠️ Framing, not judgment, is a live confound in this repo.** Both models are measured to follow
   prompt framing over page content. The drafter's prompt carries a bucket-framing sentence about
   quality-review items; the judge's rubric carries a differently-worded one. **The blind judge's
   finding-side prompt therefore reuses the drafter's wording as closely as the two roles allow, and any
   surviving difference is quoted in the written read** — otherwise a per-class difference may be the
   framing sentence rather than the rater.
4. **⚠️ Per-class n did not grow, so per-class comparison is descriptive only** — and **the two raters
   do not share a per-class n even at the pinned unit.** The frozen drafter baseline's per-class n is
   `document-title` **5**, `empty-heading` **13**, `label` **11**, `link-name` **15** — summing to **44**,
   not 40, because `drafter_score` deliberately carries the honest misses in as drafts-less cases so a
   failed one counts as the automatic miss it is. **The judge can never hold those rows**: a case that
   mints no finding produces no `Finding`, so there is nothing to judge. The judge's per-class n is
   therefore 5 / 11 / 11 / 13 = 40, and the gap is **class-structured, not spread**:

   | class | drafter units | judge-visible units | gap | of the gap, failed (an automatic miss) |
   |---|---|---|---|---|
   | `document-title` | 5 | 5 | 0 | 0 |
   | `empty-heading` | **13** | 11 | **2** | 1 |
   | `label` | 11 | 11 | 0 | 0 |
   | `link-name` | **15** | 13 | **2** | 1 |
   | **total** | **44** | **40** | **4** | **2** |

   So a per-class κ difference on `empty-heading` or `link-name` is partly a difference of denominator.
   The smallest class still cannot be certified at any effect size, the bar M7 recorded. **No per-class
   number is tested**, and every per-class row carries **both** n. *(Per-finding the two larger classes
   would read 17 and 21 and the two smaller ones would not move at all — all their cases are
   singletons.)*

### The injected-versus-real gap

M5 left the baseline:

```
injected SC swap            1.00
injected conformance flip   0.82
real errors                 0.33   ← a threefold gap
```

**If the gap narrows, anchoring was the dominant cause and the mechanism is demonstrated.**
**If it does not move, anchoring is not the (only) cause** — the remainder is attributed elsewhere and
is explicitly out of scope here. This decomposes M5's two-cause diagnosis quantitatively, and **both
outcomes are results.**

**⚠️ The gap is measured on the anchored configuration only — a property of the method, not a
shortcut.** Both mutations edit the **draft**, and a blind judge never reads the draft: its model call
is byte-identical whether the draft is natural, SC-swapped or conformance-flipped. "Caught" then
reduces to arithmetic. An SC swap always substitutes a criterion the judge did not name, so detection
is **1.00 by construction**. A conformance flip always changes the value, so it is caught exactly when
the judge already agreed — detection is a **restatement of the natural agreement rate**. **Neither
number contains one bit of judge behaviour.** Running the mutations under blind and reporting the
result would trip the guard below on pure algebra, and report the milestone failed for a reason that is
not about the judge.

### No product threshold — but two degenerate endpoints

**There is no pass/fail gate on the routing signal.** Every disagreement goes to a human; no threshold
selects among them, so there is nothing to tune and nothing to certify at the product level.

**But two outcomes would make the mechanism useless, and both are declared in advance:**

| Endpoint | Reading |
|---|---|
| **Disagreement rate very high** | the queue is not filtered — human cost returns to where it started, and the signal is not doing work |
| **Disagreement rate very low** | almost nothing routes — the judge is effectively absent |

These are **health checks read in prose, not thresholds**. No numeric cut-off is pre-registered,
because inventing one without evidence is exactly the mistake this spec is trying not to make. The
rate is reported with its absolute count and interpreted honestly.

### Controls

1. **Nothing upstream moves.** Every finding and every draft comes from M7's frozen
   `citation_grounding_run_1.json`; the drafter is never called. The judge's prompt is the only thing
   that changes.
2. **⚠️ Both configurations receive identical finding-side input, referent included** — including the
   anchored baseline, which is why it has to be rebuilt rather than taken from M5. **The finding-side
   input is built once and frozen as an artifact that both configurations read**, rather than rebuilt
   per configuration: byte-identity is then a property of one file, not a claim about two code paths.
   **⚠️ The candidate list the drafter actually saw was never recorded.** Retrieval is deterministic on
   a frozen corpus, but nothing on disk proves today's list is the one the drafter answered. Freezing
   discharges the comparison this milestone tests (anchored vs blind); the weaker claim — that the
   judge's input equals the drafter's — is **carried as a limitation, corroborated at best, never
   asserted as verified**.
3. **⚠️ Build the judge's own noise floor first.** `judge.py`'s own docstring states that cloud models
   are not bit-reproducible even at temperature 0. **Re-run the anchored configuration N times and
   measure its own variance.** Without this, any improvement could be cloud jitter. This is what M5 did
   for the drafter, applied to the judge.
4. **`judge_version` tracks the change automatically.** The rubric text's sha256 already feeds
   `judge_version`, so the configurations carry distinct version strings by construction.
5. **Iterate the rubric on the dev set, never on the frozen set.** The same overfitting risk M7 faced
   with prompts. Freeze, then touch ACT once, and record how many times it was touched. **The drafter's
   cite-nothing-when-clean convention must be in the rubric before that freeze** — see *what code
   compares*.

### Pre-committed reporting rules

| Outcome | Verdict |
|---|---|
| blind clears the pre-registered test against anchored | **Supported** — anchoring was the dominant cause |
| directional but p ≥ 0.05 | **Worked but uncertifiable** (reported as such, following M7) |
| no movement | **Anchoring was not the cause** — attributed to out-of-scope causes |
| **⚠️ injected detection rises while real detection does not** | **Effective only on clean signal — does not transfer.** *Read on the anchored configuration; the blind numbers are algebra and are not eligible to trip this row* |

**The last row is the most important guard.** This project has walked into the same trap three
times — `document-title`'s recall of 2/2, M8's filename shortcut, and injected detection at 1.00
against 0.33 on real errors. **The fourth time must be recognised.**

---

## What is explicitly not measured

1. **Production routing behaviour.** M9 computes the comparison **offline in `clearway/eval/` against
   frozen drafts**. The orchestrator, the review queue, and the HITL gate are untouched. Wiring the
   signal into the running pipeline is a later milestone; M9 establishes whether it is worth wiring.
2. **Shared retrieval bias.** The shared candidate list is a deliberate trade (see *what the judge
   receives*), and its residual correlation is not quantified here. **⚠️ It is a stronger shared prior
   than the phrase suggests**: the query is built from the rule and its help text, so every finding of a
   rule receives the same criteria in the same order, and both readers inherit that ordering intact.
   **How large the residual is, and whether it should be broken, is carried forward as an open
   requirement with no milestone attached** — no milestone is planned past this one, and naming a future
   one would be inventing a plan the results have not chosen yet.
3. **The benchmark's validity.** The benchmark always scores against ACT gold. Repairing the judge
   makes the benchmark *report* a better judge number; it does not make the benchmark more valid. **If
   the benchmark needed a good judge to be sound, it would be circular.**
4. **The judge as a verifier.** Its role is disagreement detection. Nothing here claims the judge can
   replace human review or that agreement may be read as verification — two independent readers
   agreeing is still `drafter-judged, unverified`.
5. **Any change to the drafter.** Drafts are frozen throughout.
6. **Multi-model ensembles.** The literature is explicit that a three-family ensemble still admits 55%
   of wrong answers and does not address anchoring, at three times the cost. Deliberately not done.
7. **The judge's behaviour on image classes.** The image findings are not among the 54 this milestone
   replays.
8. **Whether any of this transfers to real pages.** All numbers remain on ACT's synthetic pages.

---

## Goal & exit criterion

Convert the judge from a marker grading a paper with the answer on it into an independent rater, and
measure what that does to the routing decision.

**The deliverable, stated plainly: a disagreement rate with an absolute count, and enough context to
know whether following it pays.** Everything below serves that. The paired test on Comparison 1 is a
check on how the number was arrived at, not the thing being delivered.

**Exit criterion:**

1. **The judge's noise floor is established** — the run-to-run variance of a fixed configuration is
   known, and every difference is read against it.
2. **The anchored baseline is rebuilt on referent-carrying input** — M5's figures are not reused.
3. **Under blind, agreement is decided by code**, on raw four-value `conformance` equality and exact
   `sc_id` set match; the model emits no assessment of the draft. **⚠️ The `sc_id` axis carries a
   declared artefact floor** — the drafter cites inconsistently on clean rows (7 of 54, concentrated in
   the two smallest classes), so part of its disagreement is formatting and is reported as such. The
   conformance axis carries the signal; see *what code compares*.
4. **The two configurations are compared at the routing-decision level**, each configuration's decision
   taken from its majority verdict across passes and then collapsed to the case with flag-if-any, scored
   against ACT gold into M5's four cells, under the one-sided sign test (α = 0.05) **on 40 case-level
   units** at **the discordant threshold derived from T3's noise floor** — or reported under one of the
   other pre-committed verdicts.
5. **All Group A and Group B metrics reported**, with the disagreement rate carrying its absolute count,
   `drafter–judge κ` labelled descriptive-only, and **the two raters' per-class κ against ACT gold set
   side by side under the four declared comparison conditions**.
6. **The injected-versus-real gap re-measured on the anchored configuration** and compared against M5's
   threefold gap, with the reason it is not computed under blind recorded in the read.
7. **The observation unit pinned before any run**, with measured clustering behind it. **Settled: per
   case, keyed by `act_testcase_id`, flag-if-any within the case, applied after the per-finding majority
   across passes.** The disagreement rate stays per-finding and says so wherever it is quoted.
8. **All runs frozen**, carrying `judge_model`, `judge_version` and full provenance.
9. **The stale M6 scaffold references clarified** — the composite-metric and reflection-counter fields
   were documented as "filled by M9's reflection loop"; M9 is not that milestone. **Correct the
   description in this milestone's written read; do not edit M6.**

**What would falsify the milestone:** both configurations land cleanly, the noise floor holds, and
blind routes no better than anchored. That would mean anchoring was not the dominant cause — a
valuable negative result, and one that says the remaining correlation lives somewhere M9 did not
touch.

---

## How to use these tickets

**T0** is pre-flight, **makes no model calls**, and can redirect the whole milestone. **T1** fixes the
observation unit. **T2** gives the judge the referent — the shared precondition for both
configurations. **T3** rebuilds the anchored baseline and the noise floor. **T4** is the blind
configuration. **T5** runs the comparison and the diagnostic decomposition. **T6** freezes and writes
the read. The appendix configuration, if run, slots between T4 and T5.

Strictly sequential, one reviewable ticket at a time.

**⚠️ T0 is the stop-loss.** If the `gpt-5.6-luna` snapshot is no longer available, a model change and
a structural change would land together and nothing could be attributed. In that case the anchored
baseline must first be rebuilt under the new model — the milestone gains a stage rather than
proceeding as written. **Settled: the snapshot is available, so the milestone proceeds as written** —
see the pre-flight block in the evidence ledger.

---

## Tickets

### T0 — Pre-flight *(no model calls; stop-loss)*
- **Produces:** the four facts that can redirect the milestone.
- **Detail:**
  - **Whether the `gpt-5.6-luna` snapshot is still available on the account** (the default pinned at
    `clearway/llm/cloud.py:31`). **⚠️ If not, stop and revise the design** — a model change plus a
    structural change is unattributable.
  - **Whether M5's per-finding judge results were retained.** If only the aggregate 31/16/8/8 survives,
    rebuilding the anchored baseline is **mandatory rather than optional**.
  - **The current `reasoning_effort` value**, since it feeds `judge_version` and must be held fixed
    across configurations.
  - **The call budget, computed from the frozen artifact rather than estimated** — the natural-draft
    count, the share of conformance-correct drafts (which sets how many conformance-flip calls the
    anchored configuration adds), and the resulting total per configuration. **Recorded before anything
    is spent.**
- **Acceptance:** all four answered and recorded; if the snapshot is unavailable, a revised design is
  proposed before proceeding.
- **Settled.** All four are in the *Verified* ledger below, and the computed ones are frozen in
  `benchmark/reports/judge_preflight.json` — rebuild with
  `uv run --env-file .env python -m clearway.eval.judge_preflight` (zero model calls; the snapshot
  check is a model *listing*, which runs no inference). **Stop-loss outcome: proceed as written.** The
  pre-flight did, however, turn up one fact that changes the rubric freeze rather than the model pin —
  see the corrected cite-nothing-when-clean paragraph under *what code compares*.
- **Depends on:** —

### T1 — Observation unit and clustering structure
- **Produces:** the clustering profile of the judge's observations, and the pinned unit.
- **Detail:** measure how the judge's observations distribute across cases (findings per case; whether
  verdicts within a case are homogeneous). Decide per-finding or per-case on that basis **and write it
  into the spec before anything runs.** **⚠️ Count the observations, not the manifest rows** — a case
  that mints no finding contributes nothing to judge, so dividing two totals overstates how flat the
  structure is.
- **Rationale:** M6 set the drafter's unit to per-case to avoid pseudo-replication; M8 abandoned a
  statistic entirely for the same reason. **The judge's observations must not be treated as independent
  without stating the ground.**
- **Acceptance:** the clustering profile is frozen; the unit and its rationale are in the spec.
- **Settled — zero model calls.** The unit is **per case**, keyed by `act_testcase_id`, with the case
  decision taken **flag-if-any** over the findings, applied *after* the per-finding majority across
  passes. The full profile and its arithmetic are in *the observation unit* section above and frozen in
  `benchmark/reports/judge_observation_unit.json` (rebuild:
  `uv run python -m clearway.eval.judge_observation_unit`; deterministic — `created_at` is read off the
  replay pass, so a rebuild is byte-identical). **54 observations in 40 clusters against 44 manifest
  rows**; the deciding number is that the judge's own majority routing decision carries a within-case
  correlation of **+0.424** (pairwise) / **+0.384** (ANOVA), putting the per-finding effective n at
  **39.7 / 40.7 against 40 clusters** — the two estimators straddle the boundary, so the finer unit buys
  **under one observation**, which is nothing. The pin is a code constant (`OBSERVATION_UNIT`) rather than prose, so the
  later stages import it instead of restating it. **Also settled here, from the same artifacts:** what
  the case collapse **erases** from the sign test's currency (13.3% of the finding-level discordance
  under the null; 8.0 case-level discordant pairs per pass-pair), and the **repairable ceiling** — 7 of
  40 judge-visible cases act-wrong, 15 of 54 findings, 9 of the drafter's 44 with 2 unreachable. Those
  two numbers together are the power statement handed to T3, and it is tight. Things this turned up that
  were **not** asked for, all recorded above: the Group B join key is `act_testcase_id` and not
  `finding_id`; the disagreement rate has to stay per-finding while the test is per-case; the two raters'
  per-class denominators differ **44 against 40**, so ground (2) is *necessary, not sufficient*;
  **`DrafterKappaBaseline` is the pre-referent drafter and must not supply the drafter's side**; the
  confusion matrix's unit change reaches four unit-free published gauges; and the within-case correlation
  of a *real* between-configuration difference remains unmeasurable until T3.
- **Depends on:** T0

### T2 — Give the judge what the drafter saw
- **Produces:** `_judge_user_prompt` carrying `Finding.referent` and the retrieved SC candidate list.
- **Detail:** the judge currently receives only `finding.html`, while since M7 the drafter also
  receives the resolved accessible name, page-topic signal, or surrounding context. **Blinding is only
  valid if the judge sees the same material.** The retrieved candidate list is passed too — shared
  question, independent answer.
- **⚠️ Acceptance:** the finding-side input is **built once and frozen as an artifact both
  configurations read**, and byte-identity across the two is asserted by test against that file; only
  the presentation of the draft differs. The artifact records that the candidate list was **rebuilt,
  not recovered**, so no later reader mistakes it for the one the drafter saw.
- **Depends on:** T1

### T3 — Rebuild the anchored baseline + the judge noise floor
- **Produces:** the current rubric's performance on **referent-carrying** input, and its own variance.
- **Detail:** replay the judge over M7's frozen drafts, **running the same configuration N times**
  (N ≥ 3). Compute the full Group A and Group B metric set.
- **Rationale:** cloud models are not bit-reproducible even at temperature 0. **Without a noise floor,
  any difference could be cloud jitter.**
- **Acceptance:** the baseline is frozen with per-run variance; M5's figures are retained **as
  historical context only**, never as the paired comparator. **⚠️ The discordant count required by T5's
  sign test is derived from this floor and written into the spec here — before T4 makes its first
  call.** **⚠️ The floor is measured at the unit T1 pinned** — a case-level discordant count, taken
  after both collapses in their pinned order — because a threshold counted per finding cannot govern a
  test scored per case. Two figures are reported, not one: the **per-case** discordant count that fixes
  the threshold, and the **per-finding** count beside it, so the flag-if-any collapse's cost stays
  visible.
- **⚠️ The scorer it would be natural to reuse is on the wrong unit.** `judge_score.score_judge` tallies
  the four cells from one `JudgedDraft` per **finding**, and `JudgeConfusion` has no field that records
  which unit its cells are on. So the judged rows must be collapsed to the case *before* they reach the
  scorer, and the unit must be written into the run artifact beside the cells — otherwise this stage
  freezes a per-finding matrix that a later reader takes for a per-case one, and the two are
  indistinguishable on disk. See *the observation unit*.
- **⚠️ Also measured here, and only here:** the within-case correlation of a **real**
  between-configuration difference. T1 measured the correlation of each configuration's routing *levels*,
  and it measured the *null* difference between passes of one configuration — but the contrast the sign
  test consumes is anchored ↔ blind, and no artifact carries two configurations' judge output. Report it
  beside the threshold; if it comes out materially **negative**, say so, because a per-case collapse would
  then be costing power rather than buying honesty.
- **⚠️ The threshold is set against a ceiling of 7.** T1 measured 7 of the 40 case-level units act-wrong,
  against a mean null movement of 8.0 cases per pass-pair, with a null `b` reaching 5 — the exact bar
  `sign_test_p(5, 0)` clears. **So five discordant pairs is demonstrably not a safe threshold**, and
  whatever is fixed here must be justified against those two figures rather than against α alone. If the
  arithmetic says no attainable effect can clear the floor, that is a finding to record here, not a
  reason to loosen the test.
- **Depends on:** T2

### T4 — The blind configuration
- **Produces:** a judge that never sees the draft and only answers independently; agreement computed in
  code.
- **Detail:** the judge receives the finding (referent + candidate list) and emits its own conformance
  and cited SC. **`citation_correct` and `conformance_correct` are derived in code** — raw four-value
  equality on conformance, exact set match on `sc_id` — **and the model no longer emits those
  booleans.** This makes the judge a genuine independent rater and returns κ to what it claims to
  measure.
- **⚠️ Where the judge's own answer is stored, and where it is not.** The two derived booleans fit
  `JudgeResult` unchanged, because the verdict is already assembled in code. **The judge's own
  conformance and cited SC are not added to it** — `JudgeResult` is a production shape under
  `CONTRACTS.md` §3 (`extra="forbid"`, and editing §3 obliges §5 + §6 in the same change), and putting
  an eval-only experiment's fields into the product contract makes every consumer handle them being
  absent forever. They go in the run artifact, where every other eval-only field already lives. Group
  A's *direction of disagreement* is what needs them, so they are mandatory there.
- **⚠️ The artifact carries an explicit configuration marker.** `citation_correct` and
  `conformance_correct` mean *"the drafted SC is right"* under anchored and *"the judge named the same
  SC"* under blind — same field names, different questions. Without a marker the two artifacts are
  indistinguishable on disk and will eventually be compared wrongly.
- **⚠️ Acceptance:** the model's output contains **no** assessment of the draft; agreement is decided
  entirely in code and reproducible from the frozen artifact; run-to-run variance is read against T3's
  noise floor.
- **Depends on:** T3

### T5 — Comparison and diagnostic decomposition
- **Produces:** **both** comparisons, kept apart — Comparison 1 (anchored ↔ blind) and Comparison 2
  (blind judge ↔ frozen drafter). Neither is reported without naming which it is.
- **Detail:** map each configuration's output to a **binary routing decision** (flag / release) from
  its **majority verdict across passes**, collapse that to the case with **flag-if-any** (the pinned
  order — passes first, findings second), score the case decision against ACT gold into M5's four cells,
  and run the **one-sided exact sign test (α = 0.05)** on that per-case unit, at the discordant
  threshold pinned in T3. Report the full Group A and Group B metric sets, the two raters' per-class κ
  against gold side by side under the four declared conditions, and the injected-versus-real gap
  **on the anchored configuration**.
- **⚠️ The per-finding table is reported beside the test, never instead of it.** The case collapse
  disagrees with a within-case majority on 2 of 40 cases and hides an internal split in 2 of the 7
  multi-finding cases; a case-level figure that is false one level below it is a mistake this project has
  already made once.
- **⚠️ Acceptance:** if injected detection rises while real detection does not, the verdict is
  **effective only on clean signal** — success may not be claimed. **The guard is read on anchored
  only**; blind's injected numbers are arithmetic and are not eligible to trip it. Degenerate endpoints
  on the disagreement rate are read in prose.
- **Depends on:** T4

### T6 — Freeze and write the honest read
- **Produces:** the frozen final state and its written analysis.
- **Detail:** report both configurations across every metric, the noise floor, and cost. The written
  read must state plainly whether anchoring was the dominant cause, what the disagreement rate means
  for human workload in absolute terms, **and that under the blind configuration κ is
  methodologically valid for the first time**. It must also **correct the stale M6 scaffold
  description** — those fields were documented as being filled by "M9's reflection loop", and M9 is
  not that milestone; record what actually fills them, without editing M6.
- **Rule: report ugly numbers as they are.** The unacceptable failure is not a low score but an
  **untrustworthy** one — passing off injected detection as capability, reporting the flagged-item hit
  rate without the miss rate, or reading cloud jitter as improvement.
- **⚠️ Rule: lead with the disagreement rate, not the p-value.** The rate and its absolute count are
  the deliverable; Comparison 1's test is a check on how it was arrived at. A report that opens on a
  significance verdict has buried its own result.
- **⚠️ Rule: every number names its comparison and its unit.** Comparison 1 is judge vs judge;
  Comparison 2 is the blind judge vs the frozen drafter. They share a run and several metric names, so an
  unlabelled figure is ambiguous even to someone who read this spec. **And two units are in play** — the
  tested comparison is per case (40), the disagreement rate is per finding (54) — so a bare count is
  ambiguous even once its comparison is named.
- **⚠️ Rule: write it for someone who did not build it.** Three metric families land here and they
  answer three different questions — **how much human work the mechanism creates** (disagreement rate),
  **how alike the two readers are** (drafter–judge κ), and **which of them is more often right** (each
  rater's κ against gold). **State which question a number answers, in a sentence, before the number.**
  Absolute counts beside every rate; no metric name used without a plain-language gloss on first use;
  the four comparison conditions stated where the side-by-side table appears, not in a footnote. The
  existing reports in `docs/` are denser than this, and that is not the target here.
- **Depends on:** T5

---

## Runs and cost

| Configuration | Passes | Judge calls per pass | Why more than one call per finding |
|---|---|---|---|
| anchored (baseline + noise floor) | 3 | one natural **+ one SC-swap + one conformance-flip per conformance-correct draft** | the injected gap is measured here, and every mutation is its own judge call |
| blind | 3 | one per finding | the mutations are inert here — see *the injected-versus-real gap* |
| *commit-first (appendix, optional)* | *3* | *as anchored if the gap is wanted, else as blind* | |

**⚠️ Well above the natural-draft count, because the injected mutations are judge calls too** — the
earlier draft of this spec counted only the natural pass and understated the milestone by a multiple.
The exact figure follows from the frozen run's size and its share of conformance-correct drafts;
**T0 computed it from the artifact and recorded it before anything was spent.** Zero drafter calls, and
the order of magnitude stays far below the preceding three milestones.

### The budget, counted off the frozen artifact — recorded before the first call

`citation_grounding_run_1.json` (sha256 `191e40e5…`) carries **54 natural drafts over 40 cases**, of
which **39 are conformance-correct** against ACT gold under `stats.COLLAPSE_RULE` — a share of
**0.722**, which is what makes the anchored side's cost depend on the drafter's accuracy rather than on
the case count alone.

| Configuration | Per pass | Passes | Total (floor) |
|---|---|---|---|
| **anchored** | 54 natural + 54 SC-swap + 39 conformance-flip = **147** | 3 | **441** |
| **blind** | 54 | 3 | **162** |
| **Grand total** | | | **603 judge calls — a FLOOR, not the spend** |

*(The optional commit-first probe would add 441 if the injected gap is wanted there, or 162 if not —
outside the 603, and nothing in the exit criterion depends on it.)*

**⚠️ 603 is the floor and the ceiling is 1206, because a retry leaves no trace on disk.** `Judge` takes
`retries: int = 1` and neither harness that constructs it overrides that, so **one logical call may
reach the model twice** when the first response is off-schema. The run artifact writes one row either
way, so the difference between floor and ceiling **cannot be recovered from the artifact afterwards** —
it is only visible in the provider's usage. This project has already been caught by exactly this: the
image-channel work reported a call total that was a floor for the same reason. **Quote the figure as
"≥ 603 calls, ceiling 1206", never as "603 calls",** and read the real spend off the provider.

Frozen at `benchmark/reports/judge_preflight.json`; reproduce with
`uv run --env-file .env python -m clearway.eval.judge_preflight`. **The record carries a
`reproducible_digest` over everything but its own timestamp**, which is what a rebuild is checked
against — a wall-clock `created_at` would otherwise make a genuine edit and a re-run look alike.

**⚠️ Read 39 carefully — three different quantities in this milestone are 39.** The conformance-flip
denominator here (39 of 54 M7 drafts), M5's conformance-flip n (39 of 63 M5 drafts), and M5's
false-alarm denominator (39) are numerically equal and mean different things over different draft sets.

For scale: M7's drafter passes took 2–3.5 hours each (a local thinking model at ~11 tok/s with no cap
on its reasoning budget). **M9 makes no drafter calls at all** — every draft is reused from the frozen
artifact. **⚠️ The per-call cost and latency of the cloud judge remain UNVERIFIED and cannot be settled
by T0** — no frozen artifact records judge token usage, so the only way to observe them is to make a
call, which T0 does not do. The order of magnitude is nonetheless far below the preceding three
milestones; the first anchored pass is where the real figure appears, and it is recorded there.

**This is the cheapest and best-powered milestone in the project.**

---

## Evidence ledger

**Verified — read from the repo or the external literature at spec time.** `clearway/llm/cloud.py`
still pins `_DEFAULT_MODEL = "gpt-5.6-luna"`, overridable via `CLEARWAY_JUDGE_MODEL`; the judge module
is intact and **was not removed**. `judge.py` raises at construction if the judge model equals the
drafter model, so the "use a different family" half of the standard advice **is already done**.
`judge_version` is the first 8 hex of the rubric text's sha256 plus reasoning effort, so any rubric
edit is tracked automatically. `_JudgeVerdict` uses `extra="forbid"`, required for the cloud Responses
API's strict json-schema mode. `_judge_user_prompt` passes only `finding.rule_id`, `help`, `target`,
`html`, plus the draft's conformance and cited SCs — **it does not pass `Finding.referent`**, which
exists post-M7 and which the drafter does use. `DraftRow` carries `conformance` (a four-value enum),
`citations`, `remediation`, `severity` and `confidence`, the last documented in-schema as decorative.
`stats.py` defines `FLAGS = {does_not_support, partially_supports}` and
`CLEAN = {supports, not_applicable}`, with a `partial_flags` knob for sensitivity. In the frozen M7
run the drafter emitted `supports` 28 times, `does_not_support` 21, `partially_supports` 5, and
`not_applicable` 0. **⚠️ Corrected at T0: `cited_sc_ids` is empty on 21 of the 28 `supports` rows, not
on all 28** — the other 7 cite anyway, and they are the whole of `document-title` (3 of 3) plus 4 of
`empty-heading`'s 6, while `label` (7 of 7) and `link-name` (12 of 12) are uniformly empty. Every
flagging row does cite, every citing row names exactly one SC, and exactly one distinct SC per rule
(`label` 3.3.2, `empty-heading` 2.4.6, `document-title` 2.4.2, `link-name` 2.4.4). So the unwritten
convention the rubric has to carry is a **majority habit with a class-structured exception**, not an
invariant — and one run old: in the preceding frozen run all 27 of its `supports` rows cited, several
with two or three SCs (see *what code compares*). The frozen draft record holds `finding_id`, `target`,
`conformance`, `cited_sc_ids`, `confidence` and
`remediation` — **no `Finding`, so no `html`, `help` or `referent`**, which is why the judge's input has
to be rebuilt by re-scanning rather than read off the artifact. M5 judge figures: κ 0.137; correct_release 31 / missed_error 16 / false_alarm 8 /
correct_catch 8 (63 total); miss_rate 0.67; false_alarm_rate 0.205; injected_sc_swap 1.00 (n = 63);
injected_conformance_flip 0.82 (n = 39); the flagged-item hit rate of 8/16 against a base rate of
24/63 is a 1.31× enrichment. `offline_inject.py` provides two pure mutations with no LLM and states
that injected detection is an **upper bound** on real catching. **External literature:** arXiv
2607.05904 measures a verify prompt's false-positive rate at 0.719; requiring the judge to commit its
own answer first — candidate still visible — drops it to **0.012** while the judge commits correctly
97% of the time; full blinding gives 0.012 at discrimination 0.96; the effect reproduces across
families; **a three-family ensemble still accepts 55% of wrong answers**; the operative cause is
candidate anchoring rather than family, scale or visibility. Reflection-loop literature distinguishes
**intrinsic** self-correction (the model critiques itself) from **extrinsic** (external verifiers,
tools, or a stronger LLM), reports that intrinsic self-correction without external feedback often
degrades performance, and documents an accuracy–correction paradox in which models with higher initial
accuracy benefit less. Agent pattern catalogues distinguish a reflection loop (agent self-assesses)
from a Ralph loop (deterministic checks decide the exit) from evaluator-optimizer (a second agent
approves), and advise adding reflection only where the failure mode is verifiable against an external
source.

**Inference — reasoned, not directly observed.** That Clearway's judge co-signing 15 of 16 false
positives is a symptom of anchoring: the symptom matches the mechanism the literature describes, but
**this has not been measured on Clearway** — T3 and T4 are what would verify it. That structured
output generates fields in schema order, and therefore that field order can enforce commitment: this
is general behaviour of strict json-schema mode and **has not been verified against this repo's cloud
client**. That blinding restores κ to its "two independent raters" definition is a methodological
argument, not an experimental result. ~~That clustering is light is an impression, not a
measurement~~ — **measured at T1 and no longer an inference; see the settled block below.** That sharing
the retrieved candidate list keeps disagreement attributable to judgment is a design argument; the size
of the residual shared bias is unmeasured. That today's retrieval reproduces the list the drafter
answered follows from a deterministic embedder over a frozen corpus — **nothing on disk records the
original, so this can be corroborated but never verified**.

**Settled at pre-flight — zero model calls spent.** Frozen in `benchmark/reports/judge_preflight.json`
(rebuild: `uv run --env-file .env python -m clearway.eval.judge_preflight`).

1. **The `gpt-5.6-luna` snapshot is still addressable on the account.** Established from the provider's
   **model listing** (`GET /v1/models`, 125 ids, `gpt-5.6-luna` present, alongside `gpt-5.6-sol` — the
   technique classifier's pin — and `gpt-5.6-terra`). A listing is metadata: no inference, no tokens,
   no cost. **⚠️ It proves the id resolves, not that a Responses call at `effort=medium` will succeed**
   — that is one call away and is not spent here. **Stop-loss outcome: proceed as written.** An
   unreadable listing raises rather than reporting the snapshot as retired, so a network failure can
   never masquerade as a retirement. **The listing is read from the host the judge's own provider would
   reach** — the endpoint follows `OPENAI_BASE_URL` / `OPENAI_API_BASE`, which the `litellm` route the
   cloud client uses also honours, and the record states that **no override was in force** when this
   answer was taken. A check against a hardcoded host could otherwise confirm a snapshot on a provider
   the judge never calls.
2. **M5's per-finding judge results were retained in full — but they are on the wrong drafts.** All
   three M5 passes (`benchmark/runs/run_{1,2,3}.json`) carry `judge_conformance_correct`,
   `judge_citation_correct` and `judge_verdict` on **63/63 rows each**, and run_1 re-derives the frozen
   31/16/8/8 exactly. So nothing was lost. **⚠️ It changes nothing about the rebuild, because the run
   this milestone replays carries no judge output at all**: `citation_grounding_run_1.json` is
   drafter-only, 0 of its 54 rows judged. Rebuilding the anchored baseline is therefore **mandatory**,
   and would have been even had M5 kept nothing — the retained rows are usable only as historical
   context, exactly as the exit criterion already requires. **A second reason the M5 rows are not a
   baseline:** their injected results are keyed by `rule_name` and `caught` alone, with no
   `finding_id`, so they cannot be joined back to a finding or re-partitioned per class.
3. **`reasoning_effort` is `medium`, and `judge_version` is `rubric=e396f37f; effort=medium`.**
   Resolution order is `CLEARWAY_JUDGE_EFFORT` → `_DEFAULT_EFFORT` (`clearway/llm/cloud.py:32`); the
   checked-in `.env` does **not** set the variable (`env.example` does, to the same value), so the
   effective value comes from the code default either way. **⚠️ The rubric hash is unchanged since M5**
   — `e396f37f` in `run_{1,2,3}.json` and in today's `judge.py` — so the anchored configuration is the
   same instrument M5 measured, and the rebuilt baseline will differ from M5's by its *input* alone.
   **`judge_version` therefore cannot tell the two anchored measurements apart**; only a T2 or T4 rubric
   edit moves it, and until one lands the version string is not the thing that distinguishes runs.
4. **The call budget is ≥ 603 judge calls, ceiling 1206** — anchored 3 × 147 = 441, blind 3 × 54 = 162 —
   counted from 54 natural drafts of which 39 (0.722) are conformance-correct under
   `stats.COLLAPSE_RULE`. Full arithmetic in *Runs and cost*. The correctness predicate is pinned by test
   to the acceptance scorer's own `act_correct`, so the budget is counted under the rule the run will be
   scored by. **⚠️ 603 is a floor:** `Judge(retries=1)` lets one logical call reach the model twice and
   the artifact records one row either way, so the record carries `grand_total_is_a_floor` and
   `grand_total_ceiling` rather than a single `grand_total` — a bare total would be read as the spend.
   The attempt count is derived from `Judge`'s declared default, and a test fails if any call site starts
   overriding it.

**Settled at the observation-unit stage — zero model calls.** Frozen in
`benchmark/reports/judge_observation_unit.json` (rebuild:
`uv run python -m clearway.eval.judge_observation_unit`; deterministic, so a rebuild is byte-identical
and the freeze is pinned by file comparison rather than by a self-digest).

1. **The structure: 54 observations in 40 clusters, against 44 manifest rows.** One judge call per minted
   finding; one cluster per minting ACT case. The 4 non-minting rows are honest misses that are never
   judged, so they are rows and not clusters — 54/44 = 1.23 against the true 54/40 = **1.35**. Sizes
   1×33, 2×2, 3×3, 4×2; **7 multi-finding cases hold 21 of the 54 observations (38.9%)**; Kish mean
   cluster size `Σm²/Σm` = **1.852**. **All the clustering is in two classes** — `label` (11 cases / 17
   findings) and `link-name` (13 / 21); `document-title` (5 / 5) and `empty-heading` (11 / 11) are
   entirely singletons, so the unit cannot move a number on them.
2. **The judge's own routing decision clusters within a case; the drafter's verdicts do not.** Read off
   the three earlier judged passes restricted to the four scored rules — **the same 40 cases with the
   same per-case finding ids as the replay pass, asserted rather than assumed** — the within-case
   intracluster correlation of `judge_conformance_correct` is **+0.168 / +0.464 / +0.524** across the
   three passes and **+0.424 on the majority verdict** (19 of 23 within-case pairs agree against a
   chance rate of 0.698; 5 of 7 multi-finding cases uniform). The drafter's own verdicts on the replay
   pass go the other way: **ρ = −0.142** on raw four-value conformance, 1 of 7 multi-finding cases
   uniform, within-case pair agreement 8/23 = 0.348 against a chance rate of 0.429 — *below* chance.
   Under the FLAG/CLEAN collapse the drafter reads ρ = +0.042; on the cited-SC set, +0.363; on the joint
   (conformance, SC set) pair, +0.177.
3. **Therefore per case, and it is arithmetic rather than preference.** Design effect
   `1 + (1.852 − 1)·ρ`: the per-finding effective n is **39.7 at ρ = +0.424** against the **40** clusters
   a per-case unit gives outright, 38.7 and 37.3 at two of the three individual passes, 54.0 only at
   ρ = 0 and **29.2** at the ρ = 1 bound (below the cluster count, because unequal sizes weight the big
   clusters). **⚠️ Two estimators, deliberately both quoted:** the same majority stream gives
   ρ = **+0.384** under the one-way random-effects (ANOVA) form, hence an effective n of **40.7** —
   *above* the cluster count. The two straddle it, so the claim is not a strict inequality but the
   weaker and more defensible one: **the two units differ by under a single observation**, so the finer
   one buys nothing measurable while costing an independence assumption the data does not support, with
   2 clusters holding 15% of the observations. The other two grounds are not marginal and carry the pin
   on their own.
4. **⚠️ Two statements elsewhere in the repo that this measurement makes false, recorded rather than
   silently edited.** `drafter_score.py` justifies per-case scoring with "within one ACT case the
   elements are homogeneous (the same judgment repeated)" — the *gold* is homogeneous by construction
   (`act_gold.py`, and that claim stands), but **the raters' answers are not**: 6 of the 7 multi-finding
   cases carry mixed drafted verdicts and within-case agreement is below chance. The per-case unit
   survives on the three grounds above; **its stated reason in that docstring does not.** And
   `MetricCI.effective_n`'s clustering caveat — "cases cluster in ~5 rules … the honest precision is
   `effective_n` (≈ #rules)" — **does not describe the judge's routing stream**: at the rule layer the
   correlation is **−0.048** over 411 pairs, so the routing correlation lives at the case, not at the
   rule. It also does not transfer to a paired contrast in the first place, because both configurations
   receive the same per-rule framing and a shared level effect cancels.
5. **Context, not part of the pin: the judge disagreed with itself on 15 of 54 findings** across three
   passes of one fixed configuration (27.8%) — a prior on why the repeat-pass collapse exists at all, and
   on why T3 measures the floor before T5 fixes a threshold.
6. **What the pin does not reach, stated so it is not assumed to:** the two injected-detection rates
   (per mutated draft, n = 54 and 39), the call budget (call counts, not observations), and — the one
   with a code consequence — the confusion matrix, whose cells now sum to 40 rather than 63 while
   `JudgeConfusion` has no field that says so, `judge_score.score_judge` builds them per finding, and
   four **unit-free gauge names** publish rates derived from them. The full site list is in *the
   observation unit*.
7. **One cluster is one page — established by hashing, not inferred, and it is guarding against
   something the corpus contains by the dozen.** The 40 in-scope minting cases yield **40 distinct
   fixture digests**, checked at freeze time and raised on collision; and the reassuring half that
   actually carries the claim: **all 44 manifest rows yield 44 distinct digests — no two rows of the gold
   share bytes.** But the tree around them is full of duplicates: **67 fixture files, 55 distinct
   digests, 12 duplicate groups** (all of size 2), so **24 files — better than a third of the corpus —
   sit in a duplicate pair.** The pattern is perfectly regular: **all 12 pairs are
   `Link is descriptive` against `Link in context is descriptive`**, the two sibling link rules assigning
   their own outcome to the same page; **not one group lies within a single rule.**
   **⚠️ An earlier draft rested this on `act_gold.contradictory_gold_twins()` being empty, which cannot
   support it — and now the reason is quantified.** Two filters hide all 12 groups from that helper:
   it iterates only **manifest rows**, and the AAA-only link rule is outside `RULE_TO_AXE`, so **9 of the
   12 groups retain exactly one row and 3 retain none** (those 3 are `inapplicable` on both sides, which
   the manifest builder skips) — **no group retains two**; and it then keeps only groups whose ACT
   outcomes *differ*, which is **2 of the 12**. So its emptiness is doubly uninformative. What keeps the
   clusters distinct is not scarcity of duplicates but **which side of each pair the scope admitted** — a
   scope change re-admitting that rule would put two clusters on one page, which is why the check raises
   rather than reports.
8. **The repairable ceiling and the null floor** — `7/40` cases against a mean `8.0/40` per pass-pair,
   with the full tables and the b/c split in *the observation unit*. Both were measurable here; the power
   table previously deferred all of the first to T3.

**A partial judge noise floor already exists, on the wrong input *and on the other unit*.**
`benchmark/reports/noise_floor.json` records a 3-pass SD of **0.158 on judge κ** and **0.105 on the judge
miss rate**, and the four routing cells move materially across those passes — 31/16/8/8, 28/21/11/3,
31/18/8/6. **⚠️ Those cells are PER FINDING and sum to 63**, M5's unscoped draft count; T3's floor is a
**per-case** discordant count over 40, so the two are not the same quantity and neither figure may be
substituted for the other. *(The scoped per-case null movement over the same passes is the 8.0-per-pair
figure measured at T1, which is the directly comparable number.)* It is, however, a prior worth stating:
this judge's own run-to-run movement is already the size of the effects M9 hopes to detect, which is
exactly why T3 measures the floor before T5 fixes a threshold.

**Unverified — settle in the Plan phase.** The judge's actual run-to-run variance under a fixed
configuration **on referent-carrying input** (T3). **The real unit cost and latency of cloud judge
calls — ⚠️ not settleable at T0:** no frozen artifact records judge token usage, so observing them
requires a call, and the first anchored pass is the earliest honest place to record them. What
disagreement rate the blind configuration actually produces, and therefore what human workload it
implies.

---

## Appendix — the commit-first configuration

**Optional. A mechanism probe, not a product decision.**

Between *anchored* (sees the draft, grades it) and *blind* (never sees the draft) sits a third setting:
the judge sees the draft but must **write its own verdict first**. The literature reports this alone
collapses the false-positive rate from 0.719 to 0.012 — nearly the full effect of blinding, with the
candidate still visible.

Running it separates two effects that *blind* bundles together: **committing before assessing** versus
**not seeing the candidate at all**. If commit-first captures most of the improvement, anchoring is
confirmed as the mechanism in the narrowest possible sense.

**Implementation note — schema field order enforces it mechanically.** `judge.py` calls `complete_json`
with a Pydantic schema under the cloud Responses API's strict json-schema mode, and **structured output
generates fields in schema order.** Placing the judge's own verdict before the grading fields makes
commitment a constraint on generation order rather than an instruction in prose:

```
own_conformance      ← generated first
own_cited_sc
citation_correct     ← generated after
conformance_correct
rationale
```

**Nothing in the exit criterion depends on this configuration.** It is worth running if the cost is
acceptable and the mechanism question is interesting; skipping it costs the milestone nothing.
