# Blinding the judge — what a second, independent reader actually produces

**What this is.** Two frozen runs of the same cloud judge over one frozen set of drafts, and the answer
to the question they were built to test: **if the judge stops grading the draft and answers for itself,
does a human get sent to better places?** The drafts never moved, the drafter was never called, and the
only thing that changed between the two runs is the judge's own prompt.

**Nothing here is scored by a language model.** W3C ACT expert gold is the only ruler, and every
comparison is deterministic code. The judge is the *subject* of this measurement, never an instrument
of it.

Frozen numbers, all of them re-derivable from the files themselves:
[`judge_comparison.json`](../benchmark/reports/judge_comparison.json) (both comparisons),
[`judge_anchored_baseline.json`](../benchmark/reports/judge_anchored_baseline.json) (the graded
configuration and the noise floor),
[`judge_blind_baseline.json`](../benchmark/reports/judge_blind_baseline.json) (the independent
configuration),
[`judge_drafter_comparator.json`](../benchmark/reports/judge_drafter_comparator.json) (the drafter's
side, recomputed from the same drafts).

---

## Read this first — the vocabulary, because two of everything lives here

**Two configurations of one judge**, same model (`gpt-5.6-luna`), same reasoning effort, same frozen
finding-side input, three passes each:

| | what the judge is shown | what it produces | it raises its hand when |
|---|---|---|---|
| **graded** *(the code as it stood — the thing being measured against)* | the finding **and the draft written for it** | a grade of that draft | it grades the draft incorrect |
| **independent** *(the change)* | the finding **only** | its own verdict and its own cited criteria | **code** finds its answer differs from the draft |

**Two comparisons**, and every number below says which one it belongs to:

- **Comparison 1 — judge vs judge.** Did removing the draft make the *routing decision* better? Graded
  against independent, scored against ACT gold. This is the only thing here with a p-value, and it is
  the **less useful** of the two.
- **Comparison 2 — the independent judge vs the frozen drafter.** What does the second reader actually
  look like, and is it worth having? Descriptive by construction: no p-value anywhere.

**Two units**, and a bare count is ambiguous without one:

- **the finding** — one flagged element on a page; 54 of them. The disagreement rate is per finding,
  because it counts people-visits and a queue is walked one finding at a time.
- **the case** — one ACT test page; 40 of them, each holding one to four findings. The tested
  comparison is per case, because two findings on one page are not two independent observations.

---

## 1. The deliverable: how much human work the mechanism creates

*This section answers one question: **if we send a human every time the two readers disagree, how many
visits is that?*** Comparison 2, per **finding** (54).

**The independent judge disagrees with the drafter on 21 of 54 findings (0.3889), spread over 17 of the
40 pages.**

That is the queue as it would actually be walked. But part of it is a formatting habit rather than a
difference of opinion, so the honest price is quoted twice:

| Comparison 2, per finding (54) | headline | of which can carry a real difference of opinion |
|---|---|---|
| **independent** | **21 (0.3889)**, over 17 cases | **14 (0.2593)**, over 10 cases |
| graded | 28 (0.5185), over 19 cases | 7 (0.1296), over 6 cases |

**The two rows count different events and must never be averaged or subtracted.** "Graded" means *the
judge marked the draft wrong*; "independent" means *the judge's own answer differs from the draft*. They
share a denominator and nothing else.

**Why the second column exists.** A disagreement can land on either of two axes: the conformance verdict
(does this element pass or fail) or the set of success criteria cited. The drafter carries an unwritten
citation habit — of its 28 clean rows, **21 cite nothing and 7 cite anyway** — and nobody ever told the
judge which. The second column keeps only findings carrying a **conformance-axis**
disagreement: the visits that can find a real disagreement rather than a citation-formatting mismatch.

**On the independent side that subtraction is licensed by a set identity, not by a matching count.** Its
7 citation-only disagreements *are exactly* the 7 clean rows the drafter cites on — every one forced by
the convention. On the graded side the citation-only count (21) and the cite-nothing count (21) are
equal **and the sets still differ by one swap**, so no graded row is written off on the strength of a
total.

### What those visits find

*This answers: **is a visit worth making, and what does the queue miss?*** These two are a pair and are
never quoted apart.

**First, why the counts below are smaller than the queue above.** The queue is 21 findings over 17
pages; the flagged set counted here is **14 findings over 10 pages** — the second column of the table
above, exactly. The difference is not a discrepancy: the scorer that builds these confusion cells
flags on the **conformance axis alone**, deliberately, and its own docstring says why. The drafter is
steered to cite criteria that disagree with ACT gold — a framing choice of ours, not a capability —
so folding the citation axis into the flag predicate would penalise the judge for our choice and
pollute the one number that matters here, the miss rate. So the confusion cells describe the
substantive column; the extra 7 visits in the headline queue are citation-only and appear in no cell
below.

At the page level (Comparison 1's confusion cells, per **case**, 40): the independent configuration
raises its hand on **10 of 40 cases**, and **5 of those 10 hold a genuinely wrong draft** — a visit is
worth making about half the time. Of all **7** cases whose draft is genuinely wrong, it flags **5**.

Per **finding** (54): it flags **14**, of which **8** are genuinely wrong (0.5714); of all **15** wrong
findings it flags **8** (0.5333). The uglier half of that pair is the miss rate: **7 of 15** wrong
findings, **2 of 7** wrong cases, are released without a hand going up.

The graded configuration, for contrast: flags **6 of 40** cases, **3** of them genuinely wrong, catching
**3 of the 7** wrong cases (per finding: flags 7, 4 genuinely wrong, catching 4 of 15).

### Is the rate degenerate?

Two outcomes were declared in advance as making the mechanism useless: a rate so **high** that the queue
is not filtered at all, and one so **low** that nothing routes and the judge is effectively absent. No
numeric cut-off was pre-registered, deliberately. **Neither endpoint is reached.** 21 findings of 54 —
14 of them substantive — over 17 of 40 pages is a real filter and a real workload: about a third of
findings and just under half the pages.

### Per finding-class

*Does the disagreement concentrate where the drafter is weak, or is it uniform?* Comparison 2, per
finding, headline → substantive:

| class | findings | independent | graded | independent, substantive |
|---|---|---|---|---|
| `document-title` | 5 | 3 (0.600) | 0 (0.000) | **0 (0.000)** — the whole rate is the citation habit |
| `empty-heading` | 11 | 5 (0.4545) | 2 (0.1818) | 1 (0.0909) |
| `label` | 17 | 6 (0.3529) | 8 (0.4706) | 6 (0.3529) — unmoved |
| `link-name` | 21 | 7 (0.3333) | 18 (0.8571) | 7 (0.3333) — unmoved |

**`document-title` carries two caveats and neither is optional.** All three of its disagreements are
citation-axis, on the three rows where the drafter cites while clean — the conformance verdicts agree on
all five. And 3 of its 5 findings render a **byte-identical question**, so it is closer to three
observations than five. Any `document-title` figure here, a zero included, is read with both.

**Expect the citation axis to be quiet, and it is.** All findings of one rule receive the same retrieved
candidate criteria in the same order — four candidate lists across the whole set of 54 — so the two
readers are choosing from the same five ids on every finding of a rule. The conformance axis is where
the signal lives.

### Which way the disagreements point

*When the two verdicts differ, is one reader systematically harsher?* Comparison 2, independent only
(the graded configuration has no verdict of its own to point anywhere), per finding:

**On 13 of the 14 conformance disagreements the drafter is the stricter reader; on 1 the judge is.**
None are undecided. **These are not peer raters.** The independent judge answers `supports` 41 times
against the drafter's 28, and uses `partially_supports` **zero** times against the drafter's 5.

### How alike the two readers are

*Cohen's κ is agreement between two raters with the agreement they would reach by coin-flipping removed:
1.0 is perfect, 0.0 is chance.* Comparison 2, per **finding**, on the raw four-value conformance scale —
the same rule code compares them on:

**drafter–judge κ = 0.4943** (they give the same answer on 40 of 54 findings, 0.7407).

**This number must never become a target.** Raising it means moving the drafter toward the judge, which
is optimising against the judge. It is reported because it characterises the pair, not because it should
go up — and no interval on it is tight, because the measured within-page correlation puts its effective
sample size near 40 rather than 54.

---

## 2. Which of the two readers is more often right

*This answers: **when they disagree, whose answer should you believe — and on what?*** Comparison 2, per
**case**, against ACT gold. It is the reason the disagreement rate has a consequence attached: without
it you know how many people to send, not what they will find.

**This table is the first time the judge's κ means what κ claims to mean.** κ is defined as agreement
between two *independent* raters. The graded judge could see the drafter's answer — it was a marker
grading a paper with the answer written on it — so the number computed from it was not measuring what κ
is defined to measure. Withholding the draft restores the definition. That is a methodological
correction, not an experimental result, and it is why the graded configuration has no column here at
all: a judge that grades a draft emits no verdict of its own to score.

**The four conditions this comparison is read under, stated here rather than in a footnote:**

1. **The two raters do not carry the same variance.** The drafter's frozen passes are bit-identical, so
   its κ is a fixed number. A cloud judge is not bit-reproducible even at a fixed effort, so its κ is a
   draw — reported as the majority verdict over three passes, with the per-pass values and their spread
   printed beside it, never as one pass placed against a deterministic number.
2. **Model and role are confounded.** The judge is a cloud reasoning model, the drafter a local one. A
   difference is *different model **and** different role*. That is enough for the product question — is a
   second reader worth having — and is not enough for any claim about what either model can do.
3. **Framing is a live confound.** Both models follow prompt framing over page content. The judge's
   finding side reuses the drafter's own referent and candidate sentences, but two differences survive:
   the drafter states each finding's provenance and the judge's input does not, and the **order** of the
   shared material differs (drafter: candidates then referent; judge: referent then candidates).
   Position is framing.
4. **Per-class n did not grow, so no per-class number is tested.** Every row carries **both**
   denominators.

**The denominators differ and nothing subtracts one from the other.** The judge is quoted over its own
**40** judge-visible cases and the drafter over its **44**. The gap is the 4 cases that produced no
finding at all: there is nothing for a judge to read, while the drafter's stream carries them because a
failed one is the automatic miss it is. The gap sits entirely in `empty-heading` (2) and `link-name`
(2), 2 of the 4 carrying gold `failed` — so a difference on either of those classes is **partly a
difference of denominator**.

| class | judge κ (n) | drafter κ (n) | more often right | judge κ per pass (SD) |
|---|---|---|---|---|
| `document-title` | **1.0000** (5) | **1.0000** (5) | tied | 1.000 / 1.000 / 1.000 (0.000) |
| `empty-heading` | 0.6071 (11) | **0.6750** (13) | drafter | 0.6071 / 0.6071 / 0.8136 (0.119) |
| `label` | 0.4407 (11) | **0.8197** (11) | drafter | 0.4407 / 0.6333 / 0.4407 (0.111) |
| `link-name` | **0.4507** (13) | 0.2105 (15) | **judge** | 0.2973 / 0.4507 / 0.4507 (0.089) |

Pooled, the judge reads **κ 0.5652 over its 40 cases** (same answer as gold on 32 of 40, 0.800). The
drafter is deliberately **not** pooled: the comparator freezes it per class, and pooling two raters over
different denominators is exactly the arithmetic the declaration above forbids.

**The answer is class-shaped, not global.** The second reader is better exactly on `link-name` — the
class whose deciding fact is not on the page at all, and which the drafter-side work could never
reach — and materially worse on `label`, the class that work repaired. Where the drafter is strong the
judge adds noise; where the drafter is blind the judge sees. Under the four conditions above, none of
these differences is tested and none may be read as certified.

---

## 3. The check: did removing the draft improve the routing decision?

*Comparison 1, per **case** (40).* This is a check on how the disagreement rate was arrived at, not the
result — and it is the less useful comparison by construction, because at best it establishes that the
independent configuration routes better than a mechanism this project had already judged broken.

**Both configurations get 33 of 40 cases right.**

| Comparison 1, per case (40) | released correctly | **missed error** | false alarm | caught correctly | κ |
|---|---|---|---|---|---|
| graded | 30 | 4 | 3 | 3 | 0.3578 |
| independent | 28 | **2** | 5 | 5 | **0.4815** |

**The κ movement is a trade, not an improvement in accuracy.** Case-level accuracy is identical (33 of
40 both), and the share of each flagged set that is genuinely wrong is identical (0.5 both; 0.5714 both
per finding). What actually moves is **recall**: 3 of 7 real errors flagged, against 5 of 7 — bought
with a flagged set that grows from 6 cases to 10. Quoting 0.3578 → 0.4815 without the accuracy identity
beside it would report a trade as a gain. κ moved because the marginals moved.

### The test

One-sided exact sign test on discordant pairs, α = 0.05, at the bar fixed in writing before the
independent configuration ran:

> **n = 6 discordant cases, b = 3 wins for independent, c = 3 wins for graded, one-sided p = 0.6562.**
> **The bar was 6** — statistical bar 6, jitter floor bar 5, **binding bar: statistical**. It does not
> clear, and b is not even larger than c.

Two things that bar is not. It is not a bar the evidence "narrowly missed" through bad luck with the
count: `required_wins` came back as a number rather than *unattainable*, so α set it at this discordant
count, not the judge's own jitter and not the count itself. And the floor bar of 5 is the largest
one-way movement the graded configuration produces against **itself** when nothing changes — a bar
below it would certify noise.

### The pre-committed verdict

**Anchoring was not the dominant cause.** This is the pre-declared falsification condition, reached
as a result rather than as a failure: removing the anchor did not make the routing decision measurably
better, so whatever correlation remains between the two readers lives somewhere this work did not touch.

The six discordant cases, all named in the record: the independent configuration's 3 wins are two
genuinely-wrong cases it flags and the graded one releases (`label`, `link-name`) plus one clean case
the graded one flags and it releases (`empty-heading`). The graded configuration's 3 wins are all the
same event pointing back — clean cases the independent one flags (`label` ×2, `empty-heading`).

**Per finding, beside the test and not governing it:** n = 9, b = 5, c = 4, p = 0.5. A threshold counted
per finding cannot govern a test scored per case.

### What the page-level collapse hides

A page is flagged if *any* of its findings is flagged. That is the product reading — one raised hand
sends the specialist — but it makes within-page disagreement invisible, so it is counted rather than
assumed. Of the 7 pages holding more than one finding: the graded configuration is internally split on
**4** (11 findings) and flag-if-any lands on a different answer from a within-page majority on **3 of
40** cases; the independent one is split on **6** (19 findings), differing on **4 of 40**. The
per-finding table is therefore reported beside the test, never instead of it.

---

## 4. The noise floor — what this judge does when nothing changes

*Every difference above is read against this.* Cloud models are not bit-reproducible even at a fixed
effort, so each configuration ran three passes and its own variance was measured.

| three passes of one fixed configuration | graded | independent |
|---|---|---|
| per-case κ | 0.4805 / 0.4815 / 0.4805 (mean 0.4808, SD **0.0006**) | 0.3774 / 0.4815 / 0.5331 (mean 0.4640, SD 0.0793) |
| per-finding κ | 0.2994 / 0.2961 / 0.2270 (mean 0.2742, SD 0.0409) | 0.3262 / 0.3874 / 0.2961 (mean 0.3366, SD 0.0465) |
| findings whose decision is not unanimous | 9 of 54 (0.1667) | 6 of 54 (0.1111) |
| cases moving between two passes | **3, 4, 7** | 1, 2, 1 |
| largest one-way case movement | **4** | 2 |

**⚠️ A κ SD of 0.0006 is not stability, and reading it as stability is the trap this table exists to
prevent.** The graded configuration's passes 1 and 3 produce identical cells and pass 2 different ones,
yet all three κ land within 0.001 of each other — while those same three passes disagree on up to **7 of
40 case decisions**. A spread taken on a summary statistic says nothing about whether the decisions
underneath it moved. That is exactly why the jitter bar in the test above is a discordant *count* and
not a κ SD.

**And the six discordant cases the test ran on sit inside the graded configuration's own pass-to-pass
movement of 3, 4 and 7 cases.** The measured effect is the size of the noise.

**⚠️ The majority-of-three collapse costs the judge its best cells, and the headline κ may never be set
beside a single-pass κ.** The graded configuration's three passes read 30/3/3/4, 28/2/5/5 and 30/3/3/4
per case; the majority reads **30/4/3/3** — one fewer catch and one more miss than *any* individual
pass, κ 0.3578 against a per-pass 0.4805–0.4815. The reason is mechanical: its catches are not
unanimous, so requiring two passes out of three discards the ones a single draw found. Both
configurations get the same treatment and the comparison stays fair; the two estimators are simply not
interchangeable.

**One measurement that came out the uncomfortable way and is reported as measured.** The page collapse
is supposed to *absorb* disagreement — findings that differ arriving together on the same page. Measured
on the real contrast between the two configurations (9 findings and 6 cases route differently), the
within-page correlation of that difference is **−0.0957: negative**. A negative value means the collapse
is cancelling differences against each other, so the per-case unit is **costing power rather than buying
honesty**. It is stated because it was asked for in advance and because it points the wrong way; it does
not license re-cutting the unit, which was pinned before any call was spent.

---

## 5. Injected errors versus real ones

*This answers: **does the judge only catch mistakes someone planted for it?*** Comparison 1, and
**measured on the graded configuration only**, per mutated draft:

| | detection | denominator |
|---|---|---|
| planted citation swap | **1.000** | 54 mutated drafts |
| planted verdict flip | **0.8974** | 39 mutated drafts |
| **real errors** | **0.2667** per finding / **0.4286** per case | 15 wrong findings / 7 wrong cases |

**The gap has not closed.** On this run's own drafts, needing no comparison to any other set, planted
detection runs **3.75×** and **3.36×** real detection per finding, **2.33×** and **2.09×** per case.

**⚠️ The 1.000 is worth less than it looks.** The planted swap substitutes a decoy criterion, and no
decoy appears in any class's retrieved candidate list — which this configuration now shows the judge. So
"is this citation wrong" is answerable by checking a list, with no accessibility judgment involved at
all. A high figure here carries *less* judge behaviour than the same figure did before the candidate list
was shared, not more. The verdict flip is unaffected: no candidate list speaks to a verdict.

**Why the independent configuration has no figures here.** Both mutations edit the **draft**, and a
blind ask is byte-identical whatever the draft says. "Caught" would then reduce to arithmetic — a swap
is caught 1.000 by construction because the judge named its own criterion, and a flip is caught exactly
when the judge already agreed, which is a restatement of the natural agreement rate. Neither number
would contain one bit of judge behaviour, so both are recorded as **empty (n = 0), not zero**.

**The pre-committed guard, and it trips.** The rule was: *if planted detection rises while real detection
does not, the mechanism is effective only on clean signal and does not transfer.* Against the earlier
acceptance figures, planted verdict-flip detection rose (0.82 → 0.8974, swap flat at 1.000) while real
detection did not (0.33 → 0.2667 per finding, the unit the 0.33 was measured on). **So it trips.** Two
things bound it: the comparison **crosses draft sets** — 63 drafted findings with 24 wrong then, against
54 with 15 now, so both movements are movements of the *set* as much as of the judge — and **no success
is being claimed anyway**, because the routing comparison's verdict is not "supported". The within-run
gap above needs no cross-set comparison and is the sturdier of the two readings.

---

## 6. What it cost

Counted at the client seam, below the judge, so a retry the judge made appends its own row:

| | asks | transport calls | beyond one per ask | priced | latency (mean / median / max) | wall clock |
|---|---|---|---|---|---|---|
| graded | 441 | **441** | **0** | $0.999812 | 3581 / 3044 / 13467 ms | 1580.8 s |
| independent | 162 | **162** | **0** | $0.269071 | 2674 / 2345 / 10060 ms | 434.3 s |
| **total** | **603** | **603** | **0** | **$1.268883** | | |

Mean per call: $0.002267 graded (median $0.001929, range $0.000483–$0.010244), $0.001661 independent
(median $0.001765, range $0.000553–$0.004294). Tokens are the provider's own: 428,688 in / 112,839 out
graded, 175,053 in / 29,292 out independent, the output counts including whatever reasoning the effort
setting bought.

**Two things this table is not.** The dollar figures are a **local price table applied to the provider's
token counts, not an amount anyone was billed** — the billed total is read off the provider. And 603 is
still a **floor for the spend**: what the seam count rules out is a retry inside the judge, and a retry
inside the provider's own client sits below that seam and is a separate, unbounded uncertainty. The
pre-run estimate was ≥ 603 calls with a ceiling of 1206 (each call allowed two attempts); both halves
came in at exactly one call per ask, so the judge-level half of that ceiling is retired by measurement
rather than merely unapproached.

---

## 7. Reconciling the two judge κ this repo now publishes

**A reader who finds both will think one of them is wrong. They are both right, and this section is the
reconciliation.** Neither of the earlier documents is edited: they report a frozen result correctly for
the set they were measured on.

- **`README.md` and [`acceptance-analysis.md`](acceptance-analysis.md) say the judge grades external ACT
  gold at κ ≈ 0.** The frozen scorecard
  ([`scorecard.json`](../benchmark/reports/scorecard.json)) holds **0.137**, and the noise floor
  ([`noise_floor.json`](../benchmark/reports/noise_floor.json)) holds a three-run **SD of 0.158**. The
  **mean ≈ 0.005** across those three runs, and the two other per-run values it averages — **−0.171** and
  **0.049**, one of them worse than a coin — are **in neither JSON**: they live only in the per-run table
  in `acceptance-analysis.md`, beside the per-run confusion cells the mean is computed from. The first of
  the three is the 0.137 the scorecard holds.
- **The graded baseline frozen here reports κ 0.227 per finding and 0.3578 per case.**

Both score against the **same** gold set (`act-acceptance@1`). **Four things differ at once, and no one
of them is the explanation:**

1. **The drafts.** The earlier figure grades the acceptance run's **63** drafted findings; this one
   grades the frozen replay drafts — **54 findings over 40 cases**, with their own count of wrong
   answers. κ against gold is a property of the graded set as much as of the grader.
2. **What the judge is shown.** The rubric text is *unchanged*. What moved is the finding-side input,
   which now carries the resolved referent and the retrieved candidate criteria. The judge's old version
   string could not date that input at all; it can now, because the string was widened to hash the whole
   prompt (`rubric=e396f37f…` then, `prompt=afadca26; effort=medium` here).
3. **The unit.** 0.3578 is per case (40), 0.227 per finding (54), the earlier 0.137 per drafted finding
   (63). **No two of the three share a denominator.**
4. **The estimator.** The earlier figures are single-pass κ, one per run. The headline here is the
   majority-of-three collapse, which *costs* the judge cells against any single pass — this run's own
   per-pass per-finding κ are **0.2994 / 0.2961 / 0.2270**.

**What the larger number does not license.** Those four moved together, so nothing attributes the
difference to any one of them — least of all to the judge having got better. **The earlier read is not
retracted.** At the pinned unit this judge still **releases 4 of the 7 cases whose draft is genuinely
wrong and flags 3 clean ones**: 7 of 40 routing decisions wrong. That is a different set of seven from
the seven repairable cases, overlapping only in the 4 misses, and the two must not be written against
each other.

---

## 8. Two scaffold fields, and what actually fills them

Five inert fields were added to the internal evaluation metrics some time ago, and the ticket that added
them recorded that this work would fill them. **It does not, and the record is corrected here rather
than by editing that ticket.**

- **`citation_hallucination_rate_composite`, `hallucinations_queued_total`, `citations_queued_total`** —
  the composite (shipped ⊕ queued) hallucination fields. **What fills them is review-queue routing in
  the running pipeline**, and this work is offline by construction: the orchestrator, the review queue
  and the human-in-the-loop gate were never touched. They stay `None`, which reads as *not yet
  produced*, never as a measured zero.
- **`reflection_iterations_total`, `reflection_caught_repaired_total`** — the drafter self-revision
  counters. **What fills them is a drafter reflection pass, and no such pass exists.** What was built
  here is not a reflection loop and is not a step toward one: it is an *independent dual read* — two
  readers answer the same question without seeing each other's answer, and code compares them, the way
  discordant screening reads go to arbitration. There is no self-examination and no second attempt, which
  is precisely what keeps optimisation pressure off the judge. The drafter was never called.

The field descriptions in the schema already say the right thing (*"None until the review queue routes
findings"*, *"None until a reflection loop runs"*); what was stale is the surrounding prose naming this
work as the filler.

---

## 9. What this does not establish

1. **Production behaviour.** Everything here is offline against frozen drafts. Whether the disagreement
   signal is worth wiring into the running pipeline is what this measured; wiring it is not done.
2. **That the two readers are independent in every respect.** They share the retrieved candidate list
   deliberately — same question, independent answer — so a bad retrieval ordering misleads both and they
   agree for the wrong reason. The prior is stronger than "shared": there are **four candidate lists
   across all 54 findings**, one per class and constant inside it. The size of that residual is not
   quantified.
3. **That the 40 pages are 40 independent questions.** The 54 findings render only **45 distinct** asks,
   in 8 duplicate groups, and **not one group lies inside a single page** — so two pages can be sent a
   byte-identical question. It lands hardest on the smallest class (`document-title`: 3 asks for 5
   findings).
4. **That both readers see the same material on every class.** The referent block is built per class,
   and `empty-heading` has none — **0 of its 11 findings** carry referent material for *either* reader.
   "The judge now sees what the drafter sees" is not uniform across the four classes.
5. **Anything about model capability.** Model and role are confounded (conditions 2 and 3 above), so no
   κ difference here says what either model can do.
6. **That any of this transfers to real pages.** Every number is on ACT's synthetic fixtures.
7. **Whether agreement means verification.** It does not. Two independent readers agreeing is still
   `drafter-judged, unverified`.

---

## Where the numbers live

| file | holds | rebuild |
|---|---|---|
| [`judge_comparison.json`](../benchmark/reports/judge_comparison.json) | both comparisons, kept apart | `uv run python -m clearway.eval.judge_comparison` |
| [`judge_anchored_baseline.json`](../benchmark/reports/judge_anchored_baseline.json) | the graded configuration, its noise floor, the planted-error gap, cost, the jitter bar | the frozen 441 calls; `--rederive` recomputes every field from the stored answers |
| [`judge_blind_baseline.json`](../benchmark/reports/judge_blind_baseline.json) | the independent configuration, its own answers and noise floor, cost | the frozen 162 calls; `--rederive` likewise |
| [`judge_drafter_comparator.json`](../benchmark/reports/judge_drafter_comparator.json) | the drafter's per-class κ **recomputed from these same drafts** | `uv run python -m clearway.eval.judge_drafter_comparator` |
| [`judge_observation_unit.json`](../benchmark/reports/judge_observation_unit.json) | the clustering behind the per-case unit, and the repairable ceiling | `uv run python -m clearway.eval.judge_observation_unit` |
| [`judge_finding_input.json`](../benchmark/reports/judge_finding_input.json) | the finding-side input **both** configurations read, byte for byte | needs a live scan and retrieval |

**The drafter's side of the side-by-side table is recomputed from the drafts this work replays, not read
off the frozen per-class drafter baseline** — that file predates the referent work and would get *which
of them is right* wrong on `document-title` and `label`.
