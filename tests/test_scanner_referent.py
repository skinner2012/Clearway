"""Referent extraction: the deterministic, bounded per-node material the scanner captures.

The referent is the thing you must be able to see to make the judgment. axe hands us the
offending element and nothing around it, so a judgment that depends on the page — is this
title descriptive? does this label name the field? where does this link point? — is being
asked of an input that cannot answer it. `clearway/scanner/referent.py` captures that
material inside the live page session and rides it through `AxeNode` -> `Finding`.

What these tests hold down, in order of how much a failure would cost:

1. **`Finding.id` does not move.** It hashes (source_url, rule_id, target); referent material
   must stay out of it, or per-case paired comparisons against a frozen verdict vector break.
2. **No prompt moved.** Capturing material is not injecting it. The drafter prompt must be
   byte-identical whether or not a finding carries a referent.
3. **Bounded for real pages, not for these fixtures.** Every extractor has a named source, a
   pinned budget and a deterministic truncation rule, reviewed against a vendored snapshot of
   a real 57k-character page whose extracted output is committed next to it.
4. **Deterministic across repeat scans**, so a frozen run reproduces.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from clearway.drafter.llm import _system_prompt, _user_prompt
from clearway.normalizer.normalize import normalize
from clearway.scanner import scan
from clearway.scanner.referent import (
    BUDGETS,
    CONTEXT_ANCESTOR_MAX_DEPTH,
    REAL_PAGE_REFERENTS,
    REAL_PAGE_SNAPSHOT,
)
from clearway.schemas.models import (
    AxeBucket,
    AxeNode,
    AxePass,
    Citation,
    Finding,
    NodeReferent,
    ReferentExcerpt,
    ReferentSource,
    ScanResult,
)

FIXTURES = Path(__file__).resolve().parent.parent / "clearway" / "fixtures"
PAGES = FIXTURES / "pages"
ACT_HTML = FIXTURES / "act-gold" / "html"


def _referent() -> NodeReferent:
    """A fully-populated referent — every extractor present, so anything that leaks it into an
    id or a prompt has the widest possible chance to show."""
    return NodeReferent(
        accessible_name=ReferentExcerpt(text="First name:", source=ReferentSource.ACCESSIBLE_NAME),
        document_title=ReferentExcerpt(text="Apple harvesting season", source=ReferentSource.DOCUMENT_TITLE),
        page_topic=ReferentExcerpt(text="Clementines will be ready to harvest.", source=ReferentSource.H1),
        section_heading=ReferentExcerpt(
            text="Shipping", source=ReferentSource.NEAREST_SECTION_HEADING, in_accessibility_tree=True
        ),
        surrounding_context=ReferentExcerpt(
            text="Download Ulysses in HTML", source=ReferentSource.ANCESTOR_TEXT, ancestor_depth=2
        ),
    )


def _scan_result(*, with_referent: bool) -> ScanResult:
    node = AxeNode(target=["#fname"], html='<input id="fname">', referent=_referent() if with_referent else None)
    return ScanResult(
        url="file:///page.html",
        scanned_at="2026-07-23T00:00:00Z",  # type: ignore[arg-type]  # pydantic parses the ISO string
        tool_version="4.12.1",
        passes=[AxePass(rule_id="label", tags=["wcag412"], help="Form elements must have labels", nodes=[node])],
    )


# ---------------------------------------------------------------------------
# 1. Finding.id must not move
# ---------------------------------------------------------------------------


def test_referent_material_does_not_enter_the_finding_id() -> None:
    """`Finding.id` hashes (source_url, rule_id, target) — the *place*. If referent material
    entered it, the same element would hash differently once the scanner learned to look
    around it, and every frozen per-case verdict would stop pairing."""
    without = normalize(_scan_result(with_referent=False))
    with_ = normalize(_scan_result(with_referent=True))
    assert [f.id for f in without] == [f.id for f in with_]
    assert with_[0].referent == _referent(), "the material must still be carried, just not hashed"


def test_the_finding_id_of_a_real_scan_is_unchanged_by_extraction() -> None:
    """The pinned id for the `label` finding on the M0 fixture, computed before extraction
    existed. A literal, so a refactor of the hash inputs cannot quietly agree with itself."""
    findings = normalize(scan(str(PAGES / "home.html")))
    label = next(f for f in findings if f.rule_id == "label" and f.source_bucket is AxeBucket.VIOLATIONS)
    assert label.id == hashlib.sha256(f"{label.source_url}|label|{label.target}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 2. No prompt moved
# ---------------------------------------------------------------------------


def test_the_drafter_prompts_are_byte_identical_with_and_without_a_referent() -> None:
    """Capturing the material is not injecting it. Referent injection is per-class and lands in a
    sibling change; the CONTROL class `empty-heading` is never injected, so its prompt must stay
    byte-identical whether or not a referent rides along — the anchor that proves the instrument
    works (M7: if injection leaks into the control, the comparison means nothing). The classes that
    ARE injected are pinned verbatim in their own injection tests (test_referent_injection_label)."""
    citations = [Citation(sc_id="2.4.6", url="https://www.w3.org/WAI/WCAG22/#headings-and-labels")]
    bare = Finding(
        id="x",
        source_url="file:///p.html",
        rule_id="empty-heading",
        target="#fname",
        html='<input id="fname">',
        source_bucket=AxeBucket.PASSES,
    )
    carrying = bare.model_copy(update={"referent": _referent()})
    assert _user_prompt(bare, citations) == _user_prompt(carrying, citations)


def test_the_drafter_prompt_text_is_pinned() -> None:
    """The CONTROL (`empty-heading`) prompt pinned to a hash of its exact bytes, carrying a full
    referent. A hash catches what two-calls-agree cannot: an injection that leaked into the control
    would move this even while the with/without comparison stayed internally consistent — so this is
    M7's "the control holds, byte-identical by test" as a byte-exact pin. The injected `label`
    prompt's bytes are checked verbatim in test_referent_injection_label, not here."""
    citations = [Citation(sc_id="2.4.6", url="https://www.w3.org/WAI/WCAG22/#headings-and-labels")]
    finding = Finding(
        id="x",
        source_url="file:///p.html",
        rule_id="empty-heading",
        target="#fname",
        html='<input id="fname">',
        help="Assess whether the heading is meaningful",
        source_bucket=AxeBucket.PASSES,
        referent=_referent(),
    )
    system = hashlib.sha256(_system_prompt().encode()).hexdigest()
    user = hashlib.sha256(_user_prompt(finding, citations).encode()).hexdigest()
    assert system == "61863e4570cd6b80bc9c48bf9fecd7f61e15835794793c29ddae70046dbed2ad"
    assert user == "1e1de624d83f54fbc96215c4a71d47ac0b47641fa499e03fdd96a5d03b4ecaa6"


# ---------------------------------------------------------------------------
# 3. Availability is distinguishable from emptiness
# ---------------------------------------------------------------------------


def test_absent_material_is_none_and_present_but_empty_material_is_an_empty_string() -> None:
    """A consumer must be able to tell "this page has no title" from "this page's title is
    blank" — the second is a finding about the page, the first is a gap in our input."""
    absent = NodeReferent()
    assert absent.document_title is None
    present_but_empty = ReferentExcerpt(text="", source=ReferentSource.DOCUMENT_TITLE)
    assert present_but_empty.text == ""


def test_referent_shapes_are_strict_and_default_to_absent() -> None:
    """Optional-with-default, so every already-frozen artifact still validates under
    `extra="forbid"`; strict, so a typo in an extractor is a failure rather than a silent key."""
    assert AxeNode(target=["#a"]).referent is None
    assert Finding(id="x", source_url="u", rule_id="r", target="#a").referent is None
    with pytest.raises(ValueError):
        NodeReferent(page_title="oops")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        ReferentExcerpt(text="t", source=ReferentSource.H1, budget=10)  # type: ignore[call-arg]


def test_a_payload_written_before_extraction_existed_still_validates() -> None:
    """Why the fields are Optional-with-default rather than required. Both shapes are
    `extra="forbid"`, and findings are persisted (orchestrator checkpoints, review records) by
    processes that ran before this ticket. A payload with no `referent` key must still load,
    and must load as *absent* rather than as an empty referent."""
    node = AxeNode(target=["#a"], html="<a>").model_dump()
    finding = Finding(id="x", source_url="u", rule_id="r", target="#a").model_dump()
    del node["referent"], finding["referent"]
    assert AxeNode.model_validate(node).referent is None
    assert Finding.model_validate(finding).referent is None


def test_the_frozen_baseline_artifacts_are_untouched() -> None:
    """The paired comparison's left-hand side. Capturing referent material must not disturb it —
    these files are read, never rewritten, by anything in this ticket."""
    benchmark = Path(__file__).resolve().parent.parent / "benchmark"
    frozen = sorted(benchmark.glob("runs/run_*.json")) + [benchmark / "reports" / "verdict_vector.json"]
    for path in frozen:
        payload = json.loads(path.read_text())
        assert payload["axe_core_version"] == "4.12.1", f"{path.name}: pinned engine must not drift"
        assert "referent" not in path.read_text(), f"{path.name}: predates extraction and stays that way"


# ---------------------------------------------------------------------------
# 4. Bounded, named, deterministic — reviewed against a real page
# ---------------------------------------------------------------------------


def test_every_budget_is_a_pinned_positive_constant() -> None:
    assert set(BUDGETS) == {
        "accessible_name",
        "document_title",
        "page_topic",
        "section_heading",
        "surrounding_context",
        "context_ancestor_max_depth",
    }
    assert all(isinstance(v, int) and v > 0 for v in BUDGETS.values())
    assert BUDGETS["context_ancestor_max_depth"] == CONTEXT_ANCESTOR_MAX_DEPTH == 3


def _excerpts(referent: NodeReferent) -> list[tuple[str, ReferentExcerpt]]:
    return [(name, value) for name, value in referent if isinstance(value, ReferentExcerpt)]


def _assert_within_budget(referent: NodeReferent) -> None:
    for name, excerpt in _excerpts(referent):
        assert len(excerpt.text) <= BUDGETS[name], f"{name} exceeded its pinned budget"
        assert excerpt.truncated == (len(excerpt.text) == BUDGETS[name] or excerpt.truncated)


def test_the_real_page_snapshot_and_its_extracted_output_are_both_vendored() -> None:
    """The review artifact. Extraction reviewed against fixtures alone would be reviewed against
    2-220 character bodies — "dump the whole body" scores perfectly there and is useless on a
    real page. So the review runs on a vendored snapshot of a named, live page, and its output
    is committed so the review is auditable rather than attested."""
    assert REAL_PAGE_SNAPSHOT.is_file()
    assert (REAL_PAGE_SNAPSHOT.parent / "NOTICE").is_file(), "provenance: URL, retrieval date, licence"
    assert REAL_PAGE_REFERENTS.is_file()


def test_extraction_on_the_real_page_reproduces_the_committed_output() -> None:
    """Re-extracts against the vendored snapshot and compares to the committed fixture. This is
    both the real-page review and the strongest determinism check available offline."""
    expected = json.loads(REAL_PAGE_REFERENTS.read_text())
    findings = normalize(scan(str(REAL_PAGE_SNAPSHOT)))
    actual = {f"{f.rule_id} {f.target}": (f.referent.model_dump(mode="json") if f.referent else None) for f in findings}
    assert actual == expected["referents"]


def test_the_real_page_is_large_enough_for_the_review_to_mean_anything() -> None:
    """If the review page were fixture-sized, the review would prove nothing about budgets."""
    expected = json.loads(REAL_PAGE_REFERENTS.read_text())
    assert expected["page"]["rendered_body_chars"] > 5_000
    assert expected["page"]["html_chars"] > 50_000


def test_no_extractor_degenerates_into_the_whole_page_on_the_real_page() -> None:
    """The failure this ticket is written against: an extractor that is really "dump the body".
    On a 10k-character body every excerpt must still sit inside its pinned budget, and the
    body-text topic tier must not be what answers, because a real page has an h1."""
    expected = json.loads(REAL_PAGE_REFERENTS.read_text())
    body_chars = expected["page"]["rendered_body_chars"]
    seen_sources = set()
    for payload in expected["referents"].values():
        if payload is None:
            continue
        referent = NodeReferent.model_validate(payload)
        _assert_within_budget(referent)
        for _, excerpt in _excerpts(referent):
            seen_sources.add(excerpt.source)
            assert len(excerpt.text) < body_chars, "an excerpt the size of the page is not an excerpt"
    assert ReferentSource.RENDERED_BODY_TEXT not in seen_sources, "the body tier is the last resort, not the answer"


def test_the_context_window_stays_near_the_node_on_a_real_page() -> None:
    """Prefix-truncating a large ancestor would return the top of the page instead of the
    node's neighbourhood. The window is centred on the node's own text, so a truncated context
    must still contain something from around the node, not the masthead."""
    expected = json.loads(REAL_PAGE_REFERENTS.read_text())
    truncated = [
        NodeReferent.model_validate(p).surrounding_context
        for p in expected["referents"].values()
        if p is not None and p.get("surrounding_context") and p["surrounding_context"]["truncated"]
    ]
    assert truncated, "a 57k-character page must exercise context truncation, or the review is vacuous"
    for context in truncated:
        assert context is not None
        assert len(context.text) == BUDGETS["surrounding_context"]
        assert context.ancestor_depth is not None and 1 <= context.ancestor_depth <= CONTEXT_ANCESTOR_MAX_DEPTH


# ---------------------------------------------------------------------------
# 5. Determinism, and behaviour on the fixtures the acceptance set actually uses
# ---------------------------------------------------------------------------


def test_extraction_is_deterministic_across_repeat_scans() -> None:
    """Same page scanned twice -> byte-identical referents. A run is frozen once and every
    downstream number is a pure function of it, so extraction that drifted between scans would
    make the freeze a lie."""
    first = {f.target: f.referent for f in normalize(scan(str(PAGES / "home.html")))}
    second = {f.target: f.referent for f in normalize(scan(str(PAGES / "home.html")))}
    assert first == second
    assert any(r is not None for r in first.values()), "home.html must yield referent material at all"


# The five held-out `document-title` cases, by ACT testcase id -> the <title> each one carries.
# The drafter's whole input for all five is `Target: html` / `HTML: <html lang="en">`; the title
# is nowhere in it. That is why the class produces one prompt for five cases.
DOCUMENT_TITLE_CASES = {
    "30012df5a74ec5df2f74d8522c451233882d5f3a": "Clementine harvesting season",
    "23ecf6c48bb8c1619c59cdbc5fe2e6def8f80d6e": "Clementine harvesting season",
    "5e5cb1efed740d903d45d885d47363a5b068274f": "Clementine harvesting season",
    "64ad3868e9022dcfa3f8ba5a3ac1943fd1a9a240": "Apple harvesting season",
    "e53e988e29ce9f96fb282825cc089df9b5b65753": "First title is incorrect",
}


def test_the_document_title_is_captured_where_the_drafter_has_never_seen_it() -> None:
    """The capability, on the class that most needs it: the resolved title now rides on the
    finding. This ticket does not inject it — it makes injection possible."""
    for testcase_id, title in DOCUMENT_TITLE_CASES.items():
        findings = [f for f in normalize(scan(str(ACT_HTML / f"{testcase_id}.html"))) if f.rule_id == "document-title"]
        assert findings, f"{testcase_id}: expected a document-title finding"
        for finding in findings:
            assert finding.target == "html", "the element snippet really is just <html …>"
            assert title not in finding.html, "…which is why the title has to be captured separately"
            assert finding.referent is not None and finding.referent.document_title is not None
            assert finding.referent.document_title.text == title


def test_the_topic_signal_never_carries_a_title_that_lives_inside_the_body() -> None:
    """One vendored case places `<title>` inside `<body>`. A `textContent`-based topic tier
    would hand that case its own correct answer and score a fix that never happened. The tier
    reads rendered text, where a `display:none` title is not present."""
    leaky = ACT_HTML / "5e5cb1efed740d903d45d885d47363a5b068274f.html"
    body = leaky.read_text().split("<body", 1)[1]
    assert "<title>" in body, "the leak-prone fixture must still be leak-prone, or this guards nothing"
    for finding in normalize(scan(str(leaky))):
        assert finding.referent is not None and finding.referent.page_topic is not None
        assert finding.referent.page_topic.source is ReferentSource.RENDERED_BODY_TEXT
        assert "Clementine harvesting season" not in finding.referent.page_topic.text


def test_the_accessible_name_matches_axes_own_computation_on_hidden_referents() -> None:
    """The two cases where a hand-rolled name resolver would diverge from axe: a labelling
    element that is `aria-hidden`, and one that is `display:none`. Both are currently-correct
    cases, so an extractor that skipped hidden referenced elements would break them."""
    for testcase_id, expected in (("88a1646138", "First name:"), ("925f5da929", "Go Search")):
        path = next(ACT_HTML.glob(f"{testcase_id}*.html"))
        findings = [f for f in normalize(scan(str(path))) if f.rule_id == "label"]
        assert findings, f"{testcase_id}: expected a label finding"
        for finding in findings:
            assert finding.referent is not None and finding.referent.accessible_name is not None
            assert finding.referent.accessible_name.text == expected


def test_extraction_survives_every_vendored_act_fixture() -> None:
    """The spec lists cross-fixture survival as unverified: a guarded setup/teardown that works
    on one probe page is not a guarantee over the whole set. Every case the acceptance run
    scans is scanned here, and every minted finding must carry material or an explicit absence."""
    cases = sorted(ACT_HTML.glob("*.html"))
    assert len(cases) >= 60, "the vendored ACT set is the acceptance input; it must be complete"
    for path in cases:
        for finding in normalize(scan(str(path))):
            assert finding.referent is not None, f"{path.name}: {finding.target} extracted nothing at all"
            _assert_within_budget(finding.referent)
