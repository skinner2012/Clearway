"""The ACR/VPAT evidence block: write-all-in, and the per-row verification-state trust label.

Two things are pinned here.

**Write-all-in (already as-built, pinned so it stays that way).** The orchestrator appends every
assembled `DraftRow` to the shipped set; the *only* rows that never reach the report are the ones the
HITL gate holds back — a `NeedsReview` still `PENDING`, or one a specialist `REJECTED`. An
`APPROVED` / `EDITED` row ships. Nothing else filters rows out: not a low citation verdict, not a
hallucinated citation, not a weak finding class. The report tells the reader how far to trust a row;
it does not silently drop it.

**The trust label.** Each row carries one of three verification states — `oracle-verified`,
`human-reviewed`, `drafter-judged, unverified` — derived from the validator's `CitationVerdict`s and
the reviewer's `ReviewStatus`, and from nothing else. In particular **never** from
`DraftRow.confidence`, which is measured to carry no signal (single populated bin, values pinned
~0.85-1.0 regardless of correctness); sourcing a client-facing assurance from it would launder a
broken number. Both the behaviour and the absence of confidence from the derivation are asserted.

The prompt-identity tests at the bottom are this change's blast-radius receipt: the drafter's
`passes`-bucket prompt is a pure function of the finding, and this file pins its exact bytes, so a
report-layer change cannot silently perturb the model's input.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from clearway.cli import (
    _TRUST_DRAFTER_JUDGED,
    _TRUST_HUMAN_REVIEWED,
    _TRUST_ORACLE_VERIFIED,
    _render_drafts,
    _trust_label,
)
from clearway.drafter.llm import _system_prompt, _user_prompt
from clearway.normalizer.quality_review import QUALITY_REVIEW_RULES
from clearway.oracle import AxeCoreOracle
from clearway.orchestrator import InMemoryOrchestratorStore, execute
from clearway.schemas.models import (
    AxeBucket,
    Citation,
    CitationCheck,
    CitationVerdict,
    Conformance,
    ConformanceLevel,
    DraftRow,
    Finding,
    L1Status,
    NeedsReview,
    ReviewReason,
    ReviewStatus,
    Severity,
    Trace,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- builders ----------------------------------------------------------------


def _row(finding_id: str = "f1", **overrides: object) -> DraftRow:
    fields: dict[str, object] = {
        "finding_id": finding_id,
        "conformance": Conformance.DOES_NOT_SUPPORT,
        "citations": [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A)],
        "remediation": "Add an alt attribute to the image.",
        "severity": Severity.SERIOUS,
        "confidence": 0.9,
    }
    fields.update(overrides)
    return DraftRow(**fields)  # type: ignore[arg-type]


def _check(verdict: CitationVerdict, sc_id: str = "1.1.1") -> CitationCheck:
    """A `CitationCheck` whose L0/L1 fields are the ones the validator's decision table produces for
    `verdict` — so the fixture is a state the validator can actually emit, not an invented one."""
    if verdict is CitationVerdict.VERIFIED:
        return CitationCheck(sc_id=sc_id, l0_valid=True, l1_status=L1Status.MATCH, verdict=verdict)
    if verdict is CitationVerdict.UNVERIFIABLE:
        return CitationCheck(sc_id=sc_id, l0_valid=True, l1_status=L1Status.NO_ORACLE, verdict=verdict)
    return CitationCheck(sc_id=sc_id, l0_valid=True, l1_status=L1Status.MISMATCH, verdict=verdict)


def _trace(finding_id: str, checks: list[CitationCheck]) -> Trace:
    return Trace(
        run_id="r1",
        finding_id=finding_id,
        config_id="c1",
        model="m",
        checks=checks,
        created_at=_NOW,
    )


def _review(finding_id: str, status: ReviewStatus, draft: DraftRow | None = None) -> NeedsReview:
    return NeedsReview(
        run_id="r1",
        finding_id=finding_id,
        draft=draft if draft is not None else _row(finding_id),
        reason=ReviewReason.UNVERIFIABLE_JUDGMENT,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _finding(rule_id: str, bucket: AxeBucket, *, tags: list[str] | None = None) -> Finding:
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://page.html",
        rule_id=rule_id,
        axe_tags=tags if tags is not None else [],
        target="img",
        html="<img>",
        help="help text",
        impact=Severity.SERIOUS,
        source_bucket=bucket,
    )


def _spine_draft(finding: Finding, citations: list[Citation]) -> DraftRow:
    return _row(finding.id, citations=[c.model_copy() for c in citations])


def _rendered_labels(block: str) -> list[str]:
    """The label off each row's `Trust` line, in row order — the rendered label, not the legend."""
    return [line.split(" : ", 1)[1] for line in block.splitlines() if line.startswith("  Trust ")]


# --- write-all-in: only the review gate ever removes a row -------------------


def _execute_findings(findings: list[Finding], store: InMemoryOrchestratorStore) -> list[DraftRow]:
    drafts: list[DraftRow] = []
    execute(
        findings,
        run_id="r1",
        config_id="c1",
        model="m",
        created_at=_NOW,
        do_retrieve=lambda f: [Citation(sc_id="1.1.1", title="Non-text Content", level=ConformanceLevel.A)],
        do_draft=_spine_draft,
        oracle=AxeCoreOracle(),
        store=store,
        on_assembled=drafts.append,
    )
    return drafts


def test_every_oracle_backed_finding_is_written_into_the_report() -> None:
    """Write-all-in: no assembled row is filtered out of the evidence block. Three oracle-backed
    violations go in, three rows come out, and each finding id is named in the rendered report."""
    findings = [_finding(f"rule-{i}", AxeBucket.VIOLATIONS, tags=["wcag2a", "wcag111"]) for i in range(3)]
    drafts = _execute_findings(findings, InMemoryOrchestratorStore())
    assert [d.finding_id for d in drafts] == [f.id for f in findings]

    out = _render_drafts("page", drafts, [])
    assert "3 finding(s) drafted for evidence" in out
    for finding in findings:
        assert finding.id in out


def test_only_pending_and_rejected_rows_are_withheld() -> None:
    """The review gate is the sole exclusion. A judgment finding with no oracle verdict is gated:
    PENDING withholds it; a specialist's APPROVED / EDITED resolution puts it back in the report;
    REJECTED keeps it out."""
    finding = _finding("link-name", AxeBucket.PASSES)

    store = InMemoryOrchestratorStore()
    assert _execute_findings([finding], store) == []  # fresh flag -> PENDING -> withheld
    assert store.load_reviews()[0].status is ReviewStatus.PENDING

    for shipping_status in (ReviewStatus.APPROVED, ReviewStatus.EDITED):
        resolved = InMemoryOrchestratorStore()
        resolved.save_review(_review(finding.id, shipping_status, draft=_row(finding.id)))
        drafts = _execute_findings([finding], resolved)
        assert [d.finding_id for d in drafts] == [finding.id]

    rejected = InMemoryOrchestratorStore()
    rejected.save_review(_review(finding.id, ReviewStatus.REJECTED))
    assert _execute_findings([finding], rejected) == []


def test_a_hallucinated_citation_is_still_written_in() -> None:
    """A row the oracle contradicts is NOT dropped — it ships, labelled for what it is. Hiding it
    would take the failure out of the report and out of the hallucination rate at once."""
    row = _row("f1")
    out = _render_drafts("page", [row], [], traces=[_trace("f1", [_check(CitationVerdict.HALLUCINATED)])])
    assert "f1" in out
    assert _rendered_labels(out) == [_TRUST_DRAFTER_JUDGED]


# --- the label derives from verification state -------------------------------


def test_all_citations_verified_by_the_oracle_reads_oracle_verified() -> None:
    label = _trust_label(_row(), [_check(CitationVerdict.VERIFIED)], None)
    assert label == _TRUST_ORACLE_VERIFIED


def test_one_unverified_citation_downgrades_the_whole_row() -> None:
    """`oracle-verified` means every cited criterion was confirmed. One citation the oracle could not
    check is one unproven claim in the shipped row, so the row is not oracle-verified."""
    checks = [_check(CitationVerdict.VERIFIED), _check(CitationVerdict.UNVERIFIABLE, "2.4.4")]
    assert _trust_label(_row(), checks, None) == _TRUST_DRAFTER_JUDGED


def test_a_hallucinated_citation_never_reads_as_verified() -> None:
    """The oracle actively contradicted the cited criterion. It must land on the floor label, never
    on anything that reads as confirmation."""
    assert _trust_label(_row(), [_check(CitationVerdict.HALLUCINATED)], None) == _TRUST_DRAFTER_JUDGED


def test_a_row_citing_nothing_is_not_oracle_verified() -> None:
    """Vacuous truth is not verification: zero citations means the oracle confirmed zero claims."""
    assert _trust_label(_row(citations=[]), [], None) == _TRUST_DRAFTER_JUDGED


def test_no_verification_evidence_fails_closed() -> None:
    """A row whose checks are unavailable to the renderer labels down, never up."""
    assert _rendered_labels(_render_drafts("page", [_row("f1")], [])) == [_TRUST_DRAFTER_JUDGED]


def test_both_human_resolutions_read_as_human_reviewed() -> None:
    for status in (ReviewStatus.APPROVED, ReviewStatus.EDITED):
        assert _trust_label(_row(), [_check(CitationVerdict.UNVERIFIABLE)], status) == _TRUST_HUMAN_REVIEWED


def test_human_review_outranks_oracle_verification() -> None:
    """Precedence: a row a specialist signed reads `human-reviewed` even when its citations all
    verify. The oracle grounds cited criteria only — never the remediation prose, which on an edited
    row is the human's text — so the human is the accurate provenance for what the reader reads."""
    checks = [_check(CitationVerdict.VERIFIED)]
    assert _trust_label(_row(), checks, ReviewStatus.EDITED) == _TRUST_HUMAN_REVIEWED
    assert _trust_label(_row(), checks, None) == _TRUST_ORACLE_VERIFIED  # same row, no human: unchanged


def test_the_renderer_labels_each_row_from_its_own_verification_state() -> None:
    """Three rows, three states, in one block — the label is per row, not per report."""
    rows = [_row("verified"), _row("judged"), _row("signed")]
    traces = [
        _trace("verified", [_check(CitationVerdict.VERIFIED)]),
        _trace("judged", [_check(CitationVerdict.UNVERIFIABLE)]),
        _trace("signed", [_check(CitationVerdict.UNVERIFIABLE)]),
    ]
    out = _render_drafts("page", rows, [], traces=traces, reviewed=[_review("signed", ReviewStatus.APPROVED)])
    assert _rendered_labels(out) == [_TRUST_ORACLE_VERIFIED, _TRUST_DRAFTER_JUDGED, _TRUST_HUMAN_REVIEWED]


# --- the label NEVER derives from confidence ---------------------------------


def test_the_label_never_derives_from_confidence() -> None:
    """⚠️ The acceptance criterion. `DraftRow.confidence` is decorative and measurably broken
    (over-confidence gap +0.392, one populated bin, values pinned high regardless of correctness).
    Wiring it into a client-facing trust label would launder that broken number into an assurance.

    Asserted twice, so neither escape hatch is open:
    1. behaviourally — sweeping confidence across its whole range leaves every label, and the whole
       rendered block, byte-identical, for every verification state;
    2. structurally — the derivation's source code does not mention confidence at all, so a future
       edit that reads `row.confidence` fails here even if it happens not to change these fixtures.
    """
    states: list[tuple[list[CitationCheck], ReviewStatus | None]] = [
        ([_check(CitationVerdict.VERIFIED)], None),
        ([_check(CitationVerdict.UNVERIFIABLE)], None),
        ([_check(CitationVerdict.HALLUCINATED)], None),
        ([], None),
        ([_check(CitationVerdict.VERIFIED)], ReviewStatus.APPROVED),
        ([_check(CitationVerdict.UNVERIFIABLE)], ReviewStatus.EDITED),
    ]
    for checks, status in states:
        labels = {_trust_label(_row(confidence=c), checks, status) for c in (0.0, 0.25, 0.5, 0.85, 1.0)}
        assert len(labels) == 1, f"label moved with confidence for {checks} / {status}"

    blocks = {
        _render_drafts(
            "page", [_row("f1", confidence=c)], [], traces=[_trace("f1", [_check(CitationVerdict.VERIFIED)])]
        )
        for c in (0.0, 0.5, 1.0)
    }
    assert len(blocks) == 1  # the whole evidence block is confidence-independent

    source = inspect.getsource(_trust_label).replace(_trust_label.__doc__ or "", "")
    assert "confidence" not in source, "the trust label must not read confidence"


# --- `supports` never renders as a hard pass ---------------------------------


def test_supports_never_renders_as_a_hard_pass() -> None:
    """⚠️ The acceptance criterion. `supports` is the least-trustworthy row in the report: it is a
    'no problem here' claim, and it arises on the quality-review classes whose referent is weakest.
    It never renders as a bare verdict — the caveat that it is a claim rather than a confirmed pass
    travels with it in every verification state."""
    row = _row("f1", conformance=Conformance.SUPPORTS)
    for checks, reviewed in (
        ([_check(CitationVerdict.VERIFIED)], []),
        ([_check(CitationVerdict.UNVERIFIABLE)], []),
        ([], []),
        ([_check(CitationVerdict.VERIFIED)], [_review("f1", ReviewStatus.APPROVED)]),
    ):
        out = _render_drafts("page", [row], [], traces=[_trace("f1", checks)], reviewed=reviewed)
        assert "  Conformance : Supports" not in out.splitlines(), "bare 'Supports' reads as a hard pass"
        assert "Supports -- unverified claim, not a certified pass" in out
        assert _rendered_labels(out) != [_TRUST_ORACLE_VERIFIED], "a `supports` row is never oracle-verified"


def test_supports_is_never_oracle_verified() -> None:
    """The oracle grounds cited criteria, never a conformance verdict — and on the one bucket it does
    ground (`violations`) it positively contradicts a `supports` claim. So a verified citation on a
    `supports` row proves the citation, not the pass, and must not be relabelled as if it did."""
    row = _row(conformance=Conformance.SUPPORTS)
    assert _trust_label(row, [_check(CitationVerdict.VERIFIED)], None) == _TRUST_DRAFTER_JUDGED
    # …and a human signature still reads as exactly that, no more.
    assert _trust_label(row, [_check(CitationVerdict.VERIFIED)], ReviewStatus.APPROVED) == _TRUST_HUMAN_REVIEWED


def test_the_report_explains_its_labels() -> None:
    """An unexplained label is a decoration. The block states what each of the three states means."""
    out = _render_drafts("page", [_row("f1")], [])
    for label in (_TRUST_ORACLE_VERIFIED, _TRUST_HUMAN_REVIEWED, _TRUST_DRAFTER_JUDGED):
        assert label in out


# --- blast radius: the drafter's `passes` prompt is byte-identical ------------
#
# This change is report-layer only, so the model's input must be provably untouched. The prompt is a
# pure function of (finding, citations); the expected bytes below are written out here in full, in a
# file this change owns, so any drift in prompt assembly OR in the quality-review help text — the two
# inputs that compose a `passes`-bucket prompt — fails here.

_PASSES_FRAMING = (
    "a QUALITY-REVIEW item: axe confirmed a name/attribute is PRESENT but does NOT judge "
    "whether it is meaningful — assess the CONTENT's quality; present-but-inadequate is "
    "does_not_support or partially_supports, never supports"
)

# The frozen help text each quality-review class carries into its prompt.
_EXPECTED_HELP = {
    "link-name": (
        "The link has an accessible name — judge whether it describes the link's PURPOSE in "
        "context for WCAG 2.4.4; 'click here', 'read more', or a bare URL does NOT."
    ),
    "label": (
        "The form field has a programmatic label — judge whether it clearly identifies the "
        "field's PURPOSE for WCAG 1.3.1 / 3.3.2; a placeholder-as-label or a vague label does NOT."
    ),
    "document-title": (
        "The page has a non-empty <title> — judge whether it DESCRIBES the page's topic or purpose "
        "for WCAG 2.4.2; a generic 'Untitled' / 'Home' / boilerplate title does NOT."
    ),
    "empty-heading": (
        "The heading has non-empty text — judge whether it DESCRIBES the section's topic for "
        "WCAG 2.4.6; a generic or off-topic heading (e.g. 'Weather' over opening hours) does NOT."
    ),
}

# (rule_id, target, html) for the four classes under test.
_PASSES_CASES = [
    ("link-name", "a", '<a href="#desc">More</a>'),
    ("label", "input", '<input type="text" id="q">'),
    ("document-title", "html", '<html lang="en">'),
    ("empty-heading", "h2", "<h2>Weather</h2>"),
]


def _passes_finding(rule_id: str, target: str, html: str) -> Finding:
    """A `passes`-bucket finding shaped as the normalizer builds one: the whitelist's quality-review
    help REPLACES axe's rule help (`normalizer/normalize.py`)."""
    return Finding(
        id=f"h:{rule_id}",
        source_url="file://page.html",
        rule_id=rule_id,
        target=target,
        html=html,
        help=QUALITY_REVIEW_RULES[rule_id],
        source_bucket=AxeBucket.PASSES,
    )


def test_quality_review_help_text_is_unchanged() -> None:
    """The help is half of every `passes` prompt, so it is pinned with the assembly."""
    for rule_id, expected in _EXPECTED_HELP.items():
        assert QUALITY_REVIEW_RULES[rule_id] == expected


def test_passes_bucket_prompts_are_byte_identical() -> None:
    """⚠️ No `passes`-bucket prompt changed. The acceptance experiment is drawn entirely from this
    bucket, so this is the receipt that a report-layer change cannot have reached it."""
    for rule_id, target, html in _PASSES_CASES:
        expected = (
            f"Finding ({_PASSES_FRAMING}): axe rule '{rule_id}' — {_EXPECTED_HELP[rule_id]}\n"
            f"Target element: {target}\n"
            f"HTML: {html}\n"
            "Candidate WCAG success criteria you may cite:\n"
            "- (none retrieved)\n"
            "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
        )
        assert _user_prompt(_passes_finding(rule_id, target, html), []) == expected


def test_the_candidate_criteria_block_is_byte_identical() -> None:
    """The retrieved-candidates section of a `passes` prompt, pinned with real citations."""
    citations = [
        Citation(sc_id="2.4.4", url="https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html"),
        Citation(sc_id="4.1.2", url="https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"),
    ]
    expected = (
        f"Finding ({_PASSES_FRAMING}): axe rule 'link-name' — {_EXPECTED_HELP['link-name']}\n"
        "Target element: a\n"
        'HTML: <a href="#desc">More</a>\n'
        "Candidate WCAG success criteria you may cite:\n"
        "- 2.4.4 (https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html)\n"
        "- 4.1.2 (https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html)\n"
        "Draft the conformance verdict, the SC ids you cite, a one-sentence remediation, and your confidence."
    )
    assert _user_prompt(_passes_finding("link-name", "a", '<a href="#desc">More</a>'), citations) == expected


def test_the_system_prompt_is_byte_identical() -> None:
    """The system prompt is shared by every bucket, so it is pinned alongside the user prompt."""
    assert _system_prompt() == (
        "You are an accessibility specialist drafting ONE conformance row for a VPAT/ACR. "
        "Output ONLY a single JSON object matching the schema — no prose, no markdown, no code fences.\n"
        "Rules:\n"
        "- conformance: EXACTLY one of supports | partially_supports | does_not_support | not_applicable\n"
        "- cited_sc_ids: only WCAG SC ids from the provided candidates that genuinely apply (may be empty)\n"
        "- confidence: a DECIMAL number between 0 and 1 (e.g. 0.85), never a word\n"
        "- remediation: one concrete sentence on how to fix it\n"
        'Example: {"conformance":"does_not_support","cited_sc_ids":["1.1.1"],'
        '"remediation":"Add a descriptive alt attribute.","confidence":0.9}'
    )
