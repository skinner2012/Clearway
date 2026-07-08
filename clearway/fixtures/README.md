# Clearway fixtures — eval corpus

A **fixed, versioned** set of HTML pages with **deliberately planted** accessibility signals. This is the ground truth the scanner (T2/T4), oracle (T6), and eval (T8) are measured against. Random/live pages are never used for eval (ARCHITECTURE §4.2) — reproducibility requires a frozen corpus.

Two eval sets, one machine-readable manifest each:

- **`m0-core@1`** → [`expected_m0.json`](expected_m0.json) — the M0 verifiable violations (frozen regression anchor).
- **`m1-core@1`** → [`expected_m1.json`](expected_m1.json) — the M0 page **plus** two *needs-review* fixtures that populate the unverifiable bucket.

`tests/test_fixtures.py` guards that these planted signals stay present and that each manifest stays in sync with its pages.

> **Status of the mappings.** All `axe rule → WCAG SC → tag → target → impact` values below are **confirmed** against the pinned axe-core 4.12.1 (violations at T2; needs-review items at T4).

## `m0-core@1` — verifiable violations

### `pages/home.html`

Produces **exactly 3** violations under default axe-core — no more. `<title>`, an `<h1>`, and a `<main>` landmark are present so axe does not raise incidental `document-title`, `region`, or `bypass` findings.

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

## Changing a set

Any change to a planted signal is a **version bump**: increment `version` (and `eval_set_id`) in the relevant `expected_m*.json` and here. Downstream eval runs are tagged with the set version, so a bump never silently invalidates past results.
