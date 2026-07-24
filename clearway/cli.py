"""`clearway` CLI — the entrypoint that runs the forward path and moves the trust metric.

`clearway run <fixture>` scans one page end-to-end; `clearway eval` runs the whole `m1-core@1`
fixture set. Both print the stratified trust metrics — the overall `citation_hallucination_rate`,
the verifiable-subset rate, and the honest `unverifiable_share` — and (unless `--no-emit`) push
them via OTel so the Grafana panel updates. The rates are the real drafter's *emergent* values —
the M0 planting demo lever was retired at T3, so the honest measurement is what the panel shows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clearway.observability import (
    record_eval_report,
    setup_metrics,
    setup_operational_metrics,
    setup_tracing,
    shutdown,
    shutdown_operational_metrics,
    shutdown_tracing,
)
from clearway.orchestrator import Retrieve, run, run_set
from clearway.orchestrator.store import OrchestratorStore
from clearway.schemas.models import (
    Citation,
    CitationCheck,
    CitationVerdict,
    Conformance,
    DraftRow,
    NeedsReview,
    OnlineEvalReport,
    ReviewStatus,
    Trace,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _print_metrics(report: OnlineEvalReport) -> None:
    """Print the stratified trust metrics for one report: the overall hallucination rate plus its
    split by oracle-verifiability (verifiable-subset rate + the honest `unverifiable_share`)."""
    m = report.metrics
    print(
        f"{report.eval_set_id}  run {report.run_id}  "
        f"findings={m.findings_total} citations={m.citations_total} hallucinations={m.hallucinations_total}"
    )
    print(
        f"  citation_hallucination_rate={m.citation_hallucination_rate:.3f}  "
        f"verifiable={m.citation_hallucination_rate_verifiable:.3f}  "
        f"unverifiable_share={m.unverifiable_share:.3f} "
        f"({m.citations_unverifiable_total}/{m.citations_total})"
    )


# --- ACR/VPAT evidence rendering ---------------------------------------------
# ARCHITECTURE §2: "Findings -> ACR/VPAT-shaped output with correct citations, severity,
# remediation." `run` assembles one DraftRow per non-withheld finding; this renders them as the
# plain-text rows a specialist reads. `confidence` is deliberately omitted — the field is
# decorative (see its schema note) — and each row is drafted evidence, never a final decision:
# Clearway does not render the conformance verdict, the specialist does.
#
# Write-all-in: every assembled row goes into the block. The ONLY rows that never reach it are the
# ones the HITL gate holds back — a `NeedsReview` still PENDING, or one a specialist REJECTED
# (`orchestrator/machine._gate`). Nothing else filters: a contradicted citation, a weak finding
# class, and a low-confidence draft all still ship. The reader is told how far to trust a row (the
# per-row verification-state label below) rather than having it silently removed — a row dropped
# from the report is also dropped from the trust metrics, which flatters the headline instead of
# improving it.

_ROW_LABEL_W = 11  # widest label ("Conformance" / "Remediation"), so the value columns align
_VALUE_COL = 2 + _ROW_LABEL_W + 3  # "  " + label + " : "
_VALUE_INDENT = " " * _VALUE_COL
_RULE_W = 72
_WRAP_W = _RULE_W - _VALUE_COL


# --- per-row verification-state ("trust") label -------------------------------
# What actually stands behind one row, in three states, derived from verification state ONLY: the
# validator's `CitationVerdict`s (did the oracle confirm every criterion this row cites?) and the
# reviewer's `ReviewStatus` (did a specialist sign it?).
#
# `DraftRow.confidence` is deliberately NOT an input and must never become one. It is measured to
# carry no usable signal — one populated bin, values pinned ~0.85-1.0 regardless of correctness —
# so a label sourced from it would launder a broken number into a client-facing assurance. See the
# field's own schema note and docs/acceptance-analysis.md.

_TRUST_ORACLE_VERIFIED = "oracle-verified"
_TRUST_HUMAN_REVIEWED = "human-reviewed"
_TRUST_DRAFTER_JUDGED = "drafter-judged, unverified"

_TRUST_LEGEND = (
    f"Trust labels -- {_TRUST_ORACLE_VERIFIED}: an automated oracle confirmed every criterion the "
    f"row cites. {_TRUST_HUMAN_REVIEWED}: a specialist approved or edited it. "
    f"{_TRUST_DRAFTER_JUDGED}: model output that nothing has confirmed."
)

# A `supports` verdict is a "no problem here" claim, and it arises on the quality-review classes
# whose referent is weakest. The oracle grounds cited criteria, never a conformance verdict — and on
# the one bucket it does ground (`violations`) it positively contradicts a `supports` claim. So it
# never renders as a bare verdict, and never as oracle-verified.
_SUPPORTS_CAVEAT = "unverified claim, not a certified pass"


def _trust_label(row: DraftRow, checks: list[CitationCheck], review_status: ReviewStatus | None) -> str:
    """Which of the three verification states this row is in.

    Precedence is `human-reviewed` > `oracle-verified` > `drafter-judged, unverified`:

    - A specialist's APPROVED or EDITED resolution outranks everything. It is the later and stronger
      attestation, and on an EDITED row the remediation prose is the human's — the oracle never
      grounded a word of it, so naming the oracle would misattribute what the reader is reading.
    - `oracle-verified` requires at least one citation and EVERY citation VERIFIED. One
      HALLUCINATED (the oracle contradicted it) or UNVERIFIABLE (no oracle verdict to check against)
      citation leaves an unproven claim in the shipped row, and zero citations verify nothing at all.
    - Everything else is the honest floor: the drafter said it, nothing confirmed it.
    """
    if review_status in (ReviewStatus.APPROVED, ReviewStatus.EDITED):
        return _TRUST_HUMAN_REVIEWED
    if row.conformance is Conformance.SUPPORTS:
        return _TRUST_DRAFTER_JUDGED
    if checks and all(c.verdict is CitationVerdict.VERIFIED for c in checks):
        return _TRUST_ORACLE_VERIFIED
    return _TRUST_DRAFTER_JUDGED


def _fmt_conformance(conformance: Conformance) -> str:
    """The Conformance enum in standard VPAT/ACR wording: `does_not_support` -> 'Does Not Support'.
    `supports` alone never renders bare — it carries `_SUPPORTS_CAVEAT`, so the least-trustworthy
    row in the report cannot be read as a certified pass."""
    text = conformance.value.replace("_", " ").title()
    if conformance is Conformance.SUPPORTS:
        return f"{text} -- {_SUPPORTS_CAVEAT}"
    return text


def _fmt_citation(citation: Citation) -> list[str]:
    """One cited SC as one or two lines: 'id Title (Level X)', then its URL underneath if present."""
    level = f" (Level {citation.level.value})" if citation.level is not None else ""
    head = " ".join(part for part in (citation.sc_id, citation.title) if part) + level
    return [head, citation.url] if citation.url else [head]


def _labelled(label: str, value: str) -> str:
    return f"  {label:<{_ROW_LABEL_W}} : {value}"


_REASON_LABEL = {
    "unverifiable_judgment": "no automated oracle",
    "axe_incomplete": "axe could not decide",
}


def _withheld_line(withheld: list[NeedsReview]) -> str | None:
    """One ASCII line summarising what the review gate held back from the evidence, by reason — so a
    run that ships few rows explains the gap (a real page withholds most findings into the queue)
    instead of looking empty. None when nothing was withheld."""
    if not withheld:
        return None
    counts = Counter(r.reason.value for r in withheld)
    parts = ", ".join(f"{n} {_REASON_LABEL.get(reason, reason)}" for reason, n in counts.most_common())
    return f"{len(withheld)} withheld for specialist review ({parts}) -- see: clearway review list --status pending"


def _render_drafts(
    target: str,
    drafts: list[DraftRow],
    withheld: list[NeedsReview],
    *,
    traces: Sequence[Trace] = (),
    reviewed: Sequence[NeedsReview] = (),
) -> str:
    """Render the assembled DraftRows as one plain-text ACR/VPAT evidence block — pure ASCII, no
    colour or box-drawing, so it survives a copy-paste into an article. Returns the whole block; the
    caller prints it.

    Every row in `drafts` is rendered (see the write-all-in note above). `traces` carries the
    authoritative per-finding `CitationCheck`s and `reviewed` the human-resolved records that DID
    ship, which together are the only inputs to each row's verification-state label. Both default to
    empty, and a row with no verification evidence labels DOWN, never up — an absent trace can only
    understate what stands behind a row."""
    checks_by_finding = {t.finding_id: t.checks for t in traces}
    status_by_finding = {r.finding_id: r.status for r in reviewed}
    rule = "=" * _RULE_W
    out: list[str] = [rule, f"ACR / VPAT evidence -- {target}", rule, ""]
    withheld_line = _withheld_line(withheld)
    if not drafts:
        out.append("No rows assembled for evidence -- the page produced no findings that reached drafting,")
        out.append("or every finding was withheld for specialist review.")
        if withheld_line is not None:
            out.append(withheld_line)
        return "\n".join(out)
    out.append(f"{len(drafts)} finding(s) drafted for evidence -- not a final conformance decision.")
    if withheld_line is not None:
        out.append(withheld_line)
    out.extend(textwrap.wrap(_TRUST_LEGEND, width=_RULE_W))
    out.append("")
    for i, row in enumerate(drafts, start=1):
        out.append(f"[{i}] {row.finding_id}")
        label = _trust_label(row, checks_by_finding.get(row.finding_id, []), status_by_finding.get(row.finding_id))
        out.append(_labelled("Trust", label))
        out.append(_labelled("Conformance", _fmt_conformance(row.conformance)))
        out.append(_labelled("Severity", row.severity.value if row.severity is not None else "unspecified"))
        if row.citations:
            cited = [line for citation in row.citations for line in _fmt_citation(citation)]
            out.append(_labelled("WCAG", cited[0]))
            out.extend(_VALUE_INDENT + line for line in cited[1:])
        else:
            out.append(_labelled("WCAG", "(none cited)"))
        wrapped = textwrap.wrap(row.remediation.strip(), width=_WRAP_W) or ["(none provided)"]
        out.append(_labelled("Remediation", wrapped[0]))
        out.extend(_VALUE_INDENT + line for line in wrapped[1:])
        out.append("")
    return "\n".join(out).rstrip()


@contextmanager
def _telemetry(emit: bool) -> Iterator[None]:
    """Bracket the whole run with OTel telemetry when emitting. Spans AND the operational LLM/
    pipeline metrics are produced *during* `execute()`, so — unlike the trust gauges, set from the
    finished report — they must be set up before the run and flushed after. `--no-emit` skips all of
    it; spans/metrics then fall back to inert no-op API calls, so an offline run needs no stack."""
    if emit:
        setup_metrics()  # installs the global MeterProvider the operational metrics export through
        setup_operational_metrics()
        setup_tracing()
    try:
        yield
    finally:
        if emit:
            # force-flush before this short-lived process exits (T9)
            shutdown_tracing()
            shutdown_operational_metrics()
            shutdown()


def _print_resume_notice(run_id: str, done_count: int, total_count: int, next_finding_id: str | None) -> None:
    """`execute()`'s `on_resume` hook, wired to a real print — fires before the run proceeds, so a
    resumed `run`/`eval` confirms it's actually skipping finished work before real drafts take
    35-50s each."""
    where = f"continuing from {next_finding_id}" if next_finding_id is not None else "nothing left to do"
    print(f"resuming run {run_id}: {done_count}/{total_count} findings already complete, {where}")


def _print_progress(step: str, index: int, total: int, label: str) -> None:
    """`execute()`'s `on_progress` hook, wired to a stderr print so a long real-LLM run (drafting is
    ~35-50s per finding) shows where it is. Goes to stderr, so redirecting stdout to a file still
    captures only the report. Flushed, so each line appears live rather than at the end."""
    if step == "scan":
        line = f"scanning {label} ..."
    elif step == "normalize":
        line = f"{total} finding(s) found"
    else:  # retrieve / draft / validate, per finding
        line = f"  [{index}/{total}] {step} {label}"
    print(line, file=sys.stderr, flush=True)


# --- HITL review queue (T3) --------------------------------------------------


def _open_store() -> OrchestratorStore:
    """The durable store the review commands read/write. Reuses `run._default_store` (real Postgres
    + ensure_schema) so tests patch a single seam; imported lazily so `clearway review` never builds
    a DB connection when another subcommand is invoked."""
    from clearway.orchestrator.run import _default_store

    return _default_store()


def _resolve_review(store: OrchestratorStore, finding_id: str, run_id: str | None) -> NeedsReview | None:
    """Find one queued review by `finding_id` (+ optional `--run-id` to disambiguate). Prints why
    and returns None when it's unknown or queued under more than one run."""
    if run_id is not None:
        review = store.load_review(run_id, finding_id)
        if review is None:
            print(f"no review for finding {finding_id} in run {run_id}", file=sys.stderr)
        return review
    matches = [r for r in store.load_reviews() if r.finding_id == finding_id]
    if not matches:
        print(f"no review found for finding {finding_id}", file=sys.stderr)
        return None
    if len(matches) > 1:
        runs = ", ".join(sorted(r.run_id for r in matches))
        print(f"finding {finding_id} is queued in multiple runs ({runs}); pass --run-id", file=sys.stderr)
        return None
    return matches[0]


def _resume_hint(review: NeedsReview) -> str:
    return f"resume to assemble: clearway eval --run-id {review.run_id}"


def _review_list_cmd(args: argparse.Namespace) -> int:
    status = ReviewStatus(args.status) if args.status else None
    reviews = _open_store().load_reviews(status=status)
    if not reviews:
        print("review queue is empty")
        return 0
    for r in reviews:
        print(f"{r.finding_id}  run={r.run_id}  {r.status.value:<8}  {r.reason.value:<20}  {r.draft.conformance.value}")
    return 0


def _review_show_cmd(args: argparse.Namespace) -> int:
    review = _resolve_review(_open_store(), args.finding_id, args.run_id)
    if review is None:
        return 1
    print(f"finding {review.finding_id}  run {review.run_id}")
    print(f"  status={review.status.value}  reason={review.reason.value}")
    print("  draft:")
    print(json.dumps(review.draft.model_dump(mode="json"), indent=2))
    if review.edited_draft is not None:
        print("  edited_draft:")
        print(json.dumps(review.edited_draft.model_dump(mode="json"), indent=2))
    return 0


def _edit_draft_in_editor(draft: DraftRow) -> DraftRow | None:
    """Open the DraftRow as JSON in `$EDITOR`, re-validating on save. Returns the edited row, or
    None if the buffer no longer parses as a valid DraftRow."""
    editor = os.getenv("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tf.write(json.dumps(draft.model_dump(mode="json"), indent=2))
        path = tf.name
    try:
        subprocess.run([editor, path], check=True)
        edited_text = Path(path).read_text()
    finally:
        os.unlink(path)
    try:
        return DraftRow.model_validate_json(edited_text)  # re-validate on save
    except ValidationError as exc:
        print(f"edited draft is not a valid DraftRow:\n{exc}", file=sys.stderr)
        return None


def _apply_review_outcome(
    store: OrchestratorStore, review: NeedsReview, status: ReviewStatus, edited: DraftRow | None
) -> None:
    store.save_review(
        review.model_copy(update={"status": status, "edited_draft": edited, "updated_at": datetime.now(UTC)})
    )


def _review_approve_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    _apply_review_outcome(store, review, ReviewStatus.APPROVED, review.edited_draft)
    print(f"approved {review.finding_id} — {_resume_hint(review)}")
    return 0


def _review_edit_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    base = review.edited_draft or review.draft
    if args.remediation is not None:
        edited: DraftRow | None = base.model_copy(update={"remediation": args.remediation})
    else:
        edited = _edit_draft_in_editor(base)
        if edited is None:
            return 1
    _apply_review_outcome(store, review, ReviewStatus.EDITED, edited)
    print(f"edited {review.finding_id} — {_resume_hint(review)}")
    return 0


def _review_reject_cmd(args: argparse.Namespace) -> int:
    store = _open_store()
    review = _resolve_review(store, args.finding_id, args.run_id)
    if review is None:
        return 1
    _apply_review_outcome(store, review, ReviewStatus.REJECTED, review.edited_draft)
    print(f"rejected {review.finding_id} — it will stay out of the assembled output")
    return 0


def _corpus_ingest_cmd(args: argparse.Namespace) -> int:
    from clearway.corpus import (
        LiteLLMEmbedder,
        PgCorpusStore,
        build_corpus_version,
        fetch_wcag_json,
        ingest,
        parse_sc_meta,
        parse_wcag_json,
    )

    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    corpus_version = build_corpus_version(embedder)
    data = fetch_wcag_json()
    chunks = parse_wcag_json(data, corpus_version=corpus_version)
    if args.limit:
        chunks = chunks[: args.limit]
    stored = ingest(chunks, embedder, store)
    # Enrich: upsert the per-SC reference rows (title + level) under the same corpus_version.
    # Metadata-only — no embedding, no re-embed of the chunks above; corpus_version is unchanged.
    meta_stored = store.upsert_sc_meta(corpus_version, parse_sc_meta(data))
    print(
        f"ingested {stored} chunks  sc_meta={meta_stored}  "
        f"corpus_version={corpus_version}  total={store.count(corpus_version)}"
    )
    return 0


def _mcp_serve_cmd(args: argparse.Namespace) -> int:
    """Launch the standalone MCP retrieval server: a long-lived host process exposing the RAG
    retriever as one read-only tool over streamable HTTP at `/mcp`. Builds the same retriever as
    an in-process run (shared `build_default_retriever`), so the corpus_version it serves is
    pinned for the process lifetime. Host/port come from `.env` (CLEARWAY_MCP_HOST / _PORT)."""
    from clearway.mcp_server import build_server
    from clearway.retriever import build_default_retriever

    host = os.getenv("CLEARWAY_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("CLEARWAY_MCP_PORT", "8848"))
    retriever = build_default_retriever()
    server = build_server(retriever, host=host, port=port)
    print(
        f"clearway mcp-serve: retrieve_wcag_evidence on http://{host}:{port}/mcp  "
        f"corpus_version={retriever.corpus_version}"
    )
    # The server is a separate process, so it needs its own tracer provider to export the tool span
    # (child of the caller's run trace) to the collector → Tempo. Exporting is safe with no collector
    # up (batched, failures logged not raised); flush on shutdown (Ctrl-C) so buffered spans leave.
    setup_tracing()
    try:
        server.run(transport="streamable-http")
    finally:
        shutdown_tracing()
    return 0


def _corpus_query_cmd(args: argparse.Namespace) -> int:
    from clearway.corpus import LiteLLMEmbedder, PgCorpusStore, build_corpus_version

    embedder = LiteLLMEmbedder()
    store = PgCorpusStore()
    corpus_version = build_corpus_version(embedder)
    hits = store.query(embedder.embed_query(args.text), k=args.k, corpus_version=corpus_version)
    for hit in hits:
        print(f"{','.join(hit.sc_ids):8} {hit.text[:90]}")
    return 0


def _retrieve_seam(args: argparse.Namespace) -> Retrieve | None:
    """Resolve the retrieve transport toggle. In-process (`None`) is the default — a normal run
    needs no server. MCP is opt-in: the `--retrieve-via-mcp` flag, or `CLEARWAY_RETRIEVE_TRANSPORT=mcp`
    in the environment (the flag wins). When on, build the MCP-client seam against `CLEARWAY_MCP_URL`;
    the durable orchestrator retries a dead server and fails that step cleanly, so the toggle is safe
    to flip without changing the pipeline's output (parity is by construction)."""
    via_mcp = (
        bool(getattr(args, "retrieve_via_mcp", False)) or os.getenv("CLEARWAY_RETRIEVE_TRANSPORT", "").lower() == "mcp"
    )
    if not via_mcp:
        return None
    from clearway.orchestrator.mcp_retrieve import build_mcp_retrieve

    url = os.getenv("CLEARWAY_MCP_URL", "http://127.0.0.1:8848/mcp")
    print(f"retrieve transport: MCP → {url}")
    return build_mcp_retrieve(url)


def _run_cmd(args: argparse.Namespace) -> int:
    with _telemetry(args.emit):
        result = run(
            args.target,
            retrieve=_retrieve_seam(args),
            run_id=args.run_id,
            on_resume=_print_resume_notice,
            on_progress=_print_progress,
        )
        if args.emit:
            record_eval_report(result.report)
    print(
        _render_drafts(
            args.target,
            result.drafts,
            result.withheld,
            traces=result.traces,
            reviewed=result.reviewed,
        )
    )
    print()
    _print_metrics(result.report)
    if args.emit:
        print("emitted → OTel (the Grafana panel will update)")
    return 0


def _eval_cmd(args: argparse.Namespace) -> int:
    """Run the whole `m1-core@1` fixture set (the manifest's pages) and report the stratified
    trust metrics. This is the M1 exit-criterion command — the set is where the two incomplete
    fixtures make `unverifiable_share` non-trivial. Needs the real corpus stack + Ollama."""
    manifest = json.loads((_FIXTURES / "expected_m1.json").read_text())
    targets = [str(_FIXTURES / page["path"]) for page in manifest["pages"]]
    with _telemetry(args.emit):
        report = run_set(
            targets,
            eval_set_id=manifest["eval_set_id"],
            retrieve=_retrieve_seam(args),
            run_id=args.run_id,
            on_resume=_print_resume_notice,
            on_progress=_print_progress,
        ).report
        if args.emit:
            record_eval_report(report)
    _print_metrics(report)
    if args.emit:
        print("emitted → OTel (the Grafana panel will update)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clearway", description="Clearway accessibility evidence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the forward path over one page and emit the trust metric")
    run_p.add_argument("target", help="fixture path or URL to scan")
    run_p.add_argument(
        "--no-emit",
        dest="emit",
        action="store_false",
        help="compute and print only; do not push the metric to OTel",
    )
    run_p.add_argument(
        "--run-id",
        default=None,
        help="resume an existing run id instead of starting a fresh one (target must be the same page)",
    )
    run_p.add_argument(
        "--retrieve-via-mcp",
        action="store_true",
        help="retrieve over the MCP server (CLEARWAY_MCP_URL) instead of in-process; default is in-process",
    )
    run_p.set_defaults(emit=True, func=_run_cmd)

    eval_p = sub.add_parser("eval", help="run the m1-core@1 fixture set and emit the stratified trust metrics")
    eval_p.add_argument(
        "--no-emit",
        dest="emit",
        action="store_false",
        help="compute and print only; do not push the metrics to OTel",
    )
    eval_p.add_argument(
        "--run-id",
        default=None,
        help="resume an existing run id instead of starting a fresh one",
    )
    eval_p.add_argument(
        "--retrieve-via-mcp",
        action="store_true",
        help="retrieve over the MCP server (CLEARWAY_MCP_URL) instead of in-process; default is in-process",
    )
    eval_p.set_defaults(emit=True, func=_eval_cmd)

    review_p = sub.add_parser("review", help="triage the HITL needs-review queue (list/show/approve/edit/reject)")
    review_sub = review_p.add_subparsers(dest="review_command", required=True)

    list_p = review_sub.add_parser("list", help="list queued reviews")
    list_p.add_argument(
        "--status", choices=[s.value for s in ReviewStatus], default=None, help="filter by review status"
    )
    list_p.set_defaults(func=_review_list_cmd)

    show_p = review_sub.add_parser("show", help="show a queued review's draft + context")
    show_p.add_argument("finding_id", help="the flagged finding's id (from `review list`)")
    show_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    show_p.set_defaults(func=_review_show_cmd)

    approve_p = review_sub.add_parser("approve", help="approve a queued draft as-is")
    approve_p.add_argument("finding_id")
    approve_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    approve_p.set_defaults(func=_review_approve_cmd)

    edit_p = review_sub.add_parser("edit", help="edit a queued draft (opens $EDITOR unless --remediation)")
    edit_p.add_argument("finding_id")
    edit_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    edit_p.add_argument("--remediation", default=None, help="quick single-field edit without opening the editor")
    edit_p.set_defaults(func=_review_edit_cmd)

    reject_p = review_sub.add_parser("reject", help="reject a queued draft (kept out of the assembled output)")
    reject_p.add_argument("finding_id")
    reject_p.add_argument("--run-id", default=None, help="disambiguate when a finding is queued in more than one run")
    reject_p.set_defaults(func=_review_reject_cmd)

    ingest_p = sub.add_parser("corpus-ingest", help="fetch WCAG 2.2, chunk + embed, upsert into pgvector")
    ingest_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="ingest only the first N chunks (0 = all)",
    )
    ingest_p.set_defaults(func=_corpus_ingest_cmd)

    mcp_serve_p = sub.add_parser(
        "mcp-serve", help="serve the retriever as a standalone MCP server (retrieve_wcag_evidence over HTTP)"
    )
    mcp_serve_p.set_defaults(func=_mcp_serve_cmd)

    query_p = sub.add_parser("corpus-query", help="embed a query and print the nearest corpus chunks")
    query_p.add_argument("text", help="query text, e.g. 'images need a text alternative'")
    query_p.add_argument(
        "-k",
        type=int,
        default=5,
        help="how many results to return",
    )
    query_p.set_defaults(func=_corpus_query_cmd)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
