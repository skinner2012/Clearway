# M1 — first-pass weak spots

Closes the M1 exit criterion (`specs/M1-forward-path.md`, T8, "first-pass failure read"). M1 passed
— this is the honest read of the **first real run** of the forward path over the whole eval set,
naming where retrieval and drafting are still weak. It is the input list for M2's deep dashboard,
M4's routing, and M5's calibration — refinement targets, not blockers.

## The run

- **When:** 2026-07-08. **Config:** `m1-single@1` (one model, no routing). **Model:** `gemma4:31b`, temp 0.
- **Set:** `m1-core@1` — 3 pages, 5 findings (3 verifiable `violations` + 2 `incomplete`). **Run:** `6d5e2ba7`.
- **Retriever:** real embedder + pgvector, k=5. **Oracle:** axe-core 4.12.1 (`AxeCoreOracle`).

| finding (rule → gold SC) | retrieved (rank order) | cited | verdict |
|---|---|---|---|
| html-has-lang → 3.1.1 | **3.1.1**, 4.1.2, 2.5.6, 1.4.12, 3.1.2 | 3.1.1 | VERIFIED |
| image-alt → 1.1.1 | **1.1.1**, 1.4.9, 1.4.6, 1.4.5, 1.4.4 | 1.1.1 | VERIFIED |
| label → 4.1.2 | 2.5.3, 3.3.2, 1.4.9, 1.4.5, **4.1.2** | 4.1.2 **+ 3.3.2** | VERIFIED **+ HALLUCINATED** |
| color-contrast → *(incomplete)* | 1.4.3, 1.4.11, 1.4.6, 1.4.1, 2.4.13 | 1.4.3 | UNVERIFIABLE |
| video-caption → *(incomplete)* | 1.2.2, 1.2.4, 1.4.7, 1.1.1, 1.4.11 | 1.2.2 | UNVERIFIABLE |

**Metrics:** 6 citations, 1 hallucination. overall `citation_hallucination_rate` = **0.167**,
verifiable-subset rate = **0.250** (1/4), `unverifiable_share` = **0.333** (2/6).

## Weak spots

1. **Retrieval buries the gold SC under semantic neighbours.** On `label`, the correct 4.1.2 came
   back **last (rank 5)** while "Labels or Instructions" (3.3.2) ranked 2. Cosine similarity
   conflates adjacent SCs, and here it ranked the wrong one higher — the direct cause of the run's
   only hallucination. → M2 (a *gold-SC-rank* panel: distribution of where the correct SC lands),
   M4 (a reranker over the k=5 window).

2. **The drafter over-cites.** For `label` it emitted **two** citations (4.1.2 *and* 3.3.2) for one
   finding. Every citation past the minimal-correct set is pure hallucination surface — and it made
   `citations_total` = 6 vs the 5 findings, so even the offline stub's "1 citation per finding"
   assumption doesn't hold on the real model. There is no citation budget / "cite the single best
   SC" discipline in the prompt. → M5 (drafting-prompt precision, a citation cap).

3. **Confidence is decorative — it does not track correctness.** The hallucinated draft carried
   **0.95**; the two UNVERIFIABLE drafts carried **0.9 and 1.0**. Confidence sits at 0.9–1.0
   everywhere and is *highest* exactly where the answer is unverifiable or wrong. It currently
   carries zero trust signal. → M5 (this is the calibration target: confidence must fall on wrong /
   un-checkable citations).

4. **Two-thirds of the answer is verifiable, one-third rests on un-checked judgment.**
   `unverifiable_share` = 0.333 is structural: the oracle only adjudicates axe `violations`, so the
   `incomplete`-bucket citations get `NO_ORACLE` by construction — and those are the drafts the
   model was *most* confident about (up to 1.0). The honest headline is that a third of the output
   cannot be automatically contradicted. → M2 (deep dashboard surfaces the split), M5.

5. **No second opinion.** `m1-single@1` is one model, one pass, temp 0 — no routing, no
   self-consistency, no cross-model disagreement. A vote or a disagreeing second model would most
   likely have caught the 3.3.2 hallucination. → M4 (routing / ensemble).

## Smaller notes

- **Sample size is tiny.** 4 verifiable citations total, so one fault swings the verifiable rate to
  0.25. The "~0 by construction" framing is aspirational; the rates won't be stable until the eval
  set is larger. → M2 (grow the fixture set).
- **Single-page `run` mislabels its metric.** `clearway run <page>` still emits under
  `eval_set_id="m0-core@1"` (a leftover from M0). Harmless for the set-level `eval` command
  (`m1-core@1`), but the label is wrong for ad-hoc single runs. → cheap fix, deferred out of T8.
