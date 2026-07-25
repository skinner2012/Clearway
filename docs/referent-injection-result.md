# Putting the referent in the input — the measured answer

**What this is.** Two frozen drafter runs and the answer to the question they were built to test. The
question was fixed before either run existed: **is accuracy on the classes whose deciding fact is missing
from the drafter's input governed by whether that fact is *present*, rather than by model strength?** Same
model, same weights, same temperature — only the input changed.

**Nothing here is scored by an LLM.** W3C ACT expert gold is the only ruler and every comparison is
deterministic code. The judge — measured elsewhere in this repo to sit at chance on external gold and to
co-sign the drafter's own false positives — appears in **no number in this document**, by design and by
pre-registration.

Frozen numbers: [`drafter_kappa_baseline.json`](../benchmark/reports/drafter_kappa_baseline.json) (the
pre-registration), [`referent_injection_result.json`](../benchmark/reports/referent_injection_result.json),
[`citation_grounding_result.json`](../benchmark/reports/citation_grounding_result.json),
[`citation_grounding_technique_match.json`](../benchmark/reports/citation_grounding_technique_match.json).

## The one-line verdict

**The thesis is supported in direction and not certified: pooled b = 5, c = 1, p = 0.109 against
α = 0.05.** It moved 7 of the 10 reachable errors in the two classes it treats, broke one, and moved
nothing at all in the class whose deciding fact is not in the page. The most useful thing it produced is
not the p-value but a diagnosis: **the failures were an input problem, not a model problem — and exactly
one class is beyond reach of any prompt.**

---

## The ruler, fixed before the runs existed

| | |
|---|---|
| Test | one-sided exact sign test on **discordant pairs**, α = 0.05 |
| Oracle | ACT gold, keyed by `act_testcase_id` |
| Primary endpoint | **pooled** over `label` + `link-name` — 10 reachable errors |
| Secondary | per-class tests, per-class κ, mechanism |
| Case set | **44** cases (40 minting + 4 honest misses, 54 findings) |
| Verdicts | *certified* / *worked but uncertifiable* / *failed*, pre-committed |
| Failure line | pooled **b ≤ 2** = *thesis not supported*, in those words |

The endpoint is pooled because **per-class certification carries zero margin by construction**: both
certifiable classes have exactly 5 reachable errors, so each needs 5 improvements and 0 regressions — a
perfect run, twice, independently. That is a property of the gold set's size, not of any fix. **A
near-miss under that bar is a near-miss, not a failed fix.**

`document-title` **cannot be certified at any fix quality** — 3 reachable errors, best attainable
p = 0.125. It is argued on mechanism only; reporting it as "certified" would be a specification violation.

## The two runs, one prompt change each

| Run | Its single prompt-touching change | Judge | Passes |
|---|---|---|---|
| **referent injection** | per-class referent blocks — resolved accessible name, nearest section heading, resolved page title + topic tier, bounded surrounding context | absent | 3 |
| **citation grounding** | the criterion's **normative text** carried into the prompt (400-char prefix budget) + a single-citation budget | absent | 3 |

**Prompt growth, measured per class** by nulling each input rather than reverting code:

| Class | n | bare | +referent | +grounded | growth |
|---|---|---|---|---|---|
| `document-title` | 5 | 895 | 1068 | 2929 | 3.27× |
| `empty-heading` *(control)* | 11 | 939 | **939 (+0)** | 2801 | 2.98× |
| `label` | 17 | 949 | 1017 | 2111 | 2.23× |
| `link-name` | 21 | 994 | 1457 | 3137 | 3.15× |

The control moved by **exactly zero characters** under referent injection — independent corroboration
that the injection did not leak into the anchor class. The grounding change, by contrast, lands on
**every** class including the control, which is why the control test for the second run is *κ unchanged*,
not *bytes unchanged*.

---

## The primary endpoint

| Run | b | c | p | thesis |
|---|---|---|---|---|
| referent injection | 5 | 2 | 0.227 | directional, not significant |
| **citation grounding** *(final)* | **5** | **1** | **0.109** | **directional, not significant** |

**The margin is one case.** At b = 5, c = **0** the pooled p would be **0.031** and the thesis would be
certified. The single surviving regression (`5e67cab9c6`, `link-name`) is the whole distance between
"supported" and "certified". That is a statement about the gold set's size, not about the size of the
effect — and it is why the endpoint was pooled in the first place.

## Per class

| Class | baseline κ | final κ | 2×2 tp·fp·fn·tn | b/c | p | verdict |
|---|---|---|---|---|---|---|
| `document-title` | 0.000 | **+1.000** | 2·0·0·3 | 3/0 | 0.125 | worked but uncertifiable |
| `label` | 0.127 | **+0.820** | 5·1·0·5 | 4/0 | 0.0625 | worked but uncertifiable |
| `link-name` | 0.211 | 0.211 | 4·4·2·5 | 1/1 | 0.750 | **failed** |
| `empty-heading` *(control)* | 0.675 | **0.675** | 4·1·1·7 | 0/0 | — | **held** |

## Mechanism, reported for every class

| Class | distinct prompts | `constant_classifier` | false positives | reachable errors moved |
|---|---|---|---|---|
| `document-title` | **1 → 3** | **True → False** | **3 → 0** | 3 of 3 |
| `label` | **6 → 14** | False | **4 → 1** | 4 of 5 |
| `link-name` | 13 → 19 | False | 4 → 4 | 1 of 5 |
| `empty-heading` | 9 → 9 | False | 1 → 1 | 0 of 1 *(must not move)* |

**`document-title` is the cleanest result in the milestone, and it is not a p-value.** Its original
κ = 0.000 was never evidence of a broken model: all five cases received a **byte-identical prompt**
(`Target: html` / `HTML: <html lang="en">` — the `<title>` was not in it), and at `temperature = 0`
five identical prompts *must* produce five identical answers. κ = 0.000 was the only score the input
permitted. Given the resolved title, the same model with the same weights discriminates perfectly.

**The distinction that matters is not fixture vs prompt but *where the fact lives*:**

| | Class | Outcome |
|---|---|---|
| In the page **and** in the prompt | `empty-heading` | already worked (κ 0.675, untouched control) |
| In the page, **absent from the prompt** | `document-title`, `label` | **fixed — 7 of 10 reachable errors** |
| **Not in the page at all** | `link-name` | unreachable — no prompt can contain it |

`link-name`'s deciding fact is the link's **destination**: whether "Workshop" is descriptive depends on
what the link goes to, which lies outside a single-page DOM. Injected surrounding context is a *proxy*,
and on `3bb1986371` it makes the existing link text look **more** justified, not less. This class is
therefore **structurally unfixable by prompt work**, in this milestone and in the multimodal one after it.

## Did the second run eat the first?

**No — `prior_gains_lost: 0` on every class, `eats_prior_run: false`.** Citation grounding kept every gain
referent injection bought and *recovered* one of its regressions (`link-name` b=1, c=0 against the prior
run; κ 0.054 → 0.211, back to its pre-injection value). **The grounding change stays**: no rollback and no
class-conditioning, which is what the exit criterion required be decided on evidence.

## Citations: the pair of numbers, and a failed acceptance criterion

| | referent injection | citation grounding |
|---|---|---|
| gold SC-match (**hit rate**: did any cited id land in gold) | 1.000 (14/14) | **0.667 (10/15)** |
| SC-citation **precision** (id-level) | 0.636 (14/22) | 0.667 (10/15) |
| ids cited per case | 1.57 | **1.00** |
| findings citing nothing | 0 | **21** — *all of them `supports` rows* |

**The grounding ticket's stated acceptance was "the gold SC-match does not fall". It fell**, 1.000 →
0.667, and that is reported as the failure it is. Two honest qualifications, neither of which rescues it:

- **The criterion was ill-posed before the run.** At 14/14 the hit rate was **saturated** — a case-level
  "did any cited id land in gold" rate can only fall or stay when citations are narrowed. An acceptance
  test that cannot be passed, only failed, is not a test.
- **The pair shows it was a bad trade anyway.** Cutting citations by 36% (1.57 → 1.00 per case) lost a
  third of the gold hits while precision moved only 0.636 → 0.667. The budget removed citations that were
  *hitting* gold.

**But the escape clause is a genuine improvement, and the two must not be confused.** All 21 findings that
now cite nothing are `supports` rows — **not one flagging row lost its citation**. A row claiming "no
problem here" is no longer forced to manufacture a criterion it does not need.

**So the grounding ticket bundles two mechanisms with opposite effects**, and one run cannot separate
them: the normative text plausibly drives the verdict gains (recall 0.778 → **0.833**, `link-name`
recovery), while the citation budget drives the SC-match loss. The one-prompt-change rule was honoured at
the ticket level but not at the mechanism level. **Recommended follow-up: keep the `supports` escape,
drop "cite the single most applicable" for flagging rows, and measure the two separately.**

## Remediation fix-direction — the first measurement of it this project has taken

`remediation_technique_match` was `null` in every previously-frozen run: the drafter wrote the sentences
and the artifact writer dropped them, so the metric was uncomputable without re-drafting. This run is the
first that persists remediation text (**51 of 54 findings**; the 3 blanks are `supports` rows with nothing
to remediate).

**As computed: κ = +0.276**, CI [+0.072, +0.494], n = 22, raw agreement 0.545, `constant_classifier:
false`. **Coverage is 2 of 4 classes** — only `label` (G131) and `document-title` (G88/H25) carry ACT
technique gold; `link-name` and `empty-heading` carry none and are **absent from the number, not passing
it**.

**⚠️ That headline is contaminated, and the contamination inverts it on half the data.** Split by gold:

| | agrees | n |
|---|---|---|
| gold **failed** — a fix genuinely is required | **8** | 10 |
| gold **passed** — nothing to fix | 4 | 12 |

On a gold-*passed* case, "No remediation necessary — the label clearly identifies the purpose" is the
**correct** answer but scores as a **miss** (rule-level gold says G131), while proposing a G131 fix is a
**false positive** that scores as **agreement**. On those 12 sentences the metric rewards the wrong
behaviour and penalises the right one. **The defensible reading is the gold-failed subset: 8 of 10 drafted
fixes point at the technique ACT names.**

**A corroboration worth noting.** Both misses are the same case — `5d11716ba4`, where the drafter wrote
*"No remediation is necessary as the label clearly identifies the field's purpose"* on a case ACT marks
**failed**. That is the trailing-colon case from the pre-registered predictions. Two independent
instruments — the paired verdict test and the fix-direction classifier — catch the same error on the same
case by different routes.

**Its limit, stated so it is not over-read.** It scores **direction, not usefulness**, and it measures the
drafter→classifier *chain*, not the drafter alone. Whether any fix is actually useful to an implementer
still needs a human specialist and remains unmeasured.

## Drafter-side rates

| | referent injection | citation grounding |
|---|---|---|
| recall | 0.778 (n=18) | **0.833** (n=18) |
| false-positive rate | 0.231 (n=26) | 0.231 (n=26) |
| FP on non-trivial true negatives | 0.250 (6/24) | 0.250 (6/24) |
| ECE / over-confidence gap | 0.231 | 0.209 |
| `abstained_n` | 0 | **0** |

Confidence remains uninformative and is retained only as an internal calibration receipt; no
reader-facing surface reads it. The abstention channel exists in the system prompt and has **still never
been used** across either run.

---

## What the exclusions bought, and whether the fix collected

Nine cases were removed from the scored set **before either run**, on a ground that existed before any
result: the ACT rule *Link is descriptive* maps to **SC 2.4.9 only, Level AAA**, outside the Level A/AA
target every drafted conformance row is scored against. Its sibling *Link in context is descriptive*
carries the Level A criterion 2.4.4 and stays scored. 53 cases → 44.

The exclusion had two arithmetic side effects, and a reader who cannot see them cannot audit any
improvement:

- **One manufactured win.** `6566c139dc…` was retained and was a false positive. Before the scoping it was
  *unwinnable* — its byte-identical twin carries the opposite gold, so any input change that fixed one
  broke the other. The scoping converted it into one of the five wins the class needs, **by no fix at all**.
- **One unscored regression.** That twin, `48cbc84f4c…`, was *correct* and is now dropped. Fixing
  `6566c139dc…` predictably flips it to wrong, and that regression is no longer scored anywhere.

**Did the fix collect the manufactured win? No.** `6566c139dc…` is still a false positive in the final
run. The scoping handed the class a free winnable error and the fix did not take it — so the exclusion
inflated the *opportunity* without inflating the *result*.

## The two pre-registered predictions, scored

Both were **argued**, not arithmetic, and both were failure predictions. **A confirmed prediction of
failure is still a failure** — two errors not fixed, not two successful forecasts. Scored mechanically
from the frozen vectors; the interpretation here is by the author of this read, who did not author the
prompt tickets.

1. **`e419548ab0` will not be separated from `5d11716ba4` by the accessible name** — their accnames differ
   only by a trailing colon (`Name` vs `Name:`) while their gold outcomes are opposite. **Held**: neither
   moved. This is the single reason `label` lands at 4 of 5 rather than 5 of 5, i.e. the reason it is not
   certified.
2. **`3bb1986371` resists surrounding-context injection** — its gold turns on a destination outside the
   DOM. **Held**: it did not move.

## Controls

| Control | Status |
|---|---|
| Referent verifiably present in every fixed-class prompt | **green**, asserted offline before each run |
| Control class prompt byte-identical (referent injection) | **yes** — measured at +0 characters |
| Control class κ unchanged (both runs) | **yes** — 0.675, 2×2 identical |
| Case set = 44 | **yes** |
| Five provenance fields match the baseline | **yes** — re-verified after an infrastructure restart mid-run |

### ⚠️ Determinism holds where the numbers need it, and fails one level below

The specification required determinism to be **re-verified, not assumed**, and warned that earlier
agreement was partly *guaranteed* by prompt degeneracy. With injection splitting the prompts (14/9/3/19
distinct per class), this check finally tests something. It returns a split answer, and collapsing the two
levels would overstate the result.

- **Finding level — determinism does NOT hold.** 53 of 54 findings are identical across every pass
  (**98.1%**). Exactly one drifts, on `970cf7f07c` (`link-name`, gold *passed*): the same finding drafts
  `supports` with no citation in two passes and `does_not_support` citing 2.4.4, with a remediation
  sentence, in the third — **a 2:1 split across three observations**. It is a coin-flip on a near-tie,
  not a one-off glitch and not a stable disagreement, and it recurs on the *same* finding rather than
  wandering. The canonical pass (pass 1, the one every number is built from) sits with the majority.
- **The mechanism is numerical, not sampling.** `temperature = 0` removes sampling randomness, not
  numerical nondeterminism. The server reuses cached KV prefixes across requests (visible in its log as
  `cached n_tokens = …, memory_seq_rm[…]`), so the same prompt can be computed from different cache states
  and a near-tie between two tokens can resolve differently. **"Deterministic at temperature 0" is a claim
  about the sampler, not about the stack.**
- **Case level — determinism holds, and every acceptance number lives here.** 40 of 40 case verdicts
  identical on every pass, so κ, the 2×2s and the paired tests are unaffected.
- **That absorption was luck, not design.** The drifting finding's case already flagged on two other
  findings, so flag-if-any absorbed the flip all three times. Had it been the only flagging finding on its
  case, the case verdict would have moved and κ with it. **The honest statement is: at the level the
  claims are made the runs agree; one level below they do not, and the lossy collapse is what hides it.**
  A drafter noise floor at the finding level is **unbuilt**, and is named here as required future work
  rather than waved off — the measured rate to build it against is 1 finding in 54, splitting 2:1.

**⚠️ The instability is a symptom, and the disease is more interesting than the wobble.** The case is a
download table: a header spanning three columns reading *Ulysses*, and three links beneath it — `HTML`,
`EPUB`, `Plain text`. ACT marks it **passed**: in context, each link's purpose is plain. The drafter's
answers are:

| link | verdict |
|---|---|
| `HTML` | fails — all three passes |
| **`EPUB`** | **passes twice, fails once** — the drifting finding |
| `Plain text` | fails — all three passes |

**Three links of identical kind, in one row of one table, receive three different treatments.** No
principle separates `EPUB` from `HTML`. So the drift is not a borderline judgment wobbling at its
threshold; it is what an **absent judgment** looks like when sampled repeatedly. The class whose deciding
fact is missing from the input does not fail *loudly* — it produces confident, inconsistent, arbitrary
answers, which is exactly the failure mode this milestone's thesis predicts and the reason `link-name`
cannot be repaired by prompt work.

**A consequence worth recording for whoever builds the trust signal.** This project needs a confidence
measure that is not the model's self-report, which is measured to be uninformative. Repeat-sampling
agreement was previously dropped on the reasoning that `temperature = 0` makes repeated drafts identical,
so agreement is trivially 1.0 and carries no signal. **That reasoning is now partly falsified: measured
agreement is 0.98, not 1.00.** The channel is not structurally empty — but at one unstable finding in 54
it is far too sparse to be useful at three passes, and establishing it properly needs repeated sampling
of individual findings (cheap: seconds each) rather than repeated full passes (hours). That is the
experiment to run, and it does not require raising the temperature.

**⚠️ And one exposure that survives the collapse.** The fix-direction metric is scored **per finding**,
not per case, so flag-if-any does not protect it. It was unaffected here only because the drifting finding
belongs to `link-name`, which carries no ACT technique gold. A drift on a `label` or `document-title`
finding would move that number directly.

## Held-out model-run count, and a degree of freedom already spent

**Nine drafter passes over the held-out ACT set**: 3 pre-injection baseline, 3 referent injection, 3
citation grounding. The technique classifier adds no drafter call — it reads remediation text from an
already-frozen artifact.

**The specification was authored with sight of the decisive held-out cases.** It names
`e419548ab0`/`5d11716ba4`, `3bb1986371`, `1ba642803c`, `88a1646138` and `925f5da929` in advance, and
derives one ticket's target from held-out fixture bodies. That is a real, spent degree of freedom and
**the model-run counter does not measure it**. Naming decisive cases in advance beats discovering them
afterwards and rationalising, but it is not a clean hold-out and nothing here claims one.

## The local-drafter choice: what it bought, what it cost, and why it could not be revisited

The drafter is a local `gemma4:31b` at `temperature = 0`. That choice shaped this milestone more than any
prompt in it.

**Why it could not be changed mid-experiment.** The drafter is not a tool used *by* the experiment; it is
the **subject of** it. Its digest is one of the five provenance fields the dry gate refuses to run without,
and the pre-registered test pairs case-by-case against a verdict vector *this* model produced. Swapping it
would not make the comparison unfair — it would make it **undefined**.

**What it bought.** Zero marginal cost per call, which is what made **9 held-out passes** and a
three-pass determinism protocol affordable at all; genuine replay determinism at the case level; no vendor
coupling in the component under study.

**What it cost, measured.** `gemma4:31b` is a thinking model with **no cap on its reasoning budget**:
1372–3758 tokens per finding at ~11 tok/s, i.e. **2–5.7 minutes each**, so one 54-finding pass runs 2–3.5 h.
The grounding change made this worse — 2.84× longer prompts *and* longer thinking. **On this hardware the
cost of grounding is not tokens; it is whether a pass finishes in a working day.**

**The epistemic limit this places on every number here** — and the one an outside reader will press on.
The thesis is *"referent presence, not model strength, governs accuracy on these classes"*. Holding the
model fixed and moving the input tests the antecedent, but it does **not** establish the contrapositive.
**Whether a stronger drafter would clear the same cases without the referent is untested here**, and
nothing in this document licenses the claim that it would not.

**How a model change would have to be done.** Not by swapping models into this comparison, but by
**re-freezing the baseline** under the new model — its own verdict vector, its own per-class κ, pairing
only within its own runs. κ and the verdict vector are model-specific artifacts.

## What the run cost operationally, and what broke

The measurement is unaffected by this section. It is recorded because a benchmark that cannot be re-run
reliably is not yet a finished instrument, and because two of the three faults were **misdiagnosed** in
ways worth not repeating.

1. **The chat client had no request timeout.** A lost response blocked a multi-hour pass in `recv()` with
   no error, no log line and no end. **Fixed**: every request now carries a bound (`CLEARWAY_CHAT_TIMEOUT_S`).
   The bound is on *waiting*, not sampling, so it cannot change what a reachable model returns — verified,
   since the passes drafted before and after it agree byte-for-byte.
2. **The container runtime wedged.** Postgres accepted TCP while never answering queries, so every citation
   retrieval timed out; `docker restart` itself hung. Remedied by restarting the runtime — after which the
   five provenance fields were **re-verified against the frozen baseline** before resuming, because a
   corpus that did not survive intact would have made the run incomparable.
3. **⚠️ Two "stalls" were not stalls.** A thinking model generating 3000+ tokens produces no pass output
   and does not refresh the server's model keepalive — so both "the log is quiet" and "the keepalive is
   stale" report *healthy long work* as a hang. Acting on them killed valid generations and livelocked the
   run. **The signal that works** is the inference server's own decode log, which writes a timing line every
   few seconds: a real wedge is the pass being quiet **and** the server emitting nothing.

**Recommended follow-ups**: set `num_retries = 0` on the chat client so the bound is exactly one attempt
(a retry currently doubles the effective wait); build the finding-level noise floor named above.

## What is not measured

1. **Whether any of this transfers to real pages.** Every number sits on ACT's *synthetic* cases, whose
   rendered bodies run 2–220 characters. A fix certified here is not a fix proven in production.
2. **`document-title`'s fix in the significance sense** — structurally uncertifiable at n = 5.
3. **The link destination** — outside a single-page DOM and unreachable to this work and its successor.
4. **The nine excluded cases** — scoped out; neither fixed nor failed.
5. **Remediation usefulness** — direction only; usefulness needs a human specialist.
6. **Anything needing a human expert**, including whether expert-minutes-per-finding has fallen. Still the
   one unproven link in the value proposition.
7. **The image classes and anything needing sight.**
8. **Whether the drafter abstains on the right cases** — `abstained_n = 0` across both runs.
9. **Sampling agreement as a trust signal** — structurally unavailable at `temperature = 0`.
10. **Whether a stronger drafter would need the referent at all.** The model is held fixed by design, so
    "a better model would have got these right anyway" is a live alternative explanation this milestone
    neither tests nor refutes.
11. **The violations bucket**, which now assembles SC and conformance in code rather than asking the model.
    It ships **unmeasured**: there is no violations-bucket gold, so its benefit is mechanical, not
    demonstrated.
12. **The two grounding mechanisms separately** — normative text and citation budget shipped in one run and
    their opposite-signed effects cannot be attributed individually.
