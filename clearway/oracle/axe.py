"""Regime A oracle: derive ground-truth WCAG success criteria from axe-core tags.

axe-core carries the applicable success criteria on each rule as `wcag<p><g><crit>` tags
(e.g. `wcag111` -> 1.1.1, `wcag1410` -> 1.4.10). Level/version/category tags (`wcag2a`,
`wcag21aa`, `cat.forms`, `best-practice`, `ACT`, ...) are not success criteria and are ignored.
This is the hard, near-free ground truth for the oracle-rich regime (ARCHITECTURE §4.8 / §5).
"""

from __future__ import annotations

import re

from clearway.oracle.wcag import VALID_SC_IDS
from clearway.schemas.models import Finding, OracleRegime, OracleVerdict

# Matches only pure success-criterion tags: wcag + principle + guideline + criterion digits.
# `wcag2a`, `wcag21aa`, `cat.forms`, `best-practice` etc. deliberately do NOT match.
_SC_TAG = re.compile(r"^wcag(\d)(\d)(\d+)$")

ORACLE_VERSION = "wcag2.2-sc@1"


def tag_to_sc_ids(tags: list[str]) -> list[str]:
    """Decode axe tags into canonical dotted SC ids, keeping only real WCAG 2.2 criteria.

    Deduplicated and sorted. A tag that decodes to a non-existent SC is dropped (defensive:
    keeps the oracle from ever emitting an id that would itself fail L0).
    """
    found: set[str] = set()
    for tag in tags:
        match = _SC_TAG.match(tag)
        if match is None:
            continue
        sc_id = f"{match.group(1)}.{match.group(2)}.{int(match.group(3))}"
        if sc_id in VALID_SC_IDS:
            found.add(sc_id)
    return sorted(found)


class AxeCoreOracle:
    """Ground truth for Regime A — implements the `Oracle` Protocol (CONTRACTS §3).

    Returns `None` for a finding whose tags carry no recognizable WCAG SC, so it falls
    through to the LLM-judge / human review per the "prefer the hardest oracle" layering.
    """

    @property
    def regime(self) -> OracleRegime:
        return OracleRegime.A_DIGITAL

    @property
    def version(self) -> str:
        return ORACLE_VERSION

    def verdict_for(self, finding: Finding) -> OracleVerdict | None:
        sc_ids = tag_to_sc_ids(finding.axe_tags)
        if not sc_ids:
            return None
        return OracleVerdict(
            success_criteria=sc_ids,
            severity=finding.impact,
            source="axe-core",
            confidence=1.0,
        )
