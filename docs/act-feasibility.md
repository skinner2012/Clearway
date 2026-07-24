# ACT acceptance-gold feasibility

Which W3C ACT rules can actually reach this pipeline, and how large the resulting acceptance set
is. A Clearway `Finding` exists only when axe emits something; judgment items are minted from axe's
`passes[]` bucket for a global set of existence-only rules (`QUALITY_REVIEW_RULES`). So an ACT rule "reaches" the pipeline
only if scanning its example page mints a `passes` judgment `Finding` for the axe rule that carries
its call.

**Method.** Each vendored ACT example (passed + failed) was run through the real `scan → normalize`
with the production quality-review rule set, and we recorded whether — and how many — `passes`
findings minted for the rule's axe rule. Everything here is reproducible from the vendored copy
(`clearway/fixtures/act-gold/`, frozen by `export_sha256 a805d865…`); axe-core is pinned at 4.12.1.

## Reachable set — four scored rules

Five rules surface through axe. Four are **scored**; *Link is descriptive* surfaces but is scoped out on
conformance level (see "Dropped by analysis" below), so it is shown here for completeness and excluded
from the totals.

| ACT rule | WCAG SC | Level | axe rule | passed → mint (TN) | failed → mint (TP) |
|---|---|---|---|---|---|
| Link in context is descriptive | 2.4.4 · 2.4.9 | A | `link-name` | 8 / 9 | 5 / 6 |
| Form field label is descriptive | 2.4.6 | AA | `label` | 6 / 6 | 5 / 5 |
| Heading is descriptive | 2.4.6 | AA | `empty-heading` | 7 / 8 | 4 / 5 |
| HTML page title is descriptive | 2.4.2 | A | `document-title` | 3 / 3 | 2 / 2 |
| **Total (minting = the real set)** | | | | **24 / 26** | **16 / 18** |
| *Link is descriptive (surfaces; scoped out — AAA only)* | *2.4.9* | *AAA* | *`link-name`* | *3 / 4* | *4 / 5* |

**Reachable n = 40 cases (24 true negatives + 16 true positives).** `empty-heading` and
`document-title` were confirmed to PASS on present-but-non-descriptive content (i.e. they mint a
judgment finding rather than a hard violation), so both were added to the rule set. Two rules were
added and the change absorbed as described in "Cost of growing the rule set" below.

### Two denominators — report both

Seven cases mint **more than one** finding for their rule (a page with several links / labels).
Inspecting them, each ACT case is **homogeneous**: every same-type element shares the tested
property (e.g. a failed 3-link page has three links that *all* fail 2.4.9; the passed twin has three
that *all* pass 2.4.4 once context is present). So the page-level gold label applies **uniformly**
to every minted finding, and each case expands to `expected_finding_count` `GoldLabel`s. This yields
two honest denominators:

- **By case: 40** (24 TN + 16 TP) — the ACT unit. With honest misses carried in, the scored set is **44**.
- **By finding: 54** (33 TN + 21 TP) — what actually gets scored.

The multi-mint findings within one case are **not independent** (same rule, same context, one
draft framing), so per-finding `n` overstates power; effective `n` stays ≈ the rule count (4).
Report intervals with that clustering caveat.

## The 4 honest misses (recorded, not dropped)

Four failed/passed cases mint **no** finding — the pipeline never gets to judge them. Both causes are
structural and legitimately outside axe's reach:

- **2 headings** — `<h1 aria-hidden="true">`: removed from the accessibility tree, so `empty-heading`
  correctly never fires.
- **2 "links"** — `<span role="link">` / `<div role="link">`: ARIA pseudo-links, not `<a href>`, so
  axe's `link-name` does not apply.

These are listed in the manifest's `honest_misses` (each with `expected_finding_count: 0`). A failed
case that mints nothing is counted an honest miss, never silently excluded.

## Dropped by analysis — six rules

| Dropped ACT rule(s) | Why it is not scored here |
|---|---|
| Image accessible name is descriptive; Image not in the accessibility tree is decorative | Ground truth is the **content of the image**, which a DOM-only pipeline cannot see. The ACT filename leaks the answer, so we would measure filename-matching, not image-text judgment — it does not transfer to real pages. Needs a multimodal drafter (a future iteration). |
| Links with identical accessible names have equivalent purpose; …and same context… | The ACT outcome is defined over a **set** of links. Clearway mints one independent per-element `Finding` and judges each in isolation, so it structurally cannot represent the cross-element judgment; every failed case would score a systematic miss. |
| Error message describes invalid form field value | **No axe rule** confirms the error message EXISTS, so it never mints a `Finding` — a systematic miss. |
| Link is descriptive | **Conformance level.** It maps to SC 2.4.9 only — **Level AAA** — and every conformance row Clearway drafts is scored against a **Level A/AA** target. Its sibling *Link in context is descriptive* carries the Level A criterion 2.4.4 and stays scored, so the link judgment is narrowed, not dropped. Unlike the rows above this rule *does* reach the pipeline: its 9 cases are vendored and mint normally, and it is excluded by scope rather than by feasibility. |

The first five drops are confirmed by analysis (those rules' HTML is deliberately **not** vendored); the
exclusions and their reasons live in `clearway/eval/act_gold.py` (`EXCLUDED_RULES`) and are guarded by
`tests/test_act_gold.py`. The consequences of the last one — including one error it converts to winnable
and one regression it stops scoring — are recorded in `docs/drafter-kappa-baseline.md` and on the frozen
baseline artifact.

## Cost of growing the rule set

Adding `empty-heading` (SC 2.4.6, a new rule) and `document-title` (SC 2.4.2, a deferral reversal)
to the quality-review rule set mints new judgment findings on every fixture carrying a
heading/title — i.e. all of them, because the set is **global**. That perturbation was absorbed, not hidden:

- `quality-gold@1 → @2`, its per-page bijection scoped to each page's own rule (the two new rules are
  validated against ACT gold, not relabelled here; the M4 κ replays a frozen set and is unchanged).
- The m0/m1 orchestrator/CLI/normalizer finding **counts** were updated; the citation-based
  exit-criterion metrics (`2/3`, `2/5`) are unchanged because the two new rules carry no canned
  citation offline and are measured against ACT gold here, not in the offline stub.
- Recorded in `CONTRACTS.md` §6 (v0.15) and `clearway/normalizer/quality_review.py`.

## Bottom line

The acceptance set is real but **coarse**: 44 cases (54 findings) clustered in four rules, so the
effective sample is closer to the rule count than to 44. That is the true size of the intersection
"DOM-decidable **and** single-element **and** a judgment axe can't make" between ACT and this
architecture — there is no larger honest denominator to recover. It supports a "works / cries wolf"
verdict, not a fine accuracy figure.
