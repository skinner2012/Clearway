# ACT acceptance-gold feasibility

Which W3C ACT rules can actually reach this pipeline, and how large the resulting acceptance set
is. A Clearway `Finding` exists only when axe emits something; judgment items are minted from axe's
`passes[]` bucket for a whitelist of existence-only rules. So an ACT rule "reaches" the pipeline
only if scanning its example page mints a `passes` judgment `Finding` for the axe rule that carries
its call.

**Method.** Each vendored ACT example (passed + failed) was run through the real `scan → normalize`
with the production quality-review whitelist, and we recorded whether — and how many — `passes`
findings minted for the rule's axe rule. Everything here is reproducible from the vendored copy
(`clearway/fixtures/act-gold/`, frozen by `export_sha256 a805d865…`); axe-core is pinned at 4.12.1.

## Reachable set — five rules

| ACT rule | WCAG SC | axe rule | passed → mint (TN) | failed → mint (TP) |
|---|---|---|---|---|
| Link in context is descriptive | 2.4.4 · 2.4.9 | `link-name` | 8 / 9 | 5 / 6 |
| Link is descriptive | 2.4.9 | `link-name` | 3 / 4 | 4 / 5 |
| Form field label is descriptive | 2.4.6 | `label` | 6 / 6 | 5 / 5 |
| Heading is descriptive | 2.4.6 | `empty-heading` | 7 / 8 | 4 / 5 |
| HTML page title is descriptive | 2.4.2 | `document-title` | 3 / 3 | 2 / 2 |
| **Total (minting = the real set)** | | | **27 / 30** | **20 / 23** |

**Reachable n = 47 cases (27 true negatives + 20 true positives).** `empty-heading` and
`document-title` were confirmed to PASS on present-but-non-descriptive content (i.e. they mint a
judgment finding rather than a hard violation), so both were added to the whitelist. Two rules were
added and the change absorbed as described in "Whitelist cost" below.

### Two denominators — report both

Eight cases mint **more than one** finding for their rule (a page with several links / labels).
Inspecting all eight, each ACT case is **homogeneous**: every same-type element shares the tested
property (e.g. a failed 3-link page has three links that *all* fail 2.4.9; the passed twin has three
that *all* pass 2.4.4 once context is present). So the page-level gold label applies **uniformly**
to every minted finding, and each case expands to `expected_finding_count` `GoldLabel`s. This yields
two honest denominators:

- **By case: 47** (27 TN + 20 TP) — the ACT unit.
- **By finding: 63** (36 TN + 27 TP) — what actually gets scored.

The multi-mint findings within one case are **not independent** (same rule, same context, one
draft framing), so per-finding `n` overstates power; effective `n` stays ≈ the rule count (5).
Report intervals with that clustering caveat.

## The 6 honest misses (recorded, not dropped)

Six failed/passed cases mint **no** finding — the pipeline never gets to judge them. Both causes are
structural and legitimately outside axe's reach:

- **2 headings** — `<h1 aria-hidden="true">`: removed from the accessibility tree, so `empty-heading`
  correctly never fires.
- **4 "links"** — `<span role="link">` / `<div role="link">`: ARIA pseudo-links, not `<a href>`, so
  axe's `link-name` does not apply.

These are listed in the manifest's `honest_misses` (each with `expected_finding_count: 0`). A failed
case that mints nothing is counted an honest miss, never silently excluded.

## Dropped by analysis — five rules

| Dropped ACT rule(s) | Why it cannot be scored here |
|---|---|
| Image accessible name is descriptive; Image not in the accessibility tree is decorative | Ground truth is the **content of the image**, which a DOM-only pipeline cannot see. The ACT filename leaks the answer, so we would measure filename-matching, not image-text judgment — it does not transfer to real pages. Needs a multimodal drafter (a future iteration). |
| Links with identical accessible names have equivalent purpose; …and same context… | The ACT outcome is defined over a **set** of links. Clearway mints one independent per-element `Finding` and judges each in isolation, so it structurally cannot represent the cross-element judgment; every failed case would score a systematic miss. |
| Error message describes invalid form field value | **No axe rule** confirms the error message EXISTS, so it never mints a `Finding` — a systematic miss. |

The drops are confirmed by analysis (these rules' HTML is deliberately **not** vendored — only the
five survivors are); the exclusions and their reasons live in `clearway/eval/act_gold.py`
(`EXCLUDED_RULES`) and are guarded by `tests/test_act_gold.py`.

## Whitelist cost

Adding `empty-heading` (SC 2.4.6, a new rule) and `document-title` (SC 2.4.2, a deferral reversal)
to the **global** quality-review whitelist mints new judgment findings on every fixture carrying a
heading/title — i.e. all of them. That perturbation was absorbed, not hidden:

- `quality-gold@1 → @2`, its per-page bijection scoped to each page's own rule (the two new rules are
  validated against ACT gold, not relabelled here; the M4 κ replays a frozen set and is unchanged).
- The m0/m1 orchestrator/CLI/normalizer finding **counts** were updated; the citation-based
  exit-criterion metrics (`2/3`, `2/5`) are unchanged because the two new rules carry no canned
  citation offline and are measured against ACT gold here, not in the offline stub.
- Recorded in `CONTRACTS.md` §6 (v0.15) and `clearway/normalizer/quality_review.py`.

## Bottom line

The acceptance set is real but **coarse**: 47 cases (63 findings) clustered in five rules, so the
effective sample is closer to the rule count than to 47. That is the true size of the intersection
"DOM-decidable **and** single-element **and** a judgment axe can't make" between ACT and this
architecture — there is no larger honest denominator to recover. It supports a "works / cries wolf"
verdict, not a fine accuracy figure.
