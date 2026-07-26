# Ablation review — the opaque image set, case by case

**What this document is.** The derived set is gated by two executable checks — no gold-relevant token
survives in any path-bearing attribute of a minted prompt, and the prompt-level exclusion rule finds
no new opposite-gold twin. Both are offline, model-free and asserted by tests. Neither can tell you
whether the *right* thing was removed, because both operate on a token list this repo derived from
the same paths it is checking. This document is the third gate: a person reading all seven prompts
before and after and saying, case by case, what went and what stayed.

**Set:** `act-image-opaque@1` (`clearway/fixtures/act-image-opaque/`), derived from
`act-image-leaky@1` by `clearway/eval/image_opaque.py`.
**Evidence:** the strings below are the *minted* `finding.html` — what the drafter is actually shown —
read out of the live pipeline over both sets, not the fixture files.
**The rest of the prompt is identical across the two sets**: same rule, same bucket, same `target`
(`img`), same help text, verified per case.

---

## Case by case

### 1. `be6b29e220…` — qt1vmo, gold **passed**, image: W3C logo

```
before  <img src="/test-assets/shared/w3c-logo.png" alt="W3C">
after   <img src="/img/a.png" alt="W3C">
```

**Removed:** `w3c-logo` — the accessible name `W3C` restated in the filename. **Survives:** nothing;
`shared` is gone with the directory. **Judgment:** correct. The leaky prompt let a text-only drafter
match `W3C` against `w3c-logo` and answer without seeing anything; the opaque prompt cannot be
answered from the text at all.

### 2. `530266c611…` — qt1vmo, gold **failed**, image: W3C logo

```
before  <img src="/test-assets/shared/w3c-logo.png" alt="ERCIM">
after   <img src="/img/a.png" alt="ERCIM">
```

**Removed:** `w3c-logo` — here the *mismatch* between name and filename was the cue, and it pointed at
the right answer. **Survives:** nothing. **Judgment:** correct, and note it cuts the other way: this
case got *easier* in the leaky condition for a bad reason, and the ablation removes that too.

### 3. `cfd1636ab4…` — 9eb3f6, gold **passed**, image: Nyhavn

```
before  <img src="/test-assets/image-filename-as-accessible-name-9eb3f6/nyhavn" alt="Nyhavn">
after   <img src="/img/b.png" alt="Nyhavn">
```

**Removed:** `nyhavn` (the alt, verbatim, case-insensitively) *and* the directory
`image-filename-as-accessible-name-9eb3f6`, which names the deciding criterion in words and the rule
in its id. **Survives:** nothing. **Judgment:** correct. This is the case the whole ablation exists
for — the leaky prompt was answerable by string equality against a directory that told you which
equality to test.

### 4. `607ad4964a…` — 9eb3f6, gold **passed**, image: bread

```
before  <img src="/test-assets/image-filename-as-accessible-name-9eb3f6/pain" alt="pain">
after   <img src="/img/c.png" alt="pain">
```

**Removed:** `pain` and the same directory. **Survives:** nothing in the path. The page's `lang="fr"`
survives in the file but is **not** in the minted snippet, so it is not in the prompt either — the
drafter sees `pain` with no French context and no picture. **Judgment:** correct.

### 5. `1ff696703e…` — 9eb3f6, gold **passed**, image: Nyhavn

```
before  <img src="/test-assets/image-filename-as-accessible-name-9eb3f6/nyhavn.jpeg"
             srcset="\n\t\t\t/test-assets/…/nyhavn 1.5x,\n\t\t\t/test-assets/…/paris  2x\n\t\t"
             alt="Nyhavn">
after   <img src="/img/b.png"
             srcset="\n\t\t\t/img/b.png 1.5x,\n\t\t\t/img/b.png  2x\n\t\t"
             alt="Nyhavn">
```

**Removed:** three paths, not one — this is the case that makes a filename-only rewrite insufficient.
The `srcset` carried the literal tokens `nyhavn` *and* `paris`, the second of which is the answer to a
*different* case in the same pool. **Survives:** the descriptors `1.5x` / `2x`, the two tabs, the
newlines and the double space before `2x`, all byte-exact. **Judgment:** correct. The three candidates
collapse onto one name because they are one image — the same 32 822 bytes under three names upstream —
so the collapse loses no information the page had. It is also what keeps this prompt from becoming a
near-twin of case 3 by an accident of numbering: it is still distinct, by the `srcset` attribute
itself, which was true before the ablation too.

### 6. `f7406b89f8…` — 9eb3f6, gold **failed**, image: Nyhavn

```
before  <img src="/test-assets/image-filename-as-accessible-name-9eb3f6/paris" alt="Paris">
after   <img src="/img/b.png" alt="Paris">
```

**Removed:** `paris` and the directory. **Survives:** nothing. **Judgment:** correct — and this is the
sharpest single instance of the leak. Upstream, the file named `paris` *is* the Nyhavn photograph, so
the filename agreed with the alt and disagreed with the pixels. A text-only drafter reading the leaky
prompt sees a perfect name/filename match on a case whose gold is **failed**; the cue was not just
uninformative, it was actively misleading. After ablation the case is decided only by looking.

### 7. `a2333ec76e…` — 9eb3f6, gold **failed**, image: Nyhavn — *the specificity control*

```
before  <img src="/test-assets/…/94251e110d24a4c2b6e6ce76e7203374" alt="94251e110d24a4c2b6e6ce76e7203374">
after   <img src="/img/b.png" alt="94251e110d24a4c2b6e6ce76e7203374">
```

**Removed:** the digest from the `src`, and with it the *visible relation* "the accessible name is the
filename". **Survives, deliberately:** the digest in the `alt`. **Judgment:** correct, and this is the
one case where preserving the alt matters most. The case is decided by text alone — a hex digest
describes nothing, whatever renders — so its gold (`does_not_support`) rests on the alt, which is
untouched. That is precisely what makes it usable as the control in the mismatched condition: it
should not move when the picture changes, and if it does, the manipulation is moving something other
than perception.

---

## Set-level judgments

**The naming is per asset, not per case.** Two cases share `/img/a.png`, four share `/img/b.png`, one
has `/img/c.png` — multiplicity 4 / 2 / 1, matching the three distinct images measured before any of
this was built. A per-case index would have invented a distinguishing token the originals never had
and would have made informationally identical prompts differ by one digit. Confirmed against the
manifest and the fixture bytes.

**The gold carries over, and one thing does not.** Every `alt` is byte-identical and every rendered
image is the same bytes, so the WCAG 1.1.1 question — does this name describe this image? — has both
of its sides untouched, and the labels transfer. What does **not** transfer is `9eb3f6`'s own
applicability: that rule is about an accessible name that *is* the filename, and after ablation no
name is a filename. Five of the seven cases come from that rule. The set does not score the rule
outcome, it scores 1.1.1, and no report over this set may claim otherwise. This is recorded on the
manifest and in the set's NOTICE as well as here.

**The residual help-text tension, stated rather than absorbed.** The help says a filename or a generic
word does not describe an image. After full-path ablation `alt="Nyhavn"` and `alt="pain"` no longer
*look* like filenames, which is the intended effect; `pain` may still read as a generic word to a
model that does not know it is French, and `94251e11…` still reads as a filename-shaped string. Both
are properties of the alt text ACT authored, not of the ablation, and both are unchanged between the
two conditions — so they cannot move the comparison the set exists to support.

**Nothing else changed.** Blanking every URL on both sides leaves the two files byte-identical on all
seven cases, and the non-path attributes match one by one. The `lang`, the doctype, the descriptors
and the whitespace are ACT's.

**The permutation is a derangement, and it was frozen before any verdict.** Seven rows over full
40-character testcase ids; each case's `true_image` is measured from its own `src` and the authored
`mismatched_image` differs from it on every row. Three of the seven cells cannot move by construction
and say so — two because their alt is wrong under every image in the pool, one because it is the
specificity control. They stay in the statistic; only their power is described.

---

## Sign-off

| | |
|---|---|
| Prepared by | Claude (implementer) — case-by-case reading above, 2026-07-26 |
| Reviewer | Skinner Cheng, 2026-07-26 |
| Date reviewed | 2026-07-26 |

**What the reviewer is being asked to confirm:** that for each of the seven cases the removed tokens
are the ones that leaked the answer, that the preserved `alt` on case 7 is intended, and that the
gold-carry-over argument (1.1.1 preserved, `9eb3f6` applicability not) is accepted as the set's
declared meaning.
