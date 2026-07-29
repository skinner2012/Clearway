# The image channel — the measured answer, and the one it buried

**What this is.** Six frozen drafter conditions over seven ACT image cases, and the honest read of what
they support. Two endpoints were fixed before any of their calls were spent: **D**, whether attaching the
*wrong* picture behind a byte-identical prompt moves the verdict; and **A**, whether a drafter told it has
no picture says so. Both are reported here with the numbers that qualify them.

**Nothing here is scored by an LLM.** W3C ACT expert gold is the only ruler and every comparison is
deterministic code. The judge — measured elsewhere in this repo to sit at chance on external gold and to
co-sign the drafter's own false positives — appears in **no number in this document**.

Frozen numbers: [`image_endpoint.json`](../benchmark/reports/image_endpoint.json),
[`image_absence_endpoint.json`](../benchmark/reports/image_absence_endpoint.json),
[`image_text_only_difference.json`](../benchmark/reports/image_text_only_difference.json),
[`blind_judgment.json`](../benchmark/reports/blind_judgment.json),
[`image_condition_dry_receipt.json`](../benchmark/reports/image_condition_dry_receipt.json),
[`drafter_payload_baseline.json`](../benchmark/reports/drafter_payload_baseline.json),
[`captured_image_discrimination.json`](../benchmark/reports/captured_image_discrimination.json),
[`multimodal_transport_probe.json`](../benchmark/reports/multimodal_transport_probe.json).

**They are not all evidence of the same kind, and the difference matters.** Five of them —
`image_endpoint`, `image_absence_endpoint`, `image_text_only_difference`, `blind_judgment` and
`image_condition_dry_receipt` — were rebuilt through their own entry points while this document was being
written, and `git status` came back empty: they regenerate byte-identically through current code.
`drafter_payload_baseline` likewise re-derives model-free, through its own test rather than a command.
**The last two regenerate through nothing**: `captured_image_discrimination` and
`multimodal_transport_probe` are receipts of spent model calls (3 and 2), written once by scripts under
[`scripts/`](../scripts/), and their tests only read them. Rebuilding those two would mean re-spending
five held-out calls, which is why they are asserted by reading and not by rebuild.

The six run artifacts under [`benchmark/runs/`](../benchmark/runs/) cannot be regenerated at all — 112
drafted rows of calls that cannot be re-spent — and are pinned by digest in **two** places: the four conditions of D in
`tests/test_blind_judgment.py` (`FROZEN_BEFORE_THE_MARKING`, which also pins the payload baseline and the
dry receipt), and the two announced conditions in `tests/test_image_absence_run.py` (`FROZEN_ANNOUNCED`).

**This is a point-in-time record and is frozen.** The six conditions it reads carry `created_at` stamps
running from 2026-07-28T14:18Z to 2026-07-29T00:20Z; every number below was re-derived from those artifacts on
2026-07-28 and nothing measured after them appears here. A fix that follows from this reading belongs in
its own record — a frozen report edited to carry a later result is no longer frozen.

## The one-line verdict

**The channel was built and the pixels are demonstrably read. The endpoint registered to prove it came
out `inconclusive` — D = 1 over 6 retained cells, p = 0.176 — and the reason is a ceiling in the case
set, not a failure of the channel.** The second endpoint came out **`closed`, A = 6 of 6, and that number
is the most misleading thing in this document**: four of the six rows that reported *"I could not see the
picture"* shipped **`supports`** — *"this image is fine"* — in the same JSON object.

**Reporting an absence and acting on it are two different things. This milestone demonstrated the first
and, in the same breath, measured the second failing.**

---

## The instrument, fixed before the runs existed

| | |
|---|---|
| Model | `gemma4:31b`, `temperature = 0`, digest `6316f0629137…` — the same tag and digest the two previous milestones ran |
| Oracle | ACT gold, keyed by `act_testcase_id`; collapse `FLAGS = {does_not_support, partially_supports}`, `CLEAN = {supports, not_applicable}` |
| Case set | **7 cases / 7 findings**, `act-image-opaque@1` (and its un-ablated twin `act-image-leaky@1`) |
| Primary endpoint | **D** = pool cases whose `with-image` verdict differs from `mismatched-image`, over 7 cells fixed in advance |
| Second endpoint | **A** = of the 6 image-decided cases, how many blind rows report the evidence as `absent`, out of 6 |
| Verdicts | pre-committed for both, covering every value each could take |

### What the case set can and cannot carry

- **7 of 27 candidate cases (26 %).** Of 51 published cases across the three ACT image rules, **27 are
  usable → 15 mint a finding → 7 reach the pool**, after 4 are dropped as prompt-level twins (both halves
  of two pairs, never one) and 4 belong to the retracted rule below. Of the 12 usable cases that mint
  nothing, none fails for a reason that has anything to do with pictures: axe's `image-alt` selector is
  `img` only, so 4 `<svg>`, 4 `<canvas>` and 2 `<input type="image">` cases never mint, and 2 more are
  `aria-hidden`. All 7 pool cases render their image (`naturalWidth` 72 / 320 / 150), asserted separately
  on the leaky set and the opaque set — the gold presumes the image loaded, so this is a validity
  requirement and not a nicety.
- **Three visual discriminations, not seven.** Four of the seven cases render the *same* 32 822-byte
  JPEG, two the same 1 927-byte PNG logo, one a 7 350-byte JPEG of bread. The effective independent unit
  count is **3**, which is why **no sign test is computed anywhere in this milestone** — any paired
  statistic over this pool is pseudo-replication at any threshold.
- **The pool leans on a rule ACT has withdrawn.** Verbatim, from the frozen export and the rule page:
  *"This rule is not maintained anymore and should not be used."* `9eb3f6` — *DEPRECATED — Image filename
  is accessible name for image* — carries **5 of the 7 pool cases (71 %)**; the live rule `qt1vmo` carries
  **2 (29 %)**. ACT deprecated it as superseded by `qt1vmo` (Community Group call 2021-01-14, PR #1538);
  **no dispute about expected outcomes appears in the record**, which is the only reason the cases are
  usable at all.
- **The ablated set scores WCAG 1.1.1, not the deprecated rule's own outcome.** The ablation replaces
  `src`, `srcset` and the directory component with `/img/{a,b,c}.png`, one letter per distinct image. The
  `alt` text and the rendered bytes are untouched, so *"does this accessible name describe this image"* is
  unmoved. What the ablation **does** destroy is `9eb3f6`'s own applicability — it is a rule about a name
  that *is* the filename, and after ablation no name is a filename, **on five of the seven cases**. The
  labels still carry because the set is scored on 1.1.1; they would not carry as `9eb3f6` outcomes. A
  case-by-case human review of all seven before/after prompts is at
  [`image-ablation-review.md`](image-ablation-review.md).

### Three decisions that qualify every number below

**1. All six conditions were drafted against PINNED candidate criteria, not live retrieval.** The
candidate block holds the single criterion the class is about (1.1.1), where a live retriever returns
several candidates including distractors. **These are therefore not production's candidates and nothing
here may be read as what a live scan would surface.** The reason is that both endpoints rest on
byte-identical prompts, and a retrieval service is one more thing that can move between two calls hours
apart. It is identical across all six conditions, so it cannot move D, A, or the leaky→opaque difference.
It bought one thing back: the pre-wiring payload control could be re-checked **on a live pass** — all 28
recorded payload hashes of the two text-only conditions equal `drafter_payload_baseline.json`, which a
retrieved block would have made uncheckable.

**2. D's four conditions never tell the model a picture is attached.** Keeping the prompt text identical
is what the statistic rests on, and it also means **the model was never told to look**. Pre-registered as
a choice and reported as a limitation. A's two conditions do tell it — that is their manipulation — which
is why their prompts differ by construction and why they are a separate registry: **0 prompt hashes are
shared with D's four**, checked rather than asserted.

**3. These runs had no pre-flight gate.** The repo's dry gate is pinned to the 44-case acceptance set and
its referent blocks and was not generalised, so **no gate ran before any image condition**. Stated rather
than implied.

---

## The primary endpoint: D

> **D = the number of pool cases whose `opaque/with-image` verdict differs from its
> `opaque/mismatched-image` verdict.** Defined over cells fixed in advance, never over verdicts.

| | |
|---|---|
| **D** | **1** |
| Cells | 7 defined · **6 retained** · 1 excluded for within-condition drift (`1ff696703e`) |
| Live cells | 4 defined · 3 retained |
| Null rate used | **0.03175 = 2 / 63**, this milestone's own measurement |
| Null rate compared against | 0.01852 = 1 / 54, the referent-injection milestone's; the rule is `max(·,·)` and this one is larger |
| p(D ≥ 1 \| 6 retained cells) | **0.176** |
| **Verdict** | **`inconclusive — indistinguishable from drift`**, one of the four pre-committed outcomes |
| Direction *(secondary)* | **1 / 1 toward_flag**, the pre-registered direction; 0 toward clean |
| Specificity control `a2333ec76e` | did **not** move ✓ |

The one disagreement: **`be6b29e220`**, `alt="W3C"`, shown the **bread** — `supports` becomes
`does_not_support` across all three samples of each condition.

### Per-condition stability

| condition | samples | pairs | disagreeing | rate |
|---|---|---|---|---|
| `leaky/no-image` | 1 | 0 | — | **not measurable** |
| `opaque/no-image` | 3 | 21 | 0 | 0.000 |
| `opaque/with-image` | 3 | 21 | **2** | 0.095 |
| `opaque/mismatched-image` | 3 | 21 | 0 | 0.000 |
| `opaque/told-no-image` | 3 | 21 | 0 | 0.000 |
| `opaque/told-with-image` | 3 | 21 | 0 | 0.000 |

`leaky/no-image` is **not measured**, which is not the same as measured and found perfect. The null rate
is pooled over the three sampled conditions of D **including the cell D excludes** — estimating it from
the retained cells alone would condition it on the very stability the endpoint acts on. All 2 of the 63
disagreements sit in one finding of `with-image`, which is the cell D drops.

### The receipts — proof the manipulation actually ran

**84 receipt rows over 3 samples, 0 failures.** Every row records the `sha256` the drafter reports having
*sent*, never one a caller believes it passed. All **7 of 7** digests differ between `with-image` and
`mismatched-image`, exactly where the permutation frozen before any verdict existed says they should, and
the live rows match the model-free rehearsal frozen at wiring time. A byte *count* could not have checked
this: four of the seven findings render the same photograph.

### Two numbers a mechanical reading of D would bury

**1. There was a ceiling, and the spec's power description missed it.** `opaque/with-image` already
flagged **6 of 7** cells, including **3 of the 4 live** ones. The pre-registered direction is
*toward flag*, so a cell already flagged had nowhere to go. **Exactly one cell was free to move in the
predicted direction — and it moved.** The "4 live cells" description overstates the power that existed;
effective power was **1 cell**, and D = 1 is that one cell being 1 for 1.

**2. The binary collapse absorbs two thirds of the movement.** At the raw four-value `Conformance`,
**3 of the 7 cells moved**, all toward more severe — `be6b29e220` (counted), `cfd1636ab4`
`partially_supports → does_not_support` (**not** counted: both collapse to FLAG), and `1ff696703e`
(excluded for drift). Over the 6 retained cells alone: raw conformance moved on 2, the collapse counts 1.
**D stays on the axis it was registered on** — redefining an endpoint after seeing the data is this
project's own definition of a specification violation — but the cost is printed here rather than left in
the artifact.

**And D systematically under-detects attendance.** A mismatched picture may make the drafter genuinely
*uncertain* rather than cleanly flip it, and the stability filter codes that uncertainty as noise and
drops the cell. The bias is conservative — it can only cost D, never inflate it — and the one cell it
dropped, `1ff696703e`, is precisely a cell that wobbled between `partially_supports` and `supports` with
its own picture attached.

---

## The pixels are read. That is proven from the text, not from D

Zero extra model calls; read out of the frozen rows. The three opaque conditions of D send **byte-identical
prompts** — checked, not assumed: over all 63 of their rows there is **exactly one distinct
`prompt_sha256` per case** — so the pixels are the only thing that can differ, and therefore the only
possible source of any difference in what the text describes.

| condition (canonical sample) | rows whose remediation names the picture that was attached |
|---|---|
| `opaque/no-image` | **0 of 7** |
| `opaque/with-image` | **5 of 7** |
| `opaque/mismatched-image` | **6 of 7** |

**And across all 42 rows of the two image conditions, not one describes the picture as showing anything
other than what was actually attached.** Given the bread, the drafter writes *"a descriptive alternative
that accurately describes the image of bread"* on a page whose `<img alt="W3C">` really carries the W3C
logo. Given the logo where the page carries Copenhagen, it writes *"describe the image as the W3C logo
instead of 'Nyhavn'"*.

> **This is qualitative and was not pre-registered.** It is hypothesis-generating evidence about the
> mechanism and **cannot be promoted to an endpoint**. It is reported because *"D = 1"* alone would leave
> a reader believing the channel might not deliver anything, and that belief is false.

**D = 1 is the readout being blunt. It is not the channel failing.**

### The drafter never objected to the wrong picture

Across **21 mismatched rows — every row of every sample — zero objections.** Not one says the attached
image looks nothing like what the page's markup describes. It takes the pixels as the page's own and
rewrites the remediation around them, at a confidence of **0.95 on 9 rows and 1.0 on the other 12**.

**The condition in which every single picture is wrong is the most confident condition in the milestone**
— mean confidence 0.979, against 0.926 when every picture is right:

| condition | mean confidence | range |
|---|---|---|
| `opaque/told-no-image` | 0.864 | 0.80 – 0.95 |
| `opaque/with-image` | 0.926 | 0.85 – 0.95 |
| `leaky/no-image` | 0.929 | 0.90 – 0.95 |
| `opaque/no-image` | 0.936 | 0.90 – 0.95 |
| `opaque/told-with-image` | 0.971 | 0.90 – 1.00 |
| **`opaque/mismatched-image`** | **0.979** | **0.95 – 1.00** |

The manipulation working is what D measures; **that nothing anywhere in the pipeline notices the
contradiction is a separate property of the product**, and it is stated here rather than left implied.
Confidence is a field this repo has already measured decorative and over-confident (ECE 0.392), so this
ordering is not new evidence about calibration — but it is a second, independent sighting of the same
thing, in the one condition where the ground truth of *"is the evidence sound"* was known in advance.

### Per case, the picture helped and hurt in equal measure

`opaque/no-image` → `opaque/with-image`, over the six image-decided cases:

| sub-class | cases | effect of supplying the picture |
|---|---|---|
| **the `alt` lies about the picture** (gold *failed*) | `ERCIM` on the W3C logo; `Paris` on Copenhagen | **0/2 → 2/2 — the picture fixed both** |
| **the `alt` is correct but terse** (gold *passed*) | `Nyhavn` ×2 | **2/2 → 0/2 — the picture broke both** |

Net: 4 of 7 correct before, 4 of 7 correct after. **The "accuracy unchanged" headline is two opposite
effects cancelling.** The second is *not* a perception failure: on both broken cases the drafter
described the attached picture accurately and then downgraded to `partially_supports` on the ground that
the `alt` omits *"the colorful houses and boats along the canal"*. That is an **over-strict adequacy
standard in the help text**, not a defect in the channel — and it is the same help text whose *"a
filename … does NOT describe"* clause drives the leaky→opaque difference below. One sentence in a prompt
is doing more work in this milestone's numbers than the image channel is.

---

## The leaky → opaque difference *(secondary, descriptive)*

| condition | correct | flagged | FP | FN |
|---|---|---|---|---|
| `leaky/no-image` | **4 / 7** | 6 | **3** | 0 |
| `opaque/no-image` | **4 / 7** | 2 | 1 | **2** |

**4 of the 7 cases moved, all 4 toward clean, 0 toward flag.** Removing the path cues did not change
accuracy — it removed the model's reason to flag, and the error profile inverted: the leaky condition
cries wolf, the opaque one under-flags.

**The fixture-artifact caveat, reported beside the difference and never subtracted from it.** In the
leaky condition the `alt` **equals its own filename on 4 of 7 cases verbatim**, and on **5 of 7** once one
trailing extension is stripped, while the drafter's help text says, verbatim:

> *"An alt attribute is PRESENT — judge whether it MEANINGFULLY describes the image for WCAG 1.1.1; a
> filename or generic word ('image', 'photo', 'logo') does NOT."*

So on those cases the leaky cue is close to a **string-equality trigger** — a property of how a deprecated
rule's fixtures were authored, not of pages anyone ships. Both readings of the cue rule are reported
because they disagree on exactly one case, and that case is one of the three leaky false positives: the
strict rule alone would misattribute it. Under the verbatim rule 2 of the 4 moved cases carry the cue;
under the stem rule, 3 of 4.

**This is not the ablation gate.** The gate is the offline, model-free token check the opaque set was
derived under, asserted by `tests/test_image_opaque.py`. This difference is a description of two model
runs and stands in for nothing.

### The residual help-text tension, declared rather than absorbed

After full-path ablation `alt="Nyhavn"` and `alt="pain"` no longer trip *"a filename … does NOT
describe"* — but the help still says a **generic word** does not describe. The help text was deliberately
left unchanged across all six conditions, so the tension is constant and cannot move a difference between
them; it can and does move the absolute accuracy of every one of them.

---

## The second endpoint: A — does the drafter say it is judging blind?

**The defect, measured first with zero model calls.** Across the 70 already-frozen rows of D's four
conditions, **0 of the 28 blind rows** ever signalled that the picture was unavailable — at confidence
0.90–0.95 — and **0 of the 42 sighted rows** did either. The detector is 13 phrases pinned in code
*before* the rows were read through it, deliberately high-recall, reading the one field a drafted row has
that could carry the signal. Every hit would have been named; the list is empty.

> **What was missing is the pixels, not the element.** `<img src="/img/a.png" alt="ERCIM">` sits in the
> prompt, so *"there is no image"* would have been a false statement for the drafter to make. Whether it
> received the **pixels** is a fact the system already held and never told it.

| | |
|---|---|
| **A** | **6 of 6** |
| Read from | `opaque/told-no-image`, sample 1, all six image-decided cases, **no case dropped for instability** |
| Per-case sample agreement | 6 of 6 agree across all three samples |
| Contradicted rows | 0 |
| Control 1 — `a2333ec76e` (decided by text alone) must report `not_needed` | **holds** — and it judged `does_not_support` @ 0.95, correct from the text |
| Control 2 — no `told-with-image` row may report `absent` | **holds** — all 7 said `seen` |
| Receipts | **42 rows over 3 samples, 0 failures** — each condition covers all 7 findings, the blind one attached nothing, the sighted one attached each case's **own** captured bytes |
| **Verdict** | **`closed`** |

The receipt check is the same rule D's four conditions are held to, with one difference that is the
manipulation rather than a leak: the two announced conditions are *required* to ask two different
prompts, because they announce opposite things. A single prompt across both would mean the drafter was
told the same thing about two different messages.

**One thing A had working against it, on purpose.** The announced system prompt ends with a worked
example, and that example shows `"visual_evidence":"seen"`. A counts `absent`, so an `absent` example
would have manufactured the result; a `seen` one can only make A harder to reach. It was chosen that way
before the calls were spent, and it is stated here because a reader has no other way to know the example
was not tilted toward the number that came back.

### The ordering, stated rather than left to be inferred

**The blind-judgment question was raised after D's four conditions were frozen and read.** Its endpoint A
was pre-registered in the spec before a single one of its 42 calls was spent, its two conditions were
given their own registry, and **D was neither recomputed nor re-run** — all four of its passes, both of
its reports and the dry receipt are byte-identical on disk afterwards, checked by `git diff` and pinned by
digest.

### What ships, and what A decides

- **The marking shipped on its own evidence, with no model call.** A pixel-decided finding drafted while
  `image_ref is None` now carries `visually_verified is False` from the system's own fact, and a row
  claiming it *saw* the picture against that record fails validation, retries once, then degrades to the
  visible fallback.
- **The refused claim is not lost when that happens.** Degrading produces a fallback row byte-identical
  to the one an unparseable response produces, so without a second channel a contradiction and a parse
  failure would be indistinguishable and the model's claim would be gone before any caller saw it.
  `DraftResult.contradicted_claim` carries it out of the guard, which is what let this endpoint count
  contradictions rather than abort on them. **It never fired against the real model: 0 contradicted rows
  across both announced conditions** — a measured zero, exercised offline in the drafter's own tests.
- **Blast radius over the whole scoped corpus — 68 findings across 3 scopes**, not over the seven image
  cases: the marking writes **`False` on 14**, `None` on 54, `True` on 0 (no picture is attached on a
  production draft, so that branch is not exercised by the sweep). The contradiction guard degrades
  **0 rows as shipped** — structurally, since the default response shape carries no field for the claim —
  and **14** under the adversarial bound where the announcement is on and every row claims `seen`. The
  acceptance corpus mints no `image-alt` finding at all and no assembled-path finding exists anywhere in
  the corpus; both measured, not assumed.
- **`announce_image` ships defaulted off.** **A is the number that decides whether it flips, and this
  milestone delivers the number, not the change of default.** Flipping it is a declared prompt change that
  moves every payload hash in the pre-wiring baseline and re-freezes it.

### A live gap in the payload control, routed around rather than closed

`LLMRequest` records `schema.__name__` — the class name, not the shape. **A field added to `_LLMDraft`
in place would therefore move neither `prompt_sha256` nor `payload_sha256`**: the control built to catch a
moved *ask* is blind to a moved *answer*. The announced path was given its own response-schema class so
that its hashes move exactly when its ask moves, which routes around the gap for this change. **The gap
itself is open**, named here and in `CONTRACTS.md` §5.

---

## A being `closed` is not the finding

**Four of the six withheld rows shipped `supports` — "this image is fine" — while reporting in the same
JSON object that they could not see the image.**

| case | `alt` | `visual_evidence` | conformance | confidence | remediation |
|---|---|---|---|---|---|
| `be6b29e220` | `W3C` | `absent` | **`supports`** | 0.8 | *"None required."* |
| `530266c611` | `ERCIM` | `absent` | **`supports`** | 0.9 | *"No remediation necessary."* |
| `cfd1636ab4` | `Nyhavn` | `absent` | **`supports`** | 0.9 | *"No remediation necessary."* |
| `1ff696703e` | `Nyhavn` | `absent` | **`supports`** | 0.9 | *"No remediation necessary."* |
| `607ad4964a` | `pain` | `absent` | `does_not_support` | 0.8 | *"Replace the vague alt text…"* |
| `f7406b89f8` | `Paris` | `absent` | `partially_supports` | 0.8 | *"Provide a more descriptive text alternative…"* |

All six reported `absent`, which is what A counts — and **not one of the six moderates its verdict because
of it.** The two that flagged are not counter-examples: nothing in their output ties the flag to the
missing picture, and one of them (`607ad4964a`, which ACT *passed*) is a false positive. The field moved;
the judgment did not.

`530266c611` is the one to look at twice: its `alt` reads **ERCIM** and its picture is the **W3C logo**.
ACT marks it **failed**. Blind, the drafter answered *"no remediation necessary"* at 0.9 — while
correctly reporting that it could not see the thing the `alt` is supposed to describe.

### Why it did that — reconstructed from the prompt, not guessed

The announced prompt was rebuilt through the shipped code. Two facts explain the behaviour completely:

1. **The adequacy test the help text states is decidable from text alone.** *"a filename or generic word
   ('image', 'photo', 'logo') does NOT [describe]"*. `alt="Nyhavn"` is neither a filename nor a generic
   word, so it passes that test without any pixels.
2. **Nothing in either prompt links the two fields.** The system prompt defines `visual_evidence` as
   *"about the evidence THIS judgment needed"* and defines `conformance` separately; no rule says a
   judgment reporting `absent` must moderate its verdict. The model answered two independent questions
   correctly and independently: *"did this need pixels you lacked?"* → `absent`; *"does this alt pass the
   test you were given?"* → yes.

There is no place to put the answer that would join them: `Conformance` has four values —
`supports`, `partially_supports`, `does_not_support`, `not_applicable` — and none of them means *abstain*.
Adding one would move `stats.FLAGS`/`CLEAN` and every acceptance number in the repo, and was ruled out of
scope in advance rather than re-derived as a good idea mid-ticket.

### Neither kind of missing picture licenses `does_not_support`

Read straight out of the frozen ACT export, identical for **both** pool rules:

```
wcag20:1.1.1   failed        →  not satisfied
               passed        →  further testing needed
               inapplicable  →  further testing needed
```

Two consequences, and neither is optional.

- **A missing image is not a violation.** `qt1vmo`'s Applicability excludes, verbatim, *"The element is
  an `img` element where the current request's state is not completely available"*, and its Expectation
  is relational: *"Each test target has an accessible name that serves an equivalent purpose to the
  non-text content of that test target."* No content, no second term to be equivalent to. That makes the
  rule *inapplicable*, which still maps to *further testing needed*. **A fix for the blind-row defect
  must degrade to undetermined, never to `does_not_support`** — the latter would manufacture exactly the
  cry-wolf failure the acceptance benchmark measured at FP 0.433. *(These two sentences are quoted from the
  published rule page at `https://act-rules.github.io/rules/qt1vmo`; the export vendored in this repo
  carries the outcome mapping but not the rule prose.)*
- **These pictures were not missing.** Every pool page renders its image (`naturalWidth` 72 / 320 / 150,
  asserted separately on both sets). The rule is fully applicable; *our scanner* did not send the pixels.
  Different fact, same reporting consequence: **undetermined**.

There is a third consequence that sits outside what this milestone measured but is visible in the same
mapping: an ACT *pass* licenses only *further testing needed*, so **`supports` on this class is
unsupportable at any evidence level**, not merely when the judgment was made blind. That is an
instrument-level question, strictly larger than the evidence-level one measured here. Nothing in this
document's numbers depends on it — the image conditions are scored purely by the binary FLAG/CLEAN
collapse against `expected`, which is a *detection* claim and never a conformance claim.

### The same defect this project has now built twice

`visual_evidence` (the model's claim) and `visually_verified` (the system's fact) exist, are populated,
and are pinned by tests — and **nothing in the product consumes either of them.** `cli.py`, the module
that renders the report and computes the per-row trust label, contains **zero** references to either
field; the only readers anywhere in the repo are the eval modules that exist to measure them. That is the
exact shape of the `confidence` defect the calibration milestone measured and named: a field that is
written, looks like a signal, and changes nothing. **Arrived at a second time, by a different route,
inside the milestone that was measuring honesty.**

**What the product does today, read from the code rather than measured.** `cli.py::_trust_label` grades a
row on three things — a specialist's approval, whether the conformance is `supports`, and whether every
citation verified. Two halves follow, and they are not symmetric:

- **The `supports` half is already handled.** Any row whose conformance is `supports` is forced to
  `drafter-judged` and can never reach the top label, and the rendered verdict carries an explicit caveat.
  So the four blind-and-`supports` rows above would already be labelled down — by a rule written for an
  unrelated reason, before any of this was measured.
- **The `does_not_support` half is not.** Nothing in that function reads `visually_verified`, so a row
  judged without the pixels it needed, whose citations happen to verify, has nothing standing between it
  and the strongest label this product offers. **That is a reading of the code and not a result: no
  condition in this milestone ran the citation validator, so it is undemonstrated here and is recorded as
  a question, not a finding.**

---

## Announced vs silent — measured, and explicitly not an endpoint

> **This is not an endpoint, was not pre-registered, and cannot be read as one.** n = 7 per condition, and
> the announced conditions differ from the silent ones in **both** the prompt text and the response
> schema, so the comparison is confounded by construction. It exists in no frozen report; it is computed
> here from the six run artifacts under the same `stats.is_flag` collapse every other number uses.

| condition | correct | flagged | FP | FN |
|---|---|---|---|---|
| `leaky/no-image` | 4 / 7 | 6 | 3 | 0 |
| `opaque/no-image` | 4 / 7 | 2 | 1 | 2 |
| `opaque/with-image` | 4 / 7 | 6 | 3 | 0 |
| `opaque/mismatched-image` | 3 / 7 | 7 | 4 | 0 |
| **`opaque/told-no-image`** | **5 / 7** | 3 | 1 | 1 |
| **`opaque/told-with-image`** | **6 / 7** | 4 | **1** | 0 |

The announced conditions score *better* than their silent twins — and `told-with-image` is the most
accurate condition in the milestone, with a third the false positives of `with-image`. Both of the terse
`Nyhavn` cases that the picture *broke* under the silent prompt come back correct under the announced one.
**That is a hypothesis worth testing, not a result**: it is exactly what the confound would also produce.
`opaque/mismatched-image`, for the record, is a **constant classifier** — all 21 draws `does_not_support`.

---

## The retraction, kept with its ground

A secondary class carrying its own pre-registered prediction — ACT rule `e88epe` — was **retracted before
any of its calls were spent**, and the prediction was retracted with it rather than quietly scored.

**The ground is a confound checkable with zero model calls:** within `e88epe`'s four minting cases,
reachability is *perfectly correlated with gold*. Both `passed` cases are decided by an adjacent
paragraph the minted prompt does not carry; both `failed` cases are decided by the pixels. Any aggregate
movement in that class would be uninterpretable — improvement on the reachable half and a coin flip on
the other are indistinguishable.

**A motive is declared:** the retraction removed roughly 36 model calls from the milestone.

**The precondition that makes this a pre-registration amendment rather than a post-hoc one is verified,
not asserted:** no drafter output for that rule exists anywhere in this repo. It is enforced by a test
that fails if any of its case ids, or the rule id itself, ever appears under `benchmark/`.

---

## What was spent

| what | calls | evidence |
|---|---|---|
| `leaky/no-image` | 7 | frozen run artifact |
| `opaque/no-image` | 21 | frozen run artifact |
| `opaque/with-image` | 21 | frozen run artifact |
| `opaque/mismatched-image` | 21 | frozen run artifact |
| `opaque/told-no-image` | 21 | frozen run artifact |
| `opaque/told-with-image` | 21 | frozen run artifact |
| **subtotal reaching disk** | **112** | 112 rows counted in `benchmark/runs/` |
| `opaque/no-image`, **discarded attempt** | **6** | declared below; nothing reached disk |
| capture spot-check | 3 | `captured_image_discrimination.json` (`model_calls_spent: 3`) |
| transport spike | **2** | `multimodal_transport_probe.json` (`model_calls_spent: 2`) |
| wiring smoke test | 1 | declared; no artifact |
| **pre-spec image probe** | **3** | declared; no artifact |
| **total** | **127** | |

**126 of the 127 touched held-out pool material.** The one that did not is the wiring smoke test, which
drafted `499be21170` — a case the twin-exclusion rule had already removed from the pool — so no case any
measurement reads was drafted before its own condition ran.

**⚠️ 127 is a floor, not an exact count, and the reason is worth knowing.** What is exactly counted is
**112 drafted rows** in `benchmark/runs/`. The drafter ships with `retries = 1`: an unparseable response
is retried once before degrading to a visible fallback. **No row in any condition is a fallback** — the
harness aborts a condition on one — so no row *failed*; but a row whose first attempt was unparseable and
whose retry succeeded costs two calls and looks identical on disk. The run artifacts record no attempt
count, so a recovered retry is invisible in them and every figure here treats one row as one call.

**⚠️ The pre-spec image probe is declared because it is the least visible spend in the milestone and the
most consequential.** Before this spec was written, each of the three pool images was sent to the model
directly and it resolved all three — naming the W3C logo, answering *"this is Copenhagen, not Paris"*, and
recognising *pain* as bread. **That is a model run on held-out data that resolved the milestone's largest
uncertainty before pre-registration.** It left no receipt, so its count of three is declared from the
spec's evidence ledger rather than measured from an artifact. The capture spot-check later asked the same
three questions of the *captured* bytes with pre-registered readings and resolved all three again — which
is what separates *"the capture destroyed the picture"* from *"the plumbing delivered nothing"* for every
condition afterwards.

**⚠️ The transport spike cost two calls, not one.** The first request reached the model and returned; the
script then crashed while writing its receipt, so the response was lost and the call was repeated. A spend
that leaves no artifact is the easiest kind to drop from a run count, so it is declared on the receipt
itself and here.

**⚠️ Six calls were spent and thrown away on a discarded `opaque/no-image` attempt.** The test suite was
started while that condition was drafting, and seven test files call the real model, so two requests to
the same model overlapped — read off the inference server's own log, where one measurement call took
**3m33s against a clean-run mean of ~73s**. Concurrent requests share KV-cache slots, which is the exact
mechanism the referent-injection milestone diagnosed as this stack's source of nondeterminism, and it hit
**sample 1, the canonical one**. Five findings had been drafted and a sixth was in flight; nothing reached
disk, and the condition was re-run with nothing else touching the model. **`leaky/no-image` was audited in
the same log and deliberately *not* re-run** — its seven calls are strictly sequential and end at
07:26:51, before the suite started at 07:28:46.

**⚠️ The ~73 s is that condition's own clean-run mean and is not a milestone-wide rate.** Throughput moved
by a factor of two across the run window, for reasons outside this experiment: `mismatched-image` was
written 36 minutes after `with-image`, while `told-with-image` was written **70 minutes** after
`told-no-image` — 21 calls each way. (Those are the gaps between frozen timestamps, so they are the
per-pass durations only if each pass began when the previous one was written.) A per-call rate has to be
measured off the run in hand; carrying one forward from an earlier condition produces an ETA that is
wrong by half.

---

## What this does not license

1. **That supplying the visual fact restores judgment.** The instrument cannot support that claim; the
   pool has three independent discriminations and a ceiling that left one cell free to move.
2. **That any of this transfers to real pages.** Synthetic ACT fixtures throughout, 71 % of them from a
   withdrawn rule.
3. **Broad visual competence.** Three discriminations, four of seven cases the same JPEG, two the same
   logo — and **all three were shown answerable by this model before the spec was written**. What the
   endpoint proves is that the plumbing delivers a fact the model already possessed: an integration
   result.
4. **That the image gap is closed.** 7 of 27 candidate cases — exactly the subset the channel can reach.
   `<svg>`, `<canvas>` and `<input type="image">` remain matcher-limited; `link-name`'s deciding fact is
   outside the page and is unreachable to a multimodal drafter too.
5. **Anything about a different model.** None were compared.
6. **The drift rate to useful precision.** 63 within-condition pairs corroborate the earlier 1/54; they
   cannot resolve it.

---

## Sources for the two numbers that live in no report

- **The ACT outcome mapping** is the raw `ruleAccessibilityRequirements` block in the frozen export
  `clearway/fixtures/act-gold/testcases.json`. The repo's own parser keeps only the WCAG SC ids and
  **discards the outcome mapping**, so it appears in no derived artifact and was read from the export
  directly.
- **The announced-vs-silent accuracy table** exists in no frozen artifact. It is computed from the six run
  artifacts in `benchmark/runs/` through `clearway.eval.image_score.condition_summary`, which is the same
  function and the same `stats.is_flag` collapse behind every other accuracy figure in this document.
- **The per-condition confidence table** likewise exists in no frozen artifact; it is the mean and range
  of `draft.confidence` over every row of each run artifact.
- **The remediation-naming counts and the zero-objection finding** were read by eye from the frozen rows,
  case by case. They are qualitative and are labelled as such wherever they appear.
- **`qt1vmo`'s Applicability and Expectation** are quoted from the published rule page, which is not
  vendored here — the export carries the outcome mapping and the case HTML, not the rule prose.

---

## The rule this document was written under

**Report ugly numbers as they are.** The unacceptable failure is not a low score but an untrustworthy one.
The primary endpoint of this milestone is `inconclusive`; its second endpoint is `closed` and the closure
is close to meaningless on its own; and the most useful thing produced is neither — it is the measured
demonstration that this pipeline will now tell you it could not see the picture and then tell you the
picture is fine.
