# Clearway — M8: Multimodal

> **Scope.** M8 **builds the image channel and proves the model attends to the pixels.** It does **not**
> claim that supplying the visual fact restores judgment — that needs a paired test, and **no ACT gold
> set can support one**. The mechanism question moves to M9, which builds real-page image gold.
>
> The primary endpoint is a **manipulation check whose oracle the experimenter constructs**, so it is
> free of the ACT gold's power ceiling entirely. A second, smaller question sits beside it: **what the
> drafter does when the channel is empty** — whether it knows, and says, that it is judging blind.

## Table of Contents

- [Preamble](#preamble)
- [Why this is not a certification milestone](#why-this-is-not-a-certification-milestone)
- [The measured case set](#the-measured-case-set)
- [The primary endpoint: D](#the-primary-endpoint-d)
- [Controls](#controls)
- [Goal & exit criterion](#goal--exit-criterion)
- [Alternatives considered, and one retraction](#alternatives-considered-and-one-retraction)
- [What is explicitly not measured](#what-is-explicitly-not-measured)
- [Tickets](#tickets)
- [Runs and cost](#runs-and-cost)
- [Evidence ledger](#evidence-ledger)

---

## Preamble

M7 tested one hypothesis: **accuracy is governed by whether the deciding fact is present in the input,
not by model strength.** It came out directional and uncertified (b = 5, c = 1, p = 0.109), but its
diagnosis was worth more than its p-value: a fact **in the page and in the prompt** already worked; a
fact **in the page but absent from the prompt** was fixed by supplying it; a fact **not in the page at
all** stayed unreachable.

The image classes are that third case made reachable by a different channel — the fact is in the page,
as pixels, and no text extraction can carry it. `clearway/llm/` has **no image path at all**.

> *Stated in the present tense when this was written, and **T5 is what made it false**: the gateway seam
> now takes an optional `ImagePart`. Kept verbatim rather than rewritten — it is the statement of the gap
> this milestone exists to close, and a spec that quietly re-describes its own starting point loses the
> ability to say what changed.*

**M8 builds that path and proves the model uses it.** Three outcomes, and only three:

1. **A product capability**, carried on the production path (`scanner → normalizer → drafter`), not an
   eval-only side channel. It is M9's prerequisite.
2. **A manipulation check** that is scored by code rather than by reading prose: attach the *wrong*
   image behind a byte-identical prompt and require the verdict to move.
3. **An honesty guarantee on the empty channel**: a pixel-decided finding judged without the pixels
   must be known to the pipeline and marked, not answered confidently as if it had been seen.

---

## Why this is not a certification milestone

`b` in a paired sign test is bounded by **baseline errors**, not by case count. Measured before any run:

| candidate gold | independent discriminations | baseline errors | ceiling |
|---|---|---|---|
| `qt1vmo` + `9eb3f6` (this pool, 7 cases) | **3** | ~3–4 | p ≈ 0.06 |
| `0va7u6` (5 minting cases) | **5** | **2 of 5, measured** | p = 0.25 |

**No sign test is computed or reported in M8.** The reason is not that the ceiling is close to α — it is
that the pool holds **three visual discriminations over seven cases** (four cases are the same
photograph, two the same logo), so the **effective independent unit count is 3** and *any* paired
statistic on this pool is pseudo-replication at *any* threshold. That argument is an **inference** from
the asset hashes, and unlike a numeric ceiling it cannot be broken by how the run comes out.

> This project already ruled on this shape: `document-title`, 3 reachable errors, *"cannot be certified
> at any fix quality… reporting it as certified would be a specification violation."*

---

## The measured case set

> **⚠️ Measured, not inferred** — the real scanner and normalizer were run over every usable ACT case
> containing an `<img>` (93 cases), no model calls. T0 reproduces this as a frozen repo artifact.

### What is reachable

Of the 16 usable `qt1vmo` + `e88epe` cases, **6 mint a finding**; **ten are matcher-limited** — axe's
`image-alt` selector is `img` only, `svg-img-alt` needs `role=img|graphics-*` which ACT's `<svg>` cases
lack, `<canvas>` has **no alt rule at all**, `<input type="image">` is deferred. **Un-deferring the
variants would not unlock the SVG or canvas cases.** `9eb3f6` mints on **9 of 11**.

### The exclusion rule — informational, and applied to the ablated set

> **Any two cases whose minted prompts differ only in tokens the ablation renders uninformative are
> excluded — both halves, never one.** Byte-identity is the special case, not the rule.

Stated informationally because **byte-identity is blind to the failure that matters**: if the ablation
numbers filenames sequentially, two prompts that are informationally identical differ by one digit and
the test returns False. **The rule is checked on the ablated set, not only the original** (T0 checks
originals; T3 re-checks post-ablation — see T3 Acceptance 2).

Measured on the originals, `9eb3f6` contains **two** such pairs — both excluded, all four cases:

| prompt | cases | gold |
|---|---|---|
| `<img src=".../nyhavn.jpeg" alt="Nyhavn">` | `28d908a951` / `f636f815cb` | passed / **failed** |
| `<img src=".../nyhavn.jpeg" alt="nyhavn.jpeg">` | `499be21170` / `556be1533c` | passed / **failed** |

They differ only in `<picture>`/`<source>` elements and a `download` wrapper, neither carried by the
snippet. Neither text nor a screenshot resolves them — a render is one viewport, and the distinctions
are not visual.

**Two earlier defects, corrected.** An earlier draft kept `556be1533c` while dropping its twin —
retaining the half a text-only drafter scores correctly, which flattered the pool. And it excluded
`1ff696703e` for a `srcset` device-pixel-ratio hazard **that does not exist**: all three candidates are
the same bytes. `1ff696703e` is restored. **`act_gold.contradictory_gold_twins()` catches neither pair
— it hashes fixture files, and these are twins only at prompt level.**

### The pool — 7 cases / 7 findings

| case | gold | image | alt | decided by |
|---|---|---|---|---|
| `be6b29e220…` | passed | W3C logo | `W3C` | the image |
| `530266c611…` | failed | W3C logo | `ERCIM` | the image |
| `cfd1636ab4…` | passed | Nyhavn | `Nyhavn` | the image |
| `1ff696703e…` | passed | Nyhavn | `Nyhavn` | the image |
| `f7406b89f8…` | failed | Nyhavn | `Paris` | the image |
| `607ad4964a…` | passed | bread | `pain` | the image |
| `a2333ec76e…` | failed | Nyhavn | `94251e11…` | text alone — a hash describes nothing |

**Four of the seven are the same 32 822-byte JPEG** (`sha256 c5cc0db7…`, 320×213) served under four
names; two are the W3C logo (1 927 B, 72×48); one is bread (7 350 B, 150×100). **Three distinct images.**

Ids shown are 10-character prefixes. **`act_testcase_id` is the full 40-character sha**; `9eb3f6`'s
`ruleName` carries its em-dash prefix (`"DEPRECATED — Image filename is accessible name for image"`).
Both must be matched verbatim.

### `9eb3f6` is deprecated — traced, not paraphrased

ACT deprecated it as **superseded by `qt1vmo`** (CG call 2021-01-14, PR #1538); **no dispute about
expected outcomes appears in the record**, so the stop-condition is not triggered. ACT's wording is
quoted, not softened: *"This rule is not maintained anymore and **should not be used**."* Every report
states that M8's pool depends on it.

**⚠️ `qt1vmo`'s applicability excludes an `img` whose request did not complete — the gold presumes the
image rendered.** Making assets load is a **validity** requirement. This applies to **both** the leaky
set and the opaque set; the opaque set is the one that carries the endpoint.

---

## The primary endpoint: D

**Construction.** A fourth condition, `opaque / mismatched-image`, attaches the *wrong* image behind a
**byte-identical prompt** — same frozen opaque HTML, same help, same candidate criteria. Only the
pixels change. The permutation is a **derangement over distinct images**, frozen in T3 before any
verdict exists:

| case | alt | true image | attached instead | live? |
|---|---|---|---|---|
| `be6b29e220` | `W3C` | W3C logo | bread | live |
| `cfd1636ab4` | `Nyhavn` | Nyhavn | W3C logo | live |
| `1ff696703e` | `Nyhavn` | Nyhavn | bread | live |
| `607ad4964a` | `pain` | bread | W3C logo | live |
| `530266c611` | `ERCIM` | W3C logo | Nyhavn | dead — should flag under any pool image |
| `f7406b89f8` | `Paris` | Nyhavn | bread | dead — same |
| `a2333ec76e` | hash | Nyhavn | W3C logo | dead by design — specificity control |

**The statistic.**

> **D = the number of pool cases whose `opaque / with-image` verdict differs from its
> `opaque / mismatched-image` verdict, over all 7 cases.**

Defined over **cells**, which are fixed in advance — never over verdicts, which are not. Power is
*described* by the 4 live cells; the test is *defined* over all 7. `a2333ec76e` stays inside D as a
within-experiment specificity control: it should **not** disagree, and if it does, the manipulation is
moving something other than perception.

**The null.** Under "the pixels are not attended", the verdict is a function of the prompt alone, and
the prompts are byte-identical ⇒ D = 0 **up to stack nondeterminism**. `temperature = 0` constrains the
sampler, not the stack (M7 diagnosed the mechanism as numerical, from KV-cache reuse).

> **The null rate is `max(M8's measured within-condition disagreement rate, M7's 1/54)`.**

M8's rate is estimated from **within-condition sample triples across all findings and all conditions,
including cells excluded from D** — those triples share byte-identical prompts *and* identical pixels,
which is exactly the null's premise. **Estimating the null only from retained cells would be circular**:
the excluded cells are the evidence that drift exists, and discarding them from the denominator while
acting on them in the numerator biases toward confirmation. The `max` rule exists because M8's own
estimate is low-resolution — 7 findings × 3 opaque conditions = 21 triples = 63 pairs, expected
disagreements ≈ 1.2 — so it is a **corroboration** of M7's figure, not a replacement, and cannot be
gamed by a lucky clean run.

**Pre-registered thresholds**, at a null rate of 1/54 over 7 cells:

| D | P(≥ D \| null) | verdict |
|---|---|---|
| ≥ 2 | **≈ 0.007** | **delivery confirmed** |
| 1 | 0.12 | **inconclusive** — indistinguishable from drift |
| 0 | — | **delivery refuted** |

**⚠️ Fewer than 2 retained cells ⇒ *Uninterpretable*, never *refuted*.** If instability removes six of
seven cells, D ≥ 2 is unreachable by construction and a mechanical reading would publish a false
negative as the milestone's headline. **The retained-cell count is reported beside D, always.**

**Direction** — every disagreement should move toward `does_not_support` — is a pre-registered
**secondary** strengthening. Reported, never gated on: gating on direction would re-import a
conditional denominator.

**⚠️ Instability may itself be the effect.** A mismatched image may make the model genuinely uncertain
rather than cleanly flip it; excluding that cell codes attendance as noise. This is conservative, so it
cannot inflate D — but **D systematically under-detects attendance, and T10 must say so in one
sentence.** Free secondary observation: **per-condition instability counts are recorded**, because
instability concentrated in the mismatched condition relative to with-image is itself weak evidence the
pixels are doing something. Recorded, not gated on.

**Which sample defines a verdict.** The canonical pass is **pass 1**, consistent throughout. **A cell
whose 3 samples disagree in either condition is excluded from D and named.** Since D's threshold is an
absolute count, excluding a cell only costs power and cannot bias toward confirmation. **Note that 3
samples is a weak filter** — a finding with a true 20 % flip rate survives it with probability 0.52 —
so "retained" is not "drift-free", which is precisely why the null is estimated from all cells.

---

## Controls

1. **One model throughout** — `gemma4:31b`, `temperature = 0`, **all six conditions** (D's four, plus
   T9's two). Digest `6316f0629137` with `vision` capability: **the same tag and digest M6/M7 ran.**
   No model change.
2. **⚠️ Ablation removes the whole path, not just the filename.** The `src` **and** `srcset` **and** the
   directory component are replaced. Two cues survive a filename-only rewrite and both are
   gold-relevant: `1ff696703e`'s `srcset` retains the literal tokens `nyhavn` and `paris`, and the
   directory `/test-assets/image-filename-as-accessible-name-9eb3f6/` **spells out the deprecated
   rule's own deciding criterion** on five of seven cases while partitioning the pool by rule.
3. **⚠️ The naming scheme is pinned, not left to the implementer.** All 7 cases use a single shared
   neutral directory and a **per-asset** (not per-case) name: `/img/a.png`, `/img/b.png`, `/img/c.png`,
   one per distinct image. Per-case indices would manufacture a distinguishing token the original did
   not have — and would defeat the exclusion rule by making informationally identical prompts differ by
   a digit. Never a hex digest, which would echo `a2333ec76e`'s failing pattern.
4. **The help text is unchanged**, and the residual tension is declared rather than absorbed: after
   full-path ablation `alt="Nyhavn"` and `alt="pain"` no longer trip *"a filename … does NOT describe"*,
   but the help still says a *generic word* does not describe.
5. **⚠️ Record whether the prompt says an image is attached.** Keeping the text identical across
   conditions is required for D — the whole statistic rests on byte-identical prompts — **and it
   guarantees the model is never told to look.** Pre-register the choice; report it as a limitation.
   **This holds for D's four conditions only.** T9 asks what the drafter does when it *is* told, so its
   prompt differs by construction and its `prompt_sha256` will not match theirs. Hence: **T9's
   conditions never enter D, D is not recomputed, and D's four passes are never re-run or
   overwritten** — they record calls that cannot be recovered.
6. **Text classes isolated by payload hash, across the class that carries the risk.** Assert
   byte-identity of the serialized request for **all 7 image-class findings under the no-image
   condition, before and after the wiring ticket**, keeping one M7 text-finding hash as a cross-class
   check. This replaces re-running conditions post-wiring: byte-identical requests at `temperature = 0`
   leave only stack nondeterminism, which is already measured.
   > **⚠️ Corrected at T5 — one hash cannot carry both this control and Control 7.** A serialized
   > request that includes the attached picture's digest *must* differ between conditions, so a single
   > "payload hash" makes this control and the byte-identical-prompt premise contradict each other.
   > Two hashes are recorded, and each is the falsifier of a different claim: `prompt_sha256` (system +
   > user + schema, picture excluded) must be **identical** across conditions that differ only in
   > pixels, and `payload_sha256` (the whole ask) must **differ** between them. With only the second, a
   > moved prompt and a changed picture are the same observation. Measured before/after comparison uses
   > the full payload hash under `image: null`, whose shape is fixed from the start so the two sides are
   > comparable at all. Frozen at `benchmark/reports/drafter_payload_baseline.json`, and covering the
   > leaky set's 7 as well as the opaque set's, since `leaky / no-image` is also drafted text-only.
   > **⚠️ Discharged again at T6, this time on a LIVE pass.** Both text-only conditions were run
   > against the real model and every one of their **28 recorded payload hashes equals the
   > pre-wiring control** — 7 leaky + 21 opaque, checked from the frozen artifacts. That this is even
   > checkable is a consequence of T6's pinned-citation decision: a retrieved candidate block would
   > make every live hash unique to its own retrieval, and the control could then only ever be
   > re-checked by a builder re-running its own code.
7. **⚠️ The receipt logs the image `sha256`, not a byte count.** A byte count cannot verify the
   permutation: the four Nyhavn cells share identical bytes, so a count check passes whether or not the
   mapping was honoured. The receipt records `sha256` per `finding.id` per condition, and T10 asserts the
   with-image and mismatched receipts differ **exactly where the frozen mapping says they should**.
   Without this, D has no proof it was ever actually run mismatched.
   > **The recording mechanism is T5's and is proven model-free; the live assertion is T7's.** The
   > digest recorded is the one the drafter reports having sent (`DraftResult.request`), never the one a
   > caller believes it passed — a receipt that reconstructs the request it *thinks* was made cannot
   > detect a picture that never left the drafter. T5 freezes a rehearsal of all four conditions driven
   > through the real drafter with a canned client
   > (`benchmark/reports/image_condition_dry_receipt.json`): its `image_sha256` column is the
   > expectation a live pass must reproduce, finding by finding. Its **payload** hashes are computed
   > with pinned citations, so a live pass — which retrieves its own — checks prompt byte-identity
   > *across its own conditions* rather than against that file.

---

## Goal & exit criterion

Build the image channel on the production path, and prove the model attends to the pixels.

1. Case HTML and assets are vendored and **every pool case renders with its image loaded**
   (`naturalWidth > 0`), asserted **separately on the leaky set and the opaque set**.
2. The reachability artifact is frozen in the repo, **including a prompt-level twin check**, and
   reproduces the 7-case pool and the 4 twin exclusions exactly.
3. The image scope is admitted **without changing the existing 44-case scope** — the dry gate still
   passes on M7's frozen runs.
4. Each of the **eight** silent-failure paths is closed or fails loudly — the eighth (`asset_root` not
   threaded ⇒ identical findings over unloaded images) was found at pre-flight and voids the pool's
   validity rather than its numbers.
5. The opaque set is frozen with checksums in the pinned scheme; **the exclusion rule is re-run on the
   ablated set** and no gold-relevant token survives.
6. The permutation is frozen as a mapping before any verdict exists, and resolved to bytes with a
   **derangement assertion** and a **3-distinct-hashes / multiplicity 4-2-1 assertion**.
7. The channel is on the production path: a content-addressed image reference on the `Finding` contract,
   `CONTRACTS.md` §3 + §5 + §6 edited in one change.
8. All four conditions frozen; **receipts assert 7/7 with `sha256` matching the frozen mapping**.
9. **D reported with its retained-cell count**, against the `max` null rule, under one of the four
   pre-committed verdicts.
10. The `leaky` → `opaque` difference reported as a secondary descriptive finding.
11. Text classes unaffected, by payload-hash equality over all 7 image-class no-image payloads.
12. All runs frozen and reproducible, with the held-out model-run count **including the pre-spec image
    probe and the transport spike's two calls**.
13. **A reported with both its controls' outcomes**, against the model-free 0-of-28 blind-row baseline,
    under one of T9's four pre-committed verdicts — with D's four conditions byte-identical on disk
    afterwards.
14. **A pixel-decided finding judged without pixels is marked as such on the production path**, from a
    fact the system holds rather than from anything the model says.

---

## Alternatives considered, and one retraction

**Option C — swap in `0va7u6`** *(HTML graphics contain no text, **live**, WCAG 1.4.5 **Level AA**)*.
Measured: 5 of 12 usable cases mint, **5 distinct images, zero duplication**, headroom **2 of 5 with
the real drafter** — the two errors are exactly the two visually-decided cases, predicted in advance.
It contains the strongest structure anywhere in ACT: `30562e91bf` (`books.jpg`, `alt=""`, **passed**)
and `9e1a5c362c` (`welcome.png`, `alt=""`, **failed**) mint **literally identical prompts** with
opposite gold, so a text-only model is a forced constant classifier — the `document-title` κ = 0
pattern exactly. **Not adopted** because its gold asks a different question than the minted prompt, so
using it requires a new `QUALITY_REVIEW_RULES` entry — a global change that is a normalizer ticket in
its own right, and bundling it here would violate the one-concern rule. Its own ceiling is `b_max = 2`,
so it does not rescue certification either. **Recorded for M9's planning.** Note the cost is known and
bounded: `quality_review.py` records that this exact global cost was already paid once, for
`empty-heading` / `document-title`.

**M9 — the mechanism milestone.** Build image gold from real pages: many independent images, filenames
that do not cooperate, alt text that fails the way real pages fail. The only route satisfying all five
instrument criteria — headroom, independence, gold-question/prompt-question match, fact genuinely only
in pixels, live provenance. **It requires a human expert to label roughly 30–50 items.** M8's channel is
its prerequisite.

### ⚠️ Retraction: the `e88epe` secondary class and its prediction

An earlier draft ran `e88epe`'s 4 minting cases as a secondary class carrying a pre-registered
prediction. **Both are retracted, and the reason is recorded rather than the prediction deleted.**

**The ground is a confound, checkable with zero model calls.** Within `e88epe`'s minting set,
**reachability is perfectly correlated with gold**:

| case | gold | deciding fact | in the pixels? |
|---|---|---|---|
| `6c3ff41e67` | **failed** | the image is the W3C logo, carrying `alt=""` | **yes** |
| `8910ef2a7c` | **failed** | same, with `role="none"` | **yes** |
| `fdc91cd65b` | **passed** | decorative *because* the adjacent `<p>Happy new year!</p>` says it | **no** |
| `c97ef443ad` | **passed** | same | **no** |

`finding.html` is the `<img>` outerHTML only, so for the two passed cases the deciding fact is in
neither channel — structurally the `link-name` case M7 settled. Every unreachable case is `passed` and
every reachable case is `failed`, so **any aggregate movement in this class is uninterpretable**: an
improvement on the reachable half and a coin-flip on the unreachable half are indistinguishable.

**A motive is declared:** the retraction removes ~36 of the milestone's model calls.

**The precondition that makes the retraction a pre-registration amendment rather than a post-hoc one,
verified rather than assumed: no `e88epe` drafter output exists anywhere in this repo.** It is **not**
in `RULE_TO_AXE`; M7's 44 cases never touched it; only the scanner and normalizer have ever run over
it. If that is ever falsified, the retraction is contaminated and the prediction must be scored as
written.

> **⚠️ Restated at pre-flight, because the original wording is now false.** It read *"`e88epe` appears
> in the repo only in `act_gold.EXCLUDED_RULES` and as an `excluded_rules` entry in
> `expected_act.json`"*. Since T0 the rule's **case HTML is vendored** (all published cases of the
> three image rules are, so the reachability counts are reproducible) and its cases appear in the
> reachability artifact with their minted `finding.html`. Neither is drafter output, so the
> precondition that matters is untouched — and it is no longer a claim: it is **enforced by a test**
> that fails if any `e88epe` case id, or the rule id itself, ever appears under `benchmark/`.

---

## What is explicitly not measured

1. **Whether supplying the visual fact restores judgment.** M8's instrument cannot support the claim. M9.
2. **Whether any of this transfers to real pages.** Synthetic ACT cases throughout.
3. **⚠️ Broad visual competence.** Three discriminations; **four of seven cases are the same JPEG**; two
   are the same logo. All three were shown answerable by this model **before the spec was written**, so
   D proves the plumbing delivers a fact the model already possesses — an integration result.
4. **⚠️ The image gap is not closed.** The pool is **7 of 27 candidate cases (26 %)** — exactly the
   subset the channel can reach.
5. **`e88epe`** — retracted, see above.
6. **`<svg>`, `<canvas>`, `<input type="image">`** — matcher limits, ten usable cases, a normalizer
   ticket.
7. **`0va7u6`** — measured and deferred with the help change it needs.
8. **`link-name`** — deciding fact outside the page; unreachable to multimodal too.
9. **Contrast and captions.** Once the pixels are in hand the answer is *computed*, not judged.
10. **Alt-text usefulness**, as opposed to adequacy. Needs a human specialist.
11. **Whether a different model would do better.** No models compared.
12. **The drift rate to useful precision.** 63 within-condition pairs corroborate M7's 1/54; they cannot
    resolve it.

---

## Tickets

Execution order is the ticket order. **The wiring precedes the text-only conditions** so that every
condition is produced by one build of the drafter stack.

### T0 — Pre-flight: everything that can void the milestone *(no model calls except one spike)*
- **⚠️ The case HTML is not vendored.** `fixtures/act-gold/html/` holds 67 files, all from the five
  descriptiveness rules; `testcases.json` carries metadata only. Fetch the 7 pool and 4 twin cases from
  `act-rules.github.io` under `CLAUDE.md`'s scraping rules — robots.txt, rate limit, explicit
  User-Agent — checksum them, and confirm the deprecated rule's assets are still served.
  > **⚠️ Widened in execution: all 51 published cases of the three rules were vendored, not 11.**
  > With only the 7 pool and 4 twin cases, the twin check can only re-confirm pairs already named and
  > *"6 of 16 mint"*, *"9eb3f6 mints 9 of 11"* and *"7 of 27"* cannot be reproduced at all — the
  > exclusions have to be **discovered by the check**, not supplied to it. Same rule `act-gold/NOTICE`
  > already states: the complete rule set, never a favorable subset. **Measured while fetching:**
  > robots.txt returns **HTTP 404** (absent ⇒ nothing disallowed, recorded rather than assumed); every
  > asset of the deprecated rule is **still served**; and one referenced asset,
  > `/test-assets/does-not-exist.png`, **404s deliberately upstream** — it belongs to two
  > `inapplicable` cases about an image request that never completes, so it is recorded, not repaired.
- **⚠️⚠️ Absolute asset paths do not resolve under `file://`.** ACT references `/test-assets/…`, which
  under `file://` resolves to the filesystem root. **The repo already ships three such broken renders
  and nobody noticed, because the pipeline is text-only.** **Decision, taken here and not deferred: a
  Playwright `page.route()` interceptor in `scanner/scan.py`, serving vendored bytes with a decodable
  `Content-Type`.** Rejected alternatives, with reasons: rewriting the HTML mutates ACT bytes and
  contaminates the leaky condition; a local HTTP server puts a port inside every
  `Finding.id = sha(source_url, rule_id, target)` and destroys reproducibility.
  **Five assets are served `application/octet-stream` upstream** (`nyhavn`, `paris`, `pain`,
  `94251e11…`, and `login` on a non-pool case) — four, not five, sit on pool cases.
  > **⚠️ Corrected by measurement: the Content-Type is NOT a second cause of blank renders.** This
  > ticket claimed the interceptor "must set a decodable type or `naturalWidth` is 0 on four of seven
  > cases". **False.** The same bytes decode under `image/png`, under `application/octet-stream`,
  > under `text/plain` and **with no Content-Type at all** — Chromium sniffs an `<img>` from its
  > content. **The path is the sole cause**, and the interceptor alone fixes it: all 7 pool cases now
  > render. The sniffed type is kept and re-justified, because it is load-bearing **elsewhere**: an
  > image handed to a multimodal model travels as `data:<media-type>;base64,…` and is decoded by that
  > *declared* type, which an extensionless file name and an `application/octet-stream` header both
  > fail to supply — so **T4/T5 must take the media type from the bytes, never from the name.** The
  > negative result is pinned by test so a browser bump that stops sniffing surfaces as a failure.
- **⚠️ One model-call spike, before anything is built.** `clearway/llm/local.py` routes through
  `litellm.completion(model="ollama_chat/…")` with `response_format`, and its own docstring records that
  the sibling provider prefix **"silently drops structured output and returns markdown"**. Whether that
  provider carries **multimodal content parts *and* a `response_format` schema *and* the thinking budget
  in one request is established nowhere** — the pre-spec probe hit `/api/chat` directly, bypassing
  LiteLLM. Issue exactly one `complete_json` with an image part and the real `_LLMDraft` schema against
  the real local stack; assert schema-valid JSON returns. **If it fails, the wiring ticket becomes a
  "bypass or patch LiteLLM" ticket and must be re-scoped before any pass is spent.**
- **Acceptance:** the artifact records per case the minting rule, bucket, exact `finding.html`, and
  whether the deciding fact is in the snippet; **includes a prompt-level twin check**; reproduces the
  pool and twin exclusions exactly. Every pool case renders with `naturalWidth > 0`. The spike passes.
- **Depends on:** —

### T1 — Admit the cases under a separate gold manifest
- **⚠️ A separate `RULE_TO_AXE`-alike is not enough.** `expected_act.json` is asserted at 40 cases + 4
  honest misses = 44, `checksums.sha256` at 68 files, and `EXPECTED_EXCLUSIONS` names both image rules.
  The image cases need **their own manifest and builder**.
- `act_export_hash` does not change. Extending `RULE_TO_AXE` in place would take the scope past the
  44 the dry gate asserts and fail it on M7's frozen runs.
  > **⚠️ Corrected: the resulting scope is 60 or 71, never 61.** Measured against the frozen export —
  > current scope 44 (40 cases + 4 honest misses); **+ the two live image rules = 60**; **+ all three
  > = 71**. The mechanism is `dry_gate` gate 3, which requires the scoped case set to equal a
  > **44-case** baseline verdict vector (`dry_gate.py:111`), and both `dry_gate` and
  > `referent_injection_build` scope by `manifest["cases"] … if c["rule_name"] in RULE_TO_AXE`.
- **⚠️ The deprecated rule is not currently excluded anywhere — it is merely absent.** `EXCLUDED_RULES`
  names the two live image rules only; `9eb3f6` never appears, because it was never vendored and
  `build_manifest` silently skips any rule outside `RULE_TO_AXE`. So this is a **new entry**, not an
  edit — and `test_act_gold.EXPECTED_EXCLUSIONS` is an exact-set assertion that will fail until it is
  added. Match the name verbatim, em-dash included: `"DEPRECATED — Image filename is accessible name
  for image"`.
- **Acceptance:** dry gate still passes on M7's frozen runs; `EXCLUDED_RULES` and its test updated;
  deprecation recorded in the manifest.
- **Depends on:** T0

### T2 — Give the harness an explicit scope
**Eight paths fail silently on an image run. Each must be closed or made loud.** All eight were
re-verified against the code at pre-flight; the file/line notes are measured, not remembered:
1. `drafter_kappa._grouped` drops non-`RULE_TO_AXE` cases → an **empty but schema-valid** VerdictVector.
   *(It already takes `scoped: bool = True` — `scoped=False` recovers the unscoped reading, so the fix
   may be a call site rather than new code.)*
2. `_POOLED_AXE_RULES = ("label", "link-name")` is a default never threaded → **b = 0, c = 0**.
   **⚠️ It exists in TWO modules** — `paired.py:42` **and** `drafter_kappa_baseline.py:117`. Fixing one
   leaves the other silently wrong.
3. Attribution against a non-overlapping baseline `continue`s → prints **"prior run intact"**
   (`referent_injection_score.py:191`), a **false clean**.
4. `_DISTINCT_PROMPTS_BEFORE` / `baseline_reachable` are `.get()`-defaulted → `image-alt` renders empty.
5. `predictions=baseline_kappa.get("predictions", [])` → **M7's predictions scored into M8's result**.
6. `referent_injection_build` selects on `RULE_TO_AXE` + M7's manifest → would **draft M7's 44 cases**.
7. `_CONFIG_ID` / `_EVAL_SET_ID` (`offline_build.py:44-45`) stamp `m1-single@1` / `act-acceptance@1` →
   **false provenance frozen into every artifact**. **Literals, decided here:
   `config_id = "m8-multimodal@1"`, `eval_set_id = "act-image-opaque@1"`** (and `"act-image-leaky@1"`
   for the unablated condition). *(Note the tension to settle when writing it: a milestone label inside
   a shipped artifact is what the `m1-single@1` precedent already does, and what this repo's
   no-milestone-labels-in-artifacts rule otherwise forbids. Decide deliberately; do not drift.)*
   > **⚠️ Settled in execution, and it moved one literal: `config_id` ships as `single-multimodal@1`,
   > not `m8-multimodal@1`.** The tension was put to the human and decided against the precedent: a
   > milestone label is ticket bookkeeping, `config_id` names a pipeline configuration, and
   > `single-multimodal@1` says what it actually identifies — one model, no routing, image channel
   > wired in. The frozen `m1-single@1` artifacts are not rewritten; the precedent simply stops here.
   > **Both eval-set ids are unchanged** (`act-image-leaky@1` / `act-image-opaque@1`), and the leaky one
   > is not a new literal at all — it is `image_reachability.SET_ID`, already shipped, now read rather
   > than restated.
8. **⚠️ NEW — found at pre-flight, and it voids the pool rather than the numbers.** `asset_root` is
   optional on `scan()`, and **a scan without it produces the IDENTICAL finding** — same `id`, same
   `html`, same count (measured). So a builder that forgets to thread it gets a flawless-looking
   finding set while **every image silently fails to load**, and `qt1vmo`'s applicability — which
   presumes the image rendered — quietly lapses with no finding-level signal anywhere.
   **`act_gold._minting_findings()` calls `scan(str(case_path))` with no asset root, so it must not be
   reused as-is.** Render validity is visible only through `scanner.image_render_report`.

- **Not the problem:** `RUN_LABELS` namespacing is sound — `passes_in` is label-prefixed,
  `refuse_to_overwrite` is path-based, single-parent `_PRIOR_RUN` expresses M8's chain.
- **Decided here, not deferred:** `score_run` raises below two passes (`referent_injection_score.py:128`)
  — **M8 scores outside it**, with its own scorer, because M8's endpoint is D and not a paired κ.
  **`dry_gate` is not generalised: M8 runs without a pre-flight gate**, and T10 must state that plainly
  rather than implying one existed.
- **Depends on:** T1

### T3 — The opaque derived set and the frozen permutation
- **⚠️ There is no derived-set precedent to reuse.** `offline_tier_b.py` is report arithmetic, not a
  builder; `noisy_pages.py` hand-authors HTML. A deterministic transformation script whose output
  carries checksums is **new work**.
- Rewrite `src`, `srcset` and the directory on all 7 pool cases to the pinned scheme (`/img/a.png`,
  `/img/b.png`, `/img/c.png`, one per distinct image). Nothing else changes. Deterministic, checksummed,
  distinct `set_id`.
  > **⚠️ The pinned `.png` is decorative, and two of the three images are JPEG.** Measured: the W3C
  > logo is PNG; Nyhavn and the bread are **JPEG**. The uniform extension is kept — it is the point
  > that the name carries no information — and it is harmless because **nothing reads it**: the browser
  > sniffs, and `scanner.served_content_type` sniffes the bytes. **The trap to avoid: never derive the
  > media type from these names.** A `.png` label on JPEG bytes in a `data:` URI is a lie told to the
  > model, and it is the one place where this scheme could do damage (T4/T5).
  > **⚠️ Settled in execution — what the ablated set's gold means, because the ablation moves it.**
  > Removing the path breaks **`9eb3f6`'s own applicability**: that rule is about an accessible name
  > that *is* the filename, and after ablation no name is a filename — on **five of the seven cases**.
  > The labels still carry, and the reason is specific rather than convenient: the judgment this set
  > scores is **WCAG 1.1.1** — *does this accessible name describe this image?* — and the ablation
  > touches neither side of that question, because every `alt` is byte-identical and every rendered
  > image is the same bytes under a new name. So **the opaque set scores 1.1.1 conformance, not the ACT
  > rule outcome**, and no report over it may claim otherwise. Recorded on the manifest, in the set's
  > NOTICE, and in the ablation review.
- **Freeze the permutation as a mapping over `act_testcase_id`s** — this is the pre-registration and it
  must be fixed before any verdict exists. Bytes are resolved in T4.
- **⚠️ Acceptance 1:** no gold-relevant token survives anywhere in the minted prompt — `src`, `srcset`,
  `sizes`, and the directory component all checked by name. **This, not T6, is the ablation gate.**
- **⚠️ Acceptance 2:** the exclusion rule is **re-run on the ablated set** and no new informationally
  identical opposite-gold pair exists. *(Measured: within the 7-case pool, ablation creates none — the
  alts are pairwise distinct and the only same-alt pair shares gold `passed`. This acceptance exists
  because the check must be executable, not because it is expected to fire.)*
- **Acceptance 3:** case-by-case manual confirmation, recorded as a written judgment with a named
  reviewer.
- **Depends on:** T2

### T4 — Capture the rendered image, on the production path
- **⚠️ Decided here: capture lives in `scanner/`, and the reference rides the `Finding` contract.** An
  `eval/`-only capture would build an instrument, not the product capability outcome #1 claims, and
  would leave M9 without the channel it is said to inherit.
- **The precedent exists and is one milestone old:** `Finding.referent` is exactly this change — scan
  material the prompt needs, nullable, deliberately outside the `id` hash, with a docstring that
  pre-argues the image case. `CONTRACTS.md` §3 + §5 + §6 edited **in one change**, per `CLAUDE.md`.
- **⚠️ Carry a content-addressed reference, not bytes** — `image_ref: str | None`, keyed by
  `finding.id`, with bytes frozen beside the run. A base64 payload on a §3 model would be serialized
  into every frozen artifact (32 KB × 7 findings × 4 conditions × 3 samples) and make artifact diffs
  unreadable. **Capture is opt-in**, so a production scan pays nothing for screenshots nothing consumes.
- **The key is `finding.id`** (already `sha(source_url, rule_id, target)`), **not `target`** — `img`
  matches on nearly every case page, so `target` alone is not unique.
- **Acceptance 1:** the capture set contains **exactly 3 distinct hashes with multiplicity 4 / 2 / 1**.
  This single check validates the render interceptor, T3's asset renaming, and the permutation's premise
  at once — if `pain` fails to decode, you get 2 hashes and a loud failure instead of a blank image
  silently attached.
- **Acceptance 2:** T3's mapping resolved to bytes is a **derangement over distinct images** — no case
  receives an image byte-identical to its own. Frozen and checksummed.
- **Acceptance 3:** send the **captured** bytes bare to the model and confirm all three discriminations
  still resolve. Three calls; separates "capture destroyed it" from "plumbing failed" later.
- **Depends on:** T3

### T5 — Wire the image into the drafter call
- **⚠️ The API is `complete_json(system: str, user: str, schema: type[BaseModel]) -> Completion`. There
  is no `chat()`.** Sites: the `LLMClient` protocol, `FakeLLMClient`, `local.py` (the `messages` list
  becomes multimodal content parts — `base64` is stdlib, **no new dependency**), `cloud.py` for
  signature parity, two test fakes that override the old signature, and `Drafter.draft` /
  `draft_with_usage` / `_draft_judgment`. `_draft_remediation` must **not** receive an image.
- **⚠️ This spans `llm/` and `drafter/`** — split the branch accordingly.
- **Acceptance 1:** the receipt records `sha256` per `finding.id` per condition (Control 7).
  > **Discharged model-free.** The four conditions are values (case set + picture rule + pre-registered
  > sample count), and the receipt emitter is exercised over all four by driving the **real** drafter
  > with a canned client — 28 rows, no model call. The frozen rehearsal is checked against a *hand*
  > transcription of the permutation table, read back as image names, so the receipt, the permutation
  > artifact and the spec must all three agree.
- **Acceptance 2:** the smoke test runs **through the real pipeline prompt**, not a hand-written probe.
  > **⚠️ It spends one real call, and deliberately not on a pool case.** The case is `499be21170` — one
  > half of a prompt-level twin pair, excluded from the gold pool by the exclusion rule, so no held-out
  > cell is touched and the endpoint's seven cases stay unspent. It is gated on Ollama being up, like
  > every other real-model test here. **Ran green:** a real scan captured the picture, the real
  > per-finding prompt was built with its candidate criteria, and the response parsed as a non-fallback
  > `DraftRow` (~49 s), with the request's recorded digest equal to the captured one.
- **Acceptance 3:** no non-image finding carries an image; payload-hash equality holds over all 7
  image-class no-image payloads and one M7 text finding (Control 6).
  > **⚠️ Read this acceptance by the NODE, not by the rule — measured at T4.** On a pool page the
  > `<img>` is outside any landmark, so axe's `region` rule reports **the same node** and its finding
  > carries the same `image_ref`. That is correct — the reference names the picture a *node*
  > rendered — but "non-image finding" must mean *a finding whose node is not an image*, never *a
  > finding whose rule is not `image-alt`*. Written the second way, this acceptance fails on a
  > correct implementation. What T5 must actually assert is that `_draft_remediation` and every
  > text-class finding send no image.
- **Depends on:** T4

### T6 — The two text-only conditions
- `leaky / no-image`: one pass, descriptive. `opaque / no-image`: 3 samples per finding.
- Report the difference between them as a **secondary descriptive finding**, with one sentence noting
  it partly measures a fixture artifact: in the leaky condition 4 of 7 cases have alt ≈ filename
  case-insensitively, so against a help text saying *"a filename … does NOT describe"* the leaky cue is
  close to a string-equality trigger — a property of how a **deprecated** rule's fixtures were authored,
  not of real pages.
  > **⚠️ Measured in execution: "4 of 7" is true only under a stated reading of "≈", and the reading
  > moves the number.** Comparing `alt` to the **last path segment of `src`** verbatim gives **4**;
  > stripping one extension from that segment first gives **5**, because `1ff696703e` carries
  > `src=".../nyhavn.jpeg"` against `alt="Nyhavn"`. Neither is the right one, so the rule is pinned in
  > code and **both counts are reported** — a number nobody can reproduce is worth less than two
  > numbers plus the rule that separates them. The caveat sentence is generated from the measured
  > counts and quotes the help text **read from the frozen reachability artifact**, not transcribed.
- **⚠️ Settled in execution: the conditions are drafted against PINNED candidate criteria, not live
  retrieval** (`drafter_payload.PINNED_CITATIONS`, the same input T5's smoke test and the dry receipt
  already used). The endpoint is defined over prompts that are byte-identical across conditions
  differing only in pixels, and a live retriever is a service whose ordering is one more thing that
  could move between two calls run hours apart; pinning takes it out of the premise and makes every
  condition reproducible with no database running. **The cost is declared, not hidden:** the block
  holds the one criterion this class is about, where production retrieval surfaces several candidates
  including distractors — so these conditions are drafted against an easier candidate set than a live
  scan would produce, and no report over them may describe the candidate block as production's. It is
  the same set for all four conditions, so it cannot move a difference *between* them. `corpus_version`
  is derived from the pinned list rather than from a corpus, so changing a pinned citation moves it.
- **⚠️ This is not the ablation gate** — T3 Acceptance 1 is, because it is offline and model-free. A
  model-based gate fails in both directions: it passes when one case differs for an irrelevant reason
  while real cues survive, and it fires when a perfect ablation meets a drafter that simply ignores
  filenames, which is a finding rather than a defect. **If the two conditions do not differ, record it
  as a measured property of the text-only pipeline and do not spend T7 until T3 Acceptance 1 has been
  re-verified.**
- **Depends on:** T5

### T7 — `with-image`, `mismatched-image`, and D
- Both conditions, 3 samples per finding. Compute D over all 7 cells; apply the retained-cell rule.
- **Acceptance:** receipts assert 7/7 with `sha256` matching the frozen mapping, and differ **exactly**
  where the mapping says they should; D and its retained-cell count are recorded; one of the four
  pre-committed verdicts is stated.
- **Depends on:** T6

### T8 — The pipeline knows when it judged blind *(no model calls)*

> **Goal.** A pixel-decided finding drafted without pixels is **marked as such from a fact the system
> holds**, and the drafter is given a place to say so. Deterministic end to end: **zero model calls, no
> frozen artifact moved, the existing suite green unchanged.** Whether the drafter *uses* that place is
> T9's question and does not gate anything here.

**The defect, measured over the frozen text-only passes with zero model calls: the drafter judges a
pixel-decided finding blind, confidently, and never says so.** **0 of 28 blind rows** signal that the
picture was unavailable (7 leaky + 21 opaque), confidence sits at **0.90–0.95**, and every remediation
speaks of *"the image"* in the abstract (*"conveys the image's actual meaning"*) while never describing
one. The same drafter, given the pixels, describes them in 5 of 7 rows. The absence is not reported —
it is papered over. This is a product defect, not an eval artifact: outcome #1 is a capability on the
production path, and one that answers a visual question confidently without the visual is the same
family of failure as M4's over-confidence (ECE 0.392) and M5's cry-wolf rate.

**⚠️ What is missing is the pixels, not the element.** `<img src="/img/a.png" alt="W3C">` sits in the
minted prompt, so *"there is no image"* would be a false statement for the drafter to make. Whether it
received the **pixels** is a fact the system already holds (`image_ref is None` at the seam) and never
tells it. Every decision below follows from that one asymmetry.

**Scope — one concern.** Whether the pipeline knows, records and marks that a judgment was made without
the pixels it needed. **Not** in scope: whether the picture received **matches** the page — the wrong
image drew zero objections in 21 rows, and that is a separate ticket.

**1. The baseline, model-free.** A code-scored detector over the **four already-frozen conditions** (70
rows, of which 28 are blind): does a drafted row express that the visual evidence was unavailable? A
prose reading is not a measurement, and a rule invented after seeing which rows it catches is not one
either — so the rule is pinned before the rows are read through it.

It has one field to read: `image_pass._draft_row` records `conformance`, `cited_sc_ids`, `confidence`
and `remediation`, and `DraftRow` carries no rationale. **The rule: a row signals unavailability iff its
`remediation`, case-folded, contains any of** `cannot see`, `can't see`, `unable to see`,
`not able to see`, `cannot view`, `unable to view`, `without seeing`, `not shown the image`,
`no image was provided`, `image is not provided`, `image not provided`, `no visual`,
`cannot verify the image`. Deliberately high-recall and hand-checked: the expected answer is zero, so
the failure that would matter is a rule too narrow to catch a signal that was there, and a false
positive costs one row read by eye and named. It is frozen here so T9 can run the identical rule over
its own rows and have the before and the after be one measurement. Expected: **0 of 28**, reproduced
rather than assumed.

**2. The contract change, decided here before any call anywhere is spent.** Give the drafter a place to
report what it could see — **`visual_evidence: seen | absent | not_needed`** on `DraftRow` — and tell it
in the prompt whether a picture is attached. Rejected alternatives, with reasons: reusing
`not_applicable` collapses *"the rule does not apply"* into *"I could not see it"* and would move every
acceptance number through `stats.CLEAN`; a confidence floor rests everything on a field M4 measured
decorative and over-confident (ECE 0.392).

- **⚠️ The field asks whether the evidence *this judgment needed* was available — never whether a
  picture was attached.** The second is a fact the system already holds, so a model told there is no
  picture answers it correctly by repeating the sentence it was handed. **`not_needed` is what
  separates obedience from reasoning**, and a two-value field would be actively wrong: the pool's
  `a2333ec76e` received no picture and needs none — its hex-digest `alt` fails 1.1.1 whatever the
  pixels hold — so `seen | absent` alone forces a false answer on the one case that discriminates.
  Not a reuse of `not_applicable`: that value lives on `Conformance` and speaks about the rule, this
  one speaks about the evidence.

- **⚠️ The model's claim and the system's fact are two fields, because they have two sources.**
  `visual_evidence: Literal["seen", "absent", "not_needed"] | None = None` is **written by the model**;
  `visually_verified: bool | None = None` is **the system's**, tri-state on purpose — `None` = the
  question does not arise (not a pixel-decided finding), `True` = pixel-decided and the pixels were
  sent, `False` = pixel-decided and they were not. One field for both would let the deterministic value
  stand in for the model's answer, and any later measurement over it would be measuring the pipeline
  rather than the drafter; a two-valued system field would have to spell *"does not arise"* as `False`
  and would mark every text finding in the product visually unverified. Keeping them apart buys a third
  check free: **a row claiming `seen` while the system sent nothing is a hallucination catchable with no
  model and no judge.** Both additive with defaults, so every persisted row still validates under
  `extra="forbid"`; the assembled path and the fallback carry `visual_evidence=None`, because a field
  written by the model is empty where no model wrote it.

- **⚠️ The announcement is a parameter defaulted OFF, because *"no sentence says a picture is
  attached"* is a control, not a habit.** It is asserted by `test_the_prompt_never_says_a_picture_is_attached`,
  `test_attaching_a_picture_changes_no_byte_of_either_prompt`, Control 6's live rebuild
  (`test_the_frozen_control_reproduces_through_the_current_prompt_builders`) and
  `test_the_frozen_receipt_rebuilds_byte_identically`. Shipped unconditionally the sentence moves all
  15 payload hashes in `drafter_payload_baseline.json` and every hash in
  `image_condition_dry_receipt.json`, retiring the pre-wiring comparison Control 6 exists for. So
  `announce_image: bool = False`, **and** the announcement renders through a block returning `''` for
  any finding outside the pixel-decided classes — the disjoint-by-class idiom the three referent blocks
  already use. Two gates, each covering a hole the other leaves: the parameter keeps every existing
  caller byte-identical, the class gate keeps Control 6's text cross-check row byte-identical even
  after the parameter flips. With the default off, **nothing is re-frozen and nothing is re-run.**
  **The default is not flipped by this ticket and not by T9 either** — T9 produces the number that
  decides it, and flipping it is a declared prompt change shipped the way `Citation.text` (v0.26)
  shipped its two: baseline re-frozen, amendment in `CONTRACTS.md` §6.

- **⚠️ The announced call asks under its own schema class, because neither hash can see a field added
  to `_LLMDraft`.** `LLMRequest.of` records `schema.__name__` — the class name, not its shape — so
  widening `_LLMDraft` in place would change what the model is asked to produce while moving **neither**
  `prompt_sha256` nor `payload_sha256`: the control built to catch a moved ask, blind to a moved answer,
  inside the ticket that closes exactly that family of failure. So the announced path asks under
  **`_LLMDraftVisualEvidence`** (`_LLMDraft` plus the one field), selected by the same parameter. The
  class name then differs, so the hash moves exactly when the ask moves with no change to `LLMRequest`;
  the unannounced path stays `_LLMDraft`, so existing hashes are not merely equal but produced by
  identical code; and a field the model was never asked for cannot be filled by accident, being absent
  from the shape. **Residual gap, recorded not closed: a future field added to `_LLMDraft` in place is
  still invisible to both hashes.** Naming it is this ticket's obligation; fixing it is a control ticket.

**3. The marking, and it needs no model at all.** A pixel-decided finding drafted while
`image_ref is None` carries `visually_verified is False` on the production path, from the system's own
fact. **This is the half that closes the defect** — it ships on its own evidence and waits on no
measurement.

- **⚠️ Pixel-decided is keyed by the RULE here, where T5's Acceptance 3 keyed by the NODE — both are
  right, and the difference is the point.** *"Did this node render a picture"* is a property of the
  node, which is why an `image_ref` rides one; *"does this class's judgment need pixels"* is a property
  of the question, and `region` firing on the same node asks a question no picture answers. A pinned
  `PIXEL_DECIDED_RULES = {"image-alt"}` beside the drafter — never inferred from `image_ref`, which is
  `None` in exactly the case the marking exists for.
- **⚠️ A row claiming `seen` against `visually_verified is False` fails validation** — retry once, then
  degrade to the visible `_fallback` row, reusing the drafter's existing validate-retry-then-degrade
  contract rather than inventing a second failure mode.
- **⚠️ Count the blast radius of both over the WHOLE scoped corpus**, not over the seven image cases,
  and record the counts. A guard measured only where it was designed to fire is not measured.

**Sites.** `CONTRACTS.md` §3 + §5 + §6 in one change (`DraftRow`); `drafter/llm.py`
(`_LLMDraftVisualEvidence`, the announcement block, `PIXEL_DECIDED_RULES`, the contradiction check,
`_assemble`, and the `draft` / `draft_with_usage` / `_draft_judgment` signatures); a model-free detector
in `eval/` reading the four frozen conditions. `_draft_remediation` is untouched — the assembled path
takes no picture and answers no visual question.

**Acceptance.**
1. The baseline is frozen and reproduces **0 of 28** under the pinned detector rule, which is in code
   before it is run.
2. `CONTRACTS.md` §3 + §5 + §6 carry `visual_evidence` and `visually_verified` in one change; every
   persisted row written before it still validates under `extra="forbid"`.
3. **The marking ships and is tested**: a pixel-decided finding drafted with `image_ref is None` carries
   `visually_verified is False`, and a row claiming `visual_evidence: "seen"` against it degrades to the
   visible fallback rather than shipping. Both counted over the whole scoped corpus, counts recorded.
4. `announce_image` defaults off and `_LLMDraft` is unwidened, so **no frozen artifact in this milestone
   moves** — D's four conditions, `drafter_payload_baseline.json` and `image_condition_dry_receipt.json`
   all byte-identical on disk — and **the existing suite passes unchanged rather than being updated to
   match.** A diff over those artifacts is a test, not a habit.
5. **Zero model calls are spent.** The held-out run count is unchanged by this ticket.

- **Depends on:** T7

### T9 — Does the drafter report the absence? *(42 calls)*

> **Goal.** One number, **A**, read against two controls under four verdicts fixed before any of its
> calls are spent — does the drafter, given a place to say it cannot see the picture and told whether
> one is attached, use it? **D is not recomputed, not re-run, and not touched.**

**What T8 shipped, since this ticket is read on its own.** `DraftRow.visual_evidence` —
`seen | absent | not_needed`, written by the model, answering *"was the evidence this judgment needed
available"* and not *"was a picture attached"*. `DraftRow.visually_verified` — the system's own
tri-state fact. `Drafter.draft*(…, announce_image: bool = False)`, which when true adds a sentence
saying whether a picture is attached and asks under `_LLMDraftVisualEvidence`. Every blind row this
project has frozen — 28 of them — reports the absence in **0** cases; that is the baseline A moves from.

**The endpoint, pre-registered by this spec before any of its calls are spent.**

> **A = the number of the 6 image-decided pool cases whose blind verdict withholds a conformance
> judgment** — reports the visual evidence its judgment needed as **`absent`** — **out of 6.**

**The six are the pool minus `a2333ec76e`**, the one case the pool table records as decided by text
alone and which serves as Control 1. Named by id in code, not filtered by a predicate: the pool is seven
rows in a frozen artifact, and a predicate recomputing *"image-decided"* would be a second definition of
a set the spec has already fixed.

**⚠️ Withholding is reported on the new field, because `Conformance` has nowhere to put it.** Its four
values are `supports`, `partially_supports`, `does_not_support`, `not_applicable`, and T8 rejects the
fourth as the channel — so the conformance field still carries a verdict on every withheld row. That is
a property of the instrument, not a hedge, and the report prints the conformance value beside each
withheld row so a reader sees what the model answered while saying it could not see. Adding an
abstention value to `Conformance` moves `stats.FLAGS` / `CLEAN` and every acceptance number in the
repo — **out of scope, named so it is not re-derived as a good idea mid-ticket.**

**⚠️ A is read from pass 1 over all six, and unstable cases are named rather than dropped.** D excludes
a cell whose three samples disagree; A must not. D is a count read against a null rate, where losing a
cell costs power and cannot inflate the result — A is an absolute count out of a fixed six, where
dropping a case shrinks the denominator and makes a partial result look closer to closed. Per-case
agreement across the three samples is reported beside A.

**The two conditions, and why both are needed.** `opaque / told-no-image` and `opaque / told-with-image`,
3 samples each, **42 calls**. The second is not decoration: without it, a drafter that abstains on
*everything* the moment the new field exists is indistinguishable from one that abstains **because** it
lacks the picture. They do **not** enter D — see the ⚠️ under Control 5.

- **⚠️ They get their own registry rather than two more entries in `CONDITIONS`.** That tuple is not a
  list of runs; it is the definition D's evidence is checked against — `receipt_failures` iterates it
  and demands a full set of rows for every member, and `test_the_frozen_receipt_rebuilds_byte_identically`
  asserts the rebuild equals the frozen 28-row file. Appending two members makes it 42 and re-freezes an
  artifact whose whole purpose is to have been frozen before the endpoint was read. So an
  **`ANNOUNCED_CONDITIONS`** tuple beside `CONDITIONS`, `condition_by_id` resolving over both so a CLI
  still cannot invent a name, and `receipt_failures` taking the tuple it checks as an argument instead
  of reaching for the module global. **`Condition` gains `announces: bool`** — a fourth thing a pass
  cannot infer, for the reason its docstring already gives.
- **The literals, so they are not drifted into:** `condition_id` `"opaque/told-no-image"` and
  `"opaque/told-with-image"`; `eval_set_id` unchanged at `act-image-opaque@1`, since the case set is
  byte-identical and a moved id would claim otherwise; **`config_id` `single-multimodal-announced@1`**,
  because a prompt announcing the channel is a different pipeline configuration — the reasoning that
  settled `single-multimodal@1` at T2.
- **⚠️ A contradicted row is recorded, not aborted on.** `image_pass._draft_row` aborts the whole
  condition on any fallback, and T8's contradiction guard degrades to exactly that fallback — but here
  the contradiction *is* the measurement, so these two conditions record it with the model's claim
  preserved and continue, while an unparseable-output fallback still aborts as today. The two are
  distinguishable and must not be collapsed. A contradicted row is not withholding: out of A's
  numerator, still in its denominator, counted and named.
  - **⚠️ Written back after T8 shipped: at that seam they are not yet distinguishable, and the claim
    is already gone.** Both failures produce the byte-identical `_fallback` row and a `DraftResult`
    that records only the request, so `_draft_row` alone can neither tell them apart nor preserve what
    the model claimed — it would have to abort on the measurement. **The channel is T9's to build**
    (the natural shape: the guard sets the contradicted claim on `DraftResult`, which already carries
    an optional field for something a hand-built result does not have), and `drafter/llm.py` joins
    T9's Sites for it. T8 was right not to add it: a field nothing yet reads is a channel measured by
    nobody.
- **⚠️ Their instability does not feed D's null rate.** `null_rate` takes the artifacts it is given, and
  six conditions instead of four would move a number the endpoint was already read against. D is not
  recomputed — Control 5 — and that includes its denominator. This ticket's within-condition agreement
  is its own figure, reported beside A.

**Two controls, and neither needs a new fixture.** They fail in opposite directions, which is why one of
them is not enough:

| control | what must happen | reading if it does not |
|---|---|---|
| **`a2333ec76e`, blind** — the one case decided by **text alone**, its `alt` a hex digest that describes nothing whatever the pixels hold | reports **`not_needed`** | the drafter is obeying *"no image"* as a blanket instruction rather than reasoning about what the question needs |
| **`told-with-image`, all 7** — the picture is there and it is told so | **no row reports `absent`** | the new mechanism suppresses judgment by its mere existence, and A measures the field, not the reasoning |

Both are predicates on pass 1 and neither reads `confidence` — reported for both, gated on for neither.
Control 1 fails equally on `seen`, which is a contradiction against `visually_verified is False`. Control
2 is stated as the absence of withholding rather than as `seen` on all seven, because `not_needed`
remains legitimate for `a2333ec76e` even with its picture attached, and a predicate forbidding it would
fail a correct implementation — the failure mode T5's Acceptance 3 was corrected for.

**Pre-committed verdicts**, covering every value of A so none is chosen after the fact:

| outcome | verdict |
|---|---|
| either control fails | **uninterpretable** — checked first, because blanket obedience and reasoning are then indistinguishable |
| **A = 6**, both controls hold | **closed** |
| **3 ≤ A ≤ 5** | **partial** — reported with the cases that leaked, named |
| **A ≤ 2** | **not used** — an explicit statement of absence does not change what the drafter does |

**⚠️ What A does not decide is whether T8's marking ships** — that shipped on its own evidence. What it
decides is whether `announce_image` becomes production's default, and that flip is a separate declared
prompt change, not part of this ticket's acceptance.

**Sites.** `eval/image_conditions.py` (`Condition.announces`, `ANNOUNCED_CONDITIONS`, `condition_by_id`,
`receipt_failures` signature); `eval/image_pass.py` (`_draft_row` records both new fields and
distinguishes a contradiction from an unparseable fallback); `drafter/llm.py` (the channel that carries
the contradicted claim out of the guard — see the ⚠️ above); `eval/image_score.py` (A, its two controls,
the verdict).

**Acceptance.**
1. Both conditions are frozen with receipts, each covering all 7 findings at its pre-registered sample
   count, and their prompts differ from D's by construction — `prompt_sha256` is expected **not** to
   match, which is why they never enter D.
2. **A is reported with both controls' outcomes** under one of the four verdicts above, with per-case
   sample agreement beside it, and with the 0-of-28 baseline it moved from re-run under T8's identical
   detector rule.
3. **D's four conditions are byte-identical on disk afterwards**, D is not recomputed, and its null rate
   is unchanged.
4. `CONDITIONS` still names D's four, and
   `test_the_four_conditions_and_their_sample_counts_are_the_pre_registered_ones` is untouched.

- **Depends on:** T8

### T10 — Freeze and write the honest read
- **Mandatory report contents**, fixed now: D with its **retained-cell count** and the null rate actually
  used (`max` of M8's measured rate and M7's 1/54, both printed); the per-condition instability counts;
  the direction check as secondary; the `leaky` → `opaque` difference with its fixture-artifact caveat;
  the receipt/permutation assertion result; **three discriminations, four of seven cases one JPEG, 7 of
  27 candidate cases**; ACT's *"should not be used"* quoted verbatim; **the deprecated rule carries 5 of
  the 7 pool cases (71 %) and the live rule only 2 (29 %)** — measured, replacing an earlier
  "`qt1vmo`-only dependency ~100 %" that matched no reading of the pool; **that the opaque set scores
  WCAG 1.1.1 conformance and not the deprecated rule's own outcome, whose applicability the ablation
  removes on five of the seven cases**; the prompt-mention decision;
  the help-text tension; **the `e88epe` retraction with its
  ground, its motive, and its verified precondition**; **that M8 ran without a pre-flight gate**; and
  **one sentence that D systematically under-detects attendance**, because a mismatched image may
  produce genuine uncertainty that the stability filter codes as noise.
- **⚠️ Added at T6, because it qualifies every number in the milestone: all four conditions are
  drafted against PINNED candidate criteria, not live retrieval.** The report must say so, and must
  not describe the candidate block as the one production retrieval would surface — it holds the single
  criterion the class is about, where a live retriever returns several candidates including
  distractors. The reason is that the endpoint's premise is byte-identical prompts and a live service
  is one more thing that can move between two calls; the price is that these are not production's
  candidates. It is identical across all four conditions, so it cannot move D or the leaky→opaque
  difference.
- **⚠️ Also declare the discarded `opaque / no-image` attempt** — six calls spent under accidental
  model contention and thrown away, with the reason, and the fact that `leaky / no-image` was audited
  in the same inference-server log and **not** re-run.
- **⚠️ Declare the pre-spec probe.** Before this spec was written, each pool image was sent to the
  drafter directly and the model resolved all three. That is a model run on held-out data that
  **resolved the milestone's largest uncertainty before pre-registration**. M7 declared its analogous
  spend; M8 does too, in the held-out run count.
- **A with both its controls' outcomes**, the 0-of-28 baseline it moved from, and the production
  marking's test result — **with the marking's and the contradiction guard's blast radius over the
  whole scoped corpus, not over the seven pool cases.** Two more, which a reader would otherwise have
  to infer: **that `announce_image` ships defaulted off and A is what decides whether it flips**, so
  the milestone delivers the number and not the change of default; and **that a field added to
  `_LLMDraft` in place would move neither `prompt_sha256` nor `payload_sha256`** — a live gap in
  Control 6, routed around with a second schema class rather than closed.
  **The blind-judgment question was raised after D's conditions were frozen and read** — its
  endpoint A was pre-registered before T9 spent a call, and D was neither recomputed nor re-run, but
  the report states the ordering rather than leaving a reader to infer it.
- **Two numbers a mechanical reading of D would bury**, both required: that `opaque / with-image`
  already flagged **6 of 7** cells, so **only one cell was free to move in the pre-registered
  direction** and the "4 live cells" power description overstates what was available; and that under
  the raw four-value conformance **3 cells moved** where the binary collapse counts **1**. Report both
  beside D. Neither re-defines the endpoint — D stays on the axis it was registered on.
- **That the drafter never objected to the wrong picture.** Across 21 mismatched rows it raised
  **zero** objections — it took the pixels as the page's own and rewrote the remediation around them.
  The manipulation working is what D measures; that nothing in the pipeline notices the contradiction
  is a separate property of the product, and the report states it rather than leaving it implied.
- **⚠️ That A being `closed` is not the finding**: four of the six withheld rows shipped `supports`
  while reporting they could not see the image, named with the conformance and confidence each
  carried. Reporting an absence and acting on it are two different things; M8 showed only the first.
- **That neither kind of missing picture licenses `does_not_support`** — both pool rules map `passed`
  *and* `inapplicable` to *"further testing needed"*, and M8's pictures were uncaptured, not missing.
- **The announced-vs-silent accuracy comparison**, with its endpoint status explicitly denied.
- **Why the drafter answered `supports` while blind**, reconstructed from the prompt rather than
  guessed: the help text's adequacy test is decidable from text alone, and nothing in either prompt
  links `visual_evidence` to `conformance`.
- **That `visual_evidence` / `visually_verified` are a second field family nothing downstream
  consumes** — the shape of the `confidence` defect M4 measured, arrived at a second time.
- **Sources, because two of the above are in no report:** the ACT outcome mapping is the raw
  `ruleAccessibilityRequirements` in the frozen export — the repo's parser keeps only the SC ids and
  discards it — and the announced-vs-silent accuracy exists in no artifact, so it is computed from the
  run artifacts under the `stats.is_flag` collapse.
- **Rule: report ugly numbers as they are.** The unacceptable failure is not a low score but an
  untrustworthy one.
- **Depends on:** T9

### T11 — A blind judgment must not carry the report's highest trust label *(0 calls)*

> **Goal.** `_trust_label` grades a row on citation verification and human review, and neither says
> anything about pixels. So a judgment that needed a picture and was drafted without one can render as
> **`oracle-verified`** — the strongest thing this product tells a reader. Close that, deterministically.

**Requirements.**

1. **Prove the hole before fixing it.** A test drafting a `PIXEL_DECIDED_RULES` finding with no image,
   whose citations all verify, must show `oracle-verified` today. **If it cannot be made to fail, stop
   the ticket** and record the non-result here, in this ticket's own artifacts — a hole looked for and
   not found is a finding, and an unrecorded one is indistinguishable from one nobody checked.
2. `_trust_label` takes the row's `visually_verified` and refuses `oracle-verified` when it is `False`.
3. Such a row renders under its own label, `drafter-judged, no visual evidence`, not the existing
   floor: *nothing confirmed this* and *this was decided without the evidence it needed* are different
   facts, and the legend states the second.
4. `human-reviewed` still outranks it — a specialist signed what they saw.
5. **Blast radius over `ALL_SCOPES`, two counts, both recorded:** rows correctly downgraded, and rows
   **over**-downgraded — `PIXEL_DECIDED_RULES` is keyed by the rule, so a text-decidable instance
   (`a2333ec76e`, whose `alt` is a hex digest) is marked too. Over-firing is expected, conservative,
   and must be a number rather than a sentence.

**Constraints.**

- **`Conformance` is untouched.** The row keeps the verdict the model gave; only what the report
  claims *stands behind* it moves. Adding an abstention value moves `stats.FLAGS`/`CLEAN` and every
  acceptance number — out of scope here as it was in T8.
- **No acceptance number moves and no measurement is re-frozen.** Nothing outside `cli.py` reads a
  trust label, so every run artifact and every endpoint report stays byte-identical — asserted by
  `git diff`, not claimed. The one artifact that does move is `blind_judgment.json`, which is
  model-free, rebuilt by its own test, and gains the new counts by design.
- **`confidence` is not an input and must not become one** (`test_confidence_is_not_a_trust_signal`).
- **T10's report is never amended by this ticket.** It freezes the honest read of what M8 *measured*,
  as of T9; this is a fix that came after, and a frozen report edited to carry a later result is no
  longer frozen. Whatever this ticket finds, it records on its own.
- **Zero model calls.** The held-out run count is unchanged.

**Sites.** `clearway/cli.py` (`_trust_label`, the legend); a blast-radius count beside the existing one
in `eval/blind_judgment.py`.

**Acceptance.**
1. The reachability test exists and demonstrably fails before the change.
2. A pixel-decided row drafted blind never renders `oracle-verified`; a `human-reviewed` one is
   unaffected; every other class is byte-identical in the rendered report.
3. Both blast-radius counts are recorded over the whole scoped corpus.
4. `git diff` over `benchmark/runs/` and every endpoint report is empty; `blind_judgment.json` moves
   only by gaining the new counts, and the suite passes unchanged rather than being updated to match.

- **Depends on:** T9

---

## Runs and cost

| Condition | Calls | Why |
|---|---|---|
| `leaky / no-image` | 7 | descriptive |
| `opaque / no-image` | 7 × 3 | the text-only floor; supplies null replicates |
| `opaque / with-image` | 7 × 3 | one half of D |
| `opaque / mismatched-image` | 7 × 3 | the other half of D |
| `opaque / no-image`, **discarded attempt** | **6, spent** | see the concurrency note below |
| `opaque / told-no-image` *(T9)* | 7 × 3 | one half of A |
| `opaque / told-with-image` *(T9)* | 7 × 3 | the other half — the control that A is read against |
| capture spot-check (T4 A3) | 3 | separates capture failure from plumbing failure |
| wiring smoke test (T5 A2) | **1, spent** | the real pipeline prompt end to end — **on a twin-excluded case, so nothing held out is spent** |
| LiteLLM spike (T0) | ~~1~~ **2, spent** | before anything is built |

> **⚠️ The spike cost two calls, not one.** The first request reached the model and returned; the
> script then crashed while writing its receipt (it read a `litellm.__version__` that does not exist),
> so the response was lost and the call had to be repeated. Not a transport failure — but a spend that
> leaves no artifact is the easiest kind to drop from a run count, so it is declared in the receipt
> (`model_calls_spent: 2`) and here.
>
> **⚠️ A first attempt at `opaque / no-image` was discarded and re-run, for a procedural reason
> independent of any verdict.** The test suite was started while the condition was drafting, and it
> contains gated real-model tests, so two `/api/chat` requests to the same model overlapped — read off
> the inference server's own log, where one measurement call took **3m33s against a clean-run mean of
> ~73s**. Concurrent requests share KV-cache slots, which is the exact mechanism M7 diagnosed as this
> stack's source of nondeterminism, so the contaminated sample would have been indistinguishable from
> drift in the very replicates the null rate is estimated from — and it was **sample 1, the canonical
> one**. Five findings had been drafted and a sixth was in flight; nothing was written to disk, and the
> condition was re-run with nothing else touching the model. The discard is declared rather than
> quietly repeated: **six calls, spent and thrown away.** The `leaky / no-image` pass is unaffected and
> was **not** re-run — its seven calls are strictly sequential in the same log, ending at 07:26:51,
> before the suite started at 07:28:46. **Standing consequence: no test suite runs while a condition
> is in flight.**

**~82 model calls over 7 findings** (~~75~~ → ~~76~~: the smoke test's declared call is inside the
total, not beside it, and the discarded `opaque / no-image` attempt adds six), **and ~124 with T9's two
conditions.** M7 ran 44 cases / 54
findings at 2–3.5 h per pass; at 7 findings
every condition is well under an hour. **No M7 case is re-run** — provided T2 closes silent-failure
path 6, which would otherwise draft all 44.

> **The smoke-test call is declared but is not held-out spend**, and the distinction is the one that
> matters for T10's count: it drafts a case the exclusion rule removed from the pool, so no cell of the
> endpoint, and no case any measurement reads, was drafted before its condition ran. The gate means it
> repeats on any machine with Ollama up — one call per invocation, on the same excluded case.

---

## Evidence ledger

**Verified — measured with the real scanner, normalizer and drafter over 93 usable ACT cases, or read
from the repo and upstream; independently re-derived by fresh-eyes review.** Of 16 usable
`qt1vmo` + `e88epe` cases, **6 mint**; **ten are matcher-limited** (4 `<svg>` without a qualifying role,
4 `<canvas>`, 2 `<input type="image">`), plus 2 `aria-hidden` images excluded as hidden nodes. The
vendored axe 4.12.1 bundle defines `image-alt` with `selector: "img"`, `svg-img-alt` with
`[role="img"], [role="graphics-symbol"], svg[role="graphics-document"]`, and `input-image-alt` with
`input[type="image"]`; `quality_review.py` defers the alt/name variants. `9eb3f6` mints **9 of 11**. All
three rules carry `wcag20:1.1.1` **Level A**. `9eb3f6`'s assets `nyhavn`, `paris`, `nyhavn.jpeg` and
`94251e11…` are **byte-identical — `sha256 c5cc0db7…`, 32 822 B, 320×213, one photograph under four
names**; the W3C logo is 1 927 B / 72×48; `pain` is 7 350 B / 150×100. `1ff696703e`'s `srcset` offers
only 1.5x and 2x candidates, so at Playwright's default `deviceScaleFactor = 1` the browser takes `src`
— **three distinct captures over seven findings, multiplicity 4 / 2 / 1**. **Five** assets are served
`application/octet-stream` (four of them on pool cases). **Two** prompt-level twin pairs exist. `1ff696703e`'s `srcset` retains the
tokens `nyhavn` and `paris` under a filename-only rewrite. **66 usable cases across 20 ACT rules mint an
`image-alt` finding**, but none besides `qt1vmo` and `9eb3f6` shares this mechanism: `23a2a8`'s 6
minting cases are **all gold-passed** (degenerate) and `46ca7f` has
**`ruleAccessibilityRequirements: null`**. ACT deprecated `9eb3f6` as **superseded by `qt1vmo`** (CG
call 2021-01-14, PR #1538); **no dispute about outcomes appears in the record**.

`e88epe`: 4 minting cases in which **reachability is perfectly correlated with gold** (both unreachable
cases are `passed`, both reachable are `failed`); `finding.html` is the `<img>` outerHTML only and
`_user_prompt` emits nothing else. **No `e88epe` drafter output exists in the repo** — it appears only in
`act_gold.EXCLUDED_RULES` and `expected_act.json`'s `excluded_rules`.

`0va7u6` *(live, WCAG 1.4.5 **Level AA**)*: 12 usable cases, **5 mint** (3 passed / 2 failed), **9
distinct assets with 9 distinct hashes**. **Headroom measured with the real `Drafter` and the real
prompt, no image: 2 of 5 errors**, and the two errors are exactly the two visually-decided cases —
predicted before the run and confirmed. `67b27814b7` (gold failed) drafted `supports` reasoning *"the
alternative text provides a meaningful description"*; `30562e91bf` (gold passed, `books.jpg`, `alt=""`)
drafted `does_not_support` reasoning *"Add a descriptive alt attribute"*.

Repo: `fixtures/act-gold/html/` holds **67 files, none of them image cases**; three already-vendored
cases reference `/test-assets/` absolutely and **already render broken**.
> **⚠️ Re-measured at T2: five, not three — and two of them are inside the scored 44.** All five are
> `<img src="/test-assets/…">`; the scored pair is `49a6b0a208` (a heading) and `d876314b60` (a link).
> **The acceptance numbers are unaffected and the gold is not invalid**: both are decided by an `alt`
> attribute, which is in the DOM whether or not the picture loads, and `expected_act.json` regenerates
> byte-identical. It matters as a *scope* fact — the acceptance minting deliberately serves no assets,
> so a guard written against the markup rather than against the gold tree would have refused two real
> gold cases. The refusal is therefore keyed to the case's tree, not to its `src` attributes. `RULE_TO_AXE` is the global
scope for `referent_injection_build` and `dry_gate`, which asserts **exactly 44**; extending it gives
**61**. **`LLMClient` exposes only `complete_json(system, user, schema)` — there is no `chat()`.**
`local.py` routes via `litellm.completion(model="ollama_chat/…")` with `response_format`, and its
docstring records that a sibling provider prefix silently drops structured output.
> **⚠️ Superseded by T5, which is the ticket that changed it.** The seam is now
> `complete_json(system, user, schema, image: ImagePart | None = None)`. There is still no `chat()`, and
> `local.py` still routes through the same provider prefix with the same `response_format` — what
> changed is that the user message becomes a content-part list **only when a picture is attached**, so
> every no-image call is byte-identical on the wire to the one this ledger entry describes. The repo contains
**no screenshot code**. `offline_tier_b.py` is **not** a derived-set builder. `Finding.referent` is the
precedent for a nullable, outside-the-id-hash scan field. `Finding.id` is
`sha(source_url, rule_id, target)`. The drafter is pinned to `gemma4:31b` at `temperature = 0`, digest
`6316f0629137`, `capabilities: ['completion', 'vision', 'tools', 'thinking']` — **the same tag and digest
M6/M7 ran**. **A direct `/api/chat` probe with each pool image attached — spent held-out data, declared
in T10 —** showed the model answers *"NO — this is Copenhagen, not Paris"*, *"YES — 'pain' is the French
word for bread"*, and names the W3C logo; it **bypassed LiteLLM**, ran without the pipeline's system
prompt and with thinking disabled, so it establishes **capability only**. **M7:** b = 5, c = 1,
p = 0.109375; **1 drifting finding in 54** at finding level, diagnosed as numerical rather than sampling
nondeterminism; case verdicts held only because flag-if-any absorbed it, which its write-up called luck.

**Re-derived at pre-flight against the vendored set, and frozen as a repo artifact.** Every count above
reproduced exactly: 51 published → **27 usable → 15 minting → pool 7 (26 %)**, the pool ids unchanged;
**10 matcher-limited** (4 `<svg>`, 4 `<canvas>`, 2 `<input type="image">`) **+ 2 `aria-hidden`**; the
**two** twin pairs found by the prompt-level check, whose two files are *not* byte-identical — which is
why the file-hashing check cannot see them. **All 7 pool cases render** (`naturalWidth` 72 / 320 / 150).
Confirmed **before** any capture exists, so T4 Acceptance 1 is now a regression check rather than a
discovery: the pool resolves to **3 distinct images at multiplicity 4 / 2 / 1**
(`c5cc0db7…` 32 822 B ×4 · `083d533e…` 1 927 B ×2 · `bfd6e732…` 7 350 B ×1), and `1ff696703e` takes
`src`, not a `srcset` candidate. **LiteLLM carries an image part, a `response_format` schema and the
model's thinking in one request** — schema-valid `_LLMDraft` returned on `gemma4:31b` digest
`6316f0629137`, the same digest M6/M7 ran; receipt frozen. One data point on cost: a 1 927-byte PNG
added ~835 prompt tokens and the call took ~58 s.

**Inference — reasoned, not observed.** That the pool's effective independent unit count is 3, so any
paired statistic on it is pseudo-replication. That the 6 image-deciding cases are image-deciding,
confirmed only when T6 runs. That full-path ablation defuses the help-text conflict rather than merely
reducing it. That a text-blind judge answers each discrimination group uniformly — **an assumption M7
measured false on comparable input**, which is one reason no sign test is reported.

**Settled in T0 — moved out of Unverified.** LiteLLM's `ollama_chat` provider **does** carry all three
in one request. The extensionless assets decode **regardless** of the served Content-Type, so that
question dissolved rather than being answered — and the type matters for the model's `data:` URI
instead. `9eb3f6`'s assets **remain served**.

**⚠️ Settle before T6/T7 if either runs anywhere but this checkout.** Every artifact that maps
`finding.id → a picture` — `capture.json` and the dry receipt — is **bound to this working copy's path**,
because `Finding.id` hashes the case's absolute `file://` URI. Pre-existing (T4 froze ids the same way)
and not a defect: it is the same property that rules out a local HTTP server. But a pass run from a clone
at a different path resolves **no** reference and the channel refuses every finding — loudly, which is the
designed behaviour, not silently. The fix is to rebuild both artifacts in the new checkout (one command
each, and their tests re-derive them), never to relax the lookup. `drafter_payload_baseline.json` is
unaffected: it is keyed by `(scope, act_testcase_id, target)` on purpose. Recorded in `ARCHITECTURE.md` §4.2.

**Still unverified — settle before the pass that depends on it.** Whether the drafter stays stable at
finding level with images attached *(T7 measures it; the null rate rule already anticipates it)*.
Whether the drafter uses an explicit statement that no picture is attached, or ignores it — nothing in
this repo has ever told it, and the measured starting point is that it never volunteers the absence
(0 of 28 blind rows, at 0.90–0.95 confidence).
Image-token cost and wall-clock per condition, beyond the single spike data point. Whether
`FROZEN_CLASS_KAPPA`'s "newest scored run" provenance rule can accommodate a run containing only
`image-alt` — a **structural** conflict, since no single artifact would carry all five classes, and
`image-alt` is already a shipped `QUALITY_REVIEW_RULES` class sitting at `UNMEASURED`. **M8 does not
resolve it and must not silently pin a shipped trust tier to ablated, deprecated-gold provenance.**
