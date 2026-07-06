# Clearway fixtures — M0 eval corpus

- **Set id:** `m0-core`  ·  **Version:** `1`  ·  **eval_set_id:** `m0-core@1`

A **fixed, versioned** set of HTML pages with **deliberately planted** accessibility violations. This is the ground truth the scanner (T2), oracle (T6), and eval (T8) are measured against. Random/live pages are never used for eval (ARCHITECTURE §4.2) — reproducibility requires a frozen corpus.

> **Status of the mappings below.** The `axe rule → WCAG SC → axe tag → target → impact` values are **expected** — believed from axe-core docs, **not yet confirmed**. axe-core is **not** run at T1; these are confirmed when the real scanner runs (T2) and the oracle is built (T6). See the VERIFY in ARCHITECTURE §4.8 and spec T6.

## Pages

### `pages/home.html`

Intended to produce **exactly 3** violations under default axe-core — no more. `<title>`, an `<h1>`, and a `<main>` landmark are present so axe does not raise incidental `document-title`, `region`, or `bypass` findings.

| # | Planted defect | axe rule | WCAG SC (level) | axe tag | expected target | impact |
|---|---|---|---|---|---|---|
| 1 | `<img>` with no `alt` | `image-alt` | 1.1.1 (A) | `wcag111` | `img` | critical |
| 2 | `<html>` with no `lang` | `html-has-lang` | 3.1.1 (A) | `wcag311` | `html` | serious |
| 3 | `<input>` with no label | `label` | 4.1.2 (A) | `wcag412` | `#email` | critical |

The machine-readable form is [`expected.json`](expected.json), consumed by tests from T2 onward. `tests/test_fixtures.py` guards that these planted defects stay present and that the manifest and pages stay in sync.

## Changing this set

Any change to a planted violation is a **version bump**: increment `version` (and `eval_set_id`) in [`expected.json`](expected.json) and here. Downstream eval runs are tagged with the set version, so a bump never silently invalidates past results.
