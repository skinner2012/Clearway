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
more findings than it lost on, and that question has no answer until it is known how many findings flip
**when nothing changes at all**. A cloud judge run twice under one configuration produces discordant
pairs of its own; a threshold chosen before that count is known can be cleared by jitter alone. **T3
measures the floor, and the discordant count required for a result is fixed from it, in writing, before
T4's first call.** What is fixed *here* is the test family — one-sided exact sign test, α = 0.05, on
the unit T1 pins. What is not fixed here is how many discordant pairs constitute a result.

**⚠️ Each configuration's routing decision comes from its N passes, never from one.** A single pass of
a non-reproducible judge is one draw. The per-finding decision that enters the paired test is that
configuration's **majority verdict across its passes**, and the pass-to-pass disagreement is reported
beside the result.

**⚠️ The observation unit must be fixed and pre-registered before any run.** M6 set the drafter's unit
to per-case precisely to avoid pseudo-replication, and M8 abandoned a statistic entirely for the same
reason. Clustering looks lighter here, but **the judge's observations must not be treated as
independent units without stating the ground.** T1 measures the real structure and pins the unit before
anything runs.

**Power is this milestone's chief hope, and it is not yet a fact.**

The judge is measured across the whole frozen set at once rather than inside a single finding-class, so
it starts with more observations than any per-class test M7 could run. **But the two figures that decide
whether that helps are unknown at spec time:**

| | status at spec time |
|---|---|
| **Observations** | the frozen M7 run's findings, at the unit T1 pins — **not M5's count**, which was a different and larger draft set |
| **The repairable ceiling** — how many routing decisions are currently wrong | **T3 measures it.** M5's missed errors and false alarms were counted on M5's drafts; M6–M8 then cut the drafter's false positives, so fewer drafts are wrong now and that ceiling does not transfer |
| **Discordant pairs needed for α = 0.05** | **derived from T3's noise floor.** Five suffices only if exactly five pairs are discordant and all five point one way |

**⚠️ Do not carry M5's figures into this table.** They were measured on a draft set this milestone does
not use, and quoting them as the margin would pre-register a bar against numbers that no longer apply.

### Metrics to report

**Group A — computed from the drafter's frozen row and the judge's answer alone, no gold required.**
These describe the mechanism and are the numbers that would carry over to production. **All of them
belong to Comparison 2**, and the last column says which configuration can actually produce each — an
anchored judge has no verdict of its own, so several of these do not exist on that side.

| Metric | Why | Configuration |
|---|---|---|
| **Disagreement rate**, as a rate **and an absolute count** — *the milestone's primary deliverable* | the queue volume — and a rate alone hides the workload, so it is never reported without the number of people-visits it implies | **both**, but they are different events: anchored = *it graded the draft incorrect*; blind = *its own answer differs*. Never averaged together |
| **Disagreement rate per finding-class** | concentrated in referent-weak classes, or uniform? mechanism evidence | both, same caveat |
| **Composition of disagreements** | conformance only / SC only / both — three shares | both |
| **⚠️ Direction of disagreement** | when conformance differs, is the drafter or the judge systematically stricter? A one-sided skew means these are **not peer raters** — likely a stronger cloud model correcting a weaker local one, which is useful but a different claim | **blind only** — it needs the judge's own conformance value |
| **drafter–judge κ** | agreement between two raters | **blind only** — an anchored judge produces no second verdict to agree or disagree with, which is the same reason its κ was never methodologically valid |

> **⚠️ `drafter–judge κ` is descriptive and must never become a target.** Raising it means moving the
> drafter toward the judge, which is optimising against the judge — Goodhart. It is reported because it
> characterises the pair, not because it should go up.

**Group B — requires ACT gold. Offline measurement only; never computed in production.** The first
three belong to **Comparison 1**; the last is **Comparison 2**'s only gold-scored metric and the one
that says whether following the signal pays.

| Metric | Answers | Comparison |
|---|---|---|
| **Confusion matrix** (release / missed / false alarm / catch) | is the routing decision correct — M5's shape, unchanged | 1 |
| **Share of the disagreement set that is genuinely wrong** | is a human visit worth making | 1 |
| **Share of all real errors that fall inside the disagreement set** | the routing signal's **recall** | 1 |
| **Injected-versus-real detection gap** *(anchored only — see below)* | is anchoring the dominant cause | 1 |
| **⚠️ Each rater's own κ against ACT gold, per finding-class, side by side** | **when the two disagree, which of them is more often right, and on which classes.** Neither Group A metric can answer this, and without it the disagreement rate is a number with no consequence attached: you know how many people to send, not what they will find. **Blind is what unlocks it** — an anchored judge emits a grade of a draft, not a conformance verdict, so it cannot be scored against gold as a rater at all. The drafter's side already exists, frozen, in `DrafterKappaBaseline` | **2**, blind only |

**The middle two are a pair and are reported together.** Looking only at "how many flagged items are
wrong" hides "how many wrong items were never flagged" — M5's miss rate of 0.67 is the second number,
and it is the uglier one.

### Comparing the two raters against gold — the four conditions, declared before the run

Putting the blind judge's per-class κ beside the drafter's frozen baseline is the point of that last
row, and the two *are* comparable: one eval set, one gold export, one axe-core version, one corpus
version, one collapse rule, and a join on `finding_id` that is exact rather than approximate.
**Four things would break it, and all four are declared here rather than argued afterwards.**

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
4. **⚠️ Per-class n did not grow, so per-class comparison is descriptive only.** The classes are the
   sizes M6 and M7 already worked with, and the smallest cannot be certified at any effect size — the
   bar M7 recorded. **No per-class number is tested.** Say so in the table, rather than letting a reader
   infer significance from a bold figure.

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
   taken from its majority verdict across passes, scored against ACT gold into M5's four cells, under
   the one-sided sign test (α = 0.05) at **the discordant threshold derived from T3's noise floor** — or
   reported under one of the other pre-committed verdicts.
5. **All Group A and Group B metrics reported**, with the disagreement rate carrying its absolute count,
   `drafter–judge κ` labelled descriptive-only, and **the two raters' per-class κ against ACT gold set
   side by side under the four declared comparison conditions**.
6. **The injected-versus-real gap re-measured on the anchored configuration** and compared against M5's
   threefold gap, with the reason it is not computed under blind recorded in the read.
7. **The observation unit pinned before any run**, with measured clustering behind it.
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
  call.**
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
  its **majority verdict across passes**, score that decision against ACT gold into M5's four cells,
  and run the **one-sided exact sign test (α = 0.05)** on the unit pinned in T1, at the discordant
  threshold pinned in T3. Report the full Group A and Group B metric sets, the two raters' per-class κ
  against gold side by side under the four declared conditions, and the injected-versus-real gap
  **on the anchored configuration**.
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
- **⚠️ Rule: every number names its comparison.** Comparison 1 is judge vs judge; Comparison 2 is the
  blind judge vs the frozen drafter. They share a run and several metric names, so an unlabelled figure
  is ambiguous even to someone who read this spec.
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
argument, not an experimental result. That clustering is light is an impression, not a measurement, and
the obvious way to get it is wrong — **a case that mints no finding sits in the manifest but contributes
no observation**, so dividing two totals flatters the structure; T1 measures it properly. That sharing
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

**A partial judge noise floor already exists, on the wrong input.** `benchmark/reports/noise_floor.json`
records a 3-pass SD of **0.158 on judge κ** and **0.105 on the judge miss rate**, and the four routing
cells move materially across those passes — 31/16/8/8, 28/21/11/3, 31/18/8/6. **That is a floor for the
anchored rubric on M5's *referent-free* input over M5's 63 drafts, so it is not T3's floor** and must not
be substituted for it. It is, however, a prior worth stating: this judge's own run-to-run movement is
already the size of the effects M9 hopes to detect, which is exactly why T3 measures the floor before
T5 fixes a threshold.

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
