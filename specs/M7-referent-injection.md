# Clearway — M7: Fix the drafter, test it with the ruler

> **Scope note.** M7 is the first milestone that **changes drafter behaviour**. It carries the referent
> experiment *and* the agreed output-field and report work, **sequenced around the experiment rather
> than through it**: everything that cannot touch a drafter prompt lands **before** Run A; the
> experiment runs clean; the one remaining prompt change lands **after**, alone, in Run B — so any
> regression it causes is attributable to it and nothing else.
>
> The referent work here is **textual**: text that exists in the DOM but outside what the drafter
> actually receives — which is materially less than this spec originally assumed. The **non-textual**
> referent (image alt-text, rendered-page items) is **M8: MultiModal + Referent**, which is scoped to
> that and nothing else.
>
> **The abstention channel is dropped, not deferred** — see §Dropped. The measurement says the channel it
> would add already exists and has never been used.
>
> **The deliverable is the measured answer, not a certificate.** See §Goal.

## Table of Contents

- [Preamble](#preamble)
- [What is measured, and by what](#what-is-measured-and-by-what)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [What is explicitly not measured](#what-is-explicitly-not-measured)
- [Tickets](#tickets)
- [Dropped](#dropped)
- [Evidence ledger](#evidence-ledger)

---

## Preamble

M6 turned the ruler on the drafter and froze a per-class baseline. It said something precise: the
drafter **judges** where the referent is reachable (`empty-heading`, κ = 0.675) and produces a
**constant verdict** where it is not (`document-title`, κ = 0.000, `constant_classifier: true`).

**The referent is the thing you must be able to see to make the judgment.** The drafter today
receives an element-scoped snippet — `finding.html`, the offending element and nothing around it.

### ⚠️ Measure what the drafter actually receives, not what the ticket assumes

An earlier draft of this spec claimed the drafter sees `<title>Apple harvesting season</title>` and
merely lacks the page around it. **That is false.** Assembling the real `_user_prompt` over the
vendored fixtures gives *(verified; reproduce with the T0 harness)*:

| Class | What the drafter actually receives | Distinct prompts / cases |
|---|---|---|
| **`document-title`** | `Target: html` · `HTML: <html lang="en">` — **the title is never in the prompt** | **1 / 5** |
| **`label`** | the bare `<input …>`; the labelling element is outside the snippet | **6 / 11** |
| **`link-name`** *(post-T0)* | `<a href="#desc">More</a>` — link text only | **13 / 13** |
| **`empty-heading`** *(control)* | the heading element; referent already inside it | 9 / 11 |

**This reframes what M6 measured.** `constant_classifier: true` on `document-title` is not a drafter
that stopped judging. Five byte-identical prompts at `temperature=0.0` **must** produce five identical
answers. κ = 0.000 is the *only* possible score for the input given. The drafter is not failing; it is
being asked one question and scored against five different answers.

### ⚠️ Two failure modes, not one — and they need different fixes

An earlier draft of this spec named a single quantity, *prompt degeneracy*, and claimed M7 moves it.
Measurement says there are two modes, and only one is degeneracy:

| Mode | Classes | Symptom | What injection must do |
|---|---|---|---|
| **Degeneracy** | `document-title` **1 / 5** · `label` **6 / 11** | cases gold separates receive the *same* input | **split** the prompts |
| **Insufficiency** | `link-name` **13 / 13** | every case already has a *distinct* prompt; none contains the deciding fact | **add signal** — splitting is already complete |

`link-name` post-T0 is at maximum distinctness before M7 changes anything, so *"distinct prompts
must rise"* is unsatisfiable there and any acceptance criterion phrased that way is vacuous. The two
modes share a cause — the referent is absent — but not a test. **Where the test differs, the ticket
says which mode it is treating.**

**M7's claim, and the thing under test:** accuracy on these classes is governed by *whether the
referent is present in the input*, not by model strength. Same model, same weights, same temperature —
referent in hand, it can discriminate; referent absent, it cannot, however hard it tries.

`empty-heading` is **not touched**. It is the control: the class whose referent was already reachable
and which already works. If its κ moves, something contaminated the experiment.

---

## What is measured, and by what

> ## ⚠️ The test was fixed before the result existed.
> **M6 pre-registered it. M7 does not get to choose it now.**

The baseline artifact carries the pre-registration inline: the test is **one-sided** (a fix should
improve, not merely change) at **α = 0.05**, scored on **discordant pairs** against the frozen
per-case verdict vector, keyed by `act_testcase_id`. ACT gold is the oracle. The judge is absent from
every M7 acceptance number, as in M6.

> **⚠️ What T0 may and may not change.** The **test** is fixed and inherited: one-sided, α = 0.05,
> discordant pairs, ACT gold, keyed by `act_testcase_id`. T0 does not touch any of that. What T0
> re-derives is the **estimand and the ceiling** — which cases are in a class, and how many of its
> errors a prompt-input change can reach. Correcting an estimand that provably cannot represent its
> gold, **before any M7 result exists**, is the discipline that made M6's pre-registration meaningful.
> Doing it after the run would be p-hacking; that is why T0 is first and why exit criterion 9 makes
> the ordering a gate.

> **⚠️ Standing constraint, inherited.** κ and every paired test are scored against **ACT gold, never
> the judge**. The judge sits at chance; optimising against it is Goodhart. This does not soften
> because M7 is the milestone that finally wants a number to move.

### The frozen M6 baseline *(verified — `benchmark/reports/drafter_kappa_baseline.json`)*

| Class | n (fail/pass) | tp·fp·fn·tn | κ | errors | ceiling p | M7 action |
|---|---|---|---|---|---|---|
| **`link-name`** *(pooled ×2)* | 24 (11/13) | 7·5·4·8 | 0.250 | 9 | 0.002 | context + accname |
| **`label`** | 11 (5/6) | 4·4·1·2 | 0.127 | 5 | 0.031 | accname **+ section context** |
| **`document-title`** | 5 (2/3) | 2·3·0·0 | 0.000 | 3 | 0.125 | **resolved title** + topic signal |
| **`empty-heading`** *(control)* | 13 (5/8) | 4·1·1·7 | 0.675 | 2 | 0.250 | **untouched** |

> **⚠️ The `link-name` row and every "ceiling p" here are superseded by T0.** They are the frozen M6
> record, kept as the historical anchor. The numbers M7 is measured against are below.

### ⚠️ The error counts above are NOT the achievable ceiling

A class passes on **discordant pairs**: `b` = baseline-wrong → M7-right, `c` = baseline-right →
M7-wrong, with p = P(X ≥ b) under Bin(b+c, ½). At α = 0.05 the bar is **b ≥ 5 with c = 0**
(b=5,c=0 → 0.031 ✅; b=4,c=0 → 0.0625 ❌; b=5,c=1 → 0.109 ❌; b=6,c=1 → 0.0625 ❌; b=7,c=1 → 0.035 ✅).

M6 computed each ceiling from the class's *total* errors. **Some of those errors cannot be reached by
any prompt-input change**, so the ceilings are optimistic. Two kinds are **structural** — provable
from the artifacts, and the only kinds the ledger subtracts:

1. **Honest misses** — the case mints no finding, so the drafter is never called. `link-name` ×1
   (post-T0), `empty-heading` ×1. No prompt change reaches a model that was never invoked.
2. **Contradictory gold** — two ACT rules assign **opposite outcomes to byte-identical fixture files**
   (verified: two such content-pairs, four files). Same DOM → same referent → same prompt → same
   verdict. Exactly one of each pair is permanently wrong. **T0 removes this by scoping the class**
   (below), after which the term is identically zero.

> **⚠️ A predicted failure is not a structural exclusion.** `3bb1986371`'s referent is the link
> *destination*, outside the DOM — but "the model will therefore not fix it" is a **prediction about
> model behaviour**, not arithmetic. It is pre-registered in T0 as a prediction and stays **inside**
> the reachable count. Subtracting predicted failures from the denominator is how a ceiling becomes
> unfalsifiable.

**The reachable ceiling, post-T0:**

| Class | n | errors | structural exclusions | **reachable** | best p | Margin |
|---|---|---|---|---|---|---|
| `link-name` *(in-context rule only)* | 15 | 6 | 1 honest-miss error | **5** | 0.031 | **zero** |
| `label` | 11 | 5 | — | **5** | 0.031 | **zero** |
| `document-title` | 5 | 3 | — | 3 | 0.125 | uncertifiable |
| `empty-heading` *(control)* | 13 | 2 | 1 honest-miss error | 1 | 0.500 | n/a |

*(A class's honest-miss **errors** are counted here, not its honest misses: `link-name` in-context has
two misses, one gold-failed and therefore an error, one gold-passed and therefore correct.)*

### ⚠️ Per-class certification has no margin. The thesis test does.

Both certifiable classes require **5 fixed, 0 broken** — a perfect run, twice, independently. That is
a property of the gold set's size, not of the fix. Staking the milestone on it would report failure
for a fix that worked.

**So the primary endpoint is the thesis, tested once, pooled across the two classes M7 fixes.** The
hypothesis is about *referent presence*, not about `label` or `link-name` individually, so the
estimand is the pool: **10 reachable errors**, with real margin.

| Pooled outcome | p | |
|---|---|---|
| b=5, c=0 | 0.031 | ✅ |
| b=6, c=0 | 0.016 | ✅ |
| b=7, c=1 | 0.035 | ✅ — **tolerates a regression** |
| b=8, c=1 | 0.020 | ✅ |
| b=9, c=2 | 0.033 | ✅ |
| b=6, c=1 | 0.0625 | ❌ |
| b=8, c=2 | 0.055 | ❌ |

> **This is not the pooling M6 rejected, and not the pooling M6 endorsed either.** M6 pooled to
> *estimate one class's effect*, and required a shared referent **and** a shared fix. This pools to
> *test one hypothesis across classes* — a primary endpoint, with per-class results reported as
> secondary. Different purpose, different rule. Both are stated so neither is mistaken for the other.
> **Per-class certification is still computed and reported**; it simply is not what the milestone
> rests on.

### Two frozen runs, and the rule that makes the second one mean something

A **run** is one complete pass of the pipeline over the 44-case acceptance set: scan → normalize →
retrieve → **call the drafter** → call the judge → freeze to `benchmark/runs/run_N.json`. The model is
called only there; every downstream number is a pure function of that file. A run is the unit because
it is the only place non-determinism can enter, and freezing it is what makes the numbers reproducible
without re-running the model.

**Run A — referent injection only. This is the experiment.** Per-class injection is **disjoint by
class**: the `label` branch alters only `label` prompts. The control's prompt stays byte-identical,
asserted by test, so one run yields clean per-class attribution.

**Run B — T7 only.** It confirms T7 did not undo what Run A showed, produces the final remediation text
T9 scores, and becomes the baseline M8 pairs against.

> ## ⚠️ The one-prompt-change rule
> **A run may carry at most ONE prompt-touching change.** This is what makes a regression attributable,
> and it is derived from the same argument that protects Run A: *re-running cannot separate the causes
> afterwards.*
>
> An earlier draft violated it — Run B carried **two** every-prompt changes (SC normative text **and**
> abstention) while its exit criterion demanded that any regression be blamed on "the responsible
> change". That attribution was impossible as specified. The fix is not a third run: **T7 is the only
> prompt change in Run B**, because everything else was either sequenced before Run A (T1, T2, T3 — none
> touches a `passes` prompt) or is not a prompt change at all (T8 is report-layer; T9 only *scores*
> existing text), and abstention is dropped outright.
>
> **Adding a second prompt-touching ticket to Run B costs either the attribution or another run.** Do
> not do it.

### Controls that make the comparison mean anything

1. **The control's prompt must be byte-identical**, asserted by test. If injection leaks into
   `empty-heading`, the anchor proving the instrument works is gone.
2. **The environment must be held fixed** — `drafter_model_digest`, `axe_core_version`,
   `act_export_hash`, `corpus_version`, `config_id` must match the baseline artifact exactly. All five
   are already frozen there; the check is a comparison, not an investigation.
3. **The case set must be identical — 44 cases** (the post-T0 count; T0 is the *only* change
   permitted to move it, and it moves it once, before the run). Prompt changes cannot alter which
   findings are minted — minting is the normalizer's job. `Finding.id` hashes
   `(source_url, rule_id, target)`, so referent fields must not enter it.
4. **Determinism must be re-verified, not assumed.** The drafter runs at `temperature=0.0` and M5/M6
   verified determinism *under the old prompt*. The prompt is now longer. Reuse the existing sweep:
   three passes, assert per-class agreement, freeze run_1 as canonical. If determinism no longer
   holds, a drafter noise floor must be established before any paired claim is made. *Read it for what
   it is: much of the previously-observed agreement was guaranteed by degeneracy, not stability — as
   injection splits the prompts, this check starts testing something it previously could not.*
5. **The referent must be present in the prompt, asserted offline before the model is called** — see
   the dry gate in T6.

### ⚠️ Three ways this milestone can fool itself

**A gold correction can manufacture the wins it then reports.** See T0: the exclusion converts one
previously-unwinnable error into a winnable one and hides one predictable regression. Stated there,
and again in the written read.

**Prompt iteration overfits the held-out set.** Tuning a prompt against 44 ACT cases — 11 for `label` —
fits the test and destroys it. This is M5's self-gold lesson (κ 0.79 → 0) one level up, in the input
pipeline rather than the gold.

> **Pinned separation.** Iterate on the **dev set**: `clearway/fixtures/pages/quality/` with
> `expected_quality.json`, extended by T5a/T5b. Its known weakness — it does not generalise — is what
> makes it *safe* to overfit and *unsafe* to certify with. **Every model run against the ACT set is
> counted and recorded.**
>
> **⚠️ The dev set does not currently cover two of the three classes** *(verified: `image-alt` ×9,
> `link-name` ×9, `frame-title` ×9 — **no `label`, no `document-title`**)*. As it stands the discipline
> is unenforceable for the zero-margin class. **T5a and T5b each build their own dev fixtures first.**

**⚠️ The held-out set has already been read, and the run counter does not count that.** This spec was
written with full sight of the decisive held-out cases: it names `e419548ab0`/`5d11716ba4`,
`3bb1986371`, `1ba642803c`, `88a1646138`, `925f5da929`, and derives T5b's target from held-out fixture
bodies. **That is a real, spent degree of freedom, and the model-run counter does not measure it.**
Disclosed here because it cannot be undone; whoever authors the T5a/T5b dev fixtures should know they
have seen the answers. Naming decisive cases in advance is still better than discovering them
afterwards and rationalising — but it is not the same as a clean hold-out, and this spec does not
claim one.

### What is pre-committed about reporting

Fixed now, before the run exists:

- **Certified** — clears the pre-registered one-sided test at α = 0.05.
- **Worked but uncertifiable** — verdicts moved in the right direction and the mechanism changed
  (visible in the verdict vector), but p ≥ 0.05. This is the *expected* outcome for `document-title`
  and a legitimate, reportable result, not a failure to be reframed.
- **Failed** — no directional movement, or regressions dominate. **Numerically: pooled `b ≤ 2` with
  the dry gate green, the control holding and determinism holding.** That is the thesis not supported,
  and it is reported in those words.

`document-title` cannot reach "certified" at any fix quality (n = 5, ceiling p = 0.125). Its claim is
argued on **mechanism** — distinct prompts rising from 1, `constant_classifier` flipping to `false`,
`fp: 3` falling. **Never on a per-class p-value.**

> **⚠️ A confirmed prediction of failure is still a failure.** T0 pre-registers two predictions. If
> they hold, that is *two errors not fixed* — not two successful forecasts. The written read states
> the outcome first and the forecast second, and whoever scores them is not the author of T5a/T5c.

---

## Goal & exit criterion

Put the referent in the input for the three text classes whose referent is reachable but unreached,
**test the thesis against the corrected baseline using the pre-registered test, and report the answer
as the evidence gives it.**

**Exit criterion:**

1. **⚠️ The pooled thesis test is run and reported** — `link-name` + `label`, 10 reachable errors,
   one-sided sign test at α = 0.05 against the T0 baseline. **This is the primary endpoint and it can
   fail:** pooled `b ≤ 2` is reported as *thesis not supported*.
2. **Per class, a stated verdict** of **certified / worked but uncertifiable / failed** against the
   §pre-committed definitions, measured against the T0 reachable ceiling. Certification where reached
   is reported; where not reached, mechanism evidence is reported in its place.
3. **⚠️ Mechanism is reported for every class, certified or not** — distinct prompts before/after,
   `constant_classifier` state, the 2×2, and which specific reachable errors moved. This is what
   survives when significance does not, and for `document-title` it is the *only* evidence. Reporting
   `document-title` as "certified" is a spec violation.
4. **The control holds** — `empty-heading`'s prompt byte-identical by test, κ unchanged.
5. **The referent is verifiably present** — for each fixed class, the named referent string appears
   **verbatim** in the prompt, asserted offline. Distinct-prompt counts are reported as a secondary,
   gold-free diagnostic, **never as an acceptance criterion** (see T6).
6. **Extraction is written for real pages, not fitted to fixtures** — T4's acceptance names the page
   and the artifact.
7. **Both runs frozen and reproducible** — verdict vector and full provenance each, determinism
   re-verified under the new prompt, and the **held-out model-run count recorded**.
8. **The two pre-registered predictions are scored**, by someone other than the ticket's author,
   including where a prediction was wrong.
9. **The gold correction landed and its ceiling pre-registered before Run A** — T0's reachable-error
   ledger and re-derived ceilings committed, the exclusion rationale recorded, the manufactured win and
   unscored regression disclosed, **and every stale surface superseded**. A ceiling re-derived *after*
   seeing a run is p-hacking; a corrected ceiling that leaves the optimistic one standing elsewhere is
   the same failure with extra steps.
10. **⚠️ Run B does not eat Run A.** If Run B regresses a class Run A improved, **T7 is rolled back or
    made class-conditional** — attribution is unambiguous because T7 is the run's only prompt change.
    The referent fix is the milestone's core value; a grounding tweak does not get to consume it.
11. **Phase-1 tickets provably did not touch the experiment** — T1, T2 and T3 each ship with the
    assertion that no `passes`-bucket prompt changed, and T1 additionally with "no number moves".
12. **`remediation_technique_match` non-null on the classes ACT can score**, reported
    **chance-corrected**, with its 2-of-4 coverage stated — the first remediation measurement this
    project has taken, and reported as a *direction* floor, never as evidence that fixes are useful.
13. **Report rows carry a verification-state trust label**, never derived from confidence; and
    **self-reported confidence is no longer a trust input**, surviving only as an ECE receipt.
14. **Violations-bucket SC and conformance assembled in code**, with the honest note that this ships
    unmeasured for want of violations gold.
15. **`whitelist` prose sweep done**, no broken references, no number moved.

**What would falsify the thesis:** injection lands cleanly, the referent is verifiably in every
prompt, the control holds, determinism holds, and the classes still do not move (pooled `b ≤ 2`). That
is a publishable result and must be reported as one — the ruler was built precisely so this outcome is
legible rather than deniable. **Note the ordering:** if the referent is *not* verifiably in the
prompts, the thesis was never tested and the run proves nothing about it — which is why criterion 5
gates the run rather than describing it.

---

## How to use these tickets

**Ticket order IS build order — T0 through T10, strictly in sequence, one reviewable ticket at a
time.** The numbering carries the phase structure, so a ticket's position tells you what it is allowed
to touch:

| Phase | Tickets | Why here |
|---|---|---|
| **0 — pre-registration** | **T0** | Every later number is measured against what it pre-registers |
| **1 — pre-Run-A** | **T1 · T2 · T3** | None can touch a `passes`-bucket prompt; each carries the test that proves it |
| **2 — the fix** | **T4 → T5a → T5b → T5c** | Extraction, then one class each |
| **3 — the experiment** | **T6** | Dry gate, Run A, the paired tests |
| **4 — post-Run-A** | **T7 · T8 · T9** | T7 is the only prompt change; T8 and T9 touch no prompt |
| **5 — deliverable** | **T10** | Run B, frozen scorecard, honest read |

**T5a/T5b/T5c are siblings, not a sequence break** — one referent class each, deliberately kept
separate so a wording problem in one cannot contaminate the others. Build them in order all the same.

**⚠️ Three boundaries are load-bearing.**

- **T0 must precede everything.** A ceiling derived after seeing a result is not a pre-registration.
- **Nothing in phase 1 may alter a `passes`-bucket prompt**, asserted by test in each ticket. That
  assertion is what earns those three tickets their place before the experiment; without it they belong
  after it. Both classes are zero-margin and the pooled test tolerates only one regression.
- **No prompt-touching change beyond T5a/T5b/T5c may land before Run A is frozen**, and **at most one
  may land before Run B** — see the one-prompt-change rule above.

**Module boundaries.** T4 spans `scanner/` + `schemas/`; T0 spans `eval/` + `schemas/` + docs +
tests. CLAUDE.md's one-module-per-branch rule is relaxed for these two by explicit exception, recorded
here — both are single coherent changes that cannot be split without leaving the tree inconsistent.

---

## What is explicitly not measured

1. **Whether any of this transfers to real pages.** Every number sits on ACT's **synthetic** cases,
   whose rendered bodies run 2–220 characters. A certified fix here is not a fix proven in production.
   Unmeasurable without the parked real-page transfer gold.
2. **`document-title`'s fix, in the significance sense.** Structurally uncertifiable at n = 5.
3. **The link destination.** Surrounding context is a *proxy*, not the referent: the destination lies
   outside a single-page DOM and is unreachable to M7 and M8. If `link-name` moves, it shows that
   context helps — **not** that link purpose is solved. `3bb1986371` is where this bites.
4. **The nine `Link is descriptive` cases T0 excludes.** They are scoped out as AAA-only (see T0),
   not fixed and not failed — **except** that two of them are predictably affected by M7's own change
   and go unscored. T0 says which and why.
5. **Remediation *usefulness*.** T9 scores *direction* against ACT technique gold — whether a drafted
   fix is actually **useful** still needs a human expert and stays unmeasured.
6. **Anything needing a human expert** — whether a fix is *useful*, and whether expert-minutes-per-
   finding has fallen. Still the one unproven link in the value proposition.
7. **The image classes and everything needing sight.** M8 (MultiModal + Referent).
8. **Whether the drafter abstains on the right cases.** The `not_applicable` path exists and has
   never been used (`abstained_n = 0`); abstention is dropped, so nothing here changes.
9. **Sampling agreement as a trust signal.** Structurally unavailable at `temperature=0.0`.
10. **The reflection loop.** A later milestone; unchanged by M7.

---

## Tickets

### T0 — Gold correction + reachable-ceiling pre-registration *(first, alone, no model calls)*
- **Produces:** a corrected `link-name` class definition, a per-class **reachable-error ledger**, a
  re-derived baseline, and the pre-registered ceilings every M7 claim is measured against.
- **Detail — part 1: scope `link-name` to *Link in context is descriptive*** (n = 15; drops 9 cases,
  53 → 44). Record *Link is descriptive* in `EXCLUDED_RULES` (`eval/act_gold.py`).
  **⚠️ The rationale is conformance level, and it must be stated that way.** *Link is descriptive*
  maps to **SC 2.4.9 only — Level AAA**; *Link in context is descriptive* maps to **2.4.4 (Level A)**
  + 2.4.9 (verified from the export). Clearway drafts VPAT/ACR rows, where A/AA is the conformance
  target. **Excluding a AAA-only rule is ordinary scoping, available before any result existed and
  independent of M7's outcome** — which is exactly what makes it a legitimate pre-registration.
  It also happens to remove a contradiction (the two rules assign opposite outcomes to byte-identical
  files, which a one-`Finding`-per-element pipeline cannot represent), but **that is a consequence,
  not the reason** — do not lead with it.
- **⚠️ Do not claim `EXCLUDED_RULES` precedent for the contradiction argument.** All five existing
  exclusions are properties of a rule *in isolation* (the pipeline cannot see the input; ACT's unit is
  a set of links; no `Finding` is ever minted). The link-rule contradiction is not: it dissolves if you
  change a groupby key. The AAA/AA ground needs no precedent and does not have this problem.
- **⚠️ Detail — part 2: disclose what the exclusion does to the arithmetic.** Verified:

  | pair | kept member | dropped member |
  |---|---|---|
  | `73a8392cf8cb` | `6566c139dc` — **currently an error** | `48cbc84f4c` — **currently correct** |
  | `c88b25d63bd2` | `5e67cab9c6` — currently correct | `1c577f9a13` — currently an error |

  So the exclusion **converts one previously-unwinnable error into one of the five required wins**
  (`6566c139dc`), and **hides one regression the same fix predictably causes** (fixing `6566c139dc`
  would flip its byte-identical twin `48cbc84f4c` from correct to wrong, and that twin is no longer
  scored). One manufactured win, one unscored regression. **State both in the artifact and in the
  written read.** A reader who cannot see this cannot audit the improvement.
- **Detail — part 3: emit the reachable-error ledger** per class: `total − honest-miss errors −
  contradictory-gold errors`, each exclusion named to the `act_testcase_id` with its reason.
  **⚠️ Structural exclusions only.** Predicted failures stay *in* the count — subtracting them makes
  the ceiling unfalsifiable. Post-scoping the contradictory term is identically zero, since scoping
  removed the pairs rather than subtracting their errors; keep the term in the formula with a note, so
  the ledger reads the same before and after.
- **Detail — part 4: re-derive the baseline and pre-register the ceilings** over the corrected class
  definition — a pure function over `benchmark/runs/run_1.json`, **no model re-run** — recording
  per-class p, the pooled p, α and direction, as `drafter_kappa_baseline` already does.
- **Detail — part 5: pre-register this spec's two predictions**, with reasoning and epistemic status:
  `e419548ab0` will not be separated from `5d11716ba4` by the accname (**argued** — the referents
  differ only by a trailing colon, so a drafter that accepts one should accept the other; the
  *consequence* is arithmetic but the *antecedent* is a claim about model behaviour); `3bb1986371`
  resists context injection (**argued** — its gold turns on a destination outside the DOM). A spec that
  demands falsifiable claims of the drafter states its own the same way.
- **⚠️ This is a CONTRACTS §3 change — apply the schema-edit rule and update §5 + §6 in the same
  change.** `DrafterKappaBaselineRow` is `extra="forbid"` and **derives** `p_value = 0.5**errors`
  (`drafter_kappa.py:274`), so re-deriving the row necessarily moves `errors` 9 → 6 and `p_value`
  0.00195 → 0.0156 — **you cannot re-derive a row and keep its old values in that row.** Add declared
  fields for the reachable count and the reachable p, and preserve the M6 reading either as explicit
  `m6_*` fields or as a separate historical artifact. Say which; do not leave it implied.
- **⚠️ Supersede the stale surfaces; do not merely add a corrected one beside them.**
  `benchmark/reports/drafter_kappa_baseline.json`; `docs/drafter-kappa-baseline.md` (its table and the
  line *"`link-name` (p = 0.002) and `label` (p = 0.031) clear α"*); `clearway/eval/drafter_kappa.py`
  (module docstring and `_grouped`, both stating the link rules pool); `clearway/eval/act_gold.py`
  (*"the **five** ACT descriptiveness rules"* → four); `docs/act-feasibility.md`;
  `specs/M6-drafter-kappa.md` §"Stratify by fix unit"; and **six** occurrences of the
  "two link rules pool as `link-name`" description (`schemas/models.py` ×3, `CONTRACTS.md` ×3).
  **This is the "stale TRUSTED surface" failure the repo's own methodology review named** — a number
  frozen as authoritative, later known to be optimistic, left where the next reader inherits it.
- **⚠️ What is stale in the tests is the p-value, not the boolean.** `tests/test_drafter_kappa.py` and
  `tests/test_drafter_kappa_baseline.py` assert `certifiable is True` for `link-name`. That assertion
  **stays true** post-scoping (raw errors 6 → p 0.0156; reachable 5 → p 0.031; both ≤ α). Update n,
  errors and p; **do not "fix" the boolean** — it was never wrong.
- **Acceptance:** the ledger reproduces the four reachable counts (`link-name` 5, `label` 5,
  `document-title` 3, `empty-heading` 1) **using structural exclusions only**; the re-derived baseline
  invokes no model; pairing against the M6 verdict vector still works case-by-case on the surviving
  `act_testcase_id`s; the exclusion rationale, the manufactured win, the unscored regression, the
  pre-registration and the two predictions are recorded **in the artifact**, not only in prose;
  **`empty-heading`, `label` and `document-title` are untouched** and bit-identical to M6; **no surface
  in the repo still reports the superseded ceiling as current** — asserted by a test that greps the
  specific literals (`0.001953125`, `p = 0.002`, `24 (11/13)`, "pooled"), since a test cannot judge
  prose.
- **Note:** κ for `link-name` is **not** comparable to the M6 scalar after this (different n). Say so;
  the *paired* comparison survives, which is what the tests use. Also: regenerating the manifest
  re-scans the fixtures via Playwright + axe, so this is offline of the **model**, not of the browser —
  and `load_act_gold_pairs` raises on axe drift, which is a feature.
- **Also re-derive:** the pooled FP denominator M6 used for `document-title`'s fallback argument
  shrinks when 9 cases leave, and every pooled M5/M6 rate (FP, recall, SC-match, ECE) is over the old
  53-case denominator. State the new denominators, or T7's FP/recall reporting is not like-for-like.
- **Depends on:** —

### T1 — `whitelist` → `QUALITY_REVIEW_RULES` prose sweep *(pre-Run-A)*
- **Produces:** consistent terminology. **No behavioural change.**
- **Detail:** the constant is **already named `QUALITY_REVIEW_RULES` in code**; only prose survives.
  The surface is **21 files** (verified): `schemas/models.py`, `normalizer/normalize.py`,
  `normalizer/quality_review.py`, `scanner/scan.py`, `eval/noisy_pages.py`, `fixtures/README.md`,
  `fixtures/expected_quality.json`, `fixtures/noisy-pages/page-a-title.html`, five test files,
  `CONTRACTS.md`, `ARCHITECTURE.md`, and six docs/specs. Preserve the meaning the word carried: the
  set is *global*, so adding a rule mints findings on every page.
- **Fixture risk — checked, and it is nil.** The two fixture hits are both **non-semantic**
  (verified): in `expected_quality.json` the word appears only in the free-text `.note` field, never in
  a gold label or rule id; in `page-a-title.html` it appears only inside an **HTML comment**, which is
  not rendered, not in `innerText`, and not in the accessibility tree, so axe cannot see it. Neither
  can move a scan result or a gold value. Change them or leave them; just do not rewrite *rendered*
  fixture content.
- **Acceptance:** no occurrence outside a deliberate historical reference (CONTRACTS decision-log
  entries are historical and stay); suite green; **no number moves**, asserted by re-running the frozen
  comparisons, not assumed.
- **Depends on:** T0

### T2 — Violations-bucket optimisation *(pre-Run-A)*
- **Produces:** SC and conformance assembled in code for the `violations` bucket; the model writes only
  `remediation`.
- **Detail:** axe has already confirmed the failure and the SC is derivable from its tags, so asking
  the model to decide conformance adds cost and hallucination surface for no judgment. `tag_to_sc_ids`
  in `oracle/axe.py` already does the derivation — reuse it. **This is a remediation-accuracy change,
  not only a cost change:** with the SC assembled from axe tags rather than guessed, the model writes
  its fix **against the correct criterion**, removing a real error source — and, with the SC known,
  T9's reverse-inference check becomes clean (does the fix point back at *that* SC?).
- **⚠️ Why it is safe before Run A, and the guard that makes it so.** The acceptance set is drawn
  **entirely from the `passes` bucket**, so a violations-only change cannot reach it *in principle*.
  But "the model writes only `remediation`" implies a **different response schema and a different
  system prompt** — shared code, with real blast radius. **So T2 carries the same assertion T5a/T5b/T5c
  carry: every `passes`-bucket prompt is byte-identical before and after, asserted by test.** With that
  test green the ticket is safe in the pre-Run-A window; without it, it is not.
- **⚠️ Acceptance — and an honest limit.** Violations findings carry code-assembled SC and conformance;
  the `passes` byte-identity test passes; **no per-class κ moves**, checked rather than assumed. But
  note what is *not* claimed: with no violations-bucket gold, this ticket **ships unmeasured**. Its
  benefit is mechanical (a decision the model should never have been making is removed), not
  demonstrated. Say so; do not let "narrows hallucination surface" read as a measured result.
- **Depends on:** T0

### T3 — Report: write-all-in + per-row trust label *(pre-Run-A)*
- **Produces:** every non-withheld finding in the report, each row carrying a verification-state label.
- **Detail:** write-all-in is already as-built (`run.py` appends every assembled `DraftRow`; only
  HITL-gated PENDING/REJECTED are withheld) — confirm and document rather than re-implement. Add the
  per-row label derived from **verification state**: `oracle-verified` / `drafter-judged, unverified` /
  `human-reviewed`. Inputs exist: **`CitationVerdict`** (VERIFIED / HALLUCINATED / UNVERIFIABLE — the
  enum is `CitationVerdict`, not `CitationStatus`) and `ReviewStatus` (PENDING / APPROVED / EDITED /
  REJECTED).
- **Safe before Run A:** report-layer only, strictly downstream of the drafter. It does not touch
  `_user_prompt`, and the offline acceptance pipeline does not render a report at all — zero
  intersection with the experiment.
- **⚠️ Acceptance:** the label derives from verification state and **never from confidence**, asserted
  by test. A `supports` verdict — the least-trustworthy row, a "no problem" claim on exactly the
  classes whose referent is weakest — must never render as a hard pass.
- **Depends on:** T0

### T4 — Referent extraction in the scanner *(the foundation)*
- **Produces:** deterministic per-node referent material, captured during the scan, carried into
  `Finding`.
- **Detail:** extraction happens **inside the live page session, before `browser.close()`** — after the
  scan the DOM is gone and re-fetching would break the freeze. It is **deterministic code, never an
  LLM step**. Fields ride `AxeNode` → `Finding`; both are `extra="forbid"`, so this is a **CONTRACTS §3
  change** — apply the schema-edit rule and update §5/§6 in the same change. New fields
  Optional-with-default so existing persisted artifacts still load.
- **⚠️ It must be its own `page.evaluate`, after `axe.run()` returns.** Sequence: `axe.run()` →
  collect node targets from its result → a second `evaluate` that re-queries those targets and
  extracts. *Measured behaviour, stated precisely:* `axe.setup()` **after `axe.run()` has completed
  does not throw**; what throws is `axe.setup()` **re-entry** while a tree is already set up. Guard
  with `try { axe.teardown() } catch {}` before `axe.setup()` so a partial prior state cannot wedge the
  scan, and always `teardown()` after.
- **⚠️ Acceptance — design for real pages, not for the fixtures.** ACT rendered bodies run **2–220
  characters** (verified), so "dump the whole body" would score perfectly here and be useless on a
  50,000-character page. Every extractor must be **structured and bounded** — a named source, a pinned
  character budget, a deterministic truncation rule — and must be reviewed against a **named real
  page, with the extracted output committed as a fixture** so the review is auditable rather than
  attested. Fitting extraction to the fixtures is the M5 overfitting lesson relocated into the input
  pipeline.
- **⚠️ Acceptance — `Finding.id` unchanged.** It hashes `(source_url, rule_id, target)`; referent
  fields must not enter it, or the verdict vector cannot be paired. Extraction is deterministic across
  repeat scans.
- **Depends on:** T0

### T5a — `label` → resolved accessible name **+ bounded section context** *(degeneracy)*
- **Produces:** the accname, and the nearest section heading, in the `label` prompt.
- **Detail:** **use axe's own computation, do not reimplement ARIA name resolution.** The verified
  entry point is `axe.setup(); axe.commons.text.accessibleText(el); axe.teardown();` — a raw element
  *without* `axe.setup()` throws `TypeError: … reading 'props'`, and a virtual node passed to
  `accessibleText` also throws; `accessibleTextVirtual(vnode)` is the vnode-shaped alternative. Pin the
  choice with its reason.
  **The accname is a near-perfect referent here** (verified over all 11 cases): the class shows
  **6 distinct prompts for 11 cases**, with one 4-case group and one 3-case group each spanning *both*
  gold values. Injecting the accname splits them cleanly — every `First name:` case is gold-passed,
  every `Menu` case is gold-failed.
- **⚠️ The accname alone cannot certify this class — the decisive case is named, do not discover it in
  the run.** `e419548ab0` (gold **passed**, accnames `Name, Street, Name, Street`) sits against
  `5d11716ba4` (gold **failed**, accnames `Name:, Street:, Name:, Street:`). **The referents differ by
  a trailing colon.** Accname-only injection either leaves `e419548ab0` unfixed (4 of 5) or fixes it by
  breaking `5d11716ba4` (5 fixed, 1 broken); neither certifies per class.
  What plausibly separates them is the **section context** — `e419548ab0` carries visible
  `<h2>Shipping</h2>` / `<h2>Billing</h2>`; `5d11716ba4`'s headings sit off-screen inside `<fieldset>`.
  So the referent is **accname + nearest section heading, bounded and pinned**, recording whether the
  heading was in the accessibility tree. **Whether that actually separates the pair is unverified** —
  it is the ticket's main risk and is listed as such in the ledger.
- **⚠️ `e419548ab0` needs all four of its findings to flip** under flag-if-any (verified). One
  conjunctive event, not one case.
- **Acceptance:** the resolved accname appears **verbatim** in every `label` prompt; it matches axe's
  computation on the `aria-hidden` (`88a1646138` → `First name:`) and `display:none`
  (`925f5da929` → `Go Search`) cases specifically — an extractor that skips hidden referenced elements
  breaks a currently-correct case and forfeits the class; injection appears **only** in `label`
  prompts; every other class byte-identical, asserted by test. *(Distinct prompts should rise 6 → ≥ 8;
  reported, not gating — see T6.)*
- **Prerequisite:** the `label` dev fixtures do not exist. **Build them as their own reviewable
  commit** with stated gold and a labelling rationale — gold construction is the activity M5 proved
  most dangerous, and it does not belong buried inside a prompt ticket.
- **Depends on:** T4

### T5b — `document-title` → **resolved title** + page-topic signal *(degeneracy)*
- **Produces:** the resolved `document.title` **and** a page-topic signal in the prompt.
- **⚠️ Detail — the primary referent is the title, which the drafter has never seen.** For all five
  cases the prompt is `Target: html` / `HTML: <html lang="en">` — the title is not in it (verified).
  The class produces **one distinct prompt for five cases**, which is why `constant_classifier` is
  `true`: at `temperature=0.0` an identical prompt *must* yield an identical verdict.
- **⚠️ A topic signal alone cannot work, and would pass a naively-written acceptance test.** All five
  fixtures share the identical **rendered** body text ("Clementines will be ready to harvest from late
  October through February."). Inject only the body and the prompts stay degenerate while a criterion
  phrased as *"a non-empty topic signal is produced"* reports green. **Inject the resolved title
  first**; the topic signal is what it is compared *against*.
- **⚠️ The body tier can leak the answer — use rendered text, not `textContent`.** `5e5cb1efed` places
  `<title>Clementine harvesting season</title>` **inside `<body>`** (verified), so a `textContent`
  based tier would place the correct title into that case's "topic signal" and score a fix that never
  happened. Use `innerText`, or strip `<title>` explicitly, and pin the choice.
- **Detail — the topic signal.** The originally-specified source list does not exist here: no `<h1>`,
  no `<main>`, no meta description on any of the five (verified). Use a **fallback tier** — `h1` →
  `main` → `meta[name=description]` → bounded rendered body text — recording the tier used on the
  finding, so a result is never read without knowing which source produced it.
- **Acceptance:** the resolved title appears **verbatim** in every `document-title` prompt; the tier
  used is recorded; the budget and truncation rule are pinned; no prompt contains a title that came
  from the *body-text* tier; injection appears only in `document-title` prompts. *(Distinct prompts
  should rise from 1; the three passed fixtures are three distinct files that coincide only after title
  resolution and only in rendered text, so do not assert a specific target — report the number.)*
- **Note:** even a perfect fix leaves this class at ceiling p = 0.125. It is argued on mechanism.
- **Prerequisite:** the `document-title` dev fixtures do not exist. Build them as their own commit.
- **Depends on:** T4

### T5c — `link-name` → surrounding context + accname *(insufficiency, not degeneracy)*
- **Produces:** bounded surrounding context, and the resolved accname where that is the gap.
- **⚠️ Detail — this class is NOT degenerate, and its acceptance must not pretend otherwise.**
  Post-T0 `link-name` has **13 distinct prompts over 13 minting cases — already maximal** (verified;
  all seven duplicate groups in the pooled class were cross-rule and one member of each leaves with the
  excluded rule). Every case already gets its own prompt; none contains the deciding fact. **So
  "distinct prompts must rise" is unsatisfiable here and is not an acceptance criterion.** The test is
  that the referent is *present*, not that prompts *split*.
- **Detail:** the context is present and discriminating — link text "HTML" / "EPUB" / "Plain text"
  against a `<th colspan="3">Ulysses</th>`, or against the parent cell's "Download Ulysses in …".
  **Pin the extent** — ancestor depth and character budget — in code with the rationale recorded; an
  unpinned window is an unreproducible input. The prompt must be **honest that the destination is
  unavailable**, so the model is not invited to invent one.
- **⚠️ One of the five reachable errors is an accname gap, not a context gap.** `1ba642803c` is
  `<a href="#main" aria-labelledby="instructions">` — no link text at all; the referent is the resolved
  accessible name ("Go to the main content."). *(Its byte-identical twin `515a82f230` belongs to the
  excluded rule and is no longer scored — an earlier draft said "2 of 5" from the pooled frame; it is
  one.)* An earlier draft also forbade reusing T5a's fix here; that instruction blocked the correct
  referent and is withdrawn. **Match the referent to the gap:** accname where the name is computed
  elsewhere, context where the name is present but ambiguous.
- **⚠️ One reachable error is predicted to resist, and it is named.** `3bb1986371` — link text
  "Workshop", gold **failed**, over a paragraph describing a W3C workshop. The gold turns on the
  *destination* being the workshop **report**, outside the DOM. Injected context makes "Workshop" look
  **more** justified, so this case may move the wrong way. It stays **inside** the reachable count; if
  the class lands at 4 of 5, report that the prediction held — as a failure, not a forecast.
- **Acceptance:** the extracted context (and accname where applicable) appears **verbatim** in every
  `link-name` prompt; extent pinned and documented; injection appears only in `link-name` prompts;
  every other class byte-identical.
- **Depends on:** T4, T0

> **Prompt-iteration discipline for T5a–T5c.** One class each, because prompt wording needs **several
> passes** and long prompts degrade: state the referent as one short labelled block, not prose woven
> into the existing text, and keep injected material inside its pinned budget. **Iterate on the dev
> set**, never on the ACT set. Record prompt length before and after. If a class needs more than a
> handful of passes, split the wording problem rather than growing the prompt.

### T6 — Run A + the pre-registered tests *(the experiment)*
- **Produces:** a frozen Run A, its verdict vector, the pooled thesis result, and per-class results.
- **⚠️ Detail — the dry gate runs first, and it is entirely offline.** Before the model is called
  once, assert: (1) **the named referent string appears verbatim** in every prompt of each fixed class;
  (2) the **control's prompt is byte-identical** to the T0 baseline; (3) the **five-field environment**
  matches; (4) the **case count is 44**. Each is seconds of computation against a cost of hours. **A
  run started with the dry gate red is a wasted run.**
- **⚠️ The gate is gold-free by construction, and that is deliberate.** An earlier draft asserted *"no
  two cases with opposite gold share a prompt"* — a condition computed **from held-out labels**, which
  turns the gate into a gold-supervised design loop that nothing counts. Distinct-prompt counts and
  any gold-referencing comparison are **reported after the run, never used to decide whether to run**.
- **Detail:** run the acceptance set with referent injection and nothing else changed. Freeze as
  M5/M6 do. Compute discordant pairs against the T0 baseline keyed by `act_testcase_id`; evaluate the
  **pooled** one-sided sign test (primary) and the **per-class** tests (secondary) at α = 0.05 against
  the reachable ceilings. Recompute κ, CI and 2×2 for the record — certification is the paired test,
  not CI overlap, which M6 established is simultaneously unpassable and vacuous at these n. Verify
  determinism (three passes, per-class agreement asserted). Tier B (n = 2 noisy-page smoke test) is
  re-run for completeness but is **not** a certification input.
- **⚠️ Operational: a single unparseable draft aborts the whole run.** `offline_build._draft_checked`
  raises on a fallback draft (verified) — deliberately, since a `does_not_support`@0.0 row would score
  as a phantom flag. M7 lengthens every prompt, which is what raises off-schema drift.
  `benchmark/run.partial.json` checkpoints after every case and its presence means *resume*, so an
  abort costs the remaining cases, not the run. If a fallback fires, **fix the prompt and restart — do
  not relax the guard.**
- **Acceptance:** the dry gate is green **before** Run A; the five controls hold; the pooled result
  and per-class verdicts stated against the pre-committed definitions; distinct prompts before/after
  reported per class; `document-title` never reported as certified; held-out model-run count recorded.
- **Depends on:** T5a, T5b, T5c

### T7 — SC normative text + citation budget *(post-Run-A — the only prompt change in Run B)*
- **Produces:** grounded `cited_sc_ids`.
- **Detail:** **the normative text is already retrieved and then discarded.** `CorpusChunk` carries
  `text`, but `Citation` — what the drafter receives — carries only `sc_id`, `title`, `level`,
  `source`, `url`, `technique_id`. So this is *stop dropping it at the boundary*, not *go and find it*:
  extend `Citation` (a CONTRACTS §3 change, `extra="forbid"`) and pass the text through. Add a
  **citation budget** ("cite the single most applicable"). **This is the same class of fix as the
  referent work** — information already inside the pipeline that never reaches the model — which is
  why it is worth doing and why it lands after the experiment rather than inside it.
- **⚠️ It is the only Run B change that touches a prompt, and that is load-bearing.** T8 is
  report-layer and T9 only *scores* existing text, so any regression Run B shows is attributable to
  **T7** without ambiguity. **Do not add a second prompt-touching ticket to this run** — that is
  precisely the contradiction an earlier draft carried, and it is why abstention is dropped.
- **⚠️ Acceptance — and its honest limit.** Citation hallucination rate does not rise; per-class
  verdicts re-measured against Run A so any regression is attributed here. But state plainly: at n=44,
  one run, with no noise floor for this metric, *"does not rise"* is a weak instrument. Watch prompt
  length — this is the change most likely to bloat it, and long prompts degrade.
- **Depends on:** T6

### T8 — Derived confidence signal *(post-Run-A)*
- **Produces:** a trust input that is not the model's self-report.
- **Detail:** derive from the **per-class trust prior** (`FINDING_CLASS_TRUST`: RELIABLE / WEAK /
  UNMEASURED). **⚠️ Sampling agreement is dropped.** The drafter runs at `temperature=0.0`, so repeated
  sampling returns an identical draft and agreement is trivially 1.0 — no signal. Obtaining one would
  require raising the temperature, destroying the determinism the paired test, the frozen baseline and
  the three-pass agreement check all rest on. Revisit separately, with its own noise floor, never as a
  side effect here. The self-reported number is **retained only as an ECE receipt** — internal, never
  client-facing; standard VPAT/ACR columns are Criteria / Conformance Level / Remarks, with no
  confidence column.
- **⚠️ This must follow Run A, not merely tolerate following it.** `FINDING_CLASS_TRUST`'s tiers are
  the thing M7 is trying to change: if injection works, `document-title` is no longer WEAK. Deriving a
  trust signal from the tiers *before* the run bakes in stale priors. **Refresh the tiers from the
  corrected baseline and Run A as part of this ticket**, and record that the refresh is itself a
  behavioural change with its own consumers.
- **Acceptance:** no consumer reads self-reported confidence as a trust signal; the ECE receipt still
  computes; `FINDING_CLASS_TRUST` remains the single source of truth for tiers and reflects Run A.
- **Depends on:** T6

### T9 — `remediation_technique_match` (Fix-Direction Match) *(post-Run-A)*
- **Produces:** the first measurement of remediation quality this project has ever taken.
- **⚠️ Why this is not the low-value ticket an earlier draft called it.** Its *statistical* yield is
  genuinely small — 16 scoreable cases against two rule-level gold labels. But the axis that matters
  here is different: **remediation is the product's actual value proposition ("here is how to fix
  it"), and it is currently measured by nothing at all.** `remediation_technique_match` is `null`, and
  the repo's own methodology review already recorded that as a shipped-metric gap with no exemption.
  Low yield and low importance are different things; this is the former, not the latter.
- **⚠️ And here is its limit, so it is not over-read.** It scores **direction, not usefulness**. It
  gives a *floor* — "the drafted fix at least points at the right technique" — and a regression guard.
  It does not establish that any fix is good. Whether a fix is *useful* still needs a human expert and
  remains unmeasured.
- **Detail:** reverse-inference — infer the technique the drafted fix implies, then check it against
  ACT's canonical technique codes. The technique metadata is already in the vendored export
  (`wcag-technique` namespace, 42 keys). The real constraint is **coverage**: only `label` (G131) and
  `document-title` (G88/H25) carry technique requirements; `link-name` and `empty-heading` carry none.
  Classification uses a **different model from the drafter**, scored **deterministically against ACT
  gold** — classification, not LLM-as-judge. **Confirm that second model is available locally at
  acceptable cost before starting** (CLAUDE.md: ask before adding a dependency).
- **⚠️ Acceptance:** scored **chance-corrected**, never as a raw match rate. Technique gold is
  *rule-level* — all eleven `label` cases share gold G131 — so a constant classifier scores 100% on raw
  match. That is exactly the failure κ was built to catch, and repeating it here would have the
  milestone contradict its own method. Coverage reported as 2 of 4 classes, explicitly. Scored against
  the remediation text produced by the **final** prompt, i.e. Run B's drafts.
- **Depends on:** T6, T2

### T10 — Run B + frozen scorecard + honest read *(deliverable)*
- **Produces:** the frozen post-M7 state and its written analysis.
- **Detail — Run B.** A second full pass, needed because T9 must score remediation text produced by the
  final prompt and because T7's effect on the acceptance set has to be measured rather than assumed.
  It carries **exactly one prompt-touching change (T7)**, so its verdict is attributable. If Run B
  regresses a class Run A improved, **T7 is rolled back or made class-conditional** — the referent fix
  is the milestone's core value and a grounding tweak does not get to consume it.
- **Detail:** freeze both runs with full provenance and a verdict vector M8 can pair against. Report:
  the **pooled thesis result** first; then per class κ (both readings), CI, 2×2, distinct prompts
  before/after, discordant pairs vs the T0 baseline, the per-class verdict, FP and recall. State
  without softening: whether the thesis was supported; that per-class certification was zero-margin by
  construction, so a near-miss is a near-miss and not a failed fix; that `document-title` cannot be
  certified at any fix quality and what its mechanism change shows instead; which reachable errors
  moved; **the two pre-registered predictions scored** — including where one was wrong; whether the
  control held; and the **total held-out model-run count**.
- **⚠️ Report the exclusions and what they bought.** T0 removed nine cases, converted one
  previously-unwinnable error into a win, and hid one predictable regression. All three go in the read.
  An exclusion invisible in the write-up is indistinguishable from a silent cap. **Also report that the
  spec was authored with sight of the decisive held-out cases.**
- **Rule: the referent thesis is reported as the evidence found it.** A clean falsification — injection
  landed, referents verifiably present, control held, classes did not move — is the milestone's most
  valuable possible output and is reported as a result, not a setback.
- **Depends on:** T7, T8, T9

---

## Dropped

### Abstention channel *(dropped, not deferred — carried no ticket number)*

An explicit "cannot assess" path instead of a forced verdict. **Dropped from the roadmap**, for two
independent reasons — the second of which is new evidence from this milestone. It is recorded here
rather than deleted so the decision is auditable and does not get re-proposed from scratch.

> **M8 is scoped to MultiModal + Referent and nothing else.** Abstention is not waiting there.

**1. It would break Run B's attribution.** It touches every prompt, as T7 does. Two prompt-touching
changes in one run make a regression unattributable — the contradiction an earlier draft of this spec
carried, by its own argument that *re-running cannot separate the causes afterwards*. Adding it to
Run B would cost either the attribution or a third run.

**2. ⚠️ The measurement says the channel already exists and is never used.** The system prompt already
offers `not_applicable` as one of exactly four permitted values (`drafter/llm.py`), and across all 63
findings of the frozen run the drafter chose it **zero times** — `abstained_n = 0`, verified.
`does_not_support` 38 · `supports` 18 · `partially_supports` 7 · `not_applicable` **0**. So it does not
add an escape hatch; it makes an existing, unused one louder. For that to help, the drafter would have
to *know* it cannot assess and merely lack a way to say so — but its metacognition is measurably
broken (self-reported confidence ECE 0.392, single populated bin, pinned ~0.85–1.0 regardless of
correctness), and this milestone shows why: given five byte-identical prompts it answers confidently
five times. **It does not experience a missing referent. It sees an input and answers.**

**The right sequence is therefore referent first, abstention after.** Once the referent is present,
whatever the drafter still cannot decide is genuinely undecidable, and an abstention channel has
something real to catch. Before that, abstention would mostly lower FP by lowering judgment — the
"manufactured success" this spec warns about.

**Carried forward unchanged when it lands:** the pinned collapse (abstention = CLEAN, matching the
existing `not_applicable` convention reported as `abstained_n`), coverage per class as a first-class
number, and FP reportable **only** jointly with recall and coverage. Note that the coverage half needs
no prompt change at all and can be reported today; the answer is currently 0.

---

## Evidence ledger

**Verified — read or computed from the repo, and independently re-derived by a second reviewer.**

*Frozen M6 baseline* (`drafter_kappa_baseline.json`): `link-name` n=24 (11/13) 7·5·4·8 κ 0.250 (alt
0.408) CI [−0.159, 0.600] errors 9 p 0.001953125; `label` n=11 (5/6) 4·4·1·2 κ 0.126984
CI [−0.375, 0.633] errors 5 p 0.03125; `document-title` n=5 (2/3) 2·3·0·0 κ 0.000 CI [0,0]
degenerate share 1.00 `constant_classifier: true` errors 3 p 0.125; `empty-heading` n=13 (5/8) 4·1·1·7
κ 0.675 CI [0.156, 1.000] errors 2 p 0.25. α 0.05, seed 0, 10000 resamples. Provenance: gemma4:31b
digest `6316f062…`, axe 4.12.1, ACT export `a805d865…`, config m1-single@1, corpus
wcag22-nomic-embed-text-768@1; 53 cases keyed by `act_testcase_id`. Post-T0: **44** (40 minting + 4
misses).

*Sign-test arithmetic* (exact rationals): bar is **b ≥ 5 with c = 0**. b=5,c=0 → 1/32 = 0.03125 ✅ ·
b=4,c=0 → 1/16 = 0.0625 ❌ · b=5,c=1 → 7/64 = 0.109375 ❌ · b=6,c=1 → 1/16 = 0.0625 ❌ ·
b=7,c=1 → 9/256 = 0.035156 ✅ · b=8,c=1 → 0.0195 ✅ · b=9,c=2 → 0.0327 ✅ · b=8,c=2 → 0.0547 ❌.

*Prompt structure — assembled `_user_prompt` hashed over every minting case.* `document-title`
**1 / 5**, spanning both gold values; `label` **6 / 11** with a 4-case group (2 passed + 2 failed) and
a 3-case group (2 passed + 1 failed); `link-name` 13 / 20 pooled, **13 / 13 post-T0 — maximal, no
headroom** (all 7 duplicate groups were cross-rule); `empty-heading` 9 / 11. Method precondition
verified: every ACT gold finding is `source_bucket=passes`, so `Finding.help` is
`QUALITY_REVIEW_RULES[rule_id]`, and `rag._query_text` = `f"{rule_id} {help}"` yields **exactly one
distinct query text per class** — so a constant citation block preserves the within-class partition.

*What the drafter receives.* `document-title`: `target='html'`, `html='<html lang="en">'`; no `<title>`
string from any of the five files appears in its prompt. `label`: the bare `<input>` (the
`id="fname"` form covers 4 of 11; the rest carry `aria-labelledby` or `#shipping-*`/`#billing-*`
targets). Resolved accnames: `First name:` ×4 (all gold-passed), `Menu` ×3 (all gold-failed),
`Shipping Name` (`467ca5a8f0`), `Go Search` (`925f5da929`), `Name/Street` ×4 (`e419548ab0`, gold
**passed**), `Name:/Street:` ×4 (`5d11716ba4`, gold **failed**).

*Unreachable and excluded.* Honest misses mint zero findings, so the drafter is never invoked:
`link-name` `4301e64721` + `75db8879bf`, `empty-heading` `c3ed1f47a089` — all gold-failed, hence
errors. Contradictory gold on byte-identical files (sha256 over file bytes; 53 files → 44 distinct, 9
duplicate pairs, exactly **2 pairs / 4 files** with opposite outcomes): `73a8392cf8cb` =
`48cbc84f4c` **failed** (currently correct) / `6566c139dc` **passed** (currently an error);
`c88b25d63bd2` = `1c577f9a13` **failed** (error) / `5e67cab9c6` **passed** (correct). Scoped:
*Link in context is descriptive* n=15, 6 errors, 1 honest-miss error → **5 reachable**;
*Link is descriptive* n=9, 3 errors, 1 honest-miss error → 2 reachable. Conformance levels:
*Link is descriptive* → `wcag20:2.4.9` **only (AAA)**; *Link in context is descriptive* →
`wcag20:2.4.4` **(A)** + `wcag20:2.4.9`.

*Scoring rules the arithmetic depends on.* `drafter_score._flagged` is flag-if-any over a case's
drafts, and a drafts-less case never flags — so a multi-finding FP needs **all** its findings to flip
(`e419548ab0` 4, `970cf7f07c` 3, `95f35d6374` 2). `offline_build._draft_checked` **raises and aborts
the run** on a fallback draft; `run.partial.json` checkpoints per case and means resume.
`drafter_score._rules` already applies a clustering-honest effective-n to recall / FP / SC-match — the
κ ceiling does not, which is the gap the reachable ledger closes. Re-deriving the verdict vector from
`run_1.json` with flag-if-any reproduces all 53 cases with **0 mismatches**.

*Code surface.* `CorpusChunk` has `text`; `Citation` does not. Scanner is Playwright + Chromium,
`scan()` calls `page.evaluate` twice, and the acceptance run **re-scans live**
(`act_gold._minting_findings`), so scanner-side extraction reaches the drafter. Vendored `axe.min.js`
4.12.1 exposes `axe.commons` (`aria, color, dom, forms, matches, math, standards, table, text, utils`);
`accessibleText(el)` throws without `axe.setup()` and throws on a vnode; `accessibleTextVirtual(vnode)`
works; `axe.setup()` **re-entry** throws, but `axe.setup()` **after `axe.run()` completes does not**.
`llm/local.py` sets `temperature=0.0`. `AxeNode`/`Finding` are `extra="forbid"`; `Finding.id` hashes
`(source_url, rule_id, target)`. `tag_to_sc_ids` in `oracle/axe.py`. `FINDING_CLASS_TRUST`,
`ReviewStatus` exist; the citation enum is **`CitationVerdict`** (zero occurrences of
`CitationStatus`). `abstained_n` counts `not_applicable`. `remediation_technique_match` is `None`
(zero occurrences of `remediation_direction_match`). `run.py` appends every assembled `DraftRow`. No
code identifier named `whitelist` remains; **21 files** carry it in prose or fixture content. ACT
export carries 42 `wcag-technique` keys, covering only `label` (G131) and `document-title` (G88, H25).
**Dev set: `image-alt` ×9, `link-name` ×9, `frame-title` ×9 — no `label`, no `document-title`.** ACT
rendered bodies span **2–220 characters** (`innerText`; raw `textContent` 5–247).

**Inference — reasoned, not directly observed.** Per-class injection is disjoint by class, so the run
preserves per-class attribution — this follows from branching on finding class, and the byte-identity
test makes it checkable. Prompt changes cannot alter the case set because minting is the normalizer's
function. Pooling `link-name` + `label` for the primary endpoint is justified by the hypothesis being
about referent presence rather than about a class; it is a different operation from M6's pooling, which
estimated one class's effect and required a shared fix. Rule-level technique gold makes a constant
classifier score perfectly on raw match: arithmetic, though the severity of the trap is judgement.

*On the two named predictions.* Both are **argued**, not arithmetic. For `e419548ab0`/`5d11716ba4` the
*consequence* is arithmetic (4 of 5 → 0.0625; 5 fixed with 1 broken → 0.109) but the *antecedent* —
"any drafter that accepts `Name` accepts `Name:`" — is a normative claim about what a correct drafter
should do, worn as a description of what this one will do. Models distinguish on a trailing colon
routinely. For `3bb1986371` the argument is that its gold turns on a destination outside the DOM and
the surrounding paragraph *supports* the link text. Both are named so results can be read against a
stated expectation instead of rationalised afterwards.

*On excluding* Link is descriptive. The AAA-only conformance ground is factual and outcome-independent.
The additional observation — that a one-`Finding`-per-element pipeline cannot represent contradictory
per-rule gold — is sound but is **not** the same kind of impossibility as the existing
`EXCLUDED_RULES` entries, each of which holds for a rule in isolation; this one dissolves under a
different groupby key. It is recorded as a consequence, not as the rationale.

**Unverified — settle in the Plan phase.** **Whether recording accessibility-tree visibility of the
`label` section heading actually separates `e419548ab0` from `5d11716ba4`, or whether that pair is
uncertifiable by any DOM-reachable referent — this is T5a's principal risk.** Whether determinism
survives the longer prompt (note that much previously-observed agreement was guaranteed by degeneracy,
so this check begins testing something new only as injection lands). The right extent for the
`link-name` context window and the `label` section-heading window, and whether either interacts with
the model's context limit. Whether the guarded `setup`/`teardown` extraction composes cleanly across
all 44 fixtures at scan time, not only in a single-page probe. Which tier the `document-title`
extractor should prefer when several sources exist and disagree — untestable on these fixtures, since
none carries `h1`, `main` or a meta description. Whether `FINDING_CLASS_TRUST`'s tiers should be
refreshed from the corrected baseline, and whether that refresh is itself a behavioural change
requiring its own measurement.
