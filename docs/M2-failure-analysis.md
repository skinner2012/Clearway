# M2 — honest failure analysis

Closes the M2 exit criterion (`specs/M2-control-loop.md`, T7). It continues
[`docs/M1-weak-spots.md`](M1-weak-spots.md): where retrieval, drafting, and validation still fail,
and **why** — grounded in the traces of a **real run** over the fixture set (`m1-core@1`,
**fixture-only**; live-page scanning is deferred). M2 built the machinery to *see* failures
(durable state machine, OTel/LLM telemetry, the HITL gate, `expert_edit_distance`, persisted
`EvalReport`s, the trust dashboard). This is the read of what that machinery captured. It is the
input list for M4 (routing) and M5 (judge/calibration) — refinement targets, not blockers.

Every claim below is tied to a persisted trace under one `run_id`; the per-finding evidence is in
the [appendix](#appendix--per-finding-trace).

## The run

- **When:** 2026-07-10. **Config:** `m1-single@1` (one model, no routing). **Model:** `gemma4:31b`, temp 0.
- **Set:** `m1-core@1` — 3 pages, **5 findings** (3 verifiable `violations` on `home.html` + 2 `incomplete`).
- **Run id:** `70592633bc7c470792014ae8b54c499d`. **Retriever:** real embedder (`nomic-embed-text`) + pgvector, k=5. **Oracle:** axe-core 4.12.1 (`AxeCoreOracle`, regime `A-digital`, `wcag2.2-sc@1`).

| finding (rule → gold SC) | bucket | retrieved (rank order) | gold rank | cited | verdict | conf |
|---|---|---|---|---|---|---|
| html-has-lang → 3.1.1 | violation | **3.1.1**, 4.1.2, 2.5.6, 1.4.12, 3.1.2 | 1 | 3.1.1 | VERIFIED | 1.0 |
| image-alt → 1.1.1 | violation | **1.1.1**, 1.4.9, 1.4.6, 1.4.5, 1.4.4 | 1 | 1.1.1 | VERIFIED | 1.0 |
| label → 4.1.2 | violation | 2.5.3, 3.3.2, 1.4.9, 1.4.5, **4.1.2** | **5** | 4.1.2 **+ 3.3.2** | VERIFIED **+ HALLUCINATED** | 0.95 |
| color-contrast → 1.4.3 | incomplete | **1.4.3**, 1.4.11, 1.4.6, 1.4.1, 2.4.13 | 1 | 1.4.3 | UNVERIFIABLE → **HITL queue** | 0.9 |
| video-caption → 1.2.2 | incomplete | **1.2.2**, 1.2.4, 1.4.7, 1.1.1, 1.4.11 | 1 | 1.2.2 | UNVERIFIABLE → **HITL queue** | 1.0 |

**Aggregate `EvalReport` (post-gate):** `findings_total` = **3**, `citations_total` = **4**,
`hallucinations_total` = **1**. `citation_hallucination_rate` = **0.250**, verifiable-subset rate =
**0.250** (1/4), `unverifiable_share` = **0.000** (0/4), `expert_edit_distance` = **0.0**.

Read that aggregate against the table and the numbers disagree: the table has 5 findings and 2
unverifiable citations; the report says 3 findings and 0 unverifiable. **That gap is the headline of
this milestone, not an error** — see §1.

## Weak spots

### 1. The unverifiable share didn't shrink — the HITL gate *relocated* it (metric-honesty)

M1 reported `unverifiable_share` = **0.333**. This run's automated report says **0.000**. Nothing
improved: the drop is entirely an artifact of the M2 HITL gate (T3). `_review_reason`
([machine.py:258](../clearway/orchestrator/machine.py#L258)) flags every `incomplete`-bucket finding
as `axe_incomplete`; `_gate` persists a `PENDING` `NeedsReview` and returns `None`, so the finding
is **withheld from the report** until a human resolves it. The two unverifiable findings
(`color-contrast`, `video-caption`) are therefore pulled out of the aggregate and sit in the queue:

```
needs_review (run 70592633):  c987b786 color-contrast  axe_incomplete  pending
                              377b3cf  video-caption    axe_incomplete  pending
```

So the honest denominator is **5 findings, of which 2 (40%) landed on the human** — not "0%
unverifiable." The dashboard's `unverifiable_share` gauge is only truthful when read *alongside*
needs-review queue depth; in isolation it understates the human burden to zero. M1's "one-third
rests on un-checked judgment" is now literally two drafts waiting in a queue. → **M2 dashboard**
already reserves the operational board for exactly this cross-read; **M5** must define the honest
composite metric (automated report ⊕ queue) so a clean-looking gauge can't hide the routed work.

### 2. Retrieval buries the gold SC under semantic neighbours (retrieval)

Reproduces M1 exactly. On `label`, the correct **4.1.2 came back last (rank 5)** while "Labels or
Instructions" (3.3.2) ranked 2. Cosine similarity over `nomic-embed-text` conflates adjacent
form-field SCs and here ranked the wrong one higher — the direct cause of the run's only
hallucination. The other four findings retrieved gold at **rank 1**, so the failure is
concentrated, not diffuse: it is specifically the 4.1.2/3.3.2 neighbourhood that the embedder cannot
separate. → **M4** (a reranker over the k=5 window; a *gold-SC-rank* panel to watch the distribution).

### 3. The drafter over-cites, and every extra citation is hallucination surface (drafting)

For `label` the model emitted **two** citations — 4.1.2 *and* 3.3.2 — for one finding. 4.1.2
validated VERIFIED; the extra 3.3.2 validated HALLUCINATED. That single surplus citation *is* the
run's only hallucination and is what pushed `citations_total` on `home.html` to 4 against 3 findings.
There is no citation budget or "cite the single best SC" discipline in the prompt; the model spends
citations freely, and each one past the minimal-correct set can only lower precision. → **M5**
(drafting-prompt precision + a citation cap).

### 4. Confidence is decorative and the gate can't use it (calibration)

Confidence is pinned at **0.9–1.0 everywhere and is highest exactly where the answer is unverifiable
or wrong**: the two UNVERIFIABLE drafts carry **0.9 and 1.0**, and the HALLUCINATED `label` draft
carries **0.95**. It carries no trust signal. Worse, it is operationally inert: the low-confidence
gate threshold is **0.5** ([machine.py:55](../clearway/orchestrator/machine.py#L55)), so *none* of
these drafts trip it — the incomplete pair is gated only by **bucket** (`axe_incomplete`), and the
hallucinated `label` is not gated at all and ships. A confidence signal that fired below, say, 0.7
would still miss all of them, because the model is confidently wrong. → **M5** (this is the
calibration target: confidence must fall on wrong / un-checkable citations before it can drive the
gate).

### 5. `expert_edit_distance` is structurally 0.0 — the loop hasn't been closed on this run (measurement gap)

The T4 metric reads **0.0**, but not because the drafts were perfect: it is the mean edit distance
over **resolved** (`EDITED`) reviews, and this run has **2 pending, 0 resolved**. With no human
correction yet recorded, the metric has no data to average and defaults to 0.0. The signal is live
(T4 is tested) but **vacuous until the needs-review queue is worked** — a `clearway review edit`
against either pending finding would populate it. Reporting it as "0.0 = good" would be the exact
hand-waving T7 forbids; the honest statement is "0.0 = not yet measured." → **M2 operations** (the
queue must actually be triaged for this number to mean anything); **M5** (calibration consumes real
edit distances).

### 6. No second opinion (routing)

Carried forward from M1 and still true: `m1-single@1` is one model, one pass, temp 0 — no routing,
no self-consistency, no cross-model disagreement. A vote or a disagreeing second model would most
likely have caught the 3.3.2 over-citation in §3. → **M4** (routing / ensemble).

## Operational read (T2 telemetry)

The run was operationally clean but slow, and the shape of the cost is worth stating plainly:

- **LLM calls:** 5 `chat` calls (one draft per finding). **Retries: 0. Failures: 0** — every step
  succeeded first-attempt (`pipeline_step_retries_total` and `pipeline_failures_total` absent).
- **Latency is entirely in drafting:** mean draft call **≈ 50 s** (`gemma4:31b` on local hardware);
  retrieve ≈ 0.63 s; validate ≈ 0.0 s (the oracle is deterministic, no LLM). Drafting is ~99% of
  wall-clock — the obvious target if throughput ever matters.
- **Tokens:** 2169 in / 259 out across the 5 calls (~434 in / ~52 out each). **Cost: $0** — local
  Ollama, so the cost panel is structurally zero this milestone; it lights up only against a paid
  endpoint (M4 routing).

None of this is a failure — it is the honest baseline the operational panels now make visible, and
the reason the trust board puts latency/cost on the same screen as the quality gauges.

## Smaller notes

- **Sample size is still tiny.** 4 verifiable citations in the aggregate, so one fault swings the
  verifiable rate to 0.25. The rates won't stabilise until the fixture set grows. → M5/M6 (grow the set).
- **The aggregate report and the trace store must be read together.** `findings_total` counts only
  what survived the gate; the durable `step_state` is the complete record (all 5 findings, all
  steps DONE). Any dashboard or summary that cites `findings_total` alone silently drops the routed
  work. Documented here so it is a known property, not a surprise.

## Appendix — per-finding trace

Source: `step_state` + `eval_report` for run `70592633bc7c470792014ae8b54c499d`, joined to gold SCs
via the `m1-core@1` manifest (finding id = `sha256(source_url|rule_id|target)[:16]`).

| fid | rule | gold | retrieved (rank order) | gold rank | drafted cites | per-citation verdict | conf | gated |
|---|---|---|---|---|---|---|---|---|
| 2f5854b7 | html-has-lang | 3.1.1 | 3.1.1, 4.1.2, 2.5.6, 1.4.12, 3.1.2 | 1 | 3.1.1 | 3.1.1 l0✓ l1=match → verified | 1.0 | no |
| 433d3ade | image-alt | 1.1.1 | 1.1.1, 1.4.9, 1.4.6, 1.4.5, 1.4.4 | 1 | 1.1.1 | 1.1.1 l0✓ l1=match → verified | 1.0 | no |
| 61ebe655 | label | 4.1.2 | 2.5.3, 3.3.2, 1.4.9, 1.4.5, 4.1.2 | 5 | 3.3.2, 4.1.2 | 3.3.2 l0✓ l1=mismatch → **hallucinated**; 4.1.2 l0✓ l1=match → verified | 0.95 | no (ships) |
| c987b786 | color-contrast | 1.4.3 | 1.4.3, 1.4.11, 1.4.6, 1.4.1, 2.4.13 | 1 | 1.4.3 | 1.4.3 l0✓ l1=no_oracle → **unverifiable** | 0.9 | **yes** (pending) |
| 377b3cf3 | video-caption | 1.2.2 | 1.2.2, 1.2.4, 1.4.7, 1.1.1, 1.4.11 | 1 | 1.2.2 | 1.2.2 l0✓ l1=no_oracle → **unverifiable** | 1.0 | **yes** (pending) |

All steps for all five findings are checkpointed `done` under the run id; the two gated findings are
withheld from the aggregate `EvalReport` (`trace_ids` = the three `home.html` findings only) and held
in `needs_review` as `axe_incomplete / pending`.
