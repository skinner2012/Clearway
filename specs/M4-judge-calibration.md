# Clearway — M4: Judge calibration

## Table of Contents

- [Preamble](#preamble)
- [Goal & exit criterion](#goal--exit-criterion)
- [How to use these tickets](#how-to-use-these-tickets)
- [Tickets](#tickets)

---

## Preamble

M4 is where the eval layer — Clearway's actual differentiator — reaches its sharpest point: measuring correctness on the **judgment items that have no automated oracle**. Through M3, verifiable items had a hard oracle (axe) and judgment items were only flagged `UNVERIFIABLE` — the honest "unverifiable share." M4 builds an **LLM-judge** to score those judgment-item outputs.

But the judge is the easy part. Calling a model to grade another model's output signals nothing. **The signal is the discipline** — the "who watches the watchmen" moves that make the judge trustworthy:

- **Judge ≠ drafter model.** A model grading its own family self-preferences; the judge must be a different model (the drafter is local `gemma4:31b`; the judge is a cloud reference model).
- **Calibrate the judge against gold *first*.** Before the judge is trusted to score models, measure **judge-vs-human κ** against a small gold set. Only a judge that agrees with human ground truth is allowed to judge models. This is the load-bearing step.
- **Reproducibility.** Pin the judge's model + version + temperature + prompt; record them on the trace.
- **Bias detection.** Watch for verbosity / self-preference bias; prefer rubric-based absolute scoring over pairwise (which invites position bias).

The deliverable answers one question honestly: **does the system know when it doesn't know?** — i.e., does low drafter confidence track low correctness (confidence-vs-correctness calibration). That is the concrete meaning of "measured trust."

M4 is sequenced **before routing (M5)** on purpose: once the judge can score judgment items automatically, M5's routing-config choice can be justified on judgment items too, not just the axe-verifiable subset — with no human in the comparison loop.

**On the gold set:** the ground truth here is a small, **self-built** set of digital judgment items — labelled by us with WCAG knowledge, no external expert required. It is deliberately small; its job is to *calibrate the judge*, not to be an exhaustive test set. The `GoldLabel` shape it uses is the **same shape M6's `GoldLabelOracle` reuses** for expert *physical* gold — one gold contract, two labellers/regimes (`ARCHITECTURE.md` §5). Building it also grows the judgment-item population the earlier milestones ran thin on (M1 produced only two), which stabilises the eval set as a side benefit.

**On confidence (the honest boundary M4 draws, and hands to M5).** The M1/M2 failure reads already show the drafter's self-reported confidence is **decorative** — pinned at 0.9–1.0 and *highest exactly where the answer is wrong or unverifiable*. M4 **measures and reports** this; it does **not** try to fix it. The robust fix — a real trust signal from self-consistency or cross-model disagreement — structurally needs the multi-model machinery M5 introduces, so it cannot live in M4. M4's job is therefore to **prove the need and set the bar**: its report states plainly that confidence carries no signal and hands M5 a hard requirement (synthesise a real confidence signal, or route by finding-class instead of confidence). "Ensure confidence is meaningful" is not dropped — it is correctly *located* in M5.

## Goal & exit criterion

Build an LLM-judge for judgment items, prove it trustworthy by calibrating it against a small self-built gold set, then use it to score judgment-item correctness and chart confidence-vs-correctness calibration.

**Exit criterion:**
- A small, versioned, self-built **digital judgment gold set** exists — **~12 planted fixtures spanning the judgment-item categories, yielding ≥25 labelled findings** (the κ floor).
- A **judge** (≠ the drafter model; a pinned frontier cloud snapshot + temperature + fixed rubric prompt) scores judgment-item citation + conformance correctness, reproducibly.
- **Judge-vs-human κ** is measured against the gold set — reported with **raw agreement % and per-class counts**, against a **threshold committed before the number is seen** — and the judge is only trusted to score models if it clears that bar; if the first judge misses it, M4 iterates the model until one clears it (a trusted judge is non-negotiable — M5 depends on it).
- A **confidence-vs-correctness calibration** is charted (does low confidence track low correctness?), combining the judge (judgment items) and the oracle (verifiable items), and reported honestly even when the curve is degenerate.
- The **κ + calibration panels** on the M2 dashboard — reserved as placeholders in M2 — now light up, and a written **calibration report** ships, including the confidence requirement it hands to M5.

- **Real:** self-built gold set + its fixtures, LLM-judge, judge-vs-human κ calibration, bias checks, confidence-vs-correctness calibration, calibration report, κ/calibration dashboard panels.
- **Absent:** routing / multi-model (M5), physical / Regime B (M6), any change to the **drafter**, any *fix* to confidence elicitation (M4 measures only).
  - **One scoped forward-path exception (added after T0, see T1):** the scanner gains a whitelisted `passes[] → judgment-finding` source (existence-only axe rules — `image-alt`, `link-name`, `button-name`, `document-title`, `frame-title`, `label` — that pass on *present-but-poor* content). This is **not** a new finding-proposer (same mapping code, a new provenance bucket, `AxeBucket.PASSES`), and it is required: an empirical double-filter over pinned axe 4.12.1 showed the `incomplete[]` bucket yields **zero** DOM-decidable judgment items, so without it the judge gold set is judge-impossible and κ is meaningless. No other forward-path change.

## How to use these tickets

**T0** (CONTRACTS: gold + judge + calibration schemas) is the foundation. After T0, **T1** (gold set + fixtures) and **T2** (judge) run in parallel. **T3** (judge-vs-human κ) depends on T1 + T2 — and on a drafter pass over the gold items (see T3). **T4** (confidence calibration) depends on T3; **T5** (report + dashboard) depends on T4. Build sequentially, one branch/ticket, per-commit approval, per the project's build discipline.

## Tickets

### T0 — CONTRACTS: gold + judge + calibration schemas  *(foundation)*
- **Produces:** `GoldLabel`, `JudgeResult`, `CalibrationReport` (+ its `ConfidenceBin` submodel) in `CONTRACTS.md` §3, plus the judge/calibration **scalar** fields on `EvalMetrics`. Regenerate `clearway/schemas/models.py` + exports; remove `JudgeResult` / `CalibrationReport` / `GoldLabel` from `CONTRACTS.md` §5; add a §6 change-log row.
- **Detail:**
  - `GoldLabel` = `finding_id`, `gold_success_criteria: list[str]`, `gold_conformance: Conformance`, `gold_severity: Optional[Severity]`, `labeller: str`, `gold_version: str`, `notes: str = ""`. This is the **single gold shape** M6's `GoldLabelOracle` reuses (digital self-built now, expert physical later) — do **not** fork a second gold schema.
  - `JudgeResult` = `finding_id`, `run_id`, `judge_model: str`, `judge_version: str`, `verdict: JudgeVerdict` (`correct` / `incorrect` / `partial`), `citation_correct: bool`, `conformance_correct: bool`, `rationale: str`. Kept **separate from `CitationCheck`** — a per-draft correctness verdict is a different granularity than a per-citation validator layer (this is why L2-faithfulness fields on `CitationCheck` stay deferred; see §5).
  - `CalibrationReport` = `judge_kappa: float` **(bounds `[-1.0, 1.0]` — see the landmine below; judge-vs-human)**, `judge_agreement: float` (raw %), `n: int`, `kappa_threshold: float` (the pre-committed bar), `judge_trusted: bool`, `confidence_bins: list[ConfidenceBin]` (the full calibration curve — a list, not a scalar), `bias_notes: str`, `created_at`.
  - `ConfidenceBin` (new submodel) = `lower: float`, `upper: float`, `n: int`, `mean_confidence: float`, `correctness_rate: float`, `correct_n: int`. **`n` and `correct_n` are mandatory** — a bin with n=1 otherwise makes the curve lie. This typed list is the curve's only home; it is **not** copied onto `EvalMetrics`.
  - Extend `EvalMetrics` with judge/calibration **scalars only** (a curve is not a scalar — it stays on `CalibrationReport`). All **Optional / default `None`**, since M0–M3 runs carry no judge:
    - *Judge reliability:* `judge_kappa`, `judge_agreement_rate`, `judge_gold_n`, `judge_trusted`.
    - *Judgment correctness:* `judgment_correctness_rate`, `judgment_items_total`, `judgment_correct_total` (store numerator + denominator, not just the rate — a rate without n lies).
    - *Confidence calibration:* `expected_calibration_error` (ECE — unsigned magnitude of miscalibration) and `overconfidence_gap` (signed — positive = systematically over-confident).
    - Names deliberately differ from `CalibrationReport`'s (`judge_agreement_rate` vs `judge_agreement`, `judge_gold_n` vs `n`): the flat `EvalMetrics` namespace needs the qualifier the report's context already supplies.
  - **⚠️ κ-bounds landmine:** `judge_kappa` is `[-1.0, 1.0]`, **not** `[0.0, 1.0]`. Do **not** copy `ge=0.0` from the other rate fields — a negative κ (judge *worse* than chance, the single most important red flag) would then crash the run and bury exactly the signal we need. Constrain both copies (`EvalMetrics` and `CalibrationReport`) to `ge=-1.0, le=1.0`.
  - **Semantic guard — keep `unverifiable_share` honest:** a judge-scored item is **not** promoted to "verified." The oracle is ground truth; the judge is an *estimate* whose reliability ceiling is κ. `unverifiable_share` stays as-is; never fold judge-scored items into the verified count — that inflation is precisely what this project rejects (`ARCHITECTURE.md` §4.9).
  - Keep `extra="forbid"` on every model.
- **Acceptance:** models import; JSON-schema smoke test; the three schemas no longer in §5; new §6 row; ruff/mypy green.
- **Also (CONTRACTS §5):** soften the L2 row from a hard "M4" to "M4+ / when the judge exists" — M4 produces `JudgeResult`, not L2 fields on `CitationCheck`; per-citation faithfulness remains a distinct, deferred concern.
- **Depends on:** —

### T1 — self-built digital judgment gold set (+ the fixtures it needs)
- **Produces:** ~12 versioned, planted **fixtures** spanning the judgment-item categories below, and the **gold set of `GoldLabel`s** for every judgment-item finding they produce (~25–30 findings — the κ floor).
- **Finding source — settled after T0 by an empirical double-filter (CONTRACTS change-log 0.11).** A useful judgment gold item must be **both** (1) surfaced by axe **and** (2) decidable from the DOM the drafter/judge actually receives. Axe's `incomplete[]` bucket fails (2): all 55 incomplete-capable rules in pinned axe 4.12.1 hesitate because they need pixels / render / media / cross-frame resolution — exactly what the judge also lacks, so calibrating on them yields a meaningless κ (a meaningless κ is *worse* than none). The DOM-decidable judgment items instead live in axe's **`passes[]`** bucket: *existence-only* rules that pass on garbage (`image-alt` passes `alt="DSC_0042.jpg"`; `link-name` passes "click here"; `label` passes a placeholder-only input; `frame-title` passes `title="frame"`). T1 surfaces a **whitelist** of these as judgment findings via the new `AxeBucket.PASSES` (CONTRACTS §3) — *"axe says it exists; is it any good?"*, the product's actual value proposition. This is the scoped forward-path change noted under the milestone's **Absent** list; it is **not** a new finding-proposer.
- **Detail:** the current fixture set yields only two judgment items — far too few for a meaningful κ. So T1 **authors ~12 planted fixtures across the four categories above — roughly three per category** (each planting a *present-but-poor* value that axe passes on existence but a human/LLM sees is inadequate). Organising the set around *fixtures × categories* is deliberate, and does two jobs at once:
  - **Breadth.** Covering all four categories forces κ to measure whether the judge handles the *variety* of judgment items, not just whichever category happens to dominate; the high-value ones (alt text, link text) get more fixtures than the others.
  - **Independence.** Spreading findings across ~12 fixtures — rather than cramming them into a few dense pages — keeps them *less correlated*: two findings from the same page share context, so they aren't two fully-independent data points for κ (see the independence caveat below).
  
  Categories to cover — the **four** whitelisted, existence-only axe rules empirically confirmed (pinned axe 4.12.1) to **pass** on a planted *poor-but-present* value. The live whitelist is `clearway/normalizer/quality_review.py` (its module docstring is the implementation-level record); this list is the milestone-level decision:
  - **Image alt-text meaningfulness** — `image-alt`, WCAG 1.1.1 (e.g. `alt="DSC_0042.jpg"`, `alt="image"`). *(High value — gets ≥2 fixtures.)*
  - **Link text in context** — `link-name`, WCAG 2.4.4 (e.g. "click here", "read more", a bare URL). *(High value — gets ≥2 fixtures.)*
  - **Form field label quality** — `label`, WCAG 1.3.1 / 3.3.2 (e.g. a placeholder-as-label).
  - **Frame / iframe title quality** — `frame-title`, WCAG 4.1.2 / 2.4.1 (e.g. `title="frame"`).

  **Two categories deferred, not dropped — `document-title` and `button-name`.** They were *not* confirmed to pass on poor content (a title/button with any text usually reads as adequate, so a clean present-but-inadequate case is hard to plant), *and* enabling them would mint findings on the frozen M0/M1 fixtures (every fixture has a `<title>`; `home.html` has a named `<button>`), disturbing versioned regression anchors — for the two *weakest* categories. Scoping to the confirmed four gives a smaller but **more valid** judge calibration: every gold item is a clean, DOM-decidable call, and because the *same* whitelist governs production, the set the judge calibrates on equals the set it will actually judge, so κ never overstates its reliability on its real workload. The two can be added later — each behind a fixture version bump — once a fixture confirms it passes on poor content and the product's judgment scope calls for it. (The alt/name variants `svg-img-alt` / `object-alt` / `role-img-alt` / `input-image-alt` / `select-name` extend their category the same way.)

  **Not judgment items at all in this pipeline** (the double-filter's other output): *heading structure*, *reading/tab order*, and *solid-colour contrast* are **violations** (axe hard-decides them → oracle-backed, not judgment); *gradient contrast* and *motion/animation* are DOM-undecidable (the judge can't see them either). Don't plant them.
  
  Each fixture yields ~2 judgment-item findings → **~25–30 findings total**, the floor κ needs. Label each finding: correct SC(s), conformance, severity. Version the set (`gold_version`).
  - **Single-labeller honesty:** one labeller has bias, and "judge-vs-human κ" is really judge-vs-one-person — spot-check every label against WCAG Understanding/Techniques and record disagreements in `notes`.
  - **Independence caveat (carry into T3's report):** findings from the same fixture are not statistically independent, so the *effective* n is below the raw finding count — one more reason the ~12-fixture spread beats a few dense fixtures, and why T3 reports **per-class counts**, not just an aggregate κ. Lean toward the higher end (~30).
  - Confirm empirically that each planted fixture actually lands in its whitelisted rule's **`passes[]`** result (→ `AxeBucket.PASSES`) — **not** `violations` (value too obviously bad → axe hard-decides it) and **not** `incomplete` — the way M1-T4 verified its incomplete fixtures. Don't assume: the planted value must be *present enough to pass* yet *poor enough to be a real WCAG failure*.
- **Acceptance:** ~12 fixtures spanning the categories above, together yielding **≥25 labelled judgment-item findings**; each `GoldLabel` is complete and versioned; the labelling basis (spot-check + disagreements) recorded; the fixtures reproducibly produce their judgment items (each via its whitelisted `passes[]` rule → `AxeBucket.PASSES`).
- **Out of scope:** expert-provided or physical gold (M6); a large test corpus; any forward-path change beyond the whitelisted `passes[] → judgment-finding` source.
- **Prereq (lands before the fixtures, as its own commits):** the scope amendment — `AxeBucket.PASSES` + `AxePass` / `ScanResult.passes` in CONTRACTS §3 + §6, and the scanner/normalizer emitting the four whitelisted `passes[]` rules as *reframed* quality-review judgment findings (`clearway/normalizer/quality_review.py`). The drafter also gains one additive prompt branch so it treats a PASSES finding as a quality-review task, not an already-conformant pass.
- **Depends on:** T0

### T2 — LLM-judge
- **Consumes:** a judgment-item `Finding` + its `DraftRow`. **Produces:** a `JudgeResult`.
- **Detail:** a **judge model that is not the drafter model** scores whether the drafted **citation SC(s)** and **conformance** are correct for the finding, on a rubric → `correct` / `incorrect` / `partial`, where **partial = one dimension right, the other wrong** (e.g. right SC, wrong conformance). Severity is *not* part of the verdict (noisier, lower-stakes). Use **rubric-based absolute scoring**, not pairwise, to avoid position bias.
  - **Judge model:** **`gpt-5.6-luna`** (OpenAI — a strong-reasoning frontier snapshot, clearly stronger than the local `gemma4:31b` drafter), via LiteLLM, temperature 0, fixed rubric prompt. **VERIFY** the exact snapshot id is available on the account before pinning (same discipline as the Ollama models); record `judge_model` + `judge_version` on the `JudgeResult`/trace. **Reproducibility caveat to state, not hide:** cloud models are not bit-reproducible even at temperature 0 — a pinned dated snapshot + temp 0 is the best determinism available.
  - Use the deterministic oracle where it exists — the judge is **only** for no-oracle judgment items (`ARCHITECTURE.md` §4.9), never for the axe-verifiable subset.
- **Acceptance:** returns a reproducible `JudgeResult` for a judgment item; judge model ≠ drafter model; `judge_model`/`judge_version`/temperature/prompt recorded; verdict decomposes into `citation_correct` + `conformance_correct`.
- **Out of scope:** judging verifiable items (the oracle already does); using the judge before it is calibrated (T3).
- **Optional stretch (out of the core critical path):** the "can a local model approximate the cloud judge?" experiment — run a local model as a second judge and compare to the reference judge. Feeds M5's local-vs-cloud choice; not required for M4 to ship.
- **Depends on:** T0

### T3 — judge calibration (judge-vs-human κ)  *(who watches the watchmen)*
- **Consumes:** the T1 gold set + a drafter pass over the gold items. **Produces:** the judge-vs-human κ + bias notes in the `CalibrationReport`.
- **Detail:** κ needs **both raters on the same categorical scale**, so the derivation is explicit:
  1. **Run the drafter over the gold-labelled findings** to produce real `DraftRow`s (the judge grades drafts, not gold directly — so drafts must exist first). This is a real dependency, not an aside.
  2. **Derive the human verdict** mechanically from each draft vs its `GoldLabel`: `citation_correct` = drafted SC(s) match `gold_success_criteria`; `conformance_correct` = drafted conformance matches `gold_conformance`; map to `correct` / `partial` / `incorrect` by the same rule the judge uses (T2).
  3. **Get the judge verdict** on the same drafts (T2).
  4. **Compute Cohen's κ** between the human-derived and judge verdict streams.
  - **Report honestly** (small n stays fragile even at ~30): κ **3-way and collapsed-to-binary**, alongside **raw agreement %** and **per-class counts**. **Pre-commit the trust threshold** (e.g. κ ≥ 0.6 "substantial") **before** looking at the number; set `judge_trusted` from it. **Only if the judge is trusted may it score models on non-gold items.**
  - **If the judge misses the bar, M4 does not ship it — and does not stop.** A trusted judge is non-negotiable: M5 is blocked without one, which is M4's whole reason to precede it. So iterate until a judge clears the bar — first tighten the rubric/prompt, then swap to a different / stronger judge model — re-running T3 each pass. The fallback model is **chosen at that point, not pre-named here**; record which model finally cleared the bar and at what κ.
  - **Bias checks:** rubric-based absolute scoring (position bias N/A); note any verbosity or self-preference tendency in `bias_notes`.
- **Acceptance:** judge-vs-human κ computed on the gold set with `n`, raw agreement, and per-class counts reported; the pre-committed threshold and the resulting `judge_trusted` are recorded; bias checks noted.
- **Out of scope:** scoring models on non-gold items until the judge passes.
- **Depends on:** T1, T2

### T4 — confidence-vs-correctness calibration
- **Consumes:** the trusted judge (judgment items) + the oracle (verifiable items) + `DraftRow.confidence`. **Produces:** the binned calibration curve (`CalibrationReport.confidence_bins`, counts included) **and** its two `EvalMetrics` scalars — `expected_calibration_error` (how far off) + `overconfidence_gap` (which direction). The full curve is not duplicated onto `EvalMetrics`.
- **Detail:** bin drafts by the drafter's self-reported confidence and measure correctness per bin — **oracle** for verifiable items, **trusted judge** for judgment items. Chart whether **low confidence tracks low correctness** — i.e. whether the system knows when it doesn't know. The M1/M2 reads make a **degenerate curve likely** (confidence clustered at 0.9–1.0, uninformative); **report that honestly with the bin counts** rather than dressing it up — a flat curve *is* the finding. Surface systematic over/under-confidence.
  - **Measure only — no drafter/elicitation change here.** The finding feeds M5 (see T5).
  - **Optional bounded diagnostic (your call, single-model, cheap):** re-elicit confidence once on the gold items via a verbalized-confidence-with-reasoning prompt and re-bin, purely to test whether a prompt change alone recovers any spread. If it does, cheap evidence for M5; if not, hard evidence the fix needs M5's multi-model signal. This does **not** change the shipped drafter.
- **Acceptance:** a confidence→correctness curve exists across bins with counts; the report states plainly whether confidence is calibrated, and where it isn't (including "not at all," if so).
- **Depends on:** T3

### T5 — calibration report + dashboard  *(deliverable)*
- **Produces:** the κ + calibration panels on the M2 dashboard (previously reserved placeholders, marked "M4") light up; a written **calibration report**.
- **Detail:** wire `judge_kappa` and the calibration curve into the reserved M2 dashboard panels (stable uid/panels — confirm they were reserved in M2's dashboard JSON). The **scalars** (`judge_kappa`, ECE, `overconfidence_gap`, …) export straight from `EvalMetrics` as gauges; the **curve** exports as a *labelled* gauge read from `CalibrationReport.confidence_bins` — e.g. `clearway_confidence_correctness{bin="0.6-0.8"}` — so the data lives once and is never copied onto `EvalMetrics`. Write the report: the judge's reliability (κ + raw agreement + threshold + trusted?) — **noted as judge-vs-one-labeller, not judge-vs-consensus, so κ is not over-read** — whether confidence is calibrated, where the judge or drafter systematically fails. **State the confidence requirement M4 hands M5 as an explicit M5 entry requirement** (M5-T0 picks it up): the drafter's confidence carries no usable signal, so M5 must either (a) synthesise a real confidence signal (self-consistency / cross-model disagreement) or (b) route by finding-class instead of confidence. Honest, trace-grounded — no flattering summary.
- **Acceptance:** the M2 κ/calibration panels populate from real data; the report answers "does the system know when it doesn't know?" with numbers and names concrete failure modes; the M5 confidence requirement is stated as an explicit M5 entry requirement.
- **Depends on:** T4
