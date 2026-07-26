# Clearway — M8: Multimodal

> **Scope.** M8 **builds the image channel and proves the model attends to the pixels.** It does **not**
> claim that supplying the visual fact restores judgment — that needs a paired test, and **no ACT gold
> set can support one**. The mechanism question moves to M9, which builds real-page image gold.
>
> The primary endpoint is a **manipulation check whose oracle the experimenter constructs**, so it is
> free of the ACT gold's power ceiling entirely.

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

**M8 builds that path and proves the model uses it.** Two outcomes, and only two:

1. **A product capability**, carried on the production path (`scanner → normalizer → drafter`), not an
   eval-only side channel. It is M9's prerequisite.
2. **A manipulation check** that is scored by code rather than by reading prose: attach the *wrong*
   image behind a byte-identical prompt and require the verdict to move.

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
cannot inflate D — but **D systematically under-detects attendance, and T8 must say so in one
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

1. **One model throughout** — `gemma4:31b`, `temperature = 0`, all four conditions. Digest
   `6316f0629137` with `vision` capability: **the same tag and digest M6/M7 ran.** No model change.
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
6. **Text classes isolated by payload hash, across the class that carries the risk.** Assert
   byte-identity of the serialized request for **all 7 image-class findings under the no-image
   condition, before and after the wiring ticket**, keeping one M7 text-finding hash as a cross-class
   check. This replaces re-running conditions post-wiring: byte-identical requests at `temperature = 0`
   leave only stack nondeterminism, which is already measured.
7. **⚠️ The receipt logs the image `sha256`, not a byte count.** A byte count cannot verify the
   permutation: the four Nyhavn cells share identical bytes, so a count check passes whether or not the
   mapping was honoured. The receipt records `sha256` per `finding.id` per condition, and T8 asserts the
   with-image and mismatched receipts differ **exactly where the frozen mapping says they should**.
   Without this, D has no proof it was ever actually run mismatched.

---

## Goal & exit criterion

Build the image channel on the production path, and prove the model attends to the pixels.

1. Case HTML and assets are vendored and **every pool case renders with its image loaded**
   (`naturalWidth > 0`), asserted **separately on the leaky set and the opaque set**.
2. The reachability artifact is frozen in the repo, **including a prompt-level twin check**, and
   reproduces the 7-case pool and the 4 twin exclusions exactly.
3. The image scope is admitted **without changing the existing 44-case scope** — the dry gate still
   passes on M7's frozen runs.
4. Each of the seven silent-failure paths is closed or fails loudly.
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
    probe**.

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
verified rather than assumed:** `e88epe` appears in the repo only in `act_gold.EXCLUDED_RULES` and as an
`excluded_rules` entry in `expected_act.json`. It is **not** in `RULE_TO_AXE`; M7's 44 cases never
touched it; the pre-spec measurement ran only the scanner and normalizer over it. **No `e88epe` drafter
output exists anywhere in this repo.** If that is ever falsified, the retraction is contaminated and the
prediction must be scored as written.

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
- **⚠️⚠️ Absolute asset paths do not resolve under `file://`.** ACT references `/test-assets/…`, which
  under `file://` resolves to the filesystem root. **The repo already ships three such broken renders
  and nobody noticed, because the pipeline is text-only.** **Decision, taken here and not deferred: a
  Playwright `page.route()` interceptor in `scanner/scan.py`, serving vendored bytes with a decodable
  `Content-Type`.** Rejected alternatives, with reasons: rewriting the HTML mutates ACT bytes and
  contaminates the leaky condition; a local HTTP server puts a port inside every
  `Finding.id = sha(source_url, rule_id, target)` and destroys reproducibility.
  **Four assets are served `application/octet-stream` upstream** (`nyhavn`, `paris`, `pain`,
  `94251e11…`); the interceptor must set a decodable type or `naturalWidth` is 0 on four of seven cases.
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
- `act_export_hash` does not change. Extending `RULE_TO_AXE` in place would take the scope to **61** and
  fail the dry gate on M7's frozen runs.
- **Acceptance:** dry gate still passes on M7's frozen runs; `EXCLUDED_RULES` and its test updated;
  deprecation recorded in the manifest.
- **Depends on:** T0

### T2 — Give the harness an explicit scope
**Seven paths fail silently on an image run. Each must be closed or made loud:**
1. `drafter_kappa._grouped` drops non-`RULE_TO_AXE` cases → an **empty but schema-valid** VerdictVector.
2. `paired._POOLED_AXE_RULES = ("label", "link-name")` is a default never threaded → **b = 0, c = 0**.
3. Attribution against a non-overlapping baseline `continue`s → prints **"prior run intact"**, a
   **false clean**.
4. `_DISTINCT_PROMPTS_BEFORE` / `baseline_reachable` are `.get()`-defaulted → `image-alt` renders empty.
5. `predictions=baseline_kappa.get("predictions", [])` → **M7's predictions scored into M8's result**.
6. `referent_injection_build` selects on `RULE_TO_AXE` + M7's manifest → would **draft M7's 44 cases**.
7. `_CONFIG_ID` / `_EVAL_SET_ID` stamp `m1-single@1` / `act-acceptance@1` → **false provenance frozen
   into every artifact**. **Literals, decided here: `config_id = "m8-multimodal@1"`,
   `eval_set_id = "act-image-opaque@1"`** (and `"act-image-leaky@1"` for the unablated condition).

- **Not the problem:** `RUN_LABELS` namespacing is sound — `passes_in` is label-prefixed,
  `refuse_to_overwrite` is path-based, single-parent `_PRIOR_RUN` expresses M8's chain.
- **Decided here, not deferred:** `score_run` raises below two passes (`referent_injection_score.py:128`)
  — **M8 scores outside it**, with its own scorer, because M8's endpoint is D and not a paired κ.
  **`dry_gate` is not generalised: M8 runs without a pre-flight gate**, and T8 must state that plainly
  rather than implying one existed.
- **Depends on:** T1

### T3 — The opaque derived set and the frozen permutation
- **⚠️ There is no derived-set precedent to reuse.** `offline_tier_b.py` is report arithmetic, not a
  builder; `noisy_pages.py` hand-authors HTML. A deterministic transformation script whose output
  carries checksums is **new work**.
- Rewrite `src`, `srcset` and the directory on all 7 pool cases to the pinned scheme (`/img/a.png`,
  `/img/b.png`, `/img/c.png`, one per distinct image). Nothing else changes. Deterministic, checksummed,
  distinct `set_id`.
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
- **Acceptance 2:** the smoke test runs **through the real pipeline prompt**, not a hand-written probe.
- **Acceptance 3:** no non-image finding carries an image; payload-hash equality holds over all 7
  image-class no-image payloads and one M7 text finding (Control 6).
- **Depends on:** T4

### T6 — The two text-only conditions
- `leaky / no-image`: one pass, descriptive. `opaque / no-image`: 3 samples per finding.
- Report the difference between them as a **secondary descriptive finding**, with one sentence noting
  it partly measures a fixture artifact: in the leaky condition 4 of 7 cases have alt ≈ filename
  case-insensitively, so against a help text saying *"a filename … does NOT describe"* the leaky cue is
  close to a string-equality trigger — a property of how a **deprecated** rule's fixtures were authored,
  not of real pages.
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

### T8 — Freeze and write the honest read
- **Mandatory report contents**, fixed now: D with its **retained-cell count** and the null rate actually
  used (`max` of M8's measured rate and M7's 1/54, both printed); the per-condition instability counts;
  the direction check as secondary; the `leaky` → `opaque` difference with its fixture-artifact caveat;
  the receipt/permutation assertion result; **three discriminations, four of seven cases one JPEG, 7 of
  27 candidate cases**; ACT's *"should not be used"* quoted verbatim; the `qt1vmo`-only dependency stated
  as **~100 %**; the prompt-mention decision; the help-text tension; **the `e88epe` retraction with its
  ground, its motive, and its verified precondition**; **that M8 ran without a pre-flight gate**; and
  **one sentence that D systematically under-detects attendance**, because a mismatched image may
  produce genuine uncertainty that the stability filter codes as noise.
- **⚠️ Declare the pre-spec probe.** Before this spec was written, each pool image was sent to the
  drafter directly and the model resolved all three. That is a model run on held-out data that
  **resolved the milestone's largest uncertainty before pre-registration**. M7 declared its analogous
  spend; M8 does too, in the held-out run count.
- **Rule: report ugly numbers as they are.** The unacceptable failure is not a low score but an
  untrustworthy one.
- **Depends on:** T7

---

## Runs and cost

| Condition | Calls | Why |
|---|---|---|
| `leaky / no-image` | 7 | descriptive |
| `opaque / no-image` | 7 × 3 | the text-only floor; supplies null replicates |
| `opaque / with-image` | 7 × 3 | one half of D |
| `opaque / mismatched-image` | 7 × 3 | the other half of D |
| capture spot-check (T4 A3) | 3 | separates capture failure from plumbing failure |
| LiteLLM spike (T0) | 1 | before anything is built |

**~74 model calls over 7 findings.** M7 ran 44 cases / 54 findings at 2–3.5 h per pass; at 7 findings
every condition is well under an hour. **No M7 case is re-run** — provided T2 closes silent-failure
path 6, which would otherwise draft all 44.

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
— **three distinct captures over seven findings, multiplicity 4 / 2 / 1**. Four assets are served
`application/octet-stream`. **Two** prompt-level twin pairs exist. `1ff696703e`'s `srcset` retains the
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
cases reference `/test-assets/` absolutely and **already render broken**. `RULE_TO_AXE` is the global
scope for `referent_injection_build` and `dry_gate`, which asserts **exactly 44**; extending it gives
**61**. **`LLMClient` exposes only `complete_json(system, user, schema)` — there is no `chat()`.**
`local.py` routes via `litellm.completion(model="ollama_chat/…")` with `response_format`, and its
docstring records that a sibling provider prefix silently drops structured output. The repo contains
**no screenshot code**. `offline_tier_b.py` is **not** a derived-set builder. `Finding.referent` is the
precedent for a nullable, outside-the-id-hash scan field. `Finding.id` is
`sha(source_url, rule_id, target)`. The drafter is pinned to `gemma4:31b` at `temperature = 0`, digest
`6316f0629137`, `capabilities: ['completion', 'vision', 'tools', 'thinking']` — **the same tag and digest
M6/M7 ran**. **A direct `/api/chat` probe with each pool image attached — spent held-out data, declared
in T8 —** showed the model answers *"NO — this is Copenhagen, not Paris"*, *"YES — 'pain' is the French
word for bread"*, and names the W3C logo; it **bypassed LiteLLM**, ran without the pipeline's system
prompt and with thinking disabled, so it establishes **capability only**. **M7:** b = 5, c = 1,
p = 0.109375; **1 drifting finding in 54** at finding level, diagnosed as numerical rather than sampling
nondeterminism; case verdicts held only because flag-if-any absorbed it, which its write-up called luck.

**Inference — reasoned, not observed.** That the pool's effective independent unit count is 3, so any
paired statistic on it is pseudo-replication. That the 6 image-deciding cases are image-deciding,
confirmed only when T6 runs. That full-path ablation defuses the help-text conflict rather than merely
reducing it. That a text-blind judge answers each discrimination group uniformly — **an assumption M7
measured false on comparable input**, which is one reason no sign test is reported.

**Unverified — settle in T0 or Plan.** **Whether LiteLLM's `ollama_chat` provider carries multimodal
content parts, a `response_format` schema and the thinking budget in one request** — the one link the
wiring assumes and the pre-spec probe bypassed; T0 spikes it. Whether the interceptor serves decodable
Content-Types for the four extensionless assets. Whether the drafter stays stable at finding level with
images attached. Whether `9eb3f6`'s assets remain served. Image-token cost and wall-clock per condition.
Whether `FROZEN_CLASS_KAPPA`'s "newest scored run" provenance rule can accommodate a run containing only
`image-alt` — a **structural** conflict, since no single artifact would carry all five classes. **M8 does
not resolve it and must not silently pin a shipped trust tier to ablated, deprecated-gold provenance.**
