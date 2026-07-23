# Clearway — M6: Turn the ruler on the drafter

> **Scope note.** M6 is a **measurement milestone**. It changes no drafter behaviour and fixes no
> finding-class. Its output is an honest baseline plus a statement of what that baseline can and
> cannot prove. Every drafter fix is M7 — *eval before iteration*, so no fix ships on faith.

## Table of Contents

- [Preamble](#preamble)
- [What is measured, and by what](#what-is-measured-and-by-what)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [What is explicitly not measured](#what-is-explicitly-not-measured)
- [Tickets](#tickets)
- [Evidence ledger](#evidence-ledger)

---

## Preamble

M5 scored two subjects against W3C ACT gold. The judge got a confusion matrix and a κ. **The drafter
never got a κ** — only recall, false-positive rate, SC-match and ECE, all pooled across rules.

That gap hides the structural fact M5's analysis uncovered:

> **A constant classifier and a working instrument produce similar-looking recall.**

`document-title` stamps one verdict on all five of its cases. Its recall reads 2/2 — flattering and
fake. Recall cannot separate "judged correctly" from "stamped everything and the stamp happened to
fit." **κ can**: it is chance-corrected, so a rater with no variance scores 0 however the marginals
fall.

M6 answers what M5 cannot: **per finding-class, is the drafter judging or stamping — and will I be
able to tell when M7 changes it?**

**No new mathematics.** `eval/kappa.py` computes Cohen's κ; `eval/stats.py` pins the four-value →
binary collapse. M6 points the existing instrument at a **new subject**. The one new component is the
interval machinery, which the repo has in no form (verified: no bootstrap, resample or κ-interval code
exists in `clearway/`).

M6 also clears two small debts while the measurement layer is open: the dead `low_confidence` gate,
and the offline/online **Evaluation** vocabulary. Both are ride-alongs, specified in their tickets.

---

## What is measured, and by what

> ## ⚠️ Nothing in M6 is scored by an LLM.
> **Every number is a deterministic replay of a checked-in artifact.**

| Role | Identity |
|---|---|
| **ACT gold** | **The only ground truth** — each vendored case's `expected` outcome |
| **Drafter** | **Subject under test** — its `conformance` stream is what κ measures |
| **Judge** | **Absent from every M6 number.** Not a ruler, not a subject, not an input |

**Why the judge appears nowhere.** M5 measured the judge *against* gold rather than using it *as*
gold. M6 goes further and excludes it. A drafter-vs-judge κ would compare two components sharing an
input (the same DOM) and a rubric prior (the same "never `supports`" framing), so their errors
correlate rather than cancel — that number is a **human-routing signal on disagreement**, never a
trust signal and never a scoring instrument.

> **⚠️ Standing constraint.** κ is computed against ACT gold, always. Scoring against the judge
> anywhere is Goodhart's Law: the judge sits at chance (mean κ ≈ 0.005 across M5 runs), so optimising
> against it optimises against noise.

### How the κ streams are constructed

Every element below is already pinned by M5; κ inherits them rather than inventing a second scoring
convention.

| Element | Rule | Source |
|---|---|---|
| **Unit** | One **ACT test case**, not one finding | `drafter_score.py` |
| **Drafter stream** | `FLAG` if **any** finding on the case alarms, else `CLEAN` | `_flagged` (flag-if-any) |
| **Gold stream** | `FLAG` if `expected == "failed"`, else `CLEAN` | ACT `expected` |
| **Collapse** | `FLAGS = {does_not_support, partially_supports}` · `CLEAN = {supports, not_applicable}` | `stats.is_flag` |
| **Honest misses** | Cases minting no finding enter as `CLEAN` | `benchmark._drafted_cases` |

Per case, not per finding: within one ACT case the elements are homogeneous, so counting each finding
would pseudo-replicate and report a falsely tight interval. Honest misses must be carried in or κ
inflates exactly as recall would. κ is reported under **both** readings of `partially_supports`, as
every other M5 rate is.

### ⚠️ Stratify by fix unit, not by ACT rule

The two link rules — *Link is descriptive* and *Link in context is descriptive* — share one missing
referent (the destination lies outside a single-page DOM) and receive **one** M7 fix (feed surrounding
context). The discussion notes already treat them as a single row, "link ×2".

**They are therefore one class here.** The estimand must match the intervention; splitting one fix
across two underpowered samples measures nothing twice. Pooled: n = 24, κ ≈ 0.250.

This is not the pooled κ the discussion notes reject. That warning is against blending *the one
working class* with *the constant classifier* — different referents, different fixes. Pooling on a
shared referent **and** a shared fix is principled; pooling for convenience is not.

**The four M6 classes:** `link ×2` (pooled) · `label` · `document-title` · `empty-heading` (control).

### Sanity anchors *(verified — computed from the checked-in artifacts at spec time)*

Stated **before** implementation so results cannot be tuned to fit:

| Class | n (failed/passed) | Expected κ | Why |
|---|---|---|---|
| **document-title** | 5 (2/3) | **≈ 0.000** | The constant classifier — recall reads 2/2; κ exposes it |
| **empty-heading** | 13 (5/8) | **≈ 0.675** | The control — the one reachable referent; κ must be clearly positive |

**n is per ACT case and includes honest misses** (cases minting no finding, entered as CLEAN): `empty-heading`
13 = 11 drafted + 2, `link ×2` 24 = 20 drafted + 4; `document-title` and `label` mint on every case.
Counting drafted cases only would under-count n and re-inflate κ toward recall — the very failure κ exists to catch.

Secondary: `label` ≈ 0.127, `link ×2` ≈ 0.250. An implementation missing these is wrong — investigate
before proceeding.

### Intervals, and the inferential ceiling

**The drafter is deterministic** (verified: per-class κ is bit-identical across all three frozen runs;
the M5 scorecard records `per_metric_sd = 0.0` with `dominant_source: binomial-sampling`). So the M5
noise floor supplies **no** interval here — it would report zero width, which reads as infinite
precision and is a lie. Intervals come from **resampling cases within a class**: case-level bootstrap,
percentile bounds, pinned seed.

Two mandatory honesty guards:

1. **Report the degenerate-resample share.** When a resample draws one class only, κ is undefined and
   `cohen_kappa` returns `0.0` by convention; unreported, that convention silently drags the lower
   bound toward zero.
2. **⚠️ Flag zero-width intervals as constant classifiers, never as precision.** `document-title`
   yields exactly `[0.000, 0.000]` (verified) — the tightest interval on the scorecard, meaning *no
   variance because no signal*.

**The ceiling.** M5 established a noise floor: no improvement smaller than run-to-run variance is
detectable. M6 establishes the per-class analogue, which binds harder:

> **You cannot detect an improvement the class lacks the statistical room to show.**

Per class, compute the p-value reachable if a future fix corrected *every* current error and
introduced none — the most generous outcome available. **M6 pre-registers a one-sided test**, since
M7's hypothesis is directional (a fix should improve, not merely change). Pre-registering it here,
before any M7 result exists, is what separates it from p-hacking — the same discipline as the
pre-committed `KAPPA_THRESHOLD`.

| Class | n | errors (FP/miss) | one-sided p if all fixed | Certifiable? |
|---|---|---|---|---|
| link ×2 (pooled) | 24 | 9 (5/4) | 0.0020 | **Yes** |
| label | 11 | 5 (4/1) | 0.0312 | **Yes** |
| document-title | 5 | 3 (3/0) | 0.1250 | **No** |
| empty-heading *(control)* | 13 | 2 (1/1) | 0.2500 | n/a — must not move |

Both classes M7 intends to fix are certifiable. `document-title` is not, at any fix quality — a
property of the gold set's size, not of the drafter or of any future fix. Its improvement must be
argued on **mechanism** (constant stamp → discriminating, visible in the frozen verdict vector) and on
its contribution to the pooled FP rate (n = 30, far more power), never on a per-class p-value.

**Bootstrap CI widths are wide and are reported as observed** — `label` `[-0.375, +0.633]`,
`empty-heading` `[+0.156, +1.000]`, `document-title` `[0.000, 0.000]` *(degenerate)*. Wide intervals
honestly stated are the deliverable; narrow ones would be the warning sign.

---

## Goal & exit criterion

Produce a **reproducible, frozen, per-class κ baseline** for the drafter against ACT gold, with
intervals, a pre-registered test, and an explicit statement of what the ruler can and cannot certify —
the reference every M7 claim is measured against.

At 5–24 cases per class this is a **trustworthy diagnostic** (*is this class judging or stamping?*) and
a frozen reference for paired comparison. It is **not** a precise per-class accuracy figure. Its
authority rests on honest method — external gold, deterministic replay, never LLM-scored, degeneracy
disclosed, ceilings stated — not on narrow intervals.

**Exit criterion:**

1. **A per-class κ baseline** — drafter vs **ACT gold**, per case, stratified by **fix unit**, under
   both `partially_supports` readings.
2. **Reproducible from a checked-in artifact** by a pure function, no model invocation. The M5 frozen
   runs suffice as input — no pipeline re-run.
3. **A CI per class** via seeded case-level bootstrap, reported with its degenerate share, with any
   zero-width interval flagged as a constant classifier.
4. **Sanity anchors met** — `document-title` κ ≈ 0, `empty-heading` κ ≈ 0.675.
5. **A pre-registered ceiling table** naming the test (one-sided, α = 0.05) and which classes cannot
   be certified at any fix quality.
6. **A frozen per-case verdict vector** per class, keyed by `act_testcase_id`, so M7 can run a
   **paired** comparison — a κ scalar cannot be paired against.
7. **Internal Evaluation reports the new metrics** (composite hallucination scaffold, ECE as internal
   input, reflection counters) with **no behavioural change**.
8. **`low_confidence` removed** with no regression.
9. **The Evaluation vocabulary adopted** across schema, module and documentation names.

---

## How to use these tickets

**T0** (vocabulary rename) lands first as a standalone mechanical commit, so the κ work's diff stays
clean. **T1** (per-class κ) is the spine; **T2** (intervals), **T3** (ceiling) and **T4** (verdict
vector) each depend on it. **T5** (Evals scaffold) and **T6** (`low_confidence`) depend only on T0 and
are independent of the κ chain. **T7** (frozen baseline + written read) is written last against real
output. Build strictly sequentially — `T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7` — one reviewable ticket
at a time, per the project's build discipline.

---

## What is explicitly not measured

**State these. Do not hide them.**

1. **Any improvement to the drafter.** M6 changes no prompt and no input assembly. Every number
   describes the current, known-unreliable drafter. Mistaking this baseline for a result misreads the
   milestone.
2. **`document-title`'s eventual fix.** Unprovable by significance at n = 5 even under a perfect fix.
   M6 states the limit; it does not solve it. Larger per-class gold is M8 (image cases) and the parked
   real-page transfer gold.
3. **Whether κ transfers to real pages.** The baseline rests entirely on ACT's **synthetic** pages.
   M5's lesson — self-built gold κ ≈ 0.79 collapsing to ≈ 0 on external gold — was a generalisation
   gap caught one level down. **The same gap may exist one level up**, between ACT fixtures and real
   audited pages. Unmeasurable without the parked real-page gold.
4. **The two image rules.** Excluded at M5 (ACT filenames leak the answer to a DOM-only pipeline), so
   they have no κ baseline. Closes at M8.
5. **`remediation` quality.** `remediation_technique_match` stays `null` — ACT technique metadata is
   not vendored (verified). Unmeasured, not zero. M7.
6. **Anything needing a human expert** — whether a fix is *useful*, and whether
   expert-minutes-per-finding has fallen. Unchanged from M5, still the one unproven link in the value
   proposition.
7. **The composite metric's queue side.** Scaffolded, structurally zero until M9. Must read as "not
   yet produced", never as a measured zero.

---

## Tickets

### T0 — Evaluation vocabulary rename *(standalone commit, first)*
- **Produces:** the offline/online rename across schemas, modules and docs. **No behavioural change.**
- **Detail:** `BenchmarkReport` → `OfflineEvalReport`; `AcceptanceScorecard` → `OfflineEvalScorecard`;
  `EvalReport` → `OnlineEvalReport`; `EvalMetrics` → `OnlineEvalMetrics`; `eval/benchmark*.py` →
  `eval/offline*.py`; `eval/report.py` → `eval/online.py`. **Keep the `clearway/eval/` package** — under
  the new vocabulary "eval" *is* the umbrella, so the name becomes more correct and 38 import sites are
  untouched. Sweep `CONTRACTS.md`, `ARCHITECTURE.md`, `DESIGN_NOTE.md`, `README.md` and `specs/` for the
  retired "eval vs benchmark" split. Schema renames touch CONTRACTS §3 — apply the schema-edit rule and
  update §5/§6 in the same change. Artifact-path moves (`benchmark/runs/`, `benchmark/reports/`) are
  optional; if taken, contents stay byte-identical so the frozen baseline still verifies by hash.
- **Acceptance:** full suite passes; no assertion edited except renamed symbols; every number in the
  frozen scorecard unchanged; no CLI rename required (verified — no command carries the term).
- **Depends on:** —

### T1 — Per-class κ over the frozen artifact *(the spine)*
- **Produces:** a pure function mapping a frozen offline-eval run artifact → per-class drafter κ.
- **Detail:** reuse `cohen_kappa` and `is_flag` / `COLLAPSE_RULE` — **new subject, not new math**.
  Build streams per the table above, **stratified by fix unit** (the two link rules pooled into one
  `link ×2` class; record the pooling rationale in code). Report per class: κ, raw agreement, the 2×2
  counts, n, failed/passed split — raw agreement beside κ is mandatory, since κ can be low at high
  agreement when one class dominates. Compute under both `partial_flags` settings. Input is the
  existing frozen artifact; **do not re-run the pipeline**.
- **Acceptance:** `document-title` κ ≈ 0.000 and `empty-heading` κ ≈ 0.675 reproduce from
  `benchmark/runs/run_1.json`; pooled `link ×2` κ ≈ 0.250; all three frozen runs yield identical
  per-class κ; the function is pure — no network, model or clock.
- **Depends on:** T0

### T2 — Bootstrap intervals + degeneracy reporting
- **Produces:** a seeded case-level bootstrap percentile CI per class.
- **Detail:** resample cases with replacement, recompute κ, take 2.5/97.5 percentiles. **Seed pinned
  and recorded** — bounds must be bit-reproducible. Count and report the **degenerate-resample share**
  per class. **A zero-width interval must carry a constant-classifier flag**; `document-title` will
  produce `[0.000, 0.000]`, and if it renders as the tightest number without that flag the ticket is
  not done. Record resample count and that the interval is percentile-bootstrap, **not Wilson** —
  Wilson is the contract for proportions and κ is not one; do not route κ through `metric_ci`.
- **Acceptance:** every class carries κ + CI + degenerate share + resample count + seed; re-running
  reproduces bounds exactly; the `document-title` flag is present and legible.
- **Depends on:** T1

### T3 — Pre-registered ceiling table
- **Produces:** the per-class detectable-improvement ceiling.
- **Detail:** per class, count current errors (FP and miss separately), then compute the **one-sided**
  exact sign-test p-value for a hypothetical fix correcting all of them and introducing none. **The
  one-sided direction and α = 0.05 are pre-registered in this artifact**, before any M7 result exists —
  record that explicitly, since choosing one-sided afterwards would be p-hacking. Mark each class
  certifiable / not, and state plainly that "not certifiable" describes the **gold set's size**, not the
  drafter or any future fix. State the lineage to M5's noise floor so the two read as one yardstick.
- **Acceptance:** the table reproduces the four verified rows; each carries n, error split, p and
  verdict; the pre-registration and the limitation are stated in prose, not only in cells.
- **Depends on:** T1

### T4 — Freeze the per-case verdict vector *(M7's enabler)*
- **Produces:** a committed, versioned per-class verdict vector.
- **Detail:** per class, per case — `act_testcase_id`, drafter `FLAG`/`CLEAN`, gold `FLAG`/`CLEAN`, and
  the underlying `conformance`. Keyed by `act_testcase_id` so a future run pairs case-to-case without
  re-deriving alignment. Carry the provenance the offline report already freezes (config id, eval-set
  id, corpus version, drafter model **digest**, axe-core version, ACT export hash); freeze by content
  hash. **Record the rationale in the artifact:** a κ scalar cannot be paired against, so without this
  vector M7's most sensitive test does not exist.
- **Acceptance:** the vector is committed; a paired comparison against a hypothetical second run is
  demonstrable from it alone; provenance complete.
- **Depends on:** T1

### T5 — Internal Evaluation metric scaffold *(schema + counters only)*
- **Produces:** composite hallucination fields, ECE fixed as an internal input, reflection counters.
- **Detail:** **composite (report ⊕ queue)** — fields spanning shipped and queued findings, closing the
  gap `machine.py` already documents ("a gated hallucination would fall out of
  `citation_hallucination_rate` […] acting on it correctly needs a composite metric"). The **queue side
  stays structurally zero** until M9 routes anything there; document it as scaffold so it never reads as
  a measured zero. **ECE / overconfidence gap** — fix as *internal-only* signals, no new math (the
  offline path computes them already). Settled and not revisited: self-reported confidence is decorative
  (ECE ≈ 0.329, single populated bin), so it stays an internal calibration receipt — standard VPAT/ACR
  columns are Criteria / Conformance Level / Remarks, with **no confidence column**. **Reflection
  counters** — per-finding iteration count and caught-then-repaired count, inert in M6. New fields are
  **Optional-with-default**, since `extra="forbid"` models must still load existing persisted artifacts.
- **Acceptance:** no currently-reported number moves; existing persisted reports still load; each new
  field's docstring names it as scaffold and says which milestone fills it.
- **Depends on:** T0

### T6 — Remove the `low_confidence` gate
- **Produces:** the trigger deleted; precedence reduced to `AXE_INCOMPLETE > UNVERIFIABLE_JUDGMENT`.
- **Detail:** delete the `confidence < 0.5` branch at `machine.py:294`. It goes for two independent
  reasons: it **gates on noise** (confidence is uncorrelated with correctness) and it **never fires**
  (confidence is pinned ~0.9+ against a 0.5 threshold) — so it presents as a safety mechanism while
  doing nothing. Update `tests/test_machine.py` and `tests/test_schemas.py` (the test regression
  surface). `cli.py:92` also maps `"low_confidence"` to a display label — harmless under
  retain-and-deprecate (it simply never fires), but remove it too if the enum member is ever deleted. **Settle the enum question against the repo:** `ReviewReason.LOW_CONFIDENCE` is a
  persisted value, so deleting the member may break deserialisation of stored `NeedsReview` records.
  Default — remove the trigger, retain the member marked deprecated, confirm no live record uses it
  before any later deletion. Record the rationale in the CONTRACTS decision log.
- **Acceptance:** no drafter behaviour changes; no metric moves; review-queue composition unchanged
  (verifiable, since the trigger never fired); stored records still deserialise.
- **Depends on:** T0

### T7 — Frozen κ baseline + honest read *(deliverable)*
- **Produces:** the committed per-class κ baseline artifact and a short written analysis.
- **Detail:** every class — κ (both readings), CI, degenerate share, n, failed/passed split, raw
  agreement, 2×2 counts, ceiling verdict. The written read must state, without softening: that
  `document-title` is a **constant classifier** whose flattering recall is an artifact; that
  `empty-heading` is the **control** and its positive κ is what proves the capability is real; and that
  `document-title` cannot be certified by significance at any fix quality. Ground every claim in the
  artifact — no number that cannot be pointed at.
- **Rule: report ugly numbers as they are.** The unacceptable failure is not a low κ but an
  **untrustworthy** one — computed against the judge, quoted without its degeneracy, or a zero-width
  interval presented as precision.
- **Depends on:** T2, T3, T4

---

## Evidence ledger

**Verified — computed or read from the repo at spec time.** Per-class κ: `document-title` 0.000 ·
`empty-heading` 0.675 · `label` 0.127 · `link ×2` pooled 0.250 (from `benchmark/runs/run_1.json`);
identical across all three frozen runs, so the drafter is deterministic. Bootstrap CIs (10k, seeded):
`label` `[-0.375,+0.633]` · `empty-heading` `[+0.156,+1.000]` · `document-title` `[0.000,0.000]`
degenerate; a perfect fix on `document-title` still yields `[0.000,1.000]`. Ceiling p-values as
tabulated. No κ-CI machinery exists in `clearway/`. `score_drafter` computes recall/FP/SC-match/ECE and
**no κ**; scoring is per case, flag-if-any, honest misses carried as `drafts=()`. `low_confidence` fires
at `machine.py:294`; its test regression surface is `tests/test_machine.py` + `tests/test_schemas.py` (plus
a harmless display-label at `cli.py:92`).
`machine.py:286-293` already documents the missing composite metric. M5 frozen numbers: FP 0.433 ·
recall 0.739 · ECE 0.329 · judge κ 0.137 · drafter `per_metric_sd` 0.0. `remediation_technique_match` is
`null`. `EvalReport` is emitted per-run by the orchestrator measuring gold-free proxy signals — the
online regime. Rename surface (whole-word refs, current tree): `EvalReport` 65 · `EvalMetrics` 66 ·
`BenchmarkReport` 40 · `AcceptanceScorecard` 22; no CLI command carries "benchmark". **The ACT export
holds 1134 cases across 91 rules; 8 carry a *descriptive*/*decorative* name** — 5 used, 2 image (M8), and
*Element marked as decorative is not exposed*, which carries `ruleAccessibilityRequirements: null`, so it
maps to no WCAG SC and cannot produce a `GoldLabel`. (The repo's own feasibility taxonomy flags 10
judgment-adjacent rules in all — the 5 used plus 5 it cannot score; M6's four classes come only from the
5 used.)

**Inference — reasoned, not directly observed.** Per-case (not per-finding) κ is required for
comparability with recall/FP and to avoid pseudo-replication. Pooling the two link rules is justified by
a shared referent *and* a shared M7 fix; the estimand should match the intervention. Percentile
bootstrap beats an analytic κ standard error because asymptotic normality fails at n = 5–24. The
zero-width CI is a **presentation hazard** inferred from the mechanism, not from an observed misreading.
The "has non-empty accessible name" ACT family (60+ cases) is **unusable, not overlooked**: those rules
ask whether a name *exists* while the drafter judges whether it is *good*, so ACT would mark
`<a>click here</a>` as passed while a correct drafter flags it — a construct mismatch that would
contaminate the baseline, not enlarge it. `EvalReport` maps to the online regime — grounded in what it
measures, though today it runs on fixtures. Removing `low_confidence` is operationally a no-op.

**Unverified — settle in the Plan phase.** Whether `ReviewReason.LOW_CONFIDENCE` can be deleted outright
or must be retained-and-deprecated for stored-record compatibility: no checked-in artifact serialises it
(grep of every `*.json`/`*.jsonl` is clean), so the only exposure is a live/external `NeedsReview` store,
still unchecked — default to retain-and-deprecate.

**Resolved during validation (no longer open).** The ceiling is **robust** to `partial_flags=False`: only
`link ×2` moves (errors 9→7, κ 0.250→0.408, p 0.0020→0.0078) and **no certifiability verdict flips**. No
checked-in fixture serialises the current type names, so the T0 rename cannot break stored-artifact
deserialisation. Artifact directories stay in place and the rename spellings are locked to the T0 table
(both decided).
