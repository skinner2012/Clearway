# Clearway fixtures — eval corpus

> **Looking to run or demo the pipeline over these pages?** The walkthrough (every command, end to
> end) is in the top-level [README](../../README.md#running-the-pipeline). This document describes
> the fixture **corpus itself** — what each page plants and why.

A **fixed, versioned** set of HTML pages with **deliberately planted** accessibility signals. This is the ground truth the scanner (T2/T4), oracle (T6), and eval (T8) are measured against. Random/live pages are never used for eval (ARCHITECTURE §4.2) — reproducibility requires a frozen corpus.

Two eval sets, one machine-readable manifest each:

- **`m0-core@1`** → [`expected_m0.json`](expected_m0.json) — the M0 verifiable violations (frozen regression anchor).
- **`m1-core@1`** → [`expected_m1.json`](expected_m1.json) — the M0 page **plus** two *needs-review* fixtures that populate the unverifiable bucket.

`tests/test_fixtures.py` guards that these planted signals stay present and that each manifest stays in sync with its pages.

> **Status of the mappings.** All `axe rule → WCAG SC → tag → target → impact` values below are **confirmed** against the pinned axe-core 4.12.1 (violations at T2; needs-review items at T4).

## `m0-core@1` — verifiable violations

### `pages/home.html`

Produces **exactly 3** violations under default axe-core — no more. `<title>`, an `<h1>`, and a `<main>` landmark are present so axe does not raise incidental `region` or `bypass` findings.

> **Note — judgment findings.** The `<title>` and `<h1>` also land in axe's `passes[]`, and the quality-review rule set (`QUALITY_REVIEW_RULES`) now surfaces `document-title` / `empty-heading` as **judgment** findings — and it is global, so this applies to every page. So the pipeline mints 3 violations **+ 2 judgment findings = 5** on this page (and 2 extra on every fixture with a heading/title). Those judgment items carry no oracle here and are measured against W3C ACT gold in the acceptance benchmark, not in these violation/incomplete sets — so this manifest (which tracks only violations) is unchanged.

| # | Planted defect | axe rule | WCAG SC (level) | axe tag | target | impact |
|---|---|---|---|---|---|---|
| 1 | `<img>` with no `alt` | `image-alt` | 1.1.1 (A) | `wcag111` | `img` | critical |
| 2 | `<html>` with no `lang` | `html-has-lang` | 3.1.1 (A) | `wcag311` | `html` | serious |
| 3 | `<input>` with no label | `label` | 4.1.2 (A) | `wcag412` | `#email` | critical |

## `m1-core@1` — + needs-review (unverifiable) fixtures

These land in axe's **`incomplete`** bucket: the rule ran but axe **could not decide**, so ground truth is unknown → the oracle returns `NO_ORACLE` → they score `UNVERIFIABLE` and feed `unverifiable_share` (T7). Each carries a real `wcagNNN` tag yet is **not** a confirmed violation — that distinction is the whole point. Each page is otherwise clean (`<main>`/`<h1>` present) so exactly one needs-review item fires.

### `pages/contrast-gradient.html`

| Planted item | axe rule | WCAG SC (level) | axe tag | target | impact |
|---|---|---|---|---|---|
| text over a background gradient (effective bg colour undeterminable) | `color-contrast` | 1.4.3 (AA) | `wcag143` | `p` | serious |

### `pages/video-no-captions.html`

| Planted item | axe rule | WCAG SC (level) | axe tag | target | impact |
|---|---|---|---|---|---|
| `<video>` with no captions `<track>` | `video-caption` | 1.2.2 (A) | `wcag122` | `video` | critical |

`m1-core@1` also includes `pages/home.html` for the verifiable subset, so one eval run over the set yields both strata.

## `noisy-pages` — ACT snippets embedded in realistic pages

Two hand-built realistic pages ([`noisy-pages/`](noisy-pages/)), each embedding **one ACT judgment snippet verbatim** as the **focal** case, surrounded by nav/heading/aside/footer noise. The label travels with the snippet, so these are scored **exactly like the bare ACT cases** — a deterministic comparison against ACT gold, never the judge. Built + verified by [`clearway/eval/noisy_pages.py`](../eval/noisy_pages.py); manifest [`expected_noisy_pages.json`](noisy-pages/expected_noisy_pages.json); guarded by `tests/test_noisy_pages.py`.

**`n = 2` is a smoke test** — illustrative, *not* a measured rate (no CI attaches to two points); it does **not** enter the headline scorecard. The two pages probe **opposite** harm axes:

| Page | Focal (verbatim ACT) | Outcome | Clean counterpart | Measures |
|---|---|---|---|---|
| `page-a-title.html` | HTML page title is descriptive (SC 2.4.2) | **failed** | `act-gold/…/64ad3868….html` | miss-under-noise (recall) |
| `page-b-label.html` | Form field label is descriptive (SC 2.4.6) | **passed** | `act-gold/…/90d77d3e….html` | cry-wolf-under-noise (FP) |

**Noise is hybrid, and provenance is recorded per element:**

- `act:<id>` — a real ACT *passed* snippet, embedded intact → a **W3C-certified** true negative.
- `self` — trivially-descriptive **authored** chrome (nav links, heading, a descriptive `<title>`) → human-certified as passing, **not** externally certified. An honest limitation, marked in the manifest, never dressed up as W3C gold.

Every noise element is clean by construction, so a finding raised on any of them is a **false positive**. Each page mints **only** `passes[]`-bucket judgment findings (no violations/incompletes) — `noisy_pages.build_manifest()` asserts the live composition matches the declared focal + noise exactly, so an axe-core bump that shifts a selector fails loudly. HTML alone is sufficient: the pipeline is DOM-only, so the light `<style>` is cosmetic (no `display:none`) and there is no JS.

**Methodology is preliminary** (see the M5 spec, realistic-pages tier): the noise-construction method and its limits will be iterated and re-stated in the report.

## Changing a set

Any change to a planted signal is a **version bump**: increment `version` (and `eval_set_id`) in the relevant `expected_m*.json` and here. Downstream eval runs are tagged with the set version, so a bump never silently invalidates past results.
