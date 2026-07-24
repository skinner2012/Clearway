# Finding-class trust status

The held-out acceptance benchmark scored the quality-review judgment classes against external W3C ACT
expert gold and found they differ **sharply** — one is reliable, several cry wolf on much of the clean
content, and two have never been measured at all. A specialist should read each finding in the light of
its class's trust, **not** as an indistinguishable peer of the others.

- **Code SSOT:** `FINDING_CLASS_TRUST` in [`../clearway/normalizer/quality_review.py`](../clearway/normalizer/quality_review.py)
  — every class in `QUALITY_REVIEW_RULES` must carry a tier (enforced by a test), so a new rule cannot ship unlabelled.
- **The numbers** (kept in one place so they can't drift): the per-rule table in
  [`acceptance-analysis.md`](acceptance-analysis.md).

| Finding class (axe rule) | Trust | What the benchmark measured |
|---|---|---|
| `empty-heading` | ✅ **reliable** | recall 4/5, FP 1/8 — the drafter can judge heading descriptiveness from the DOM |
| `document-title` | ⚠️ **weak** | 3/3 false positives on clean titles — a constant classifier (`does_not_support` on every title) |
| `label` | ⚠️ **weak** | ~4/6 false positives — tracks the label *mechanism* (`<label>` vs `aria-labelledby`), not the resolved name |
| `link-name` | ⚠️ **weak** | mixed (recall 3/5) with high false positives on in-context link purpose — treat as low-trust |
| `image-alt` | ❔ **unmeasured** | structurally unvalidatable text-only — ACT filenames leak the answer; needs a multimodal drafter |
| `frame-title` | ❔ **unmeasured** | no external gold anywhere — trust unknown |

## How to read a finding by its class

- **reliable** — worth acting on directly; the class judged clean/failed correctly on external gold.
- **weak** — a prompt to *look*, expecting roughly half to be false alarms; do not treat the verdict as settled.
- **unmeasured** — no validated trust signal exists for the class; treat the finding as unverified.

This is the honest interim posture while the drafter's judgment on the weak classes is unfixed and the
unmeasured classes have no gold: the classes are not equal, and the output now says so.
