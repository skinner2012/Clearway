"""The judge's finding-side input, built once and frozen as the file both configurations read.

Why this exists at all
----------------------
A comparison of two judge configurations is only about the *draft* if everything else is held. The
"everything else" is the finding side of the prompt: the rule, the task, the target, the HTML, the
**referent** captured at scan time, and the **retrieved candidate criteria**. Since the referent
landed, the drafter has been reading material the judge never saw — so a judge asked to grade a
verdict formed from facts it does not hold is measuring an information asymmetry, not a difference of
judgment.

None of that material is on the frozen drafter run. A draft record holds `finding_id`, `target`,
`conformance`, `cited_sc_ids`, `confidence` and `remediation` — **no `Finding`**, so no `html`, no
`help`, no `referent`. Rebuilding it needs a live scan (the referent is captured inside the page
session; after `axe.run()` the DOM is gone) and live retrieval (pgvector + the embedder).

**So it is rebuilt here, once, and frozen.** Rebuilding it per configuration would make byte-identity
a claim about two code paths; freezing it makes byte-identity a property of one file, which is the
only version of that claim a later reader can check.

What the file deliberately does NOT carry
-----------------------------------------
No draft-side field appears on a row — not the drafted conformance, not the drafted citations. A
configuration that must not see the draft has to be able to read this file whole, and a row carrying
the answer beside the question would make that impossible to guarantee by inspection. The one place
the drafted citations are touched is the corroboration block below, which is provenance about the
candidate list and is never part of an input row.

⚠️ The candidate list is REBUILT, not RECOVERED
-----------------------------------------------
Nothing on disk records the candidate list the drafter actually answered. Retrieval is deterministic
on a frozen corpus, and every pin the artifact could match does match — but that is corroboration,
never verification, and `candidate_list_provenance` states both halves in the record itself so no
later reader mistakes this list for the one the drafter saw. What freezing *does* discharge is the
comparison this milestone tests: the two configurations demonstrably read the same bytes.

Freeze convention
-----------------
`created_at` is READ off the replay pass rather than generated, so the record is a deterministic
function of its sources and a rebuild on the same corpus and fixtures is byte-identical. Because that
rebuild needs live services, no test can perform it — so the record also carries a
`reproducible_digest` over itself, and the test pins that digest and re-checks every block against
its own hash.

Judge calls: **zero**. The scanner and the embedder are live; the judge is not called here at all, and
no judge object is even constructed — `judge_version` is deliberately not recorded (see `pins`).

Invoke: `uv run --env-file .env python -m clearway.eval.judge_finding_input`
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from clearway.drafter.llm import referent_blocks
from clearway.eval.run_scope import ACCEPTANCE, RunScope, cases_for
from clearway.judge import FindingInput, finding_input
from clearway.schemas.models import Citation, Finding

# The scope the replay pass covers: the acceptance case set, its four scored classes, its own minting.
SCOPE = ACCEPTANCE

# The two keys a rebuild may move relative to a hand edit: the digest is computed over everything else,
# so "did this record change?" stays answerable even though the record cannot be rebuilt in a test.
_VOLATILE_KEYS: tuple[str, ...] = ("reproducible_digest",)

REBUILT_NOT_RECOVERED = (
    "The candidate list on every row was REBUILT by re-running retrieval today; it was not recovered "
    "from the drafter's run, because the list the drafter was shown was never recorded anywhere. "
    "Retrieval is deterministic on a frozen corpus and every available pin matches (see corroboration), "
    "so this is the same list the same query returns — but that is corroboration, not verification. "
    "Freezing discharges the comparison this file exists for: both judge configurations read these "
    "bytes. It does NOT establish that the judge's input equals the drafter's."
)

CANNOT_ESTABLISH = (
    "What no check here can establish: (1) that the embedder returned the same vector then as now — the "
    "model is pinned by tag and the corpus_version welds the model and dimension to the stored vectors, "
    "but no per-query vector was retained; (2) the ordering among the criteria the drafter did NOT cite — "
    "the rank of each criterion it DID cite is recorded below, which is the whole of the order evidence "
    "that exists, and it says nothing about how the unchosen candidates were arranged around them; "
    "(3) that a drafted citation appearing in today's list, at whatever rank, proves the list is "
    "unchanged — a different list containing the same criterion at the same position would look "
    "identical on both checks; (4) anything about the drafter's own prompt, which was never frozen "
    "either. The honest status is the spec's: corroborated at best, never asserted as verified."
)

BOTH_CONFIGURATIONS_READ_THIS_FILE = (
    "Both judge configurations take their finding-side prompt from `rows[].finding_block`, verbatim, "
    "through `judge.Judge.judge_prepared`. The configuration that grades a draft appends its "
    "presentation of that draft AFTER this block; the configuration that never sees the draft sends the "
    "block alone. So the finding side is not merely equal across the two — it is the same bytes, and "
    "the test asserts that against this file rather than against a second rendering of it."
)


class RebuiltInputMismatch(RuntimeError):
    """The rebuilt finding set is not the frozen run's.

    Raised rather than reported. A finding-side input built over a different case set, a different
    element set, or differently-derived ids would still be a well-formed artifact — every row would
    render, every hash would check out, and the comparison it fed would silently be about other
    findings than the frozen drafts it is joined to.
    """


def _referent_sources(finding: Finding) -> list[str]:
    """Which referent sources the scan captured on this finding — the names, not the text.

    Recorded so a later read can say which classes carried what without parsing prose out of the
    block. An absent source is omitted; a present-but-empty one is named, because "no heading above the
    field" and "the heading is blank" are different facts and the scanner already keeps them apart.
    """
    if finding.referent is None:
        return []
    return [name for name, value in finding.referent.model_dump().items() if value is not None]


def _row(case: dict[str, Any], finding: Finding, citations: Sequence[Citation]) -> dict[str, Any]:
    """One finding-side input row: the identity to join on, and the block itself with its own digest.

    `referent_rendered` is keyed to the **boundary** — the drafter's own builder returning anything at
    all — and never to the block's text. Sniffing the rendered block for a phrase would key the answer
    to the data's surface: the block interpolates the page's raw multi-line HTML verbatim, so a fixture
    whose markup happened to contain the phrase would report a referent that was never injected, and
    that false positive would land hardest on the one class whose zero carries meaning. It cuts the
    other way too — the `label` block renders the section heading alone when no accessible name was
    resolved, which a name-shaped probe would miss. The builder is the fact; its output is not evidence
    about itself.
    """
    prepared = finding_input(finding, citations)
    return {
        "act_testcase_id": case["act_testcase_id"],
        "axe_rule": case["axe_rule"],
        "target": finding.target,
        "finding_id": finding.id,
        "referent_sources": _referent_sources(finding),
        "referent_rendered": referent_blocks(finding) != "",
        "candidate_sc_ids": [c.sc_id for c in citations],
        "finding_block": prepared.block,
        "finding_block_sha256": hashlib.sha256(prepared.block.encode()).hexdigest(),
    }


def rebuild_rows(scope: RunScope = SCOPE, retriever: Any = None) -> list[dict[str, Any]]:
    """Re-scan every case the scope covers and retrieve for every finding it mints — the live half.

    The scan is the scope's own minting, so the class definition and the asset handling are the ones
    the run used; retrieval is the production retriever, so the query composition and the candidate
    width are the drafter's. Neither is re-implemented here.
    """
    if retriever is None:  # pragma: no cover - live path
        from clearway.retriever import build_default_retriever

        retriever = build_default_retriever()
    rows: list[dict[str, Any]] = []
    for case in cases_for(scope):
        findings = scope.minting_findings(scope.root / case["path"], case["axe_rule"])
        for finding in findings:
            rows.append(_row(case, finding, retriever.retrieve(finding)))
    return rows


def replay_finding_map(artifact: dict[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    """`act_testcase_id → ((finding_id, target), …)` over the frozen pass, in artifact order."""
    return {
        case["act_testcase_id"]: tuple((d["finding_id"], d["target"]) for d in case["drafts"])
        for case in artifact["cases"]
        if case["drafts"]
    }


def rows_finding_map(rows: Sequence[dict[str, Any]]) -> dict[str, tuple[tuple[str, str], ...]]:
    """The same shape over the rebuilt rows, so the two can be compared directly rather than counted."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["act_testcase_id"], []).append((row["finding_id"], row["target"]))
    return {case: tuple(items) for case, items in grouped.items()}


def assert_matches_replay_pass(rows: Sequence[dict[str, Any]], replay: dict[str, Any]) -> dict[str, Any]:
    """Refuse a rebuild that is not over the frozen pass's own cases, elements and ids.

    `finding_id` is checked as well as `target`, and that is the stronger half: the id hashes the case's
    `file://` URL, so reproducing it says the scan ran over the same file in the same place and minted
    the same element. A rebuild that matched on targets but not on ids would still join to the frozen
    drafts by target and would be a different scan.
    """
    theirs, ours = replay_finding_map(replay), rows_finding_map(rows)
    if theirs != ours:
        missing = sorted(set(theirs) - set(ours))
        extra = sorted(set(ours) - set(theirs))
        changed = sorted(k for k in set(theirs) & set(ours) if theirs[k] != ours[k])
        raise RebuiltInputMismatch(
            "the rebuilt finding-side input is not over the frozen pass's findings: "
            f"{len(missing)} case(s) absent, {len(extra)} extra, {len(changed)} minting different "
            f"element(s) or id(s) (absent={missing[:3]}, extra={extra[:3]}, changed={changed[:3]}). "
            "The judge's input has to be the input for the drafts it will be compared against."
        )
    return {
        "cases": len(ours),
        "findings": sum(len(v) for v in ours.values()),
        "finding_ids_and_targets_identical_to_the_replay_pass": True,
        "checked": "act_testcase_id → ((finding_id, target), …), compared as a whole rather than counted",
    }


def drafted_citations_inside_the_candidates(rows: Sequence[dict[str, Any]], replay: dict[str, Any]) -> dict[str, Any]:
    """The one corroboration the artifacts can actually supply: could the drafter have cited what it did?

    The drafter is instructed to cite only from the candidates it was shown, but nothing enforces it —
    `_resolve_citations` lets an unretrieved id through precisely so a hallucinated citation stays
    visible. So a drafted SC that is absent from today's rebuilt list is either a list that moved or a
    drafter that went off-list, and the two are not separable here; a drafted SC that is present is
    consistent with the list being the one it answered. **That asymmetry is the whole strength of this
    check, and it is weaker than identity.** Rows that cite nothing carry no information either way and
    are counted separately rather than folded in.

    The **rank** of each cited criterion in today's ordered list is counted here too, for the reason the
    spec applies to itself elsewhere: an available check recorded as impossible is the inverse of
    declining one deliberately. Membership is the set half of the evidence and rank is the order half —
    both weak, and the second strictly stronger than the first.
    """
    ordered = {row["finding_id"]: list(row["candidate_sc_ids"]) for row in rows}
    citing = 0
    inside = 0
    outside: list[dict[str, str]] = []
    ranks: Counter[int] = Counter()
    for case in replay["cases"]:
        for draft in case["drafts"]:
            cited = list(draft["cited_sc_ids"])
            if not cited:
                continue
            citing += 1
            candidates = ordered[draft["finding_id"]]
            missing = sorted(set(cited) - set(candidates))
            if missing:
                outside.append(
                    {"finding_id": draft["finding_id"], "sc_ids_not_in_todays_candidates": ",".join(missing)}
                )
            else:
                inside += 1
            ranks.update(candidates.index(sc) + 1 for sc in cited if sc in candidates)
    return {
        "drafts_citing_at_least_one_sc": citing,
        "drafts_whose_every_cited_sc_is_in_todays_candidate_list": inside,
        "drafts_citing_outside_todays_candidate_list": outside,
        "drafts_citing_nothing": sum(len(c["drafts"]) for c in replay["cases"]) - citing,
        "cited_sc_instances_ranked": sum(ranks.values()),
        "rank_of_each_cited_sc_in_todays_ordered_list": {str(k): v for k, v in sorted(ranks.items())},
        "reading": (
            "A citation inside the rebuilt list is consistent with the list being the one the drafter "
            "answered; a citation outside it would be either a moved list or a drafter that ignored its "
            "candidates, and nothing on disk separates those two. This corroborates and cannot verify. "
            "The rank histogram is the ORDER half of the same weak evidence, recorded because it exists "
            "rather than because it settles anything: the drafter was told to cite the single most "
            "applicable candidate, so citations clustered at the head of today's ordering are consistent "
            "with today's ordering being the one it read, and a citation at the tail would have been the "
            "interesting result. It says nothing about how the criteria the drafter did NOT cite were "
            "arranged — see `cannot_establish`."
        ),
    }


def gold_sc_reachability(rows: Sequence[dict[str, Any]], replay: dict[str, Any]) -> dict[str, Any]:
    """Is each case's ACT gold criterion inside the candidate list its findings were shown?

    **⚠️ Retrieval ADEQUACY, not provenance — which is why it sits outside the corroboration block.** It
    says the shared prior is not degenerate: both readers can reach the criterion the gold names, so the
    SC axis is measuring raters rather than a retriever that never surfaced the answer. It is no evidence
    at all that today's list is the drafter's — a list rebuilt from a different corpus could contain the
    gold criterion too, and this check would look identical.

    Counted on two denominators because they answer differently: per **finding** (does this finding's list
    cover its case's whole gold set) and per **gold-SC instance** (one count per finding-criterion pair,
    which is the denominator that notices a case whose gold names more than one criterion).
    """
    gold_of = {case["act_testcase_id"]: list(case["gold_success_criteria"]) for case in replay["cases"]}
    findings_covered = 0
    instances = covered_instances = 0
    gaps: list[dict[str, str]] = []
    for row in rows:
        gold = gold_of[row["act_testcase_id"]]
        candidates = set(row["candidate_sc_ids"])
        instances += len(gold)
        covered_instances += sum(1 for sc in gold if sc in candidates)
        if set(gold) <= candidates:
            findings_covered += 1
        else:
            gaps.append(
                {
                    "finding_id": row["finding_id"],
                    "gold_sc_ids_not_retrieved": ",".join(sorted(set(gold) - candidates)),
                }
            )
    return {
        "findings": len(rows),
        "findings_whose_candidate_list_covers_their_whole_gold_set": findings_covered,
        "gold_sc_instances": instances,
        "gold_sc_instances_inside_the_candidate_list": covered_instances,
        "findings_with_an_unreachable_gold_criterion": gaps,
        "reading": (
            "A gold criterion outside the candidate list would mean the criterion the case turns on was "
            "unreachable for BOTH readers, and the SC axis on that finding would be measuring the "
            "retriever rather than either rater. Full coverage is what makes a candidate list that is "
            "constant within a class a shared prior rather than a shared blind spot. Adequacy only: it "
            "says nothing about whether this list is the one the drafter saw."
        ),
    }


def _per_class(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which classes carry referent material, and how wide their candidate lists came back.

    The referent columns are the asymmetry inherited from the drafter: a class with no referent
    injection contributes no referent line to either reader, and a per-class read of the comparison has
    to know that rather than discover it.
    """
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_rule.setdefault(row["axe_rule"], []).append(row)
    return [
        {
            "axe_rule": rule,
            "findings": len(group),
            "findings_with_a_rendered_referent": sum(1 for r in group if r["referent_rendered"]),
            "referent_sources_captured": sorted({s for r in group for s in r["referent_sources"]}),
            "candidates_per_finding": {
                str(k): v for k, v in sorted(Counter(len(r["candidate_sc_ids"]) for r in group).items())
            },
            "distinct_candidate_lists": len({tuple(r["candidate_sc_ids"]) for r in group}),
        }
        for rule, group in sorted(by_rule.items())
    ]


def record_digest(record: dict[str, Any]) -> str:
    """sha256 over the record minus its own digest — what the freeze test pins."""
    stable = {k: v for k, v in record.items() if k not in _VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_record(
    *,
    rows: Sequence[dict[str, Any]],
    replay_path: Path,
    corpus_version: str,
    scope: RunScope = SCOPE,
) -> dict[str, Any]:
    """Assemble the record. Pure given the rebuilt rows, so its whole shape is testable offline."""
    replay = json.loads(replay_path.read_text())
    record: dict[str, Any] = {
        "artifact": "the judge's finding-side prompt input, frozen once for both configurations",
        "version": 1,
        "judge_calls_spent": 0,
        "created_at": replay["created_at"],
        "both_configurations_read_this_file": BOTH_CONFIGURATIONS_READ_THIS_FILE,
        "carries_no_draft_side_field": (
            "No row carries the drafted conformance or the drafted citations. The configuration that "
            "must not see the draft reads whole rows from this file, so the file cannot hold the answer."
        ),
        "sources": {
            "replay_pass": {
                "path": replay_path.name,
                "sha256": hashlib.sha256(replay_path.read_bytes()).hexdigest(),
                "config_id": replay["config_id"],
                "eval_set_id": replay["eval_set_id"],
                "corpus_version": replay["corpus_version"],
                "axe_core_version": replay["axe_core_version"],
                "act_export_hash": replay["act_export_hash"],
                "created_at": replay["created_at"],
            },
            "scope": {
                "scope_id": scope.scope_id,
                "manifest": scope.manifest.name,
                "eval_set_id": scope.eval_set_id,
                "axe_rules": list(scope.axe_rules),
            },
        },
        "pins": {
            "corpus_version": corpus_version,
            "retrieval_query": "the axe rule id + the finding's help text, as `Retriever._query_text` composes it",
            "normative_text_budget_chars": _normative_text_budget(),
            "no_judge_version_here_and_that_is_deliberate": (
                "`judge_version` is the sha256 of the judge's SYSTEM rubric plus its reasoning effort, and "
                "it is NOT recorded on this file. Three reasons, and the first decides it: the string is "
                "SCHEDULED TO MOVE — extending the rubric hash to cover the finding-side template is an "
                "open decision — and a field that moves for a reason unrelated to this record's content "
                "would make a rebuild indistinguishable from an edit, which is precisely the volatile-field "
                "defect the pre-flight record already has to be repaired for. Second, it is a property of "
                "the JUDGE while this file is deliberately configuration-independent: the two "
                "configurations that read these bytes will carry different version strings. Third, nothing "
                "here could validate it against a live `Judge`, so it would go stale silently. The "
                "provenance this file does carry is per-block — every row's own sha256 — and the template's "
                "tripwire is a whole-prompt literal in the judge's tests, which is where a template edit "
                "fails."
            ),
        },
        "candidate_list_provenance": {
            "rebuilt_not_recovered": True,
            "statement": REBUILT_NOT_RECOVERED,
            "corroboration": {
                "corpus_version_matches_the_replay_pass": corpus_version == replay["corpus_version"],
                "axe_core_version_matches_the_replay_pass": _axe_version() == replay["axe_core_version"],
                "act_export_hash_matches_the_replay_pass": _act_export_hash() == replay["act_export_hash"],
                "finding_set": assert_matches_replay_pass(rows, replay),
                "drafted_citations": drafted_citations_inside_the_candidates(rows, replay),
            },
            "cannot_establish": CANNOT_ESTABLISH,
        },
        "retrieval_adequacy": gold_sc_reachability(rows, replay),
        "per_class": _per_class(rows),
        "rows": list(rows),
    }
    return {**record, "reproducible_digest": record_digest(record)}


def _normative_text_budget() -> int:
    from clearway.drafter.llm import NORMATIVE_TEXT_CHARS

    return NORMATIVE_TEXT_CHARS


def _axe_version() -> str:
    from clearway.scanner import AXE_VERSION

    return AXE_VERSION


def _act_export_hash() -> str:
    from clearway.eval.act_gold import _EXPORT_SHA256

    return _EXPORT_SHA256


def report_path() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR / "judge_finding_input.json"


def load_record(path: Path | None = None) -> dict[str, Any]:
    """The frozen record, with every block re-checked against its own digest before it is handed out.

    Checked on the way in rather than trusted: this file is the input two configurations send to a paid
    model, and a block that no longer matches its recorded hash means the bytes being sent are not the
    bytes that were frozen — which is exactly the thing the freeze exists to rule out.
    """
    record = dict(json.loads((path or report_path()).read_text()))
    for row in record["rows"]:
        actual = hashlib.sha256(row["finding_block"].encode()).hexdigest()
        if actual != row["finding_block_sha256"]:
            raise RebuiltInputMismatch(
                f"finding {row['finding_id']} carries a block that does not match its recorded digest "
                f"({row['finding_block_sha256'][:12]}… vs {actual[:12]}…) — the frozen input has been "
                "edited in place, so it is no longer the input either configuration was frozen against"
            )
    return record


def prepared_inputs(record: dict[str, Any]) -> dict[str, FindingInput]:
    """`finding_id → FindingInput` — what a configuration hands to `Judge.judge_prepared`.

    The only sanctioned way to read this file into a judge call, so neither configuration can re-render
    the finding side by accident: there is nothing here to render from.
    """
    return {
        row["finding_id"]: FindingInput(finding_id=row["finding_id"], block=row["finding_block"])
        for row in record["rows"]
    }


def main() -> None:
    """Rebuild the finding-side input live and freeze it. Zero judge calls; the scanner and the
    embedder are live, and the run refuses if the rebuilt findings are not the frozen pass's."""
    from clearway.eval.run_artifacts import CITATION_GROUNDING, run_path
    from clearway.retriever import build_default_retriever

    replay_path = run_path(CITATION_GROUNDING, 1)
    retriever = build_default_retriever()
    print(f"rebuilding the judge's finding-side input over {SCOPE.scope_id} — 0 judge calls", flush=True)
    rows = rebuild_rows(SCOPE, retriever)
    record = build_record(rows=rows, replay_path=replay_path, corpus_version=retriever.corpus_version)
    corroboration = record["candidate_list_provenance"]["corroboration"]
    print(f"  {corroboration['finding_set']['findings']} findings over {corroboration['finding_set']['cases']} cases")
    for row in record["per_class"]:
        print(
            f"  {row['axe_rule']:<15} n={row['findings']:<3} referent rendered "
            f"{row['findings_with_a_rendered_referent']}/{row['findings']}  candidate lists "
            f"{row['distinct_candidate_lists']} distinct"
        )
    cited = corroboration["drafted_citations"]
    print(
        f"  corroboration: {cited['drafts_whose_every_cited_sc_is_in_todays_candidate_list']}"
        f"/{cited['drafts_citing_at_least_one_sc']} citing drafts cite inside today's candidates "
        f"({cited['drafts_citing_nothing']} cite nothing) — REBUILT, not recovered"
    )

    path = report_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {path.relative_to(Path.cwd())} — 0 judge calls")
    print(f"reproducible digest {record['reproducible_digest'][:12]}…")


if __name__ == "__main__":
    main()
