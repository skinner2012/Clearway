# Finding-class trust status

The quality-review judgment classes have been scored against external W3C ACT expert gold, and they
differ **sharply**: some agree with the experts, one is barely above chance, and two have never been
measured at all. A specialist should read each finding in the light of its class's trust, **not** as
an indistinguishable peer of the others.

## The rule that assigns a tier

> **RELIABLE** if the class's Cohen's κ against ACT gold is **≥ 0.60** on the latest frozen scored
> run; **WEAK** if it was measured and κ < 0.60; **UNMEASURED** if it has never been scored against
> gold.

The tiers are *derived by that rule*, never hand-assigned after the numbers are seen, so they can be
refreshed against a future frozen run without re-negotiating the mapping.

- **Code SSOT:** `FINDING_CLASS_TRUST` in [`../clearway/normalizer/quality_review.py`](../clearway/normalizer/quality_review.py),
  built by `derive_class_trust(FROZEN_CLASS_KAPPA, QUALITY_REVIEW_RULES)`. The threshold is
  `TRUST_KAPPA_THRESHOLD = 0.60` — Landis & Koch "substantial agreement", the same bar the judge's
  trust gate uses. Every class in `QUALITY_REVIEW_RULES` must carry a tier (enforced by a test), so a
  new rule cannot ship unlabelled; it starts UNMEASURED until someone scores it.
- **The numbers:** `benchmark/reports/referent_injection_result.json` (`mechanism[]`, three passes,
  κ identical on each). `FROZEN_CLASS_KAPPA` is pinned against that artifact by a test, so the code
  cannot quote a number the run does not contain.
- **To refresh:** re-run `derive_class_trust` against the next frozen run's per-class κ.

## ⚠️ The tiers are not equally well established

`document-title` reaches RELIABLE on **κ = 1.00 over n = 5**. That is five cases, with no measured
error — not a certification. Its structural ceiling is p = 0.125, so at that n it **cannot reach
statistical significance however good the drafter is**; a perfect score there is the best available
outcome and still weak evidence. `empty-heading` (n = 13) and `label` (n = 11) rest on more, but none
of these samples is large. The pure-κ rule was chosen with this fragility known and accepted: a
stated threshold that occasionally over-promises on a small sample is preferable to a tier table
adjusted case by case after the fact. **Read the n in the table, not just the tick.**

## Current position

| Finding class (axe rule) | Trust | κ (n) on the latest frozen run | What the measurement says now |
|---|---|---|---|
| `empty-heading` | ✅ **reliable** | κ 0.68 (n=13) | recall 4/5, FP 1/8 — the drafter can judge heading descriptiveness from the DOM. The untouched control: this class was not changed and did not move. |
| `document-title` | ✅ **reliable** | κ 1.00 (n=5) | 2 hits, 3 correct passes, no errors — but on five cases, and see the caveat above. Its former constant classifier is gone. |
| `label` | ✅ **reliable** | κ 0.82 (n=11) | recall 5/5 with 1 false positive in 6 clean cases — it now tracks the resolved field name, not just the label mechanism. |
| `link-name` | ⚠️ **weak** | κ 0.05 (n=15) | 4 false positives and 3 misses in 15 — barely above chance. The referent that decides link purpose is the link's **destination**, which is not in the DOM the drafter sees, so no in-page grounding fixes it. |
| `image-alt` | ❔ **unmeasured** | never scored | structurally unvalidatable text-only — ACT filenames leak the answer; needs a multimodal drafter. |
| `frame-title` | ❔ **unmeasured** | never scored | no external gold anywhere — trust unknown. |

κ above is the headline (strict) reading. Under the alternative partial-credit reading no tier
changes: `link-name` is 0.24, still far below the bar; the other three are unchanged.

## Where these came from — the earlier reading

The first scoring of these classes (`benchmark/reports/drafter_kappa_baseline.json`, analysed in
[`acceptance-analysis.md`](acceptance-analysis.md)) found three of the four failing, and that reading
is what the tiers used to encode:

| Finding class | κ then → now | The failure that was diagnosed |
|---|---|---|
| `empty-heading` | 0.68 → 0.68 | none — it was reliable then and is the control now |
| `document-title` | 0.00 → 1.00 | a **constant classifier**: `does_not_support` on every title, 3/3 false positives on clean ones |
| `label` | 0.13 → 0.82 | tracked the label *mechanism* (`<label>` vs `aria-labelledby`) rather than the resolved name |
| `link-name` | 0.21 → 0.05 | mixed, with false positives on in-context link purpose — and it **net-regressed** (1 case fixed, 2 broken) |

The common cause of the first three was the same: the drafter was judging a name it could not see.
Injecting the resolved referent into its input fixed the two classes whose referent is *in* the DOM
(the `<title>` text, the field's computed label) and made the one whose referent is *outside* it
worse. That diagnosis is why `link-name` stays weak rather than being retried with more of the same.

## How to read a finding by its class

- **reliable** — worth acting on directly; the class agreed with external expert gold on the cases
  measured. Not a guarantee: check the n above before treating it as settled.
- **weak** — a prompt to *look*, expecting a substantial share of false alarms; do not treat the
  verdict as settled.
- **unmeasured** — no validated trust signal exists for the class; treat the finding as unverified.

None of these tiers is the model's own confidence. The drafter's self-reported confidence is
measured to be uninformative (single populated bin, values pinned high regardless of correctness);
it is kept only as an internal calibration receipt (ECE / over-confidence gap) and is never a client-
facing signal.

## This refresh is itself a behavioural change

Moving `document-title` and `label` from **weak** to **reliable** changes what every reader of the
tiers is told to trust — a finding on either class now reads as "act on it" rather than "expect
roughly half to be false alarms". The mirrors of this table (this document and the dashboard's
per-class trust panel) are checked against `FINDING_CLASS_TRUST` by test, so they cannot drift from
the code; the code stays the single source of truth.
