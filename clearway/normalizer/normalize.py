"""Normalizer — raw `ScanResult` → canonical, deduplicated `Finding[]`.

axe reports per *rule* (an `AxeRuleResult` that may span many DOM nodes). The rest
of the pipeline works per *place* — one issue at one element — so the normalizer
explodes each rule result's nodes into individual `Finding`s, assigns a deterministic
id, and drops duplicates (ARCHITECTURE §6: scanner → normalizer → everything).

Three axe buckets become findings: confirmed `violations`, needs-review `incomplete`, and the
existence-only subset of `passes` named by `QUALITY_REVIEW_RULES` (quality-review judgment
items — see `quality_review.py` for why). They are structurally identical, so all flow through the same
path; each finding records which bucket it came from in `source_bucket` so the oracle knows
whether it carries hard ground truth (VIOLATIONS) or is oracle-poor (INCOMPLETE / PASSES →
unverifiable). For a PASSES finding the help is reframed to the quality-review task, because
axe's rule-level help ("Images must have alternate text") reads as already-conformant.
"""

from __future__ import annotations

import hashlib

from clearway.normalizer.quality_review import QUALITY_REVIEW_RULES
from clearway.schemas.models import AxeBucket, AxeRuleResult, Finding, ScanResult

# Delimiter joining the (source_url, rule_id, target) parts before hashing. Chosen
# to be vanishingly unlikely inside a URL, an axe rule id, or a CSS selector, so the
# three parts can't blur into each other and collide (e.g. so "a|b" + "c" can't equal
# "a" + "b|c").
_ID_PARTS_SEP = "|"

# Delimiter joining the selector *path* within a single target. See _flatten_target.
_TARGET_PATH_SEP = " >>> "


def _flatten_target(target: list[str]) -> str:
    """Collapse an axe node's selector *path* into one canonical string.

    axe returns `node.target` as a LIST, not a single selector: for a plain element
    it's one entry (`["#email"]`), but for content inside an iframe or shadow root it's
    the *path through the frames* (`["#frame", "#btn"]`). `Finding.target` is a single
    string, so we must flatten — and we join (rather than take just the last entry) so
    that the SAME selector in two different frames stays distinct. That distinctness
    matters because `target` feeds the finding id below: flattening to only "#btn" would
    make two genuinely different elements hash to the same id and get wrongly deduped.
    """
    return _TARGET_PATH_SEP.join(target)


def _finding_id(source_url: str, rule_id: str, target: str) -> str:
    """Deterministic id for a finding = the dedup key AND the idempotency key.

    Design:
    - **SHA-256, not Python's `hash()`** — `hash()` is randomly salted per process, so
      it would give different ids across runs. We need the SAME (source_url, rule_id,
      target) to always yield the SAME id, on any machine, in any run — that's what lets
      the orchestrator (later) resume/retry keyed by finding id without reprocessing, and
      what makes the T3 acceptance test (re-run → identical ids) hold.
    - **truncated to 16 hex chars (64 bits)** — a page has at most a few hundred findings,
      so 64 bits is astronomically collision-safe here, while staying compact in logs,
      traces, and the checkpoint table. Full 64-char digests would only add noise.
    """
    raw = _ID_PARTS_SEP.join((source_url, rule_id, target))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _findings_from_rule(source_url: str, rule: AxeRuleResult, bucket: AxeBucket) -> list[Finding]:
    """One `Finding` per offending node; carry the tags the oracle needs downstream and
    the `bucket` provenance that tells the oracle whether this finding is ground-truthable.

    Provenance is NOT folded into the id: the id is the *place* identity
    (source_url, rule_id, target), and a place never appears in two buckets at once, so
    the same element re-scans to the same id regardless of bucket.

    For a PASSES finding the help is reframed to the quality-review task: axe passed the
    mechanical check (a name/attribute EXISTS), so its rule-level help reads as conformant —
    the reframed help tells the drafter/judge to instead assess whether it is *meaningful*."""
    help_text = QUALITY_REVIEW_RULES[rule.rule_id] if bucket is AxeBucket.PASSES else rule.help
    findings: list[Finding] = []
    for node in rule.nodes:
        target = _flatten_target(node.target)
        findings.append(
            Finding(
                id=_finding_id(source_url, rule.rule_id, target),
                source_url=source_url,
                rule_id=rule.rule_id,
                axe_tags=list(rule.tags),  # carried so AxeCoreOracle can derive SC ids
                target=target,
                html=node.html,
                impact=rule.impact,
                help=help_text,
                help_url=rule.help_url,
                source_bucket=bucket,
                # Carried, not hashed: the id above is the place's identity, and the same place
                # must keep the same id however much context the scanner captures about it.
                referent=node.referent,
            )
        )
    return findings


def normalize(scan: ScanResult) -> list[Finding]:
    """Flatten a `ScanResult` into deduplicated `Finding[]`, in stable scan order.

    Three axe buckets become findings — confirmed `violations` first, then needs-review
    `incomplete`, then the existence-only `passes` (quality-review) — each tagged with its
    `source_bucket`. Only passes whose rule is in `QUALITY_REVIEW_RULES` become findings; the
    rest of axe's (large) passes[] are ignored. Dedup is by `Finding.id` (the
    (source_url, rule_id, target) hash): if the same rule hits the same place twice, we keep
    the first and drop the rest. Order is preserved (first occurrence wins) so the output is
    deterministic given a deterministic scan.
    """
    seen: set[str] = set()
    findings: list[Finding] = []
    rules_by_bucket = (
        (AxeBucket.VIOLATIONS, scan.violations),
        (AxeBucket.INCOMPLETE, scan.incomplete),
        (AxeBucket.PASSES, scan.passes),
    )
    for bucket, rules in rules_by_bucket:
        for rule in rules:
            if bucket is AxeBucket.PASSES and rule.rule_id not in QUALITY_REVIEW_RULES:
                continue  # only the listed existence-only rules are quality-review findings
            for finding in _findings_from_rule(scan.url, rule, bucket):
                if finding.id in seen:
                    continue
                seen.add(finding.id)
                findings.append(finding)
    return findings
